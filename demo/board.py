# SPDX-License-Identifier: MIT
"""REPL: from demo import board; board.show()  (不写盘、不联网)。"""


def show():
    import sys
    import os
    import machine
    print('MicroPython:', sys.implementation)
    print('Board/build:', machine.board_info())
    print('Storage:', machine.storage_info())
    print('RTC UTC:', machine.RTC().datetime())
    print('Root:', os.listdir('/'))
    print('BOARD_INFO_OK')


if __name__ == '__main__':
    show()
