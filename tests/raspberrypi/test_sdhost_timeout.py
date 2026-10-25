"""Host-side regression tests of actual SDHOST methods with fake registers/time.

Run with python -m unittest discover -s tests/raspberrypi -p test_sdhost_timeout.py.
Requires a native g++/clang++ (CXX may name its executable); no firmware build.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SDCARD = ROOT / "lib/circle/addon/SDCard"


def method(source, name):
    """Extract the complete production method, without rewriting its body."""
    match = re.search(r"(?:void|boolean) CSDHOSTDevice::" + name + r"\s*\([^)]*\)\s*\{", source)
    if match is None:
        raise AssertionError(f"Missing production method: {name}")
    start = match.start()
    depth = 1
    pos = match.end()
    while depth:
        depth += (source[pos] == "{") - (source[pos] == "}")
        pos += 1
    return source[start:pos]


def harness():
    source = (ROOT / "ports/raspberrypi/upstream_overrides/circle/addon/SDCard/sdhost.cpp").read_text()
    mmc = (SDCARD / "mmc.h").read_text()
    # Use the driver's actual register constants, MMC fields/flags and errno.
    constants = source[source.index("#define FIFO_READ_THRESHOLD"):source.index("#define MHZ")]
    structs = mmc[mmc.index("struct mmc_command;"):mmc.index("void mmc_request_done")]
    methods = "\n".join(method(source, name) for name in (
        "send_command", "read_block_pio", "write_block_pio", "transfer_pio", "finish_data"
    ))
    return r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#undef EINVAL
#undef ETIMEDOUT
#undef EILSEQ
#undef ENOTSUP
#include "mmcerror.h"
using u32 = uint32_t;
using boolean = bool;
''' + constants + structs + r'''
#define CLOCKHZ 1000000
#define pr_debug(...) ((void)0)
#define pr_info(...) ((void)0)
#define pr_warn(...) ((void)0)
#define pr_err(...) ((void)0)
#define BUG_ON(x) assert(!(x))
#define min(a,b) ((a) < (b) ? (a) : (b))
#define tasklet_schedule(x) tasklet_finish()
#define udelay(us) this->delay(us)
#define ndelay(ns) this->delay((ns)/1000)
struct Timer {
    unsigned ticks = 0;
    unsigned GetClockTicks() { return ticks++; }
};
struct Iterator {
    size_t length = 32, consumed = 0;
    u32 buffer[8] = {};
    void *addr = buffer;
    int calls = 0, stops = 0;
    bool valid = true;
};
bool sg_miter_next(Iterator *it) { ++it->calls; return it->valid; }
void sg_miter_stop(Iterator *it) { ++it->stops; }
struct Host {
    mmc_data *data = nullptr;
    mmc_command *cmd = nullptr;
    mmc_request *mrq = nullptr;
    Iterator sg_miter;
    unsigned pio_timeout = 2, ns_per_fifo_word = 1000;
    unsigned delay_after_this_stop = 0, delay_after_stop = 0, stop_time = 0;
    int debug = 0, max_delay = 0, use_busy = 0, use_sbc = 0;
    int data_complete = 0;
    u32 hcfg = 0;
};
class CSDHOSTDevice {
public:
    Host state;
    Host *host = &state;
    Timer timer;
    Timer *m_pTimer = &timer;
    mmc_command *observed_cmd = nullptr;
    bool stalled = false;
    int command_busy_reads = 0, command_reads = 0;
    int scheduled = 0, completion_error = 0, completed = 0;
    int fifo_reads = 0, fifo_writes = 0, register_writes = 0, prepared = 0;
    unsigned delayed = 0;
    u32 status = 0;
    u32 read(u32 reg) {
        if (reg == SDCMD) {
            ++command_reads;
            return command_busy_reads-- > 0 ? SDCMD_NEW_FLAG : 0;
        }
        if (reg == SDHSTS) return status;
        if (reg == SDEDM) {
            if (host->data->flags & MMC_DATA_READ)
                return SDEDM_FSM_READDATA | (stalled ? 0 : (8 << 4));
            return SDEDM_FSM_WRITEDATA | (stalled ? (16 << 4) : 0);
        }
        assert(reg == SDDATA);
        ++fifo_reads;
        return 0x12345678;
    }
    void write(u32, u32 reg) {
        ++register_writes;
        if (reg == SDDATA) ++fifo_writes;
    }
    void delay(unsigned us) { delayed += us; }
    void dumpregs() {}
    void tasklet_finish() { ++scheduled; completion_error = observed_cmd->error; }
    void prepare_data(mmc_command *) { ++prepared; }
    void transfer_complete() { ++completed; }
    boolean send_command(mmc_command *cmd);
    void read_block_pio();
    void write_block_pio();
    void transfer_pio();
    void finish_data();
};
''' + methods + r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    int scenario = std::atoi(argv[1]);
    CSDHOSTDevice dev;
    mmc_command cmd = {};
    dev.observed_cmd = &cmd;
    if (scenario <= 2) {
        dev.command_busy_reads = scenario == 0 ? 10001 : (scenario == 1 ? 3 : 10000);
        bool sent = dev.send_command(&cmd);
        if (scenario == 0) {
            assert(!sent && cmd.error == -ETIMEDOUT);
            assert(dev.scheduled == 1 && dev.completion_error == -ETIMEDOUT);
            assert(dev.delayed == 100000 && dev.command_reads == 10001);
            assert(dev.prepared == 0 && dev.register_writes == 0);
        } else {
            assert(sent && cmd.error == 0 && dev.scheduled == 0);
            assert(dev.prepared == 1 && dev.register_writes == 2);
        }
        return 0;
    }
    mmc_data data = {};
    data.flags = scenario % 2 ? MMC_DATA_READ : MMC_DATA_WRITE;
    data.blksz = 64;
    data.blocks = 1;
    dev.host->data = &data;
    dev.stalled = scenario >= 3 && scenario <= 6;
    if (scenario == 5 || scenario == 6) dev.status = SDHSTS_CRC16_ERROR;
    if (scenario == 9 || scenario == 10) dev.status = SDHSTS_REW_TIME_OUT;
    if (scenario == 11 || scenario == 12) dev.status = SDHSTS_CRC16_ERROR;
    if (scenario == 13 || scenario == 14) {
        dev.host->sg_miter.valid = false;
        dev.status = SDHSTS_CRC16_ERROR;
    }
    dev.transfer_pio();
    int expected = scenario <= 6 || scenario == 9 || scenario == 10 ? -ETIMEDOUT :
                   scenario == 11 || scenario == 12 ? -EILSEQ :
                   scenario >= 13 ? -EINVAL : 0;
    assert(data.error == expected);
    assert(dev.host->sg_miter.stops == 1);
    if (dev.stalled || scenario >= 13) {
        assert(dev.fifo_reads == 0 && dev.fifo_writes == 0);
        assert(dev.host->sg_miter.calls == 1);
    } else {
        assert(dev.host->sg_miter.calls == 2);
        assert(dev.fifo_reads + dev.fifo_writes == 16);
    }
    dev.finish_data();
    assert(data.error == expected);
    assert(data.bytes_xfered == (expected ? 0u : 64u));
    assert(dev.host->data_complete == 1 && dev.completed == 1);
}
'''


class SDHostTimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler and Path("E:/msys64/ucrt64/bin/g++.exe").is_file():
            compiler = "E:/msys64/ucrt64/bin/g++.exe"
        if not compiler:
            raise RuntimeError("A native C++ compiler is required; set CXX to its executable")
        cls.temp = tempfile.TemporaryDirectory(prefix="sdhost-timeout-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        source = directory / "sdhost_timeout.cpp"
        cls.binary = directory / ("sdhost_timeout.exe" if os.name == "nt" else "sdhost_timeout")
        source.write_text(harness())
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + cls.env.get("PATH", "")
        result = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-I", str(SDCARD), str(source), "-o", str(cls.binary)],
            env=cls.env, capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.binary), str(scenario)], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_previous_command_timeout_reaches_completion(self):
        self.run_scenario(0)

    def test_previous_command_clears_before_deadline(self):
        for scenario in (1, 2):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_software_pio_timeouts_with_clean_hardware_status(self):
        for scenario in (3, 4):
            with self.subTest(direction="read" if scenario % 2 else "write"):
                self.run_scenario(scenario)

    def test_software_pio_timeout_survives_hardware_crc_status(self):
        for scenario in (5, 6):
            with self.subTest(direction="read" if scenario % 2 else "write"):
                self.run_scenario(scenario)

    def test_successful_pio_transfers(self):
        for scenario in (7, 8):
            with self.subTest(direction="read" if scenario % 2 else "write"):
                self.run_scenario(scenario)

    def test_hardware_errors_still_propagate(self):
        for scenario in (9, 10, 11, 12):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_pio_iterator_errors_are_preserved(self):
        for scenario in (13, 14):
            with self.subTest(direction="read" if scenario % 2 else "write"):
                self.run_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
