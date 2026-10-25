# SPDX-License-Identifier: MIT
"""Contract checks for software RTC policy, without ARM/Circle hardware."""
from pathlib import Path
import unittest

PORT = Path(__file__).resolve().parents[2] / 'ports/raspberrypi'

class RTCPolicyTests(unittest.TestCase):
    def test_boot_epoch_is_2000_and_not_valid(self):
        kernel = (PORT/'kernel.cpp').read_text()
        self.assertIn('mpynn_rtc_boot_software_epoch(946684800u)', kernel)
        self.assertIn('rtc_valid = false', kernel)
        self.assertIn('rtc_source = 0', kernel)

    def test_explicit_set_marks_user_source(self):
        kernel = (PORT/'kernel.cpp').read_text()
        self.assertIn('rtc_valid = true', kernel)
        self.assertIn('rtc_source = 1', kernel)
        self.assertIn('SetTime(seconds, FALSE)', kernel)

    def test_rtc_placeholder_is_real_clock_adapter(self):
        source = (PORT/'modmachine_port.c').read_text()
        self.assertNotIn('mpynn_rtc_unavailable', source)
        self.assertIn('timeutils_seconds_since_1970', source)
        self.assertIn('mpynn_rtc_get_utc', source)
        self.assertIn('mpynn_rtc_set_utc', source)

if __name__ == '__main__':
    unittest.main()
