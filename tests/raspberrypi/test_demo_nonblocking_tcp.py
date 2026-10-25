# SPDX-License-Identifier: MIT
"""Execute independent demo with fake IO; never contact a network."""
import errno
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[2]/'demo/network/tcp.py'
class NonblockingDemoTests(unittest.TestCase):
    def run_demo(self, error=0, flags=4):
        spec=importlib.util.spec_from_file_location('demo_tcp',SOURCE)
        demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
        client=Mock()
        client.connect.side_effect=OSError(errno.EINPROGRESS)
        client.getsockopt.return_value=error
        client.getpeername.return_value=('192.0.2.1',5006)
        client.getsockname.return_value=('192.0.2.2',60001)
        poller=Mock();poller.poll.return_value=[(client,flags)]
        socket=types.SimpleNamespace(socket=Mock(return_value=client),AF_INET=2,SOCK_STREAM=1,
            SOL_SOCKET=0x0fff,SO_ERROR=0x1007,getaddrinfo=Mock(return_value=[(2,1,6,'',('192.0.2.1',5006))]))
        select=types.SimpleNamespace(poll=Mock(return_value=poller),POLLOUT=4,POLLERR=8,POLLHUP=16,POLLNVAL=32)
        time=types.SimpleNamespace(ticks_ms=lambda:0,ticks_diff=lambda a,b:a-b)
        with patch.dict('sys.modules',{'socket':socket,'select':select,'time':time}),patch.object(demo,'_lan_ready'),patch('builtins.print'):
            if error or flags & (8|16|32):
                with self.assertRaises(OSError) as raised:demo.connect_nonblocking('192.0.2.1')
                expected=error or (errno.EBADF if flags&32 else errno.ENOTCONN)
                self.assertEqual(raised.exception.args[0],expected)
            else:
                demo.connect_nonblocking('192.0.2.1')
                client.getpeername.assert_called_once_with()
        client.close.assert_called_once_with();poller.unregister.assert_called_once_with(client)
        client.send.assert_not_called();client.recv.assert_not_called()
        return client

    def test_success_poll_then_so_error_peer(self):
        client=self.run_demo()
        client.getsockopt.assert_called_once_with(0x0fff,0x1007)

    def test_connection_refused_closes_and_propagates(self):
        client=self.run_demo(errno.ECONNREFUSED,8)
        client.getpeername.assert_not_called()

    def test_hangup_zero_error_not_treated_as_success(self):self.run_demo(0,16)
    def test_invalid_poll_socket_closes(self):self.run_demo(0,32)

if __name__=='__main__':unittest.main()
