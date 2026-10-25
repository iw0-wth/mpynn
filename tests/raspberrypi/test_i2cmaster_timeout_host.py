# SPDX-License-Identifier: MIT
"""Host regression tests for the port-owned Circle I2C timeout override.

The test compiles the actual override source (not a copy of its methods) against
small register, GPIO, spin-lock, machine-info, and timer doubles.  It therefore
runs on a normal host while still checking the complete polling implementation.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
FALLBACK_CXX = Path("E:/msys64/ucrt64/bin/g++.exe")
OVERRIDE = ROOT / "ports/raspberrypi/upstream_overrides/circle"
SOURCE = OVERRIDE / "lib/i2cmaster.cpp"


STUBS = {
    "circle/types.h": r'''
#pragma once
#include <cstdint>
typedef std::uint8_t u8;
typedef std::uint16_t u16;
typedef std::uint32_t u32;
typedef std::uint64_t u64;
typedef std::uintptr_t uintptr;
typedef bool boolean;
#ifndef TRUE
#define TRUE true
#define FALSE false
#endif
''',
    "circle/gpiopin.h": r'''
#pragma once
#include <circle/types.h>
static const unsigned GPIO_PINS = 64;
enum TGPIOMode { GPIOModeInput, GPIOModeAlternateFunction0,
                 GPIOModeAlternateFunction1, GPIOModeAlternateFunction5 };
enum TGPIOPullMode { GPIOPullModeUp };
class CGPIOPin {
public:
    void AssignPin (unsigned) {}
    void SetMode (TGPIOMode) {}
    void SetPullMode (TGPIOPullMode) {}
};
''',
    "circle/spinlock.h": r'''
#pragma once
#include <circle/types.h>
extern unsigned g_acquires;
extern unsigned g_releases;
class CSpinLock {
public:
    explicit CSpinLock (unsigned = 0) {}
    void Acquire () { ++g_acquires; }
    void Release () { ++g_releases; }
};
''',
    "circle/memio.h": r'''
#pragma once
#include <circle/types.h>
void write32 (uintptr, u32);
u32 read32 (uintptr);
''',
    "circle/bcm2835.h": r'''
#pragma once
#define ARM_IO_BASE ((uintptr) 0x100000)
#define ARM_BSC_C__OFFSET 0x00
#define ARM_BSC_S__OFFSET 0x04
#define ARM_BSC_DLEN__OFFSET 0x08
#define ARM_BSC_A__OFFSET 0x0c
#define ARM_BSC_FIFO__OFFSET 0x10
#define ARM_BSC_DIV__OFFSET 0x14
''',
    "circle/machineinfo.h": r'''
#pragma once
class CMachineInfo {
public:
    static CMachineInfo *Get () { static CMachineInfo info; return &info; }
    unsigned GetClockRate (unsigned) const { return 250000000; }
};
#define CLOCK_ID_CORE 1
''',
    "circle/synchronize.h": r'''
#pragma once
#define TASK_LEVEL 0
#define PeripheralEntry() do {} while (0)
#define PeripheralExit() do {} while (0)
''',
    "circle/timer.h": r'''
#pragma once
#include <circle/types.h>
extern u64 g_ticks;
extern u64 g_tick_step;
class CTimer {
public:
    static u64 GetClockTicks64 () { g_ticks += g_tick_step; return g_ticks; }
};
''',
}


HARNESS = r'''
#include <circle/i2cmaster.h>
#include <circle/bcm2835.h>
#include <cassert>
#include <cstdint>
#include <utility>
#include <vector>

unsigned g_acquires = 0;
unsigned g_releases = 0;
u64 g_ticks = 0;
u64 g_tick_step = 1;
std::vector<std::pair<uintptr, u32>> g_writes;
unsigned g_status_reads = 0;
unsigned g_fifo_reads = 0;
unsigned g_read_phase = 0;

enum Mode { Timeout, DoneRead, DoneWrite, DoneRepeated, ErrorStatus, FifoWrite };
Mode g_mode = Timeout;

static const uintptr BASE = ARM_IO_BASE + 0x205000;
static const u32 C_I2CEN = 1u << 15;
static const u32 C_ST = 1u << 7;
static const u32 C_CLEAR = 1u << 5;
static const u32 C_READ = 1u;
static const u32 S_CLKT = 1u << 9;
static const u32 S_ERR = 1u << 8;
static const u32 S_RXD = 1u << 5;
static const u32 S_TXD = 1u << 4;
static const u32 S_DONE = 1u << 1;
static const u32 S_TA = 1u;

void write32 (uintptr address, u32 value)
{
    g_writes.emplace_back(address, value);
    if (address == BASE + ARM_BSC_C__OFFSET
        && value == (C_I2CEN | C_ST | C_READ)) {
        g_read_phase = 1;
    }
}

u32 read32 (uintptr address)
{
    if (address == BASE + ARM_BSC_FIFO__OFFSET) {
        ++g_fifo_reads;
        return 0xA0u + g_fifo_reads;
    }
    if (address != BASE + ARM_BSC_S__OFFSET) {
        return 0;
    }
    ++g_status_reads;
    switch (g_mode) {
    case Timeout:
        return 0;
    case DoneRead:
        return S_DONE | (g_fifo_reads < 2 ? S_RXD : 0);
    case DoneWrite:
        return S_DONE;
    case DoneRepeated:
        return g_read_phase ? (S_DONE | (g_fifo_reads < 2 ? S_RXD : 0)) : S_TA;
    case ErrorStatus:
        return S_DONE | S_ERR | S_CLKT;
    case FifoWrite:
        return g_status_reads <= 5 ? S_TXD : S_DONE;
    }
    return 0;
}

static void reset (Mode mode, u64 step = 1)
{
    g_mode = mode;
    g_ticks = 0;
    g_tick_step = step;
    g_writes.clear();
    g_status_reads = 0;
    g_fifo_reads = 0;
    g_read_phase = 0;
    g_acquires = 0;
    g_releases = 0;
}

static bool wrote (uintptr address, u32 value)
{
    for (const auto &entry : g_writes) {
        if (entry.first == address && entry.second == value) {
            return true;
        }
    }
    return false;
}

static void expect_balanced ()
{
    assert(g_acquires == 1);
    assert(g_releases == 1);
}

int main ()
{
    CI2CMaster master(0);
    assert(master.Initialize());
    u8 data[32] = {};

    reset(Timeout, 100001);
    assert(master.Read(0x20, data, 2) == -I2C_MASTER_TIMEOUT);
    expect_balanced();
    assert(wrote(BASE + ARM_BSC_C__OFFSET, C_CLEAR));
    assert(wrote(BASE + ARM_BSC_S__OFFSET, S_DONE));

    reset(Timeout, 100001);
    assert(master.Write(0x20, data, 2) == -I2C_MASTER_TIMEOUT);
    expect_balanced();
    assert(wrote(BASE + ARM_BSC_C__OFFSET, C_CLEAR));
    assert(wrote(BASE + ARM_BSC_S__OFFSET, S_DONE));

    reset(Timeout, 100001);
    assert(master.WriteReadRepeatedStart(0x20, data, 1, data, 2)
           == -I2C_MASTER_TIMEOUT);
    expect_balanced();
    assert(wrote(BASE + ARM_BSC_C__OFFSET, C_CLEAR));
    assert(wrote(BASE + ARM_BSC_S__OFFSET, S_DONE));

    reset(DoneRead);
    assert(master.Read(0x20, data, 2) == 2);
    expect_balanced();
    assert(g_fifo_reads == 2);

    reset(DoneWrite);
    assert(master.Write(0x20, data, 2) == 2);
    expect_balanced();

    reset(DoneRepeated);
    assert(master.WriteReadRepeatedStart(0x20, data, 1, data, 2) == 2);
    expect_balanced();
    assert(g_fifo_reads == 2);

    reset(ErrorStatus);
    assert(master.Read(0x20, data, 1) == -I2C_MASTER_ERROR_NACK);
    expect_balanced();
    assert(wrote(BASE + ARM_BSC_S__OFFSET, S_ERR));

    reset(ErrorStatus);
    assert(master.Write(0x20, data, 1) == -I2C_MASTER_ERROR_NACK);
    expect_balanced();
    assert(wrote(BASE + ARM_BSC_S__OFFSET, S_ERR));

    reset(ErrorStatus);
    assert(master.WriteReadRepeatedStart(0x20, data, 1, data, 1)
           == -I2C_MASTER_ERROR_NACK);
    expect_balanced();
    assert(wrote(BASE + ARM_BSC_S__OFFSET, S_ERR));

    reset(FifoWrite);
    assert(master.Write(0x20, data, 20) == 20);
    expect_balanced();
    assert(g_fifo_reads == 0);

    reset(DoneRead);
    g_writes.clear();
    g_status_reads = 0;
    g_acquires = g_releases = 0;
    assert(master.Read(0x20, nullptr, 1) == -I2C_MASTER_INALID_PARM);
    assert(g_writes.empty() && g_status_reads == 0);
    assert(g_acquires == 0 && g_releases == 0);

    reset(DoneWrite);
    g_writes.clear();
    g_status_reads = 0;
    g_acquires = g_releases = 0;
    assert(master.Write(0x20, nullptr, 1) == -I2C_MASTER_INALID_PARM);
    assert(g_writes.empty() && g_status_reads == 0);
    assert(g_acquires == 0 && g_releases == 0);

    reset(DoneRepeated);
    g_writes.clear();
    g_status_reads = 0;
    g_acquires = g_releases = 0;
    assert(master.WriteReadRepeatedStart(0x20, nullptr, 1, data, 1)
           == -I2C_MASTER_INALID_PARM);
    assert(g_writes.empty() && g_status_reads == 0);
    assert(g_acquires == 0 && g_releases == 0);
    return 0;
}
'''


class I2CMasterTimeoutHostTests(unittest.TestCase):
    def test_actual_override_compiles_strictly_and_covers_timeout_paths(self):
        compiler = shutil.which("g++") or shutil.which("c++")
        if compiler is None and FALLBACK_CXX.is_file():
            candidate = str(FALLBACK_CXX)
            try:
                probe = subprocess.run([candidate, '--version'], capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                probe = None
            if probe is not None and probe.returncode == 0:
                compiler = candidate
        if compiler is None:
            self.skipTest("host C++ compiler is unavailable")
        env = os.environ.copy()
        env['PATH'] = str(Path(compiler).parent) + os.pathsep + env.get('PATH', '')
        self.assertTrue(SOURCE.is_file())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, content in STUBS.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(content), encoding="utf-8")
            harness = root / "harness.cpp"
            harness.write_text(textwrap.dedent(HARNESS), encoding="utf-8")
            binary = root / "i2cmaster-host-test"
            command = [
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-DRASPPI=1", "-DAARCH=32", "-DSTDLIB_SUPPORT=1",
                "-I" + str(root), "-I" + str(OVERRIDE / "include"),
                str(SOURCE), str(harness), "-o", str(binary),
            ]
            compiled = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            executed = subprocess.run([str(binary)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)


if __name__ == "__main__":
    unittest.main()
