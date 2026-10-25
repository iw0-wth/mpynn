# SPDX-License-Identifier: MIT
"""PC demo contract with fake sockets; does not send network packets."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('udp_echo_client', Path(__file__).with_name('udp_echo_client.py'))
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class FakeSocket:
    def __init__(self, mode='ok'):
        self.mode, self.sent, self.closed = mode, [], False
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def settimeout(self, value): self.timeout = value
    def sendto(self, data, peer):
        self.sent.append((data, peer))
        return len(data) - (self.mode == 'partial')
    def recvfrom(self, length):
        if self.mode == 'timeout': raise TimeoutError('fake timeout')
        data, peer = self.sent[-1]
        if self.mode == 'corrupt': data += b'!'
        if self.mode == 'peer': peer = ('192.0.2.99', peer[1])
        return data, peer


class EchoClientTests(unittest.TestCase):
    def test_success_compares_three_datagrams_and_closes(self):
        fake = FakeSocket()
        with patch.object(demo.socket, 'socket', return_value=fake), patch('builtins.print') as output:
            demo.run('192.0.2.10')
            self.assertTrue(any(call.args == ('UDP_ECHO_ROUNDTRIP_PASS',) for call in output.call_args_list))
        self.assertEqual([len(data) for data, _ in fake.sent], [14, 256, 1283])
        self.assertEqual(fake.timeout, 5)
        self.assertTrue(fake.closed)

    def test_failures_never_report_pass_and_always_close(self):
        for mode in ('timeout', 'corrupt', 'peer', 'partial'):
            with self.subTest(mode=mode):
                fake = FakeSocket(mode)
                with patch.object(demo.socket, 'socket', return_value=fake), patch('builtins.print') as output:
                    with self.assertRaises((RuntimeError, TimeoutError)):
                        demo.run('192.0.2.10')
                    self.assertFalse(any(call.args == ('UDP_ECHO_ROUNDTRIP_PASS',) for call in output.call_args_list))
                self.assertTrue(fake.closed)

    def test_bad_destination_rejected_before_socket_creation(self):
        with patch.object(demo.socket, 'socket') as create:
            for host, port in [('example.com', 5005), ('::1', 5005), ('192.0.2.1', 0), ('192.0.2.1', 65536)]:
                with self.assertRaises(ValueError): demo.run(host, port)
            create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
