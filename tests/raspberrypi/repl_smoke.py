# SPDX-License-Identifier: MIT
# Run on the actual Pi UART REPL using paste mode (Ctrl-E), not on CPython.
import gc
import sys
import time
import json
import select

assert sys.platform == "raspberrypi"
assert sys.implementation.version[:2] == (1, 29)
assert f"{6 * 7:04d}" == "0042"
assert f"{'mpynn'!r}" == "'mpynn'"
assert f"{1.25:.2f}" == "1.25"
assert 2 ** 80 > 2 ** 64
assert json.loads('{"value":42}')["value"] == 42

# Catch regressions in register/stack root capture and exception unwinding.
def stress():
    survivors = [bytearray([n % 251]) * 97 for n in range(200)]
    for n in range(100):
        value = (n + 1) * 1.25
        try:
            garbage = [bytearray(100) for _ in range(30)]
            gc.collect()
            raise ValueError("expected")
        except ValueError:
            assert abs(value - (n + 1) * 1.25) < 0.001
        assert survivors[n][0] == n % 251
    return len(survivors)

assert stress() == 200
start = time.ticks_ms()
time.sleep_ms(20)
assert time.ticks_diff(time.ticks_ms(), start) >= 20
poller = select.poll()
poller.register(sys.stdout, select.POLLOUT)
assert poller.poll(0)
gc.collect()
print("MPYNN_PI1_REPL_SMOKE_PASS", gc.mem_free())
# Also test manually: Ctrl-C interrupts `while True: pass`; Ctrl-D at a blank
# prompt performs a soft reboot. Repeat this script after 20 soft reboots.
