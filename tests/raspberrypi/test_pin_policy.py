# SPDX-License-Identifier: MIT
"""Compile/run the actual pure-C policy without Circle or Raspberry Pi hardware.

Run: python test_pin_policy.py --cc E:/msys64/ucrt64/bin/gcc.exe
Temporary compiler inputs/outputs are removed automatically.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / "ports" / "raspberrypi"
CC = os.environ.get("CC", "E:/msys64/ucrt64/bin/gcc.exe" if Path("E:/msys64/ucrt64/bin/gcc.exe").is_file() else "gcc")

C_TEST = r'''
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include "pin_policy.h"

int main(void) {
    /* Independent physical P1 references; -1 is power/ground, not a GPIO.
     * 1-based physical pins, including the UART pads as visible but reserved.
     */
    static const int rev1[27] = {
        -1, -1, -1, 0, -1, 1, -1, 4, 14, -1, 15, 17, 18, 21,
        -1, 22, 23, -1, 24, 10, -1, 9, 25, 11, 8, -1, 7
    };
    static const int rev2[27] = {
        -1, -1, -1, 2, -1, 3, -1, 4, 14, -1, 15, 17, 18, 27,
        -1, 22, 23, -1, 24, 10, -1, 9, 25, 11, 8, -1, 7
    };
    for (int board = 1; board <= 2; ++board) {
        enum mpynn_pin_board b = (enum mpynn_pin_board)board;
        const int *reference = board == 1 ? rev1 : rev2;
        int visible_count = 0, allowed_count = 0;
        for (int p = -2; p <= 42; ++p) {
            assert(mpynn_pin_header_gpio(b, p) == (p >= 1 && p <= 26 ? reference[p] : -1));
        }
        for (int bcm = -2; bcm <= 60; ++bcm) {
            int visible = 0;
            for (int p = 1; p <= 26; ++p) {
                if (bcm >= 0 && reference[p] == bcm) visible = 1;
            }
            int console = bcm == 14 || bcm == 15;
            assert(mpynn_pin_is_visible(b, bcm) == visible);
            assert(mpynn_pin_is_console(bcm) == console);
            assert(mpynn_pin_is_allowed(b, bcm) == (visible && !console));
            visible_count += mpynn_pin_is_visible(b, bcm);
            allowed_count += mpynn_pin_is_allowed(b, bcm);
        }
        assert(visible_count == 17);
        assert(allowed_count == 15);
        assert(!mpynn_pin_is_allowed(b, 16)); // ACT LED
        for (int bcm = 28; bcm <= 31; ++bcm) assert(!mpynn_pin_is_allowed(b, bcm)); // P5
        assert(!mpynn_pin_is_allowed(b, INT_MIN));
        assert(!mpynn_pin_is_allowed(b, INT_MAX));
        assert(mpynn_pin_header_gpio(b, INT_MIN) == -1);
        assert(mpynn_pin_header_gpio(b, INT_MAX) == -1);
    }
    const int unknowns[] = {0, -1, 3, 42, INT_MAX};
    for (unsigned i = 0; i < sizeof unknowns / sizeof unknowns[0]; ++i) {
        enum mpynn_pin_board b = (enum mpynn_pin_board)unknowns[i];
        for (int bcm = -1; bcm <= 54; ++bcm) {
            assert(!mpynn_pin_is_visible(b, bcm));
            assert(!mpynn_pin_is_allowed(b, bcm));
        }
        for (int p = 0; p <= 40; ++p) assert(mpynn_pin_header_gpio(b, p) == -1);
    }
    puts("PASS: full Rev1/Rev2 P1 maps, 15 usable pins each, UART/non-header/unknown rejection");
    return 0;
}
'''


# Non-hardware contract test: compile the REAL bridge against a recording Circle
# stand-in. This checks ordering/ownership, not electrical timing or MMIO behavior.
GPIO_STUB = r'''
#ifndef TEST_GPIO_H
#define TEST_GPIO_H
#include <cassert>
#include <cstdint>
#include <vector>
using u32 = uint32_t;
#define FALSE false
enum TGPIOMode { GPIOModeInput, GPIOModeOutput };
enum TGPIOPullMode { GPIOPullModeOff, GPIOPullModeDown, GPIOPullModeUp };
struct Event { int operation; int pin; int value; };
extern std::vector<Event> events;
extern u32 pad_levels;
class CGPIOPin {
    int id = -1;
public:
    void AssignPin(unsigned p) { assert(id == -1); id = p; events.push_back({0, id, 0}); }
    void SetMode(TGPIOMode mode, bool initialize = true) {
        assert(id >= 0 && !initialize);
        events.push_back({1, id, (int)mode});
    }
    void SetPullMode(TGPIOPullMode pull) { assert(id >= 0); events.push_back({2, id, (int)pull}); }
    void Write(unsigned v) { assert(id >= 0 && v <= 1); events.push_back({3, id, (int)v}); }
    static void WriteAll(u32 value, u32 mask) {
        for (int i = 0; i < 32; ++i) if (mask & (u32(1) << i)) {
            events.push_back({3, i, !!(value & (u32(1) << i))});
        }
    }
    static u32 ReadAll() { return pad_levels; }
};
#endif
'''
MACHINE_STUB = r'''
#ifndef TEST_MACHINE_H
#define TEST_MACHINE_H
enum TMachineModel { MachineModelBRelease1MB256, MachineModelBRelease2MB256,
    MachineModelBRelease2MB512, MachineModelUnknown, MachineModelBPlus };
extern TMachineModel test_model;
class CMachineInfo {
public:
    static CMachineInfo *Get() { static CMachineInfo info; return &info; }
    TMachineModel GetMachineModel() const { return test_model; }
};
#endif
'''
BRIDGE_TEST = r'''
#include <circle/gpiopin.h>
#include <circle/machineinfo.h>
#include "gpio_bridge.h"
#include <cstdio>
std::vector<Event> events;
u32 pad_levels;
TMachineModel test_model = MachineModelBRelease1MB256;
static const char owner_a = 0, owner_b = 0;
int main() {
    const void *a = &owner_a, *b = &owner_b;
    assert(events.empty()); // Static Circle constructors must not touch hardware.
    test_model = MachineModelUnknown;
    assert(mpynn_gpio_validate(4) == MPYNN_GPIO_BOARD);
    test_model = MachineModelBPlus;
    assert(mpynn_gpio_validate(4) == MPYNN_GPIO_BOARD);
    test_model = MachineModelBRelease1MB256;
    assert(mpynn_gpio_validate(0) == 0 && mpynn_gpio_validate(21) == 0);
    assert(mpynn_gpio_validate(2) == MPYNN_GPIO_INVALID);
    test_model = MachineModelBRelease2MB256;
    assert(mpynn_gpio_validate(2) == 0 && mpynn_gpio_validate(27) == 0);
    assert(mpynn_gpio_validate(0) == MPYNN_GPIO_INVALID);
    test_model = MachineModelBRelease2MB512;
    assert(mpynn_gpio_claim(14, a) == MPYNN_GPIO_RESERVED);
    assert(mpynn_gpio_claim(15, a) == MPYNN_GPIO_RESERVED);
    assert(mpynn_gpio_claim(16, a) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_claim(-1, a) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_claim(54, a) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_claim(4, nullptr) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_release(4, a) == 0);
    mpynn_gpio_release_all(a);
    assert(events.empty());
    int v = -1;
    assert(mpynn_gpio_read(4, a, &v) == MPYNN_GPIO_UNINITIALIZED);
    assert(mpynn_gpio_write(4, a, 1) == MPYNN_GPIO_UNINITIALIZED);
    assert(mpynn_gpio_configure(4, a, -1, -1, -1) == MPYNN_GPIO_UNINITIALIZED);
    assert(mpynn_gpio_configure(4, a, 2, -1, -1) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_configure(4, a, 1, 3, -1) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_configure(4, a, 1, 0, 2) == MPYNN_GPIO_INVALID);
    assert(events.empty());
    assert(mpynn_gpio_claim(4, b) == 0); // Invalid init did not claim.
    assert(mpynn_gpio_claim(4, b) == 0);
    assert(mpynn_gpio_claim(4, a) == MPYNN_GPIO_BUSY);
    assert(mpynn_gpio_release(4, a) == MPYNN_GPIO_BUSY);
    assert(mpynn_gpio_configure(4, a, 1, 0, 1) == MPYNN_GPIO_BUSY);
    assert(events.empty());
    assert(mpynn_gpio_configure(4, b, 1, 0, 1) == 0);
    assert(events.size() == 4);
    assert(events[0].operation == 0); // Assign only once.
    assert(events[2].operation == 3 && events[2].value == 1); // Latch first.
    assert(events[3].operation == 1 && events[3].value == GPIOModeOutput);
    events.clear();
    mpynn_gpio_release_all(a);
    assert(events.empty()); // Must not touch a different owner.
    assert(mpynn_gpio_configure(4, b, 0, 1, -1) == 0);
    assert(events[0].operation == 1 && events[0].value == GPIOModeInput);
    assert(events[1].operation == 2 && events[1].value == GPIOPullModeUp);
    assert(events[2].operation == 3 && events[2].value == 1);
    events.clear();
    assert(mpynn_gpio_write(4, b, 0) == 0);
    assert(events.size() == 1 && events[0].operation == 3 && events[0].value == 0);
    events.clear();
    assert(mpynn_gpio_configure(4, b, 1, -1, -1) == 0);
    assert(events[1].operation == 3 && events[1].value == 0);
    assert(events[2].operation == 1 && events[2].value == GPIOModeOutput);
    pad_levels = u32(1) << 4;
    assert(mpynn_gpio_read(4, b, &v) == 0 && v == 1);
    assert(mpynn_gpio_read(4, a, &v) == MPYNN_GPIO_BUSY);
    assert(mpynn_gpio_read(4, b, nullptr) == MPYNN_GPIO_INVALID);
    events.clear();
    assert(mpynn_gpio_configure(4, b, 1, 99, 0) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_write(4, b, 2) == MPYNN_GPIO_INVALID);
    assert(events.empty());
    assert(mpynn_gpio_configure(7, a, 1, 0, 1) == 0);
    events.clear();
    mpynn_gpio_release_all(b);
    assert(events.size() == 2);
    assert(events[0].pin == 4 && events[0].operation == 1 && events[0].value == GPIOModeInput);
    assert(events[1].pin == 4 && events[1].operation == 2 && events[1].value == GPIOPullModeOff);
    events.clear();
    assert(mpynn_gpio_write(4, b, 1) == MPYNN_GPIO_UNINITIALIZED);
    assert(mpynn_gpio_release(4, b) == 0);
    mpynn_gpio_release_all(b);
    assert(events.empty());
    assert(mpynn_gpio_write(7, a, 0) == 0);
    events.clear();
    assert(mpynn_gpio_configure(4, a, 1, -1, -1) == 0);
    assert(events.size() == 3); // No second AssignPin after release/reclaim.
    assert(events[1].operation == 3 && events[1].value == 0);
    mpynn_gpio_release_all(a);
    std::puts("PASS: real bridge with fake Circle: ownership, validation, release, latch ordering");
}
'''


class PinPolicyTests(unittest.TestCase):
    def test_policy_compiles_and_runs_as_c(self):
        compiler = shutil.which(CC)
        if compiler is None:
            self.skipTest(f"Host C compiler not found: {CC}")
        env = os.environ.copy()
        # MSYS2's native GCC/cc1 need their runtime DLL directory on PATH.
        env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
        with tempfile.TemporaryDirectory(prefix="mpynn-pin-policy-") as temp:
            source = Path(temp) / "policy.c"
            binary = Path(temp) / ("policy.exe" if os.name == "nt" else "policy")
            source.write_text(C_TEST, encoding="utf-8")
            subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                "-I", str(PORT), str(source), "-o", str(binary),
            ], check=True, env=env)
            subprocess.run([str(binary)], check=True, env=env)

    def test_real_bridge_with_recording_circle(self):
        compiler = shutil.which(CC)
        if compiler is None:
            self.skipTest(f"Host C compiler not found: {CC}")
        env = os.environ.copy()
        env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
        with tempfile.TemporaryDirectory(prefix="mpynn-gpio-bridge-") as temp:
            root = Path(temp)
            circle = root / "circle"
            circle.mkdir()
            (circle / "gpiopin.h").write_text(GPIO_STUB, encoding="utf-8")
            (circle / "machineinfo.h").write_text(MACHINE_STUB, encoding="utf-8")
            source = root / "bridge_test.cpp"
            source.write_text(BRIDGE_TEST, encoding="utf-8")
            binary = root / ("bridge.exe" if os.name == "nt" else "bridge")
            subprocess.run([
                compiler, "-x", "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-I", str(root), "-I", str(PORT), str(source),
                str(PORT / "gpio_bridge.cpp"), "-lstdc++", "-o", str(binary),
            ], check=True, env=env)
            subprocess.run([str(binary)], check=True, env=env)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default=CC)
    args, remaining = parser.parse_known_args()
    CC = args.cc
    unittest.main(argv=[__file__, *remaining])
