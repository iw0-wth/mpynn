# SPDX-License-Identifier: MIT
"""Run actual Circle Send/Process/SendNewSegment definitions on the host.

Only queues, timer, event and packet output are doubled. Both readonly upstream
and the port-owned override are exercised: current Circle has no Nagle gate, so
short segments already transmit with outstanding data when both windows permit.
The override adds opt-in Nagle while preserving this historical default.
No firmware build or network I/O is needed.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')
SOURCES = {
    'upstream': ROOT / 'lib/circle/lib/net/tcpconnection.cpp',
    'override': ROOT / 'ports/raspberrypi/upstream_overrides/circle/lib/net/tcpconnection.cpp',
}


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


FAKE = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <string>
#include <vector>
#include <circle/net/in.h>
#include <circle/net/error.h>
using u32 = uint32_t;
using boolean = bool;
#define TRUE true
#define FALSE false
#define NEW_STATE(state) (m_State = state)
enum State { TCPStateClosed, TCPStateListen, TCPStateSynSent, TCPStateSynReceived,
 TCPStateEstablished, TCPStateFinWait1, TCPStateFinWait2, TCPStateCloseWait,
 TCPStateClosing, TCPStateLastAck, TCPStateTimeWait };
enum { TCPTimerRetransmission };
struct CNetBuffer {
 inline static unsigned copies=0;
 u32 length;
 int flags=MSG_DONTWAIT;
 explicit CNetBuffer(u32 n) : length(n) {}
 CNetBuffer(const CNetBuffer &b) : length(b.length), flags(b.flags) { ++copies; }
 u32 GetLength() const { return length; }
 void SetPrivateData(const void *p, unsigned n) {
  assert(n==sizeof(flags)); flags=*static_cast<const int *>(p);
 }
 const void *GetPrivateData() const { return &flags; }
};
struct Queue {
 std::deque<CNetBuffer *> entries;
 ~Queue() { for (auto *p: entries) delete p; }
 const CNetBuffer *Peek() const { return entries.empty()?nullptr:entries.front(); }
 bool IsEmpty() const { return entries.empty(); }
 u32 GetBytesQueued() const { u32 n=0; for(auto *p: entries) n+=p->length; return n; }
 void Enqueue(CNetBuffer *p) { entries.push_back(p); }
 void MoveOn() { assert(!entries.empty()); delete entries.front(); entries.pop_front(); }
};
struct Event {
 unsigned clears=0, sets=0, waits=0;
 void Clear() { ++clears; }
 void Set() { ++sets; }
 void Wait() { ++waits; }
 bool WaitWithTimeout(unsigned) { ++waits; return true; }
};
struct Timer { unsigned ticks=1; unsigned GetTicks() const { return ticks; } };
struct RTO {
 unsigned sent=0;
 u32 sequence=0, length=0;
 unsigned GetRTO() const { return 100; }
 void SegmentSent(u32 seq, u32 n=0) { ++sent; sequence=seq; length=n; }
};
struct CTCPConnection {
 State m_State=TCPStateEstablished, m_StateAfterFIN=TCPStateFinWait1;
 int m_nErrno=0;
 Queue m_TxQueue;
 Event m_Event, m_TxEvent;
 bool m_bNoDelay=true;
 int SetOptionNoDelay(boolean);
 bool m_bTimedOut=false, m_bSendSYN=false, m_bFINQueued=false,
      m_bFINSent=false, m_bRetransmit=false, m_bFastRecovery=false, m_bWriteShutdown=false;
 u32 m_nSND_UNA=100, m_nSND_NXT=120, m_nCWND=4096, m_nSND_WND=4096,
     m_nRCV_NXT=0, m_nISS=99, m_nIW=2144, m_nSSThresh=65535;
 unsigned m_nSND_MSS=536, m_nLastSendTicks=1, m_nSendTimeout=0, m_nDupAckCount=0;
 Timer timer;
 Timer *m_pTimer=&timer;
 RTO m_RTOCalculator;
 unsigned sends=0, timers=0, resends=0, lastFlags=0;
 u32 lastLength=0, lastSequence=0;
 bool SendSegment(unsigned flags, u32 seq, u32=0, CNetBuffer *p=nullptr) {
  ++sends; lastFlags=flags; lastSequence=seq; lastLength=p?p->length:0;
  delete p; return true;
 }
 void StartTimer(unsigned which, unsigned value) {
  assert(which==TCPTimerRetransmission && value==100); ++timers;
 }
 void ResendSegment() { ++resends; }
 int Send(CNetBuffer *, int);
 void Process();
 bool SendNewSegment(u32=0);
};
'''

HARNESS = r'''
static void unchanged(const CTCPConnection &c, u32 cwnd, u32 window) {
 assert(c.m_nCWND==cwnd && c.m_nSND_WND==window);
 assert(c.m_nSND_UNA==100 && c.m_nSSThresh==65535);
 assert(c.m_nDupAckCount==0 && !c.m_bFastRecovery);
}
static void blocked(CTCPConnection &c) {
 const unsigned copies=CNetBuffer::copies;
 assert(!c.SendNewSegment());
 assert(c.sends==0 && c.timers==0 && c.m_RTOCalculator.sent==0);
 assert(c.m_nSND_NXT==120 && c.m_nLastSendTicks==1);
 assert(c.m_TxQueue.GetBytesQueued()==17 && CNetBuffer::copies==copies);
}
int main(int argc, char **argv) {
 assert(argc==2);
 const std::string scenario=argv[1];
 CTCPConnection c;
#ifdef OVERRIDE_NODELAY
 if(scenario=="nagle-short-flight") {
  c.m_TxQueue.Enqueue(new CNetBuffer(17));
  const unsigned copies=CNetBuffer::copies;
  assert(c.SetOptionNoDelay(false)==0 && !c.m_bNoDelay);
  assert(c.SetOptionNoDelay(false)==0 && !c.m_bNoDelay);
  blocked(c); c.Process(); assert(c.sends==0);
  assert(c.SetOptionNoDelay(true)==0 && c.m_bNoDelay);
  assert(c.SetOptionNoDelay(true)==0 && c.m_bNoDelay);
  assert(c.sends==0 && c.timers==0 && CNetBuffer::copies==copies);
  assert(c.m_TxQueue.GetBytesQueued()==17 && c.m_TxEvent.waits==0);
  c.Process(); assert(c.sends==1 && c.lastLength==17);
  unchanged(c,4096,4096);
  // Turning Nagle back on defers the next short segment until an ACK arrives.
  assert(c.SetOptionNoDelay(false)==0);
  assert(c.Send(new CNetBuffer(19),MSG_DONTWAIT)==19);
  c.Process(); assert(c.sends==1 && c.m_TxQueue.GetBytesQueued()==19);
  c.m_nSND_UNA=c.m_nSND_NXT; // ACK all flight
  c.Process(); assert(c.sends==2 && c.lastLength==19 && c.m_TxQueue.IsEmpty());
  puts("PASS"); return 0;
 }
 if(scenario=="nodelay-window-limits") {
  for(bool enabled: {false,true}) {
   for(unsigned limit: {0u,1u,2u}) {
    CTCPConnection limited;
    limited.m_TxQueue.Enqueue(new CNetBuffer(17));
    assert(limited.SetOptionNoDelay(enabled)==0);
    if(limit==0) limited.m_nSND_WND=0;
    else if(limit==1) limited.m_nSND_WND=36;
    else limited.m_nCWND=36;
    const u32 cwnd=limited.m_nCWND, window=limited.m_nSND_WND;
    blocked(limited); limited.Process(); blocked(limited);
    unchanged(limited,cwnd,window);
   }
  }
  puts("PASS"); return 0;
 }
 // Full MSS and a short segment with no flight send even with Nagle enabled.
 if(scenario=="nagle-full-mss" || scenario=="nagle-short-no-flight") {
  assert(c.SetOptionNoDelay(false)==0);
  if(scenario=="nagle-full-mss") { c.Send(new CNetBuffer(c.m_nSND_MSS),MSG_DONTWAIT); }
  else { c.m_nSND_NXT=c.m_nSND_UNA; c.Send(new CNetBuffer(17),MSG_DONTWAIT); }
  c.Process(); assert(c.sends==1 && c.m_TxQueue.IsEmpty());
  unchanged(c,4096,4096); puts("PASS"); return 0;
 }
#endif
 if(scenario=="short-with-flight" || scenario=="short-no-flight" || scenario=="full-mss"
    || scenario=="msg-more" || scenario=="window-boundary") {
  u32 length=scenario=="full-mss"?c.m_nSND_MSS:17;
  if(scenario=="short-no-flight") c.m_nSND_NXT=c.m_nSND_UNA;
  if(scenario=="window-boundary") c.m_nCWND=c.m_nSND_WND=20+length;
  auto *packet=new CNetBuffer(length);
  const int flags=MSG_DONTWAIT|(scenario=="msg-more"?MSG_MORE:0);
  assert(c.Send(packet,flags)==int(length));
  assert(c.sends==0 && c.m_TxEvent.waits==0);
  const u32 previous=c.m_nSND_NXT, cwnd=c.m_nCWND, window=c.m_nSND_WND;
  c.Process();
  assert(c.sends==1 && c.lastLength==length && c.lastSequence==previous);
  assert(c.m_nSND_NXT==previous+length && c.m_TxQueue.IsEmpty());
  assert(c.m_RTOCalculator.sent==1 && c.m_RTOCalculator.length==length);
  assert(c.timers==1 && c.lastFlags==(unsigned)(TCP_FLAG_ACK|
         (scenario=="msg-more"?0:TCP_FLAG_PUSH)));
  unchanged(c,cwnd,window);
 } else if(scenario=="zero-peer-window" || scenario=="peer-window" ||
           scenario=="congestion-window" || scenario=="additional-cwnd") {
  c.m_TxQueue.Enqueue(new CNetBuffer(17));
  if(scenario=="zero-peer-window") c.m_nSND_WND=0;
  else if(scenario=="peer-window") c.m_nSND_WND=36;
  else c.m_nCWND=36;
  const u32 cwnd=c.m_nCWND, window=c.m_nSND_WND;
  blocked(c);
  if(scenario=="additional-cwnd") {
   assert(c.SendNewSegment(1)); // existing limited-transmit allowance is retained
   assert(c.lastLength==17 && c.m_nSND_NXT==137);
  } else {
   c.Process();
   assert(c.sends==0 && c.m_nSND_NXT==120 && c.m_TxQueue.GetBytesQueued()==17);
   // Even inflated congestion allowance cannot override the peer window.
   if(scenario!="congestion-window") assert(!c.SendNewSegment(8192));
  }
  unchanged(c,cwnd,window);
 } else if(scenario=="send-backpressure") {
  c.m_TxQueue.Enqueue(new CNetBuffer(TCP_CONFIG_TX_THRESHOLD));
  c.m_nSendTimeout=1;
  auto *packet=new CNetBuffer(17);
  assert(c.Send(packet,0)==-NET_ERROR_WOULD_BLOCK);
  assert(c.m_TxEvent.waits==1 && c.m_TxEvent.clears==1);
  assert(c.m_TxQueue.GetBytesQueued()==TCP_CONFIG_TX_THRESHOLD);
  delete packet; // failed Send retains caller ownership
  packet=new CNetBuffer(17);
  assert(c.Send(packet,MSG_DONTWAIT)==17);
  assert(c.m_TxEvent.waits==1 && c.sends==0);
  assert(c.m_TxQueue.GetBytesQueued()==TCP_CONFIG_TX_THRESHOLD+17);
 } else assert(false);
 puts("PASS");
}
'''


@unittest.skipUnless(CXX.is_file(), 'host g++ unavailable')
class TcpSendNewSegmentHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='mpynn-tcp-send-new-segment-')
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        cls.env = os.environ.copy()
        cls.env['PATH'] = str(CXX.parent)+os.pathsep+cls.env.get('PATH', '')
        cls.env['TMP'] = cls.env['TEMP'] = cls.env['TMPDIR'] = str(cls.root)
        cls.executables = {}
        for name, path in SOURCES.items():
            source = path.read_text(encoding='utf-8')
            constants = '\n'.join(re.search(rf'^#define {constant}(?:\([^\n]*?\))?\s+[^\n]+', source, re.M).group()
                                  for constant in ('TCP_FLAG_ACK', 'TCP_FLAG_PUSH', 'TCP_FLAG_SYN',
                                                   'TCP_FLAG_FIN', 'TCP_CONFIG_TX_THRESHOLD',
                                                   'FLIGHT_SIZE', 'min', 'max'))
            methods = '\n'.join(method(source, signature) for signature in (
                'int CTCPConnection::Send (', 'void CTCPConnection::Process (',
                'boolean CTCPConnection::SendNewSegment ('))
            extra = ''
            if name == 'override':
                extra = '\n' + method(source, 'int CTCPConnection::SetOptionNoDelay (')
                extra += '\n#define OVERRIDE_NODELAY 1\n'
                header = (ROOT / 'ports/raspberrypi/upstream_overrides/circle/include/circle/net/tcpconnection.h').read_text()
                if 'boolean m_bNoDelay;' not in header or source.count('m_bNoDelay (TRUE),') != 2:
                    raise AssertionError('Both native constructors must preserve the historical no-delay default')
            harness = cls.root / (name+'.cpp')
            harness.write_text(FAKE+'\n'+constants+'\n'+methods+'\n'+extra+'\n'+HARNESS, encoding='utf-8')
            executable = cls.root / (name+'.exe')
            result = subprocess.run(
                [str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                 '-idirafter', str(ROOT/'lib/circle/include'), str(harness), '-o', str(executable)],
                cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(name+' host compile failed:\n'+result.stdout+result.stderr)
            cls.executables[name] = executable

    def run_scenario(self, scenario):
        for name, executable in self.executables.items():
            with self.subTest(source=name):
                result = subprocess.run([str(executable), scenario], cwd=self.root, env=self.env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn('PASS', result.stdout)

    def test_default_short_with_flight_already_sends_without_nagle(self):
        self.run_scenario('short-with-flight')

    def test_short_with_no_flight_sends(self):
        self.run_scenario('short-no-flight')

    def test_opt_in_nagle_waits_for_ack_on_short_flight(self):
        # This scenario is override-only; upstream has no option/member.
        for scenario in ('nagle-short-flight', 'nagle-full-mss', 'nagle-short-no-flight',
                         'nodelay-window-limits'):
            with self.subTest(scenario=scenario):
                executable = self.executables['override']
                result = subprocess.run([str(executable), scenario], cwd=self.root, env=self.env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn('PASS', result.stdout)

    def test_full_mss_sends_with_flight(self):
        self.run_scenario('full-mss')

    def test_msg_more_changes_push_not_transmit_eligibility(self):
        self.run_scenario('msg-more')

    def test_exact_window_boundary_sends(self):
        self.run_scenario('window-boundary')

    def test_zero_peer_window_does_not_send_even_with_additional_cwnd(self):
        self.run_scenario('zero-peer-window')

    def test_peer_window_does_not_allow_partial_segment(self):
        self.run_scenario('peer-window')

    def test_congestion_window_blocks_without_changing_congestion_state(self):
        self.run_scenario('congestion-window')

    def test_existing_additional_cwnd_allowance_is_preserved(self):
        self.run_scenario('additional-cwnd')

    def test_send_backpressure_and_caller_ownership_unchanged(self):
        self.run_scenario('send-backpressure')


if __name__ == '__main__':
    unittest.main()
