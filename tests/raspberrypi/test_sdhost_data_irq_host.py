# SPDX-License-Identifier: MIT
"""Host regressions of the port's actual SDHOST data IRQ/completion methods.

Run: python -m unittest discover -s tests/raspberrypi -p test_sdhost_data_irq_host.py
Complete production data_irq, block_irq and finish_data methods are extracted
unchanged, together with actual register constants, MMC structs and MMC errno.
PIO is a counted double injecting success/software timeout/CRC; transfer_complete
is a counted double clearing host->data and completing the request. Its unrelated
stop-command and controller-idle waits are deliberately outside this test.
This is not an ARM build or a physical IRQ/MMIO/hardware ordering test.
Requires a native C++ compiler (CXX may override its executable); no network.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "ports/raspberrypi/upstream_overrides/circle/addon/SDCard/sdhost.cpp"
SDCARD = ROOT / "lib/circle/addon/SDCard"


def method(source, name):
    """Extract an entire production method, including signature, unchanged."""
    match = re.search(r"void CSDHOSTDevice::" + re.escape(name) + r"\s*\([^)]*\)\s*\{", source)
    if match is None:
        raise AssertionError(f"Missing production method: {name}")
    depth = 1
    end = match.end()
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    if depth:
        raise AssertionError(f"Incomplete production method: {name}")
    return source[match.start():end]


def harness():
    source = PORT.read_text(encoding="utf-8")
    mmc = (SDCARD / "mmc.h").read_text(encoding="utf-8")
    constants = source[source.index("#define FIFO_READ_THRESHOLD"):source.index("#define MHZ")]
    # Omit only the ARM types include and external request-done declaration.
    structs = mmc[mmc.index("struct sg_mapping_iter"):mmc.index("void mmc_request_done")]
    methods = "\n".join(method(source, name) for name in ("data_irq", "block_irq", "finish_data"))
    return r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#undef EINVAL
#undef ETIMEDOUT
#undef EILSEQ
#undef ENOTSUP
#include "mmcerror.h"
using u32 = uint32_t;
''' + constants + structs + r'''
#define pr_debug(...) ((void)0)
#define pr_err(...) ((void)0)
#define mmc_hostname(mmc) "fake-mmc"
#define BUG_ON(condition) assert(!(condition))
struct Host {
    mmc_request *mrq = nullptr;
    mmc_command *cmd = nullptr;
    mmc_data *data = nullptr;
    unsigned blocks = 0;
    u32 hcfg = 0;
    int data_complete = 0, debug = 0;
};
static const u32 BASE_HCFG = SDHCFG_BUSY_IRPT_EN | SDHCFG_WIDE_INT_BUS;
static const unsigned UNFINISHED_BYTES = 123456;
class CSDHOSTDevice {
public:
    Host state;
    Host *host = &state;
    int pio_calls = 0, complete_calls = 0, dumps = 0, reads = 0, writes = 0;
    int inject_error = 0, completion_error = 0;
    unsigned completion_bytes = 0, blocks_at_pio = 0;
    u32 last_hcfg = 0, hcfg_at_pio = 0;
    void dumpregs() { ++dumps; }
    u32 read(u32) { ++reads; return 0; }
    void write(u32 value, u32 reg) {
        assert(reg == SDHCFG && value == host->hcfg);
        ++writes;
        last_hcfg = value;
    }
    void transfer_pio() {
        assert(host->data && !host->data->error && !host->data_complete);
        assert(host->mrq && !host->mrq->done && !complete_calls);
        ++pio_calls;
        blocks_at_pio = host->blocks;
        hcfg_at_pio = host->hcfg;
        // Actual transfer_pio leaves block accounting and completion to callers.
        host->data->error = inject_error;
    }
    void transfer_complete() {
        assert(!host->cmd && host->data && host->data_complete);
        assert(host->mrq && host->mrq->data == host->data && !host->mrq->done);
        assert(host->hcfg == BASE_HCFG && last_hcfg == BASE_HCFG);
        assert(complete_calls == 0);
        ++complete_calls;
        completion_error = host->data->error;
        completion_bytes = host->data->bytes_xfered;
        host->data = nullptr;
        host->mrq->done = 1;
    }
    void data_irq(u32 intmask);
    void block_irq(u32 intmask);
    void finish_data();
};
''' + methods + r'''
struct Fixture {
    CSDHOSTDevice dev;
    mmc_command command = {};
    mmc_data data = {};
    mmc_request request = {};
    Fixture(bool writing, unsigned blocks = 3, bool pending = false, bool debug = false) {
        data.flags = writing ? MMC_DATA_WRITE : MMC_DATA_READ;
        data.blksz = 512;
        data.blocks = blocks;
        data.bytes_xfered = UNFINISHED_BYTES;
        data.mrq = &request;
        command.opcode = writing ? MMC_WRITE_MULTIPLE_BLOCK : MMC_READ_MULTIPLE_BLOCK;
        command.data = &data;
        // A pending command's error must not bypass finish_data's ordering guard.
        command.error = pending ? -EILSEQ : 0;
        request.cmd = &command;
        request.data = &data;
        dev.host->mrq = &request;
        dev.host->cmd = pending ? &command : nullptr;
        dev.host->data = &data;
        dev.host->blocks = blocks;
        dev.host->hcfg = BASE_HCFG | SDHCFG_DATA_IRPT_EN;
        dev.host->debug = debug;
    }
    void waiting(int pio, unsigned remaining, bool writing) {
        assert(dev.pio_calls == pio && dev.host->blocks == remaining);
        assert(!dev.complete_calls && !request.done && !dev.host->data_complete);
        assert(dev.host->data == &data && !data.error);
        assert(data.bytes_xfered == UNFINISHED_BYTES);
        assert(dev.host->hcfg == (BASE_HCFG |
            (writing ? SDHCFG_BLOCK_IRPT_EN : SDHCFG_DATA_IRPT_EN)));
    }
    void finished(int error, int pio, unsigned remaining, bool pending = false) {
        assert(data.error == error && dev.pio_calls == pio);
        assert(dev.host->blocks == remaining && dev.host->data_complete == 1);
        assert(dev.host->hcfg == BASE_HCFG && dev.last_hcfg == BASE_HCFG);
        const unsigned bytes = error ? 0 : data.blksz * data.blocks;
        assert(data.bytes_xfered == bytes);
        assert(request.cmd == &command && request.data == &data && data.mrq == &request);
        assert(dev.host->mrq == &request && dev.reads == 0);
        if (pending) {
            assert(dev.host->cmd == &command && command.error == -EILSEQ);
            assert(dev.host->data == &data && !dev.complete_calls && !request.done);
        } else {
            assert(!dev.host->cmd && !dev.host->data);
            assert(dev.complete_calls == 1 && request.done == 1);
            assert(dev.completion_error == error && dev.completion_bytes == bytes);
            const int writes = dev.writes, dumps = dev.dumps;
            // A repeated shared data IRQ after completion must have no effect.
            dev.data_irq(SDHSTS_DATA_FLAG | SDHSTS_CRC16_ERROR | SDHSTS_REW_TIME_OUT);
            assert(dev.complete_calls == 1 && request.done == 1 && dev.pio_calls == pio);
            assert(dev.writes == writes && dev.dumps == dumps && dev.reads == 0);
            assert(data.error == error && data.bytes_xfered == bytes);
        }
    }
};
static int software_error(const char *name) {
    if (!std::strcmp(name, "timeout")) return -ETIMEDOUT;
    if (!std::strcmp(name, "crc")) return -EILSEQ;
    assert(!"unknown software error");
    return 0;
}
static u32 hardware_status(const char *name) {
    if (!std::strcmp(name, "timeout")) return SDHSTS_REW_TIME_OUT;
    if (!std::strcmp(name, "crc")) return SDHSTS_CRC16_ERROR;
    if (!std::strcmp(name, "fifo")) return SDHSTS_FIFO_ERROR;
    if (!std::strcmp(name, "combined"))
        return SDHSTS_CRC16_ERROR | SDHSTS_FIFO_ERROR | SDHSTS_REW_TIME_OUT;
    assert(!"unknown hardware status");
    return 0;
}
static void first_write_error(const char *error, bool pending) {
    Fixture f(true, 3, pending);
    f.dev.inject_error = software_error(error);
    f.dev.data_irq(SDHSTS_DATA_FLAG); // Hardware status itself is clean.
    f.finished(software_error(error), 1, 3, pending);
    assert(f.dev.writes == 2 && !f.dev.dumps);
    assert(f.dev.hcfg_at_pio == (BASE_HCFG | SDHCFG_BLOCK_IRPT_EN));
    assert(f.dev.blocks_at_pio == 3);
}
static void subsequent_write_error(const char *error, bool pending) {
    Fixture f(true, 3, pending);
    f.dev.data_irq(SDHSTS_DATA_FLAG);
    f.waiting(1, 3, true);
    f.dev.inject_error = software_error(error);
    f.dev.block_irq(SDHSTS_BLOCK_IRPT);
    f.finished(software_error(error), 2, 2, pending);
    assert(f.dev.writes == 2 && !f.dev.dumps && f.dev.blocks_at_pio == 2);
}
static void hardware_error(const char *error, bool block, bool writing,
                           bool pending, bool debug) {
    Fixture f(writing, 3, pending, debug);
    if (block) {
        assert(writing);
        f.dev.data_irq(SDHSTS_DATA_FLAG);
        f.waiting(1, 3, true);
    }
    const u32 status = hardware_status(error);
    const int expected = status & (SDHSTS_CRC16_ERROR | SDHSTS_FIFO_ERROR)
        ? -EILSEQ : -ETIMEDOUT;
    if (block) f.dev.block_irq(SDHSTS_BLOCK_IRPT | status);
    else f.dev.data_irq(SDHSTS_DATA_FLAG | status);
    // No PIO on error IRQ and block_irq short-circuits decrement on error.
    f.finished(expected, block ? 1 : 0, 3, pending);
    assert(f.dev.dumps == (debug ? 1 : 0));
    assert(f.dev.writes == (block ? 2 : 1));
}
static void write_success(unsigned blocks) {
    Fixture f(true, blocks);
    f.dev.data_irq(SDHSTS_DATA_FLAG);
    f.waiting(1, blocks, true);
    assert(f.dev.writes == 1 && f.dev.blocks_at_pio == blocks);
    for (unsigned remaining = blocks; remaining > 0; --remaining) {
        f.dev.block_irq(SDHSTS_BLOCK_IRPT);
        if (remaining > 1) {
            f.waiting(static_cast<int>(blocks - remaining + 2), remaining - 1, true);
            assert(f.dev.blocks_at_pio == remaining - 1 && f.dev.writes == 1);
        }
    }
    f.finished(0, static_cast<int>(blocks), 0);
    assert(f.dev.writes == 2 && !f.dev.dumps);
}
static void read_case(const char *name, bool pending) {
    const bool last = !std::strcmp(name, "last");
    const bool success = last || !std::strcmp(name, "success");
    Fixture f(false, last ? 1 : 3, pending);
    f.dev.inject_error = success ? 0 : software_error(name);
    f.dev.data_irq(SDHSTS_DATA_FLAG);
    assert(f.dev.blocks_at_pio == (last ? 1u : 3u));
    assert(f.dev.hcfg_at_pio == (BASE_HCFG | SDHCFG_DATA_IRPT_EN));
    if (success && !last) {
        f.waiting(1, 2, false);
        assert(!f.dev.writes && !f.dev.dumps);
    } else {
        f.finished(f.dev.inject_error, 1, last ? 0 : 2, pending);
        assert(f.dev.writes == 1 && !f.dev.dumps);
    }
}
static void no_data() {
    Fixture f(true);
    f.dev.host->data = nullptr;
    f.dev.data_irq(SDHSTS_DATA_FLAG | SDHSTS_CRC16_ERROR | SDHSTS_REW_TIME_OUT);
    assert(!f.dev.pio_calls && !f.dev.complete_calls && !f.dev.writes);
    assert(!f.dev.dumps && !f.dev.reads && !f.request.done && !f.dev.host->data_complete);
    assert(f.dev.host->blocks == 3 && !f.data.error);
    assert(f.data.bytes_xfered == UNFINISHED_BYTES);
    assert(f.dev.host->hcfg == (BASE_HCFG | SDHCFG_DATA_IRPT_EN));
    assert(f.dev.host->mrq == &f.request && !f.dev.host->data);
}
int main(int argc, char **argv) {
    assert(argc == 7);
    const bool block = std::atoi(argv[3]) != 0;
    const bool writing = std::atoi(argv[4]) != 0;
    const bool pending = std::atoi(argv[5]) != 0;
    const bool debug = std::atoi(argv[6]) != 0;
    if (!std::strcmp(argv[1], "first_error")) first_write_error(argv[2], pending);
    else if (!std::strcmp(argv[1], "block_error")) subsequent_write_error(argv[2], pending);
    else if (!std::strcmp(argv[1], "hardware"))
        hardware_error(argv[2], block, writing, pending, debug);
    else if (!std::strcmp(argv[1], "write_success")) write_success(std::atoi(argv[2]));
    else if (!std::strcmp(argv[1], "read")) read_case(argv[2], pending);
    else if (!std::strcmp(argv[1], "no_data")) no_data();
    else assert(!"unknown scenario");
    std::puts("PASS");
}
'''


class SDHostDataIRQHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = (os.environ.get("CXX") or
                    ("E:/msys64/ucrt64/bin/g++.exe"
                     if Path("E:/msys64/ucrt64/bin/g++.exe").is_file() else None) or
                    shutil.which("g++") or shutil.which("clang++"))
        if not compiler:
            raise RuntimeError("A native C++ compiler is required; set CXX to its executable")
        temporary = tempfile.TemporaryDirectory(prefix="sdhost-data-irq-host-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        source = cls.directory / "sdhost_data_irq_host.cpp"
        source.write_text(harness(), encoding="utf-8")
        cls.binary = cls.directory / ("sdhost_data_irq_host.exe" if os.name == "nt"
                                      else "sdhost_data_irq_host")
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.directory)
        result = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(SDCARD),
             str(source), "-o", str(cls.binary)],
            cwd=cls.directory, env=cls.env, capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise AssertionError("Host C++ compilation failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, name, value="timeout", block=False, writing=True,
                     pending=False, debug=False):
        result = subprocess.run(
            [str(self.binary), name, str(value), str(int(block)), str(int(writing)),
             str(int(pending)), str(int(debug))],
            cwd=self.directory, env=self.env, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_first_write_software_error_finishes_immediately(self):
        for error in ("timeout", "crc"):
            with self.subTest(error=error):
                self.run_scenario("first_error", error)

    def test_subsequent_block_write_software_error_finishes_immediately(self):
        for error in ("timeout", "crc"):
            with self.subTest(error=error):
                self.run_scenario("block_error", error)

    def test_hardware_errors_complete_without_error_irq_pio_and_zero_bytes(self):
        for error in ("timeout", "crc", "fifo", "combined"):
            for block, writing in ((False, False), (False, True), (True, True)):
                for debug in (False, True):
                    with self.subTest(error=error, block=block, writing=writing, debug=debug):
                        self.run_scenario("hardware", error, block, writing, debug=debug)

    def test_successful_write_waits_for_block_irq_including_single_block(self):
        for blocks in (1, 3):
            with self.subTest(blocks=blocks):
                self.run_scenario("write_success", blocks)

    def test_successful_nonfinal_read_remains_pending(self):
        self.run_scenario("read", "success", writing=False)

    def test_last_read_finishes_with_full_byte_count(self):
        self.run_scenario("read", "last", writing=False)

    def test_read_software_errors_finish_with_zero_bytes(self):
        for error in ("timeout", "crc"):
            with self.subTest(error=error):
                self.run_scenario("read", error, writing=False)

    def test_pending_command_error_defers_data_completion(self):
        for error in ("timeout", "crc"):
            for name in ("first_error", "block_error", "read"):
                with self.subTest(error=error, name=name):
                    self.run_scenario(name, error, pending=True)
        for block, writing in ((False, False), (False, True), (True, True)):
            with self.subTest(hardware=True, block=block, writing=writing):
                self.run_scenario("hardware", "timeout", block, writing, pending=True)
        self.run_scenario("read", "last", writing=False, pending=True)

    def test_no_data_shared_irq_returns_without_side_effects(self):
        self.run_scenario("no_data")


if __name__ == "__main__":
    unittest.main()
