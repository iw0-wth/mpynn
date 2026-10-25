# SPDX-License-Identifier: MIT
"""软件 RTC 每次冷启动从 2000-01-01 UTC 开始；没有电池保持。

from demo import rtc
rtc.show()
rtc.check()
rtc.set_utc(2026, 5, 1, 12, 30, 0)  # 用户显式校时；按当前 UTC 填写
"""


def show():
    import machine
    import time
    print('RTC UTC:', machine.RTC().datetime())
    print('time UTC:', time.gmtime())
    print('Unix seconds:', time.time())
    print('Software clock; non-persistent, second resolution.')


def check():
    import machine
    import time
    before = time.time()
    date = machine.RTC().datetime()
    after = time.time()
    seconds = time.mktime((date[0], date[1], date[2], date[4], date[5], date[6], date[3], 0))
    assert before <= seconds <= after
    assert time.gmtime(946684800)[:6] == (2000, 1, 1, 0, 0, 0)
    start = time.time()
    time.sleep_ms(1100)
    assert time.time() >= start + 1
    print('RTC_TIME_CONSISTENCY_OK')


def set_utc(year, month, day, hour, minute, second):
    import machine
    machine.RTC().init((year, month, day, hour, minute, second, 0, None))
    show()


if __name__ == '__main__':
    print(__doc__)
