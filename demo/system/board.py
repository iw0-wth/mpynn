# SPDX-License-Identifier: MIT
"""REPL: from demo.system import board; board.show()  (不写盘、不联网)。"""


def show():
    import sys
    import os
    import machine
    print('MicroPython:', sys.implementation)
    print('Board/build:', machine.board_info())
    print('Storage:', machine.storage_info())
    print('RTC UTC:', machine.RTC().datetime())
    if hasattr(machine, 'memory_info'):
        print('Memory:', machine.memory_info())
    if hasattr(machine, 'unique_id'):
        print('Unique ID:', machine.unique_id())
    if hasattr(machine, 'freq'):
        print('ARM frequency Hz:', machine.freq())
    if hasattr(machine, 'vc4'):
        print('VC4 allowed:', machine.vc4())
    # Report the exposed surface without configuring pins, buses or watchdogs.
    print('Machine APIs:', [(name, hasattr(machine, name)) for name in
                           ('Pin', 'I2C', 'SoftI2C', 'SPI', 'SoftSPI',
                            'WDT', 'Timer', 'PWM', 'UART', 'ADC')])
    print('Root:', os.listdir('/'))
    print('BOARD_INFO_OK')


if __name__ == '__main__':
    show()
