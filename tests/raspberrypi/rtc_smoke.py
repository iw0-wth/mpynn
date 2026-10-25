# SPDX-License-Identifier: MIT
# Board-side software-clock reads only. Does not set time or write storage.
from machine import RTC
import time

rtc = RTC()
assert rtc is RTC(0)
date = rtc.datetime()
assert len(date) == 8 and 1970 <= date[0] <= 2038
assert 1 <= date[1] <= 12 and 1 <= date[2] <= 31
assert 0 <= date[3] <= 6
start = time.time()
time.sleep_ms(1100)
assert time.time() >= start + 1
try:
    RTC(1)
except ValueError:
    pass
else:
    raise AssertionError('unsupported RTC id accepted')
print('RTC_SOFTWARE_CLOCK_PASS (not battery-backed)')
