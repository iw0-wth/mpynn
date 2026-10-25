# SPDX-License-Identifier: MIT
"""Host tests for the Raspberry Pi SPI timeout override.

The C++ harness extracts the complete overridden WriteRead method, then compiles
it with strict warnings against register, timer, GPIO-independent, and lock
counting doubles. It exercises a completed transfer, a FIFO stall that later
progresses, a controller that never asserts DONE, and invalid arguments. This
is a native behavior test; it does not claim physical MMIO ordering.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ports/raspberrypi/upstream_overrides/circle/lib/spimaster.cpp"


def extract_method(source):
    match = re.search(
        r"int CSPIMaster::WriteRead\s*\([^)]*\)\s*\{", source
    )
    if match is None:
        raise AssertionError("missing overridden CSPIMaster::WriteRead")
    depth = 1
    end = match.end()
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    if depth:
        raise AssertionError("incomplete overridden WriteRead")
    return source[match.start():end]


def harness():
    method = extract_method(SOURCE.read_text(encoding="utf-8"))
    return r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

using u8 = std::uint8_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;
using uintptr = std::uintptr_t;
using boolean = bool;
constexpr boolean TRUE = true;
constexpr boolean FALSE = false;

enum { SPI_MASTER_TIMEOUT = 1, SPI_MASTER_INVALID_ARGUMENT = 2 };
static const u64 SPI_MASTER_TIMEOUT_US = 100000;
enum { CS_TXD = 1u << 18, CS_RXD = 1u << 17, CS_DONE = 1u << 16,
       CS_CLEAR_RX = 1u << 5, CS_CLEAR_TX = 1u << 4, CS_TA = 1u << 7,
       CS_CS = 3u, CS_CS__SHIFT = 0 };
#define ARM_SPI_CS (m_nBaseAddress + 0x00)
#define ARM_SPI_FIFO (m_nBaseAddress + 0x04)
#define ARM_SPI_DLEN (m_nBaseAddress + 0x0C)

static u64 fake_ticks;
static u64 fake_tick_step;
class CTimer {
public:
    static u64 GetClockTicks64() { fake_ticks += fake_tick_step; return fake_ticks; }
    static void SimpleusDelay(unsigned us) { fake_ticks += us; }
};

class FakeLock {
public:
    int acquires = 0;
    int releases = 0;
    void Acquire() { ++acquires; }
    void Release() { ++releases; }
};

enum HardwareMode { MODE_NEVER_DONE, MODE_DONE, MODE_STALL_PROGRESS };
class CSPIMaster {
public:
    const unsigned ChipSelectNone = 3;
    bool m_bValid = true;
    uintptr m_nBaseAddress = 0x1000;
    unsigned m_nCSHoldTime = 0;
    FakeLock m_SpinLock;
    HardwareMode mode = MODE_DONE;
    int peripheral_enters = 0;
    int peripheral_exits = 0;
    int cs_reads = 0;
    int cs_writes = 0;
    int fifo_reads = 0;
    int fifo_writes = 0;
    u32 last_cs_write = 0;

    u32 read32(uintptr address) {
        if (address == ARM_SPI_FIFO) {
            ++fifo_reads;
            return 0xA5;
        }
        assert(address == ARM_SPI_CS);
        ++cs_reads;
        if (mode == MODE_NEVER_DONE) return 0;
        if (mode == MODE_STALL_PROGRESS && cs_reads < 4) return 0;
        return CS_TXD | CS_RXD | CS_DONE;
    }
    void write32(uintptr address, u32 value) {
        if (address == ARM_SPI_FIFO) {
            ++fifo_writes;
            return;
        }
        assert(address == ARM_SPI_CS || address == ARM_SPI_DLEN);
        if (address == ARM_SPI_CS) {
            ++cs_writes;
            last_cs_write = value;
        }
    }
    void PeripheralEntry() { ++peripheral_enters; }
    void PeripheralExit() { ++peripheral_exits; }
    int WriteRead(unsigned, const void *, void *, unsigned);
};
''' + method + r'''

static void assert_balanced(const CSPIMaster &master) {
    assert(master.m_SpinLock.acquires == 1);
    assert(master.m_SpinLock.releases == 1);
    assert(master.peripheral_enters == 1);
    assert(master.peripheral_exits == 1);
    assert((master.last_cs_write & CS_TA) == 0);
}

static void invalid_case() {
    CSPIMaster master;
    unsigned char byte = 0;
    assert(master.WriteRead(2, &byte, &byte, 1) == -SPI_MASTER_INVALID_ARGUMENT);
    assert(master.WriteRead(0, nullptr, nullptr, 1) == -SPI_MASTER_INVALID_ARGUMENT);
    assert(master.WriteRead(0, &byte, nullptr, 0) == -SPI_MASTER_INVALID_ARGUMENT);
    assert(master.cs_reads == 0 && master.cs_writes == 0 && master.fifo_reads == 0);
    assert(master.fifo_writes == 0 && master.m_SpinLock.acquires == 0);
    assert(master.peripheral_enters == 0 && master.peripheral_exits == 0);
}

static void timeout_case() {
    CSPIMaster master;
    master.mode = MODE_NEVER_DONE;
    unsigned char byte = 0;
    fake_ticks = 0;
    fake_tick_step = 25000;
    assert(master.WriteRead(0, &byte, nullptr, 1) == -SPI_MASTER_TIMEOUT);
    assert(fake_ticks >= SPI_MASTER_TIMEOUT_US);
    assert_balanced(master);
    assert(master.fifo_writes == 0);
}

static void success_case() {
    CSPIMaster master;
    unsigned char write[3] = {1, 2, 3};
    unsigned char read[3] = {};
    fake_ticks = 0;
    fake_tick_step = 1;
    assert(master.WriteRead(0, write, read, 3) == 3);
    assert_balanced(master);
    assert(master.fifo_writes == 3 && master.fifo_reads == 3);
    assert(read[0] == 0xA5 && read[1] == 0xA5 && read[2] == 0xA5);
}

static void stall_progress_case() {
    CSPIMaster master;
    master.mode = MODE_STALL_PROGRESS;
    unsigned char write[2] = {7, 8};
    unsigned char read[2] = {};
    fake_ticks = 0;
    fake_tick_step = 1000;
    assert(master.WriteRead(0, write, read, 2) == 2);
    assert_balanced(master);
    assert(master.cs_reads >= 4);
    assert(master.fifo_writes == 2 && master.fifo_reads == 2);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    if (!std::strcmp(argv[1], "invalid")) invalid_case();
    else if (!std::strcmp(argv[1], "timeout")) timeout_case();
    else if (!std::strcmp(argv[1], "success")) success_case();
    else if (!std::strcmp(argv[1], "stall_progress")) stall_progress_case();
    else return 2;
    std::puts("PASS");
    return 0;
}
'''.replace('#include <cstdlib>\n', '#include <cstdlib>\n#include <cstring>\n')


class SPIMasterTimeoutHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = (os.environ.get("CXX") or
                    ("E:/msys64/ucrt64/bin/g++.exe"
                     if Path("E:/msys64/ucrt64/bin/g++.exe").is_file() else None) or
                    shutil.which("g++") or shutil.which("clang++"))
        if not compiler:
            raise RuntimeError("A native C++ compiler is required; set CXX")
        temporary = tempfile.TemporaryDirectory(prefix="spimaster-timeout-host-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        source = cls.directory / "spimaster_timeout_host.cpp"
        source.write_text(harness(), encoding="utf-8")
        cls.binary = cls.directory / ("spimaster_timeout_host.exe"
                                      if os.name == "nt" else "spimaster_timeout_host")
        result = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
             str(source), "-o", str(cls.binary)],
            cwd=cls.directory, capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise AssertionError("Host C++ compilation failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run(
            [str(self.binary), scenario], cwd=self.directory,
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_invalid_arguments_do_not_touch_mmio_or_resources(self):
        self.run_scenario("invalid")

    def test_done_completes_full_duplex_transfer_and_cleanup(self):
        self.run_scenario("success")

    def test_fifo_stall_then_progress_completes(self):
        self.run_scenario("stall_progress")

    def test_never_done_returns_timeout_and_balances_cleanup(self):
        self.run_scenario("timeout")


if __name__ == "__main__":
    unittest.main()
