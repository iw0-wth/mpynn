# SPDX-License-Identifier: MIT
"""Strict host lifecycle tests for the Circle-backed machine Timer bridge.

The temporary Circle double stores kernel timer callbacks and can fire them as
an IRQ would. No firmware, build tree, or hardware is used.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / "ports/raspberrypi"
GXX = Path("E:/msys64/ucrt64/bin/g++.exe")

class MachineTimerHostTests(unittest.TestCase):
    def test_generation_lifecycle_and_coalescing(self):
        if not GXX.is_file():
            self.skipTest("host C++ compiler unavailable")
        headers = {
            "circle/types.h": "#pragma once\ntypedef unsigned long long u64;\ntypedef unsigned TKernelTimerHandle;\n",
            "circle/synchronize.h": """#pragma once
#define IRQ_LEVEL 1
inline void EnterCritical(unsigned) {}
inline void LeaveCritical() {}
""",
            "circle/timer.h": """#pragma once
#include <vector>
#include <stdint.h>
typedef unsigned TKernelTimerHandle;
typedef void TKernelTimerHandler(TKernelTimerHandle, void *, void *);
class CTimer {
public:
 static CTimer *Get();
 TKernelTimerHandle StartKernelTimer(unsigned, TKernelTimerHandler *, void *, void * = 0);
 void CancelKernelTimer(TKernelTimerHandle);
 void fire();
 unsigned starts = 0, cancels = 0;
private:
 TKernelTimerHandler *handler = nullptr; void *param = nullptr;
 TKernelTimerHandle handle = 0;
};
""",
        }
        harness = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include "circle/timer.h"
#include "machine_timer.h"
static CTimer timer;
CTimer *CTimer::Get() { return &timer; }
TKernelTimerHandle CTimer::StartKernelTimer(unsigned, TKernelTimerHandler *h, void *p, void *) {
    handler = h; param = p; handle = ++starts; return handle;
}
void CTimer::CancelKernelTimer(TKernelTimerHandle h) {
    if (h == handle) { ++cancels; handler = nullptr; param = nullptr; handle = 0; }
}
void CTimer::fire() { if (handler) handler(handle, param, nullptr); }
static void check(bool v) { if (!v) std::abort(); }
int main() {
    unsigned slot = 99; check(mpynn_timer_slot_acquire(&slot) == MPYNN_TIMER_OK && slot == 0);
    check(mpynn_timer_start(slot, 2, 1, 7) == MPYNN_TIMER_OK);
    timer.fire();
    uint32_t gen = 0; check(mpynn_timer_event(slot, &gen) == MPYNN_TIMER_OK && gen == 7);
    check(mpynn_timer_event_claim(slot, 7) == MPYNN_TIMER_OK);
    // A second poll cannot duplicate an event while one callback is queued.
    check(mpynn_timer_event(slot, &gen) == MPYNN_TIMER_BUSY);
    // Full scheduler queues return the event for retry rather than dropping it.
    mpynn_timer_event_release(slot, 7);
    check(mpynn_timer_event(slot, &gen) == MPYNN_TIMER_OK);
    check(mpynn_timer_event_claim(slot, 7) == MPYNN_TIMER_OK);
    mpynn_timer_complete(slot, 7);
    check(timer.starts == 2); // periodic rearmed only after VM completion
    // Reinitialisation/deinit invalidates stale queued generations.
    check(mpynn_timer_stop(slot) == MPYNN_TIMER_OK);
    check(mpynn_timer_event(slot, &gen) == MPYNN_TIMER_BUSY);
    mpynn_timer_slot_release(slot);
    check(mpynn_timer_slot_acquire(&slot) == MPYNN_TIMER_OK);
    check(mpynn_timer_start(slot, 1, 0, 8) == MPYNN_TIMER_OK);
    timer.fire(); check(mpynn_timer_event_claim(slot, 7) == MPYNN_TIMER_BUSY);
    check(mpynn_timer_event_claim(slot, 8) == MPYNN_TIMER_OK);
    mpynn_timer_complete(slot, 8);
    check(mpynn_timer_event(slot, &gen) == MPYNN_TIMER_BUSY);
    check(mpynn_timer_deinit_all() == MPYNN_TIMER_OK);
    check(mpynn_timer_event(slot, &gen) == MPYNN_TIMER_BUSY);
    unsigned held[MPYNN_TIMER_SLOTS];
    for (unsigned i = 0; i < MPYNN_TIMER_SLOTS; ++i) check(mpynn_timer_slot_acquire(&held[i]) == MPYNN_TIMER_OK);
    check(mpynn_timer_slot_acquire(&slot) == MPYNN_TIMER_BUSY);
    for (unsigned i = 0; i < MPYNN_TIMER_SLOTS; ++i) mpynn_timer_slot_release(held[i]);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, text in headers.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            src = root / "harness.cpp"; src.write_text(harness)
            exe = root / "timer.exe"
            env = os.environ.copy(); env["PATH"] = str(GXX.parent) + os.pathsep + env.get("PATH", "")
            cmd = [str(GXX), "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I" + str(root), "-iquote", str(PORT), str(PORT / "machine_timer.cpp"), str(src), "-o", str(exe)]
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == "__main__":
    unittest.main()
