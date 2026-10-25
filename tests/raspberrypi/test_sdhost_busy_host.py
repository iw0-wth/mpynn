# SPDX-License-Identifier: MIT
"""Host regression tests of the port's actual SDHOST busy IRQ/completion methods.

Run: python -m unittest discover -s tests/raspberrypi -p test_sdhost_busy_host.py
The complete busy_irq and tasklet_finish bodies, register constants, MMC structs
and MMC errno definitions are production code. Registers, logging, iterator
cleanup, the barrier, finish_command and mmc_request_done are counted doubles.
This is not an ARM build or a claim about physical IRQ/MMIO ordering or hardware.
Requires a native C++ compiler (CXX can override the executable); no network.
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
    """Extract a whole production method, including its signature, unchanged."""
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
    # Include all actual MMC/iterator struct definitions, omitting only the ARM
    # types include and the external done declaration (provided by our double).
    structs = mmc[mmc.index("struct sg_mapping_iter"):mmc.index("void mmc_request_done")]
    methods = "\n".join(method(source, name) for name in ("busy_irq", "tasklet_finish"))
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
#define pr_err(...) ((void)0)
#define pr_warn(...) ((void)0)
#define pr_info(...) ((void)0)
#define mmc_hostname(mmc) "fake-mmc"
// The production macro runs tasklet_finish synchronously; add only a counter.
#define tasklet_schedule(tasklet) do { ++scheduled; tasklet_finish(); } while (0)
#define mmiowb() barrier()
struct Host {
    mmc_host *mmc = nullptr;
    mmc_request *mrq = nullptr;
    mmc_command *cmd = nullptr;
    mmc_data *data = nullptr;
    sg_mapping_iter sg_miter = {};
    int use_busy = 1, debug = 0;
    int overclock = 0, overclock_50 = 0, reset_clock = 0;
};
void mmc_request_done(mmc_host *, mmc_request *);
class CSDHOSTDevice {
public:
    mmc_host mmc = {};
    Host state;
    Host *host = &state;
    unsigned char buffer[512] = {};
    int dumps = 0, finishes = 0, scheduled = 0;
    int stops = 0, barriers = 0, done_calls = 0;
    int reads = 0, writes = 0;
    int snapshot_cmd_error = 0, snapshot_stop_error = 0, snapshot_data_error = 0;
    unsigned snapshot_bytes = 0;
    int snapshot_stops = 0, snapshot_barriers = 0;
    mmc_request *observed_request = nullptr;
    CSDHOSTDevice() { host->mmc = &mmc; }
    u32 read(u32) { ++reads; return 0; }
    void write(u32, u32) { ++writes; }
    void dumpregs() { ++dumps; }
    void finish_command() {
        ++finishes;
        assert(host->cmd && host->mrq && !host->use_busy);
        assert(!scheduled && !done_calls && !stops && !barriers);
    }
    void sg_miter_stop(sg_mapping_iter *it) {
        assert(it == &host->sg_miter);
        assert(it->addr == buffer && it->length == sizeof buffer);
        assert(host->data && host->cmd && host->mrq);
        assert(!host->use_busy && !scheduled && !barriers && !done_calls);
        ++stops;
        // Production Circle cleanup is a no-op; count it, don't invent effects.
    }
    void barrier() {
        assert(!host->mrq && !host->cmd && !host->data);
        assert(!host->use_busy && scheduled == 1 && done_calls == 0);
        assert(observed_request && observed_request->done == 0);
        ++barriers;
    }
    void done(mmc_host *completed_mmc, mmc_request *request) {
        assert(completed_mmc == &mmc && request == observed_request);
        assert(!host->mrq && !host->cmd && !host->data);
        assert(!host->use_busy && scheduled == 1 && barriers == 1);
        assert(request->done == 0 && done_calls == 0);
        ++done_calls;
        snapshot_cmd_error = request->cmd->error;
        snapshot_stop_error = request->stop->error;
        snapshot_data_error = request->data ? request->data->error : 0;
        snapshot_bytes = request->data ? request->data->bytes_xfered : 0;
        snapshot_stops = stops;
        snapshot_barriers = barriers;
        // Same publication contract as mmchost.cpp's mmc_request_done double.
        request->done = 1;
    }
    void busy_irq(u32 intmask);
    void tasklet_finish();
};
static CSDHOSTDevice *device;
void mmc_request_done(mmc_host *mmc, mmc_request *request) {
    assert(device);
    device->done(mmc, request);
}
''' + methods + r'''
struct Fixture {
    CSDHOSTDevice dev;
    mmc_command main = {}, stop = {};
    mmc_data data = {};
    mmc_request request = {};
    Fixture(bool stop_command, int data_state, bool debug, bool write_data) {
        device = &dev;
        main.opcode = write_data ? MMC_WRITE_MULTIPLE_BLOCK : MMC_READ_MULTIPLE_BLOCK;
        main.flags = MMC_RSP_PRESENT | MMC_RSP_CRC | MMC_RSP_BUSY;
        stop.opcode = MMC_STOP_TRANSMISSION;
        stop.flags = MMC_RSP_PRESENT | MMC_RSP_CRC | MMC_RSP_BUSY;
        request.cmd = &main;
        request.stop = &stop;
        request.data = data_state ? &data : nullptr;
        main.data = request.data;
        data.flags = write_data ? MMC_DATA_WRITE : MMC_DATA_READ;
        data.blksz = 512;
        data.blocks = 8;
        data.bytes_xfered = 4096; // Make missing busy-error byte reset observable.
        data.stop = &stop;
        data.mrq = &request;
        dev.observed_request = &request;
        dev.host->mrq = &request;
        dev.host->cmd = stop_command ? &stop : &main;
        // A stop can retain mrq->data after host->data was already finished.
        dev.host->data = data_state == 1 ? &data : nullptr;
        dev.host->debug = debug;
        dev.host->sg_miter.addr = dev.buffer;
        dev.host->sg_miter.length = sizeof dev.buffer;
        dev.host->sg_miter.consumed = 128;
    }
};
static u32 error_status(const char *name) {
    if (!std::strcmp(name, "crc7")) return SDHSTS_CRC7_ERROR;
    if (!std::strcmp(name, "crc16")) return SDHSTS_CRC16_ERROR;
    if (!std::strcmp(name, "fifo")) return SDHSTS_FIFO_ERROR;
    if (!std::strcmp(name, "rew_timeout")) return SDHSTS_REW_TIME_OUT;
    if (!std::strcmp(name, "cmd_timeout")) return SDHSTS_CMD_TIME_OUT;
    if (!std::strcmp(name, "crc7_precedence")) return SDHSTS_ERROR_MASK;
    if (!std::strcmp(name, "crc16_precedence"))
        return SDHSTS_CRC16_ERROR | SDHSTS_REW_TIME_OUT | SDHSTS_CMD_TIME_OUT;
    if (!std::strcmp(name, "rew_precedence")) return SDHSTS_REW_TIME_OUT | SDHSTS_CMD_TIME_OUT;
    assert(!"unknown error status");
    return 0;
}
static void error_case(const char *name, bool stop_command, int data_state,
                       bool debug, bool write_data) {
    Fixture f(stop_command, data_state, debug, write_data);
    CSDHOSTDevice &dev = f.dev;
    mmc_command *active = dev.host->cmd;
    const u32 status = error_status(name);
    const bool command_error = (status & SDHSTS_CRC7_ERROR) || !f.request.data ||
        !(status & (SDHSTS_CRC16_ERROR | SDHSTS_FIFO_ERROR | SDHSTS_REW_TIME_OUT));
    const int expected = status & (SDHSTS_CRC7_ERROR | SDHSTS_CRC16_ERROR | SDHSTS_FIFO_ERROR)
        ? -EILSEQ : -ETIMEDOUT;
    dev.busy_irq(SDHSTS_BUSY_IRPT | status);
    assert(active->error == (command_error ? expected : 0));
    assert(f.main.error == (command_error && !stop_command ? expected : 0));
    assert(f.stop.error == (command_error && stop_command ? expected : 0));
    assert(f.data.error == (command_error ? 0 : expected));
    assert(f.data.bytes_xfered == (data_state == 1 ? 0u : 4096u));
    assert(dev.stops == (data_state == 1 ? 1 : 0));
    assert(dev.scheduled == 1 && dev.done_calls == 1 && f.request.done == 1);
    assert(dev.barriers == 1 && dev.finishes == 0);
    assert(dev.dumps == (debug ? 1 : 0));
    assert(!dev.host->cmd && !dev.host->mrq && !dev.host->data && !dev.host->use_busy);
    // Error and byte snapshots are taken at the actual done callback, not later.
    assert(dev.snapshot_cmd_error == f.main.error);
    assert(dev.snapshot_stop_error == f.stop.error);
    assert(dev.snapshot_data_error == (f.request.data ? f.data.error : 0));
    assert(dev.snapshot_bytes == (f.request.data ? f.data.bytes_xfered : 0));
    assert(dev.snapshot_stops == dev.stops && dev.snapshot_barriers == 1);
    assert(f.request.cmd == &f.main && f.request.stop == &f.stop);
    assert(dev.reads == 0 && dev.writes == 0);
    // A duplicate IRQ returns via no-command guard; rescheduling the real
    // tasklet itself must also be harmless after it cleared the request.
    dev.busy_irq(SDHSTS_BUSY_IRPT | status);
    dev.tasklet_finish();
    assert(dev.done_calls == 1 && f.request.done == 1 && dev.scheduled == 1);
    assert(dev.stops == (data_state == 1 ? 1 : 0));
    assert(dev.barriers == 1 && dev.finishes == 0);
    assert(dev.dumps == (debug ? 2 : 1));
    assert(dev.snapshot_cmd_error == f.main.error && dev.snapshot_stop_error == f.stop.error);
    assert(dev.snapshot_data_error == (f.request.data ? f.data.error : 0));
}
static void guard_case(bool no_command) {
    Fixture f(false, 1, true, false);
    CSDHOSTDevice &dev = f.dev;
    if (no_command) dev.host->cmd = nullptr;
    else dev.host->use_busy = 0;
    mmc_command *original_cmd = dev.host->cmd;
    dev.busy_irq(SDHSTS_BUSY_IRPT | SDHSTS_ERROR_MASK);
    assert(dev.dumps == 1 && !dev.scheduled && !dev.done_calls && !dev.finishes);
    assert(!dev.stops && !dev.barriers && !dev.reads && !dev.writes);
    assert(dev.host->mrq == &f.request && dev.host->cmd == original_cmd);
    assert(dev.host->data == &f.data && dev.host->use_busy == (no_command ? 1 : 0));
    assert(!f.request.done && !f.main.error && !f.stop.error && !f.data.error);
    assert(f.data.bytes_xfered == 4096);
}
static void success_case(bool stop_command, int data_state) {
    Fixture f(stop_command, data_state, true, false);
    CSDHOSTDevice &dev = f.dev;
    mmc_command *original_cmd = dev.host->cmd;
    mmc_data *original_data = dev.host->data;
    // Unrelated, non-error status flags must not trigger error completion.
    dev.busy_irq(SDHSTS_BUSY_IRPT | SDHSTS_BLOCK_IRPT | SDHSTS_DATA_FLAG);
    assert(dev.finishes == 1 && !dev.scheduled && !dev.done_calls && !f.request.done);
    assert(!dev.stops && !dev.barriers && !dev.dumps && !dev.host->use_busy);
    assert(dev.host->cmd == original_cmd && dev.host->mrq == &f.request);
    assert(dev.host->data == original_data);
    assert(!f.main.error && !f.stop.error && !f.data.error && f.data.bytes_xfered == 4096);
    dev.busy_irq(SDHSTS_BUSY_IRPT);
    assert(dev.finishes == 1 && dev.dumps == 1 && !dev.done_calls && !dev.scheduled);
}
int main(int argc, char **argv) {
    assert(argc == 6);
    const bool stop_command = std::atoi(argv[2]) != 0;
    const int data_state = std::atoi(argv[3]);
    const bool debug = std::atoi(argv[4]) != 0;
    const bool write_data = std::atoi(argv[5]) != 0;
    if (!std::strcmp(argv[1], "no_command")) guard_case(true);
    else if (!std::strcmp(argv[1], "unexpected_busy")) guard_case(false);
    else if (!std::strcmp(argv[1], "success")) success_case(stop_command, data_state);
    else error_case(argv[1], stop_command, data_state, debug, write_data);
    std::puts("PASS");
}
'''


class SDHostBusyHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = (os.environ.get("CXX") or
                    ("E:/msys64/ucrt64/bin/g++.exe"
                     if Path("E:/msys64/ucrt64/bin/g++.exe").is_file() else None) or
                    shutil.which("g++") or shutil.which("clang++"))
        if not compiler:
            raise RuntimeError("A native C++ compiler is required; set CXX to its executable")
        temporary = tempfile.TemporaryDirectory(prefix="sdhost-busy-host-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        source = cls.directory / "sdhost_busy_host.cpp"
        source.write_text(harness(), encoding="utf-8")
        cls.binary = cls.directory / ("sdhost_busy_host.exe" if os.name == "nt" else "sdhost_busy_host")
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

    def run_scenario(self, name, stop=False, data=0, debug=False, write=False):
        result = subprocess.run(
            [str(self.binary), name, str(int(stop)), str(data), str(int(debug)), str(int(write))],
            cwd=self.directory, env=self.env, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def error_matrix(self, name):
        # Main command with/without active data; stop with no data, still-active
        # data, or request data whose host iterator has already finished.
        for stop, data in ((False, 0), (False, 1), (True, 0), (True, 1), (True, 2)):
            for debug in (False, True):
                for write in (False, True):
                    with self.subTest(status=name, stop=stop, data=data, debug=debug, write=write):
                        self.run_scenario(name, stop, data, debug, write)

    def test_crc7_completes_with_active_command_error(self):
        self.error_matrix("crc7")

    def test_crc16_completes_with_data_or_command_error(self):
        self.error_matrix("crc16")

    def test_fifo_completes_with_data_or_command_error(self):
        self.error_matrix("fifo")

    def test_read_write_timeout_completes_with_data_or_command_error(self):
        self.error_matrix("rew_timeout")

    def test_command_timeout_completes_with_active_command_error(self):
        self.error_matrix("cmd_timeout")

    def test_combined_error_status_preserves_driver_precedence(self):
        for name in ("crc7_precedence", "crc16_precedence", "rew_precedence"):
            self.error_matrix(name)

    def test_no_command_returns_without_completion_or_cleanup(self):
        self.run_scenario("no_command")

    def test_unexpected_busy_returns_without_completion_or_cleanup(self):
        self.run_scenario("unexpected_busy")

    def test_success_delegates_only_to_finish_command(self):
        for stop, data in ((False, 0), (False, 1), (True, 0), (True, 1), (True, 2)):
            with self.subTest(stop=stop, data=data):
                self.run_scenario("success", stop, data)


if __name__ == "__main__":
    unittest.main()
