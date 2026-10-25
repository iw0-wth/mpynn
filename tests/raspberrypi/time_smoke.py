# SPDX-License-Identifier: MIT
"""Read-only wall-clock consistency test for the board."""
import machine
import time

rtc = machine.RTC()
before = time.time()
date = rtc.datetime()
after = time.time()
assert before <= time.mktime((date[0], date[1], date[2], date[4], date[5], date[6], date[3], 0)) <= after
assert time.gmtime(946684800)[:6] == (2000, 1, 1, 0, 0, 0)
assert time.localtime(946684800) == time.gmtime(946684800)
assert time.time_ns() // 1000000000 >= before
start = time.ticks_ms()
time.sleep_ms(20)
assert time.ticks_diff(time.ticks_ms(), start) >= 20
print('MPYNN_RTC_TIME_CONSISTENCY_PASS')
