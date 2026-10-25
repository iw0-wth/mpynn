# SPDX-License-Identifier: MIT
# Run via UART paste mode on a Pi 1B. No GPIO output is driven by this script.
import machine
from machine import Pin
import gc

info = machine.board_info()
print(info)
assert isinstance(info['revision'], int)
assert info['ram_mb'] >= 256
serial = machine.unique_id()
assert isinstance(serial, bytes) and len(serial) == 8
assert machine.unique_id() == serial
assert isinstance(machine.freq(), int) and machine.freq() > 0
try:
    machine.freq(700000000)
    raise AssertionError('frequency setter unexpectedly accepted')
except NotImplementedError:
    pass

# Check nesting without making mailbox/printing calls inside a masked section.
a = machine.disable_irq()
b = machine.disable_irq()
machine.enable_irq(b)
c = machine.disable_irq()
machine.enable_irq(a)
assert a == 0 and b == 128 and c == 128
machine.idle()

# Pi 1B P1 GPIO4 is shared across Rev1/Rev2. Keep INPUT, no pull, no drive.
p = Pin(4)
assert Pin(4) is p and Pin(p) is p
try:
    p.value()
    raise AssertionError('uninitialized pin should not be accessed')
except ValueError:
    pass
p.init(Pin.IN, pull=None)
assert p.value() in (0, 1)
gc.collect()
assert Pin(4) is p
p.deinit()
p.deinit()  # idempotent

for invalid in (-1, 5, 6, 14, 15, 16, 19, 20, 31, 32, 53):
    try:
        Pin(invalid)
        raise AssertionError('accepted hidden/reserved GPIO %d' % invalid)
    except ValueError:
        pass

# These classes/features must not be advertised before their implementations.
for feature in ('ADC', 'DAC', 'UART', 'PWM', 'Timer',
                'lightsleep', 'deepsleep', 'reset_cause'):
    assert not hasattr(machine, feature), feature
print('MPYNN_MACHINE_BASE_SMOKE_PASS')

# Manual separate tests (not automatic):
# 1. Initialize Pin(4, Pin.IN), call machine.soft_reset(), rerun this script.
# 2. `state=machine.disable_irq(); machine.soft_reset()` must recover the REPL.
# 3. `machine.reset()` must actually restart the board and show its boot banner.
# 4. Verify Rev1 permits GPIO0/1/21 and rejects2/3/27; Rev2 vice versa.
# 5. With external circuits disconnected, scope Pin(4, Pin.OUT, value=1) for
#    unwanted initial-low pulses; then check on/off and deinit -> high impedance.
