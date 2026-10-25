# SPDX-License-Identifier: MIT
"""Execute unchanged upstream ntptime with fake network/RTC; no real queries."""
import importlib.util
from pathlib import Path
import struct
import time
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'lib/micropython/lib/micropython-lib/micropython/net/ntptime/ntptime.py'

class NTPTests(unittest.TestCase):
    def test_ntptime_sets_rtc_through_standard_datetime_api(self):
        epoch=1735689600
        response=bytearray(48);response[40:44]=struct.pack('!I',epoch+2208988800)
        class Socket:
            closed=False
            def settimeout(self,v):self.timeout=v
            def sendto(self,q,addr):self.sent=(bytes(q),addr);return len(q)
            def recv(self,n):assert n==48;return bytes(response)
            def close(self):self.closed=True
        socket=Socket();dates=[]
        fake_socket=types.SimpleNamespace(AF_INET=2,SOCK_DGRAM=2,
            socket=lambda *args:socket,getaddrinfo=lambda host,port:[(2,2,0,'',('192.0.2.1',port))])
        # Match this port's eight-field, UTC, Unix-epoch gmtime tuple.
        fake_time=types.SimpleNamespace(gmtime=lambda epoch:tuple(time.gmtime(epoch))[:8])
        spec=importlib.util.spec_from_file_location('upstream_ntptime',SOURCE)
        module=importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules',{'socket':fake_socket,'time':fake_time,
                                     'machine':types.SimpleNamespace(RTC=lambda:types.SimpleNamespace(datetime=dates.append))}):
            spec.loader.exec_module(module)
            module.settime()
        self.assertEqual(dates,[(2025,1,1,3,0,0,0,0)])
        self.assertEqual(socket.sent[0][0],0x23)
        self.assertEqual(socket.sent[1],('192.0.2.1',123))
        self.assertTrue(socket.closed)

if __name__=='__main__':unittest.main()
