# SPDX-License-Identifier: MIT
"""Run the actual board UDP demo with a fake socket, including an empty packet."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

class UDPBoardEcho(unittest.TestCase):
    def test_empty_datagram_echoes_and_socket_closes(self):
        peer=('192.0.2.1',1234)
        class Socket:
            closed=False
            sent=[]
            incoming=iter([(b'',peer),(b'abc',peer)])
            def settimeout(self,v): self.timeout=v
            def bind(self,addr): self.bound=addr
            def recvfrom(self,n): return next(self.incoming)
            def sendto(self,data,destination): self.sent.append((data,destination));return len(data)
            def close(self): self.closed=True
        sock=Socket()
        modules={
            'network':types.SimpleNamespace(LAN=lambda:types.SimpleNamespace(isconnected=lambda:True,ifconfig=lambda:('192.0.2.2',)*4)),
            'socket':types.SimpleNamespace(AF_INET=2,SOCK_DGRAM=2,socket=lambda *args:sock)
        }
        spec=importlib.util.spec_from_file_location('board_udp_demo',HERE/'udp_echo_demo.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules',modules),patch('builtins.print'):
            spec.loader.exec_module(module)
            module.run(packets=2)
        self.assertEqual(sock.sent,[(b'',peer),(b'abc',peer)])
        self.assertTrue(sock.closed)

if __name__=='__main__':unittest.main()
