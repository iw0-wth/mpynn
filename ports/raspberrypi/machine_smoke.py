# SPDX-License-Identifier: MIT
"""Small machine API smoke checks for board acceptance."""
import machine

def run():
    assert hasattr(machine, 'I2C') and hasattr(machine, 'SPI') and hasattr(machine, 'WDT')
    assert hasattr(machine, 'SoftI2C') and hasattr(machine, 'SoftSPI')
    assert hasattr(machine, 'Timer')
    print('MACHINE_SURFACE_PASS')
