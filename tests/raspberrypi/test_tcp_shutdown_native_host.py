# SPDX-License-Identifier: MIT
"""Exercise the native TCP half-close implementation on a host ABI.

The harness extracts the actual override methods and doubles only queues,
timers, events and packet output.  No firmware build, scheduler yield, GC,
or network I/O is involved.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ports/raspberrypi/upstream_overrides/circle/lib/net/tcpconnection.cpp"
CXX = Path("E:/msys64/ucrt64/bin/g++.exe")


def method(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


FAKE = r'''
#include <cassert>
#include <cstdint>
#include <deque>
#include <string>
#include <cstdio>
#include <functional>
#include <circle/net/in.h>
#include <circle/net/error.h>
#include <circle/net/sizes.h>
using u32=uint32_t; using boolean=bool; using size_t=__SIZE_TYPE__;
#define TRUE true
#define FALSE false
#define TCP_CONFIG_TX_THRESHOLD 0x10000
#define HZ_FIN_TIMEOUT 100
#define MAX_RETRANSMISSIONS 5
#define NEW_STATE(state) (m_State=state)
#define FLIGHT_SIZE (m_nSND_NXT-m_nSND_UNA)
#define min(a,b) ((a)<(b)?(a):(b))
#define max(a,b) ((a)>(b)?(a):(b))
#define TCP_FLAG_ACK (1u<<12)
#define TCP_FLAG_PUSH (1u<<11)
#define TCP_FLAG_SYN (1u<<9)
#define TCP_FLAG_FIN (1u<<8)
enum { TCPTimerRetransmission=1 };
enum State { TCPStateClosed, TCPStateListen, TCPStateSynSent, TCPStateSynReceived,
 TCPStateEstablished, TCPStateFinWait1, TCPStateFinWait2, TCPStateCloseWait,
 TCPStateClosing, TCPStateLastAck, TCPStateTimeWait };
struct CNetBuffer {
  unsigned length; int flags=0;
  explicit CNetBuffer(unsigned n=0):length(n) {}
  unsigned GetLength() const {return length;}
  void SetPrivateData(const void *p,unsigned n) {assert(n==sizeof(flags)); flags=*static_cast<const int *>(p);}
  const void *GetPrivateData() const {return &flags;}
};
struct Queue {
  std::deque<CNetBuffer *> entries;
  ~Queue(){Flush();}
  bool IsEmpty() const{return entries.empty();}
  unsigned GetBytesQueued() const {unsigned n=0;for(auto *p:entries)n+=p->length;return n;}
  void Enqueue(CNetBuffer *p){entries.push_back(p);}
  CNetBuffer *Dequeue(){if(entries.empty())return nullptr;auto *p=entries.front();entries.pop_front();return p;}
  void Flush(size_t=~size_t(0)){while(!entries.empty()){delete entries.front();entries.pop_front();}}
  const CNetBuffer *Peek() const{return entries.empty()?nullptr:entries.front();}
  const CNetBuffer *PeekFirst() const{return Peek();}
  void MoveOn(){assert(!entries.empty());delete entries.front();entries.pop_front();}
};
struct Event {std::function<void()> onwait;unsigned sets=0,clears=0,waits=0;void Set(){++sets;}void Clear(){++clears;}void Wait(){++waits;if(onwait)onwait();}bool WaitWithTimeout(unsigned){++waits;if(onwait)onwait();return true;}};
struct Timer {unsigned ticks=1;unsigned GetTicks()const{return ticks;}};
struct RTO {unsigned sent=0;unsigned GetRTO()const{return 100;}void SegmentSent(u32,unsigned=0){++sent;}void SegmentAcknowledged(u32){} };
struct Reassembly {Queue *rx; explicit Reassembly(Queue *q):rx(q){} u32 Dequeue(u32 n){return n;} void Flush(){}};
struct CTCPConnection {
 State m_State=TCPStateEstablished,m_StateAfterFIN=TCPStateFinWait1; int m_nErrno=0;
 Queue m_TxQueue,m_RxQueue; Reassembly m_ReassemblyQueue{&m_RxQueue}; Event m_Event,m_TxEvent;
 bool m_bNoDelay=true,m_bRetransmit=false,m_bSendSYN=false,m_bFINQueued=false,m_bFINSent=false,
      m_bFINReceived=false,m_bTimedOut=false,m_bFastRecovery=false,m_bReadShutdown=false,
      m_bWriteShutdown=false; unsigned m_nRetransmissionCount=0,m_nReceiveTimeout=0,m_nSendTimeout=0;
 u32 m_nSND_UNA=100,m_nSND_NXT=120,m_nSND_WND=4096,m_nRCV_NXT=0,m_nRCV_WND=4096,
     m_nISS=99,m_nCWND=4096,m_nIW=2144,m_nSSThresh=65535,m_nRecover=0;
 unsigned m_nSND_MSS=536,m_nDupAckCount=0,m_nLastSendTicks=1; Timer timer;Timer *m_pTimer=&timer;RTO m_RTOCalculator;
 unsigned sends=0;unsigned lastFlags=0;u32 lastSequence=0;unsigned lastLength=0;
 void StopTimer(unsigned){} void StartTimer(unsigned,unsigned){ } void ResendSegment(){}
 bool SendSegment(unsigned f,u32 s,u32=0,CNetBuffer *p=nullptr){++sends;lastFlags=f;lastSequence=s;lastLength=p?p->length:0;delete p;return true;}
 bool SendNewSegment(u32=0){return false;}
 int Close(); int Shutdown(unsigned); int Send(CNetBuffer *,int); int Receive(CNetBuffer **,int);
 bool IsReceiveEOF() const;
 struct TStatus {bool bConnected,bRxReady,bTxReady,bException;}; TStatus GetStatus() const;
 void Process();
};
'''


HARNESS = r'''
int main() {
  CTCPConnection c;
  // WR shutdown is deferred until queued data drains, then emits a real FIN.
  assert(c.Shutdown(1)==0 && c.m_bWriteShutdown && c.m_bFINQueued && c.sends==0);
  assert(c.Shutdown(1)==0 && c.m_bFINQueued && c.sends==0);
  c.Process();
  assert(c.sends==1 && (c.lastFlags & TCP_FLAG_FIN) && c.lastSequence==120);
  assert(c.m_State==TCPStateFinWait1 && c.m_nSND_NXT==121 && !c.m_bFINQueued);
  auto *forbidden = new CNetBuffer(3);
  assert(c.Send(forbidden,MSG_DONTWAIT)==-NET_ERROR_NOT_CONNECTED);
  delete forbidden;
  // Close after a queued/sent native FIN is idempotent and never asserts.
  assert(c.Close()==0 && c.Close()==0);

  CTCPConnection rd;
  rd.m_RxQueue.Enqueue(new CNetBuffer(7));
  const unsigned before=rd.sends;
  assert(rd.Shutdown(0)==0 && rd.m_bReadShutdown && rd.m_RxQueue.IsEmpty());
  assert(rd.sends==before && rd.IsReceiveEOF());
  CNetBuffer *out=nullptr;
  assert(rd.Receive(&out,MSG_DONTWAIT)==0 && out==nullptr);
  assert(rd.GetStatus().bConnected && rd.GetStatus().bRxReady && rd.GetStatus().bTxReady);

  CTCPConnection fw;
  fw.m_State=TCPStateFinWait2; fw.m_bWriteShutdown=true;
  assert(fw.Receive(&out,MSG_DONTWAIT)==0);
  fw.m_State=TCPStateSynSent;
  assert(fw.Shutdown(2)==-NET_ERROR_NOT_CONNECTED && !fw.m_bReadShutdown && fw.m_bWriteShutdown);
  CTCPConnection bad; bad.m_nErrno=-NET_ERROR_CONNECTION_RESET;
  assert(bad.Shutdown(1)==-NET_ERROR_CONNECTION_RESET && !bad.m_bWriteShutdown);
  // Queued TX must survive shutdown; FIN may only be sent after those writes.
  CTCPConnection queued;
  queued.m_TxQueue.Enqueue(new CNetBuffer(9));
  queued.m_RxQueue.Enqueue(new CNetBuffer(11));
  assert(queued.Shutdown(2)==0 && queued.m_bReadShutdown && queued.m_bWriteShutdown);
  assert(queued.m_TxQueue.GetBytesQueued()==9 && queued.m_RxQueue.IsEmpty());
  queued.Process(); assert(queued.sends==0 && !queued.m_bFINSent);
  auto *accepted_write=queued.m_TxQueue.Dequeue(); delete accepted_write;
  queued.Process(); assert(queued.sends==1 && queued.m_bFINSent);
  assert(queued.Shutdown(0)==0 && queued.Shutdown(1)==0 && queued.Shutdown(2)==0);
  assert(!queued.GetStatus().bTxReady && queued.GetStatus().bRxReady);
  CTCPConnection passive;
  passive.m_State=TCPStateCloseWait;
  assert(passive.Shutdown(1)==0 && passive.m_StateAfterFIN==TCPStateLastAck);
  assert(passive.Close()==0); passive.Process(); assert(passive.m_State==TCPStateLastAck);
  assert(passive.Close()==0);
  for(auto state:{TCPStateClosed,TCPStateListen,TCPStateSynSent,TCPStateSynReceived}) {
    CTCPConnection invalid; invalid.m_State=state;
    for(unsigned how=0;how<=3;++how) {
      assert(invalid.Shutdown(how)<0);
      assert(!invalid.m_bReadShutdown && !invalid.m_bWriteShutdown && !invalid.m_bFINQueued);
    }
  }
  CTCPConnection waiter;
  waiter.m_TxQueue.Enqueue(new CNetBuffer(TCP_CONFIG_TX_THRESHOLD));
  waiter.m_TxEvent.onwait=[&](){assert(waiter.Shutdown(1)==0);};
  auto *notaccepted = new CNetBuffer(4);
  assert(waiter.Send(notaccepted,0)==-NET_ERROR_NOT_CONNECTED);
  assert(waiter.m_TxQueue.GetBytesQueued()==TCP_CONFIG_TX_THRESHOLD);
  assert(waiter.m_TxEvent.sets==1); delete notaccepted;
  CTCPConnection reader;
  reader.m_Event.onwait=[&](){assert(reader.Shutdown(0)==0);};
  out=reinterpret_cast<CNetBuffer *>(1);
  assert(reader.Receive(&out,0)==0 && out==nullptr && reader.m_Event.waits==1);
  CTCPConnection completed;
  completed.m_State=TCPStateClosed;completed.m_bWriteShutdown=true;completed.m_bFINSent=true;
  assert(completed.Shutdown(2)==0 && completed.m_bReadShutdown);
  assert(completed.Receive(&out,MSG_DONTWAIT)==0 && out==nullptr);
  puts("PASS");
}
'''


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class TcpShutdownNativeHostTests(unittest.TestCase):
    def test_actual_transport_shutdown_dispatch(self):
        source = (ROOT / "ports/raspberrypi/upstream_overrides/circle/lib/net/transportlayer.cpp").read_text(encoding="utf-8")
        dispatcher = method(source, "int CTransportLayer::Shutdown (")
        program = r'''
#include <cassert>
#include <vector>
#include <circle/net/in.h>
#include <circle/net/error.h>
struct CNetConnection { virtual ~CNetConnection()=default; int protocol=IPPROTO_UDP; int GetProtocol(){return protocol;} };
struct CTCPConnection:CNetConnection {unsigned calls=0,how=9;int error=0;CTCPConnection(){protocol=IPPROTO_TCP;}int Shutdown(unsigned mode){++calls;how=mode;return error;}};
struct Slots {std::vector<void *> entries;unsigned GetCount(){return unsigned(entries.size());}void *operator[](int n){assert(n>=0 && unsigned(n)<entries.size());return entries[n];}};
struct CTransportLayer {Slots m_pConnection;int Shutdown(unsigned,int);};
''' + dispatcher + r'''
int main(){
 CTCPConnection tcp;CNetConnection udp;CTransportLayer transport;
 transport.m_pConnection.entries={&tcp,nullptr,&udp};
 for(int h:{-1,1,3})assert(transport.Shutdown(1,h)==-NET_ERROR_NOT_CONNECTED);
 assert(transport.Shutdown(3,0)==-NET_ERROR_INVALID_VALUE && !tcp.calls);
 assert(transport.Shutdown(1,2)==-NET_ERROR_PROTOCOL_NOT_SUPPORTED && !tcp.calls);
 for(unsigned how=0;how<3;++how){assert(transport.Shutdown(how,0)==0 && tcp.how==how);}
 tcp.error=-NET_ERROR_CONNECTION_RESET;
 assert(transport.Shutdown(2,0)==tcp.error && tcp.calls==4);
}
'''
        with tempfile.TemporaryDirectory(prefix="mpynn-shutdown-dispatch-") as folder:
            root=Path(folder); src=root/"dispatch.cpp"; exe=root/"dispatch.exe"
            src.write_text(program,encoding="utf-8")
            env=os.environ.copy();env["PATH"]=str(CXX.parent)+os.pathsep+env.get("PATH","")
            for command in ([str(CXX),"-std=c++17","-Wall","-Wextra","-Werror","-idirafter",str(ROOT/"lib/circle/include"),str(src),"-o",str(exe)],[str(exe)]):
                result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_native_half_close_methods(self):
        source = SOURCE.read_text(encoding="utf-8")
        # Keep this test tied to the actual packet path as well as extracted methods.
        packet = method(source, "int CTCPConnection::PacketReceived (")
        self.assertIn("m_bReadShutdown", packet)
        self.assertIn("m_ReassemblyQueue.Dequeue", packet)
        self.assertIn("SendSegment (TCP_FLAG_ACK", packet)
        definitions = "\n".join(method(source, signature) for signature in (
            "int CTCPConnection::Close (", "int CTCPConnection::Shutdown (",
            "int CTCPConnection::Send (", "int CTCPConnection::Receive (",
            "boolean CTCPConnection::IsReceiveEOF (", "void CTCPConnection::Process (",
            "CNetConnection::TStatus CTCPConnection::GetStatus (",
        ))
        definitions = definitions.replace("CNetConnection::TStatus CTCPConnection::GetStatus", "CTCPConnection::TStatus CTCPConnection::GetStatus")
        netdevice = (ROOT / "lib/circle/include/circle/netdevice.h").read_text(encoding="utf-8")
        constants = re.search(r"^#define FRAME_BUFFER_SIZE[^\n]+", netdevice, re.M).group(0) + "\n"
        with tempfile.TemporaryDirectory(prefix="mpynn-tcp-shutdown-native-") as folder:
            root = Path(folder)
            src, exe = root / "test.cpp", root / "test.exe"
            src.write_text(FAKE + constants + definitions + HARNESS, encoding="utf-8")
            env = os.environ.copy()
            env["PATH"] = str(CXX.parent) + os.pathsep + env.get("PATH", "")
            result = subprocess.run([str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror", "-idirafter", str(ROOT / "lib/circle/include"), str(src), "-o", str(exe)],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], cwd=root, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
