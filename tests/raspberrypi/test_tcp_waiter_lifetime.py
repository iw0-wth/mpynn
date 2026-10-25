# SPDX-License-Identifier: MIT
"""Compile extracted real Connect/IsTerminated methods with a deterministic event.

Not a full Circle TCP simulation. Covers waiter lifetime ordering only; an ARM
build separately compiles the full translation unit and real class declaration.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class WaiterLifetimeTests(unittest.TestCase):
    def test_closed_connection_is_pinned_until_wait_returns(self):
        if not CXX.is_file():
            self.skipTest('host g++ unavailable')
        source = (ROOT/'ports/raspberrypi/upstream_overrides/circle/lib/net/tcpconnection.cpp').read_text()
        methods = '\n'.join(method(source, signature) for signature in (
            'int CTCPConnection::Connect (void)',
            'boolean CTCPConnection::IsTerminated (void) const',
            'boolean CTCPConnection::IsReceiveEOF (void) const',
            'int CTCPConnection::GetTerminalError (void) const',
            'boolean CTCPConnection::IsAcceptReady (void) const',
            'int CTCPConnection::Accept (CIPAddress *pForeignIP, u16 *pForeignPort)'))
        header = (ROOT/'ports/raspberrypi/upstream_overrides/circle/include/circle/net/tcpconnection.h').read_text()
        self.assertIn('unsigned m_nConnectWaiters = 0;', header)
        harness = r'''
#include <cassert>
#include <functional>
using boolean = bool;
#define NET_ERROR_INVALID_VALUE 14
#define NET_ERROR_CONNECTION_RESET 54
using u16 = unsigned short;
struct CIPAddress { unsigned value=0; void Set(const CIPAddress &ip) {value=ip.value;} };
#define UNEXPECTED_STATE() ((void)0)
enum State { TCPStateSynSent, TCPStateSynReceived, TCPStateEstablished,
 TCPStateListen, TCPStateFinWait1, TCPStateFinWait2, TCPStateCloseWait,
 TCPStateClosing, TCPStateLastAck, TCPStateTimeWait, TCPStateClosed };
struct Event {
 std::function<void()> callback;
 void Clear() {}
 void Wait() { callback(); }
};
struct CTCPConnection {
 unsigned m_nConnectWaiters = 0;
 int m_nErrno = 0;
 State m_State = TCPStateSynSent;
 Event m_Event;
 bool m_bFINReceived=false, m_bActiveOpen=false, m_bReadShutdown=false;
 bool IsAcceptReady() const;
 CIPAddress m_ForeignIP;
 u16 m_nForeignPort=5006;
 int Accept(CIPAddress *, u16 *);
 struct Queue { bool empty=true; bool IsEmpty() const {return empty;} } m_RxQueue;
 int Connect(); bool IsTerminated() const;
 bool IsReceiveEOF() const; int GetTerminalError() const;
};
''' + methods + r'''
int main() {
 for (auto initial : {TCPStateSynSent, TCPStateSynReceived}) {
  for (int error : {-54, -57}) { // RST or timeout wakes the pending Connect
   CTCPConnection c; c.m_State = initial;
   c.m_Event.callback = [&]() {
    assert(c.m_nConnectWaiters == 1);
    c.m_State = TCPStateClosed; c.m_nErrno = error;
    // Same network task iteration reaches its cleanup before waiter resumes.
    assert(!c.IsTerminated());
   };
   assert(c.Connect() == error);
   assert(c.m_nConnectWaiters == 0 && c.IsTerminated());
  }
 }
 CTCPConnection c;
 c.m_Event.callback = [&]() { c.m_State=TCPStateEstablished; assert(!c.IsTerminated()); };
 assert(c.Connect()==0 && c.m_nConnectWaiters==0 && !c.IsTerminated());
 c.m_State=TCPStateClosed; c.m_nErrno=0;
 assert(c.Connect()==-NET_ERROR_INVALID_VALUE && c.IsTerminated());
 c.m_nErrno=-54;
 assert(c.Connect()==-54 && c.m_nConnectWaiters==0);
 assert(c.GetTerminalError()==-54 && !c.IsReceiveEOF());
 c.m_nErrno=0; assert(!c.IsReceiveEOF());
 c.m_bFINReceived=true; c.m_RxQueue.empty=false;
 assert(!c.IsReceiveEOF());
 c.m_RxQueue.empty=true; assert(c.IsReceiveEOF());
 c.m_State=TCPStateCloseWait; c.m_ForeignIP.value=42;
 CIPAddress peer; u16 port=0;
 assert(c.Accept(&peer,&port)==0 && peer.value==42 && port==5006);
 c.m_nErrno=-54; assert(!c.IsReceiveEOF() && c.GetTerminalError()==-54);
 assert(c.Accept(&peer,&port)==-54);
 for (int state=TCPStateSynSent;state<=TCPStateClosed;++state) {
  c.m_State=(State)state; c.m_nErrno=0; c.m_bActiveOpen=false;
  assert(c.IsAcceptReady()==(state==TCPStateEstablished || state==TCPStateCloseWait));
  c.m_nErrno=-54; assert(!c.IsAcceptReady());
  c.m_nErrno=0; c.m_bActiveOpen=true; assert(!c.IsAcceptReady());
 }
}
'''
        env = os.environ.copy()
        env['PATH'] = str(CXX.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src, exe = root/'test.cpp', root/'test.exe'
            src.write_text(harness)
            for cmd in ([str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                         str(src), '-o', str(exe)], [str(exe)]):
                r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0, r.stdout+r.stderr)


if __name__ == '__main__':
    unittest.main()
