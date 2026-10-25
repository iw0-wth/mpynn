# SPDX-License-Identifier: MIT
"""Board scripts must not mistake EIO for a successful nonblocking receive."""
import errno
from pathlib import Path
import runpy
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

class Socket:
    def __init__(self, result): self.result=result; self.closed=False
    def settimeout(self, value): assert value==0
    def bind(self, address): assert address==('0.0.0.0',0)
    def sendto(self,*args): raise AssertionError('script must not send')
    def recvfrom(self,size):
        if isinstance(self.result,BaseException): raise self.result
        return self.result
    def close(self): self.closed=True

class SmokeContracts(unittest.TestCase):
    def test_only_eagain_passes_and_socket_always_closes(self):
        for name in ('api_contract_smoke.py','network_socket_contract.py'):
            for result in (OSError(errno.EAGAIN),OSError(errno.EIO),OSError(),(b'packet',('192.0.2.1',9))):
                with self.subTest(script=name,result=result):
                    sock=Socket(result)
                    lan=types.SimpleNamespace(active=lambda:True,ifconfig=lambda:('192.0.2.2',)*4)
                    rtc=types.SimpleNamespace(datetime=lambda:(2000,1,1,5,0,0,0,0))
                    modules={
                        'machine':types.SimpleNamespace(RTC=lambda *args:rtc),
                        'network':types.SimpleNamespace(LAN=lambda:lan),
                        'socket':types.SimpleNamespace(AF_INET=2,SOCK_DGRAM=2,socket=lambda *args:sock),
                    }
                    with patch.dict('sys.modules',modules),patch('builtins.print') as output:
                        if isinstance(result,OSError) and result.args==(errno.EAGAIN,):
                            runpy.run_path(str(HERE/name),run_name='__main__')
                            self.assertTrue(output.called)
                        else:
                            with self.assertRaises((OSError,AssertionError)):
                                runpy.run_path(str(HERE/name),run_name='__main__')
                            output.assert_not_called()
                    self.assertTrue(sock.closed)

if __name__=='__main__':unittest.main()
