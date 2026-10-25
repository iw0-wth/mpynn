# SPDX-License-Identifier: MIT
"""Execute standalone server demo against fake sockets, no network traffic."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[2]/'demo/network/tcp.py'
class TcpServerDemoTests(unittest.TestCase):
    def run_demo(self, port):
        spec=importlib.util.spec_from_file_location('tcp_demo',SOURCE)
        demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
        accepted=Mock();accepted.recv.return_value=b''
        listener=Mock();listener.getsockname.return_value=('0.0.0.0',60001)
        listener.accept.return_value=(accepted,('192.0.2.1',5000))
        socket=types.SimpleNamespace(socket=Mock(return_value=listener),AF_INET=2,SOCK_STREAM=1)
        with patch.dict('sys.modules',{'socket':socket}),patch.object(demo,'_lan_ready'),patch('builtins.print') as output:
            demo.server(port=port)
        if port is None:listener.bind.assert_not_called()
        else:listener.bind.assert_called_once_with(('0.0.0.0',port))
        listener.listen.assert_called_once_with(1);listener.getsockname.assert_called_once_with()
        self.assertIn("60001",str(output.call_args_list))
        accepted.close.assert_called_once_with();listener.close.assert_called_once_with()
        accepted.sendall.assert_not_called()

    def test_implicit_listen_no_bind(self):self.run_demo(None)
    def test_explicit_ephemeral_bind(self):self.run_demo(0)
    def test_default_named_port(self):self.run_demo(5006)

if __name__=='__main__':unittest.main()
