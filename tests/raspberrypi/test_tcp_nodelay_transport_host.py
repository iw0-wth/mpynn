# SPDX-License-Identifier: MIT
"""Compile the real transport TCP_NODELAY dispatcher with native slot doubles."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

# Both unittest discovery and package-style invocation are supported.
if __package__:
    from .test_tcp_send_new_segment_host import method
else:
    from test_tcp_send_new_segment_host import method

ROOT = Path(__file__).resolve().parents[2]
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')

FAKE = r'''
#include <cassert>
#include <vector>
#include <circle/net/in.h>
#include <circle/net/error.h>
using boolean=bool;
struct CNetConnection {
 virtual ~CNetConnection()=default;
 int protocol=IPPROTO_UDP;
 int GetProtocol() const {return protocol;}
};
struct CTCPConnection: CNetConnection {
 bool enabled=true;
 unsigned calls=0;
 CTCPConnection() {protocol=IPPROTO_TCP;}
 int SetOptionNoDelay(boolean value) {enabled=value; ++calls; return 0;}
};
struct CPtrArray {
 std::vector<void*> entries;
 unsigned GetCount() const {return unsigned(entries.size());}
 void *operator[](int index) {assert(index>=0 && unsigned(index)<GetCount()); return entries[index];}
};
struct CTransportLayer {
 CPtrArray m_pConnection;
 int SetOptionNoDelay(boolean, int);
};
'''

HARNESS = r'''
int main() {
 CTransportLayer tr;
 CNetConnection udp;
 CTCPConnection tcp;
 tr.m_pConnection.entries={nullptr,&udp,&tcp};
 for(int handle: {-1,-999,0,3,999})
  assert(tr.SetOptionNoDelay(false,handle)==-NET_ERROR_INVALID_VALUE);
 assert(tr.SetOptionNoDelay(false,1)==-NET_ERROR_PROTOCOL_NOT_SUPPORTED);
 assert(tcp.calls==0 && tcp.enabled);
 assert(tr.SetOptionNoDelay(false,2)==0 && !tcp.enabled);
 assert(tr.SetOptionNoDelay(false,2)==0 && !tcp.enabled);
 assert(tr.SetOptionNoDelay(true,2)==0 && tcp.enabled);
 assert(tr.SetOptionNoDelay(true,2)==0 && tcp.enabled && tcp.calls==4);
 assert(tr.m_pConnection.entries[0]==nullptr && tr.m_pConnection.entries[1]==&udp);
}
'''


@unittest.skipUnless(CXX.is_file(), 'host g++ unavailable')
class TcpNoDelayTransportTests(unittest.TestCase):
    def test_validates_slots_and_protocol_before_tcp_setter(self):
        source = (ROOT/'ports/raspberrypi/upstream_overrides/circle/lib/net/transportlayer.cpp').read_text()
        definition = method(source, 'int CTransportLayer::SetOptionNoDelay (')
        env = os.environ.copy()
        env['PATH'] = str(CXX.parent)+os.pathsep+env.get('PATH', '')
        with tempfile.TemporaryDirectory(prefix='mpynn-tcp-nodelay-transport-') as folder:
            root = Path(folder)
            src, exe = root/'test.cpp', root/'test.exe'
            src.write_text(FAKE+'\n'+definition+'\n'+HARNESS)
            for cmd in ([str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                         '-idirafter', str(ROOT/'lib/circle/include'), str(src), '-o', str(exe)], [str(exe)]):
                result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
