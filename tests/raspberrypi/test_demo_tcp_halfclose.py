# SPDX-License-Identifier: MIT
"""Standalone half-close demo contract; fake sockets, no packets on wire."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[2] / 'demo/network/tcp.py'
PAYLOAD = b'mpynn half-close\x00' + bytes(range(256))

class TcpHalfCloseDemoTests(unittest.TestCase):
    def run_demo(self, replies, write_error=None):
        spec = importlib.util.spec_from_file_location('halfclose_demo', SOURCE)
        demo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(demo)
        sock = Mock()
        sock.shutdown.return_value = None
        sock.send.side_effect = write_error or OSError(32)
        sock.recv.side_effect = replies
        socket = types.SimpleNamespace(socket=Mock(return_value=sock), AF_INET=2,
            SOCK_STREAM=1, SHUT_WR=1, getaddrinfo=Mock(return_value=[(2,1,6,'',('192.0.2.1',5006))]))
        clock = types.SimpleNamespace(ticks_ms=lambda:0, ticks_diff=lambda a,b:a-b)
        with patch.dict('sys.modules', {'socket':socket,'time':clock}), patch.object(demo,'_lan_ready'), patch('builtins.print'):
            try:
                demo.half_close('192.0.2.1')
            finally:
                sock.close.assert_called_once_with()
        self.assertEqual(sock.shutdown.call_args_list, [unittest.mock.call(1), unittest.mock.call(1)])
        sock.sendall.assert_called_once_with(PAYLOAD)
        return sock

    def test_write_halfclosed_but_receive_full_payload_and_eof(self):
        replies = [PAYLOAD[i:i+37] for i in range(0,len(PAYLOAD),37)] + [b'']
        sock = self.run_demo(replies)
        self.assertGreater(sock.recv.call_count, 1)

    def test_wrong_send_error_is_not_hidden(self):
        with self.assertRaises(OSError) as context:
            self.run_demo([], OSError(5))
        self.assertEqual(context.exception.args[0],5)

    def test_partial_echo_before_eof_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'payload mismatch'):
            self.run_demo([b'short',b''])

    def test_excess_echo_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'excess'):
            self.run_demo([PAYLOAD+b'!'])

if __name__ == '__main__':
    unittest.main()
