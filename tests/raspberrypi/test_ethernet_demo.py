# SPDX-License-Identifier: MIT
"""Exercise the board demo with fake time/LAN, never a physical network."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class DemoTests(unittest.TestCase):
    def run_demo(self, initialized=True, connected=True):
        clock = [0]
        config = ('192.0.2.10', '255.255.255.0', '192.0.2.1', '192.0.2.1')
        lan = SimpleNamespace(active=lambda: initialized, isconnected=lambda: connected,
                              ifconfig=lambda: config)
        modules = {
            'network': SimpleNamespace(LAN=lambda: lan),
            'machine': SimpleNamespace(board_info=lambda: {}, logs=lambda: b'', network_info=lambda: {}),
            'time': SimpleNamespace(ticks_ms=lambda: clock[0], ticks_diff=lambda a, b: a-b,
                                   sleep_ms=lambda ms: clock.__setitem__(0, clock[0]+ms)),
        }
        spec = importlib.util.spec_from_file_location('board_demo', Path(__file__).with_name('ethernet_demo.py'))
        demo = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules), patch('builtins.print'):
            spec.loader.exec_module(demo)
            return demo.run(timeout_ms=300, observe_ms=300)

    def test_ready_returns_ipv4_without_socket_claim(self):
        self.assertEqual(self.run_demo()[0], '192.0.2.10')

    def test_absent_nic_is_failure(self):
        with self.assertRaises(OSError):
            self.run_demo(initialized=False)

    def test_dhcp_timeout_is_not_success(self):
        with self.assertRaises(OSError):
            self.run_demo(connected=False)


if __name__ == '__main__':
    unittest.main()
