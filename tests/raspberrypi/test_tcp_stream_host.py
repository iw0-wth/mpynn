# SPDX-License-Identifier: MIT
"""Test real stream bridge with deterministic fake transport (no real TCP)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2]/'ports/raspberrypi'
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')
FAKE = r'''
#pragma once
#include <cassert>
#include <cstdint>
#include <string>
#define TASK_LEVEL 0
#define MSG_DONTWAIT 1
extern unsigned level;
inline unsigned CurrentExecutionLevel() { return level; }
struct CNetBuffer {
 enum TPurpose { TCPSend };
 static int live, allocations;
 std::string data;
 CNetBuffer(TPurpose, size_t n, const void *p) : data((const char*)p,n) { ++live; ++allocations; }
 ~CNetBuffer() { --live; }
 size_t GetLength() const { return data.size(); }
 const void *GetPtr() const { return data.data(); }
};
struct CTransportLayer {
 struct Status { bool bConnected, bRxReady, bTxReady, bException; };
 bool writable=true, connected=true, exceptional=false;
 unsigned mss=4;
 int rx_error=0, tx_error=0, close_error=0;
 int reads=0, writes=0, closes=0;
 int nodelay_calls=0, nodelay_error=0, nodelay_handle=-1;
 bool nodelay=true;
 int SetOptionNoDelay(bool enabled, int handle) {
  ++nodelay_calls; nodelay_handle=handle;
  if(nodelay_error) return nodelay_error;
  nodelay=enabled; return 0;
 }
 // This fake records bridge calls only; it does not model FIN or TCP wire data.
 int shutdown_calls=0, shutdown_error=0, shutdown_handle=-1;
 unsigned shutdown_how=999;
 bool read_shutdown=false, write_shutdown=false;
 int Shutdown(unsigned how, int handle) {
  assert(how<=2 && refs[handle]==1);
  ++shutdown_calls; shutdown_how=how; shutdown_handle=handle;
  if(shutdown_error) return shutdown_error;
  if(how==0 || how==2) read_shutdown=true;
  if(how==1 || how==2) write_shutdown=true;
  return 0;
 }
 CNetBuffer *incoming=nullptr;
 std::string sent;
 int status_calls=0, terminal_calls=0;
 Status GetStatus(int) {
  ++status_calls; return {connected, incoming!=nullptr || rx_error!=0, writable, exceptional};
 }
 int GetTerminalError(int) { ++terminal_calls; return rx_error; }
 bool fin=false;
 bool IsReceiveEOF(int) { return fin && !incoming && rx_error==0; }
 unsigned GetMSS(int) { return mss; }
 uint16_t GetOwnPort(int h) { return 60000+h; }
 int Receive(CNetBuffer **out, int flags, int) {
  assert(flags==1); ++reads;
  if(rx_error) return rx_error;
  *out=incoming; incoming=nullptr;
  return *out ? (int)(*out)->GetLength() : 0;
 }
 int Send(CNetBuffer *packet,int flags,int) {
  assert(flags==1); ++writes;
  if(tx_error) return tx_error;
  int n=packet->GetLength(); sent+=packet->data; delete packet; return n;
 }
 // Seed refs as if each handle was transferred by connect_take.
 int refs[6]={1,1,1,1,0,1};
 int last_closed=-1, releases=0;
 int Disconnect(int handle) {
  assert(refs[handle]==1); last_closed=handle; ++closes; return close_error;
 }
 int ReleaseConnection(int handle) {
  assert(last_closed==handle && refs[handle]==1);
  --refs[handle]; ++releases; return 0;
 }
};
struct CNetSubSystem { CTransportLayer transport; CTransportLayer *GetTransportLayer() { return &transport; } };
'''
SOURCE = r'''
#include "fake.h"
#include "tcp_stream_bridge.h"
#include "network_bridge.h"
#include "socket_errno_bridge.h"
unsigned level;
int CNetBuffer::live;
int CNetBuffer::allocations;
CNetSubSystem net;
bool present=true;
CNetSubSystem *mpynn_network_get() { return present?&net:nullptr; }
extern "C" int mpynn_socket_error_from_circle(int r) { return r<0?MPYNN_IO:0; }
int main() {
 uint32_t token=999, other=999;
 assert(mpynn_tcp_stream_claim(-1,&token)==MPYNN_INVAL);
 present=false; assert(mpynn_tcp_stream_claim(0,&token)==MPYNN_NODEV && token==999);
 present=true; assert(mpynn_tcp_stream_claim(0,&token)==0);
 assert(mpynn_tcp_stream_claim(0,&other)==MPYNN_BUSY && other==999);
 assert(mpynn_tcp_stream_set_nodelay(0,1)==MPYNN_BADF);
 assert(mpynn_tcp_stream_set_nodelay(token,2)==MPYNN_INVAL);
 assert(mpynn_tcp_stream_set_nodelay(token,UINT32_MAX)==MPYNN_INVAL);
 level=1;
 assert(mpynn_tcp_stream_set_nodelay(token,0)==MPYNN_BUSY);
 assert(net.transport.nodelay_calls==0 && net.transport.nodelay);
 level=0;
 assert(mpynn_tcp_stream_set_nodelay(token,0)==0 && !net.transport.nodelay);
 assert(mpynn_tcp_stream_set_nodelay(token,0)==0 && !net.transport.nodelay);
 assert(mpynn_tcp_stream_set_nodelay(token,1)==0 && net.transport.nodelay);
 assert(mpynn_tcp_stream_set_nodelay(token,1)==0 && net.transport.nodelay);
 assert(net.transport.nodelay_handle==0 && net.transport.nodelay_calls==4);
 assert(net.transport.reads==0 && net.transport.writes==0 && net.transport.closes==0);
 assert(net.transport.releases==0 && net.transport.refs[0]==1 && CNetBuffer::live==0);
 net.transport.nodelay_error=-1;
 assert(mpynn_tcp_stream_set_nodelay(token,0)==MPYNN_IO && net.transport.nodelay);
 net.transport.nodelay_error=0;
 uint16_t own=999;
 assert(mpynn_tcp_stream_local_port(token,&own)==0 && own==60000);
 assert(mpynn_tcp_stream_local_port(token,nullptr)==MPYNN_INVAL);
 level=1;own=999;
 assert(mpynn_tcp_stream_local_port(token,&own)==MPYNN_BUSY && own==999);
 level=0;
 assert(mpynn_tcp_stream_discard(0)==MPYNN_BUSY);
 assert(mpynn_tcp_stream_discard(-1)==MPYNN_INVAL);
 char out[10]={}; size_t n=999;
 unsigned events=999;
 assert(mpynn_tcp_stream_poll(token,5,&events)==0 && events==MPYNN_TCP_POLL_WR);
 net.transport.connected=false;
 assert(mpynn_tcp_stream_poll(token,5,&events)==0 && events==(MPYNN_TCP_POLL_WR|MPYNN_TCP_POLL_HUP));
 net.transport.connected=true;
 assert(mpynn_tcp_stream_read(token,out,3,&n)==MPYNN_AGAIN && n==999);
 assert(mpynn_tcp_stream_poll(token,0,nullptr)==MPYNN_INVAL);
 net.transport.incoming=new CNetBuffer(CNetBuffer::TCPSend,6,"abcdef");
 assert(mpynn_tcp_stream_poll(token,MPYNN_TCP_POLL_RD,&events)==0 && events==MPYNN_TCP_POLL_RD);
 assert(mpynn_tcp_stream_read(token,out,2,&n)==0 && n==2 && !memcmp(out,"ab",2));
 int reads=net.transport.reads;
 int socket_error=999;
  assert(mpynn_tcp_stream_get_error(token,nullptr)==MPYNN_INVAL);
  level=1;
  assert(mpynn_tcp_stream_get_error(token,&socket_error)==MPYNN_BUSY && socket_error==999);
  level=0;
  assert(mpynn_tcp_stream_get_error(token,&socket_error)==0 && socket_error==0);
  net.transport.rx_error=-54;
  assert(mpynn_tcp_stream_get_error(token,&socket_error)==0 && socket_error==MPYNN_IO);
  assert(mpynn_tcp_stream_get_error(token,&socket_error)==0 && socket_error==MPYNN_IO);
  assert(net.transport.rx_error==-54 && net.transport.reads==reads && CNetBuffer::live==1);
  assert(net.transport.closes==0 && net.transport.releases==0 && net.transport.refs[0]==1);
 assert(mpynn_tcp_stream_read(token,out,3,&n)==0 && n==3 && !memcmp(out,"cde",3));
 assert(mpynn_tcp_stream_read(token,out,9,&n)==0 && n==1 && out[0]=='f');
 assert(net.transport.reads==reads && CNetBuffer::live==0);
 n=999; assert(mpynn_tcp_stream_read(token,out,9,&n)==MPYNN_IO && n==999);
 net.transport.writable=false;
 assert(mpynn_tcp_stream_write(token,"x",1,&n)==MPYNN_IO); // reset beats backpressure
 assert(mpynn_tcp_stream_poll(token,5,&events)==0 && (events & MPYNN_TCP_POLL_ERR));
 net.transport.rx_error=0; net.transport.fin=true;
 assert(mpynn_tcp_stream_read(token,out,9,&n)==0 && n==0);
 assert(mpynn_tcp_stream_read(token,out,9,&n)==0 && n==0); // repeatable EOF
 assert(mpynn_tcp_stream_poll(token,1,&events)==0 && events==1);
 net.transport.writable=true;
 assert(mpynn_tcp_stream_write(token,"abcdefgh",8,&n)==0 && n==4 && net.transport.sent=="abcd");
 net.transport.writable=false; n=999;
 assert(mpynn_tcp_stream_write(token,"e",1,&n)==MPYNN_AGAIN && n==999);
 net.transport.writable=true; net.transport.tx_error=-1;
 assert(mpynn_tcp_stream_write(token,"e",1,&n)==MPYNN_IO && CNetBuffer::live==0);
 net.transport.tx_error=0;
 assert(mpynn_tcp_stream_write(token,nullptr,0,&n)==0 && n==0);
 level=1; n=999;
 assert(mpynn_tcp_stream_read(token,out,3,&n)==MPYNN_BUSY && n==999);
 assert(mpynn_tcp_stream_close_all()==MPYNN_BUSY);
 level=0; net.transport.rx_error=0;
 net.transport.incoming=new CNetBuffer(CNetBuffer::TCPSend,6,"remain");
 assert(mpynn_tcp_stream_read(token,out,1,&n)==0 && CNetBuffer::live==1);
 assert(mpynn_tcp_stream_close(token)==0 && CNetBuffer::live==0);
 assert(mpynn_tcp_stream_close(token)==MPYNN_BADF);
 int nodelay_calls=net.transport.nodelay_calls;
 assert(mpynn_tcp_stream_set_nodelay(token,0)==MPYNN_BADF);
 assert(net.transport.nodelay_calls==nodelay_calls);
  socket_error=999;
  assert(mpynn_tcp_stream_get_error(token,&socket_error)==MPYNN_BADF && socket_error==999);
 own=999;assert(mpynn_tcp_stream_local_port(token,&own)==MPYNN_BADF && own==999);
 assert(net.transport.refs[0]==0 && net.transport.releases==1);
 net.transport.refs[0]=1; // A new take transfers a new owner ref.
 uint32_t tokens[4];
 for(int i=0;i<4;++i) assert(mpynn_tcp_stream_claim(i,&tokens[i])==0);
 assert(tokens[0]!=token);
 assert(mpynn_tcp_stream_set_nodelay(token,1)==MPYNN_BADF);
 assert(mpynn_tcp_stream_set_nodelay(tokens[0],0)==0 && !net.transport.nodelay);
 assert(net.transport.nodelay_calls==nodelay_calls+1);
 assert(mpynn_tcp_stream_claim(5,&other)==MPYNN_MFILE && other==999);
 assert(net.transport.refs[5]==1); // Failed claim preserves caller ownership.
 level=1; assert(mpynn_tcp_stream_discard(5)==MPYNN_BUSY);
 level=0; present=false; assert(mpynn_tcp_stream_discard(5)==MPYNN_NODEV);
 present=true; net.transport.close_error=-1;
 assert(mpynn_tcp_stream_discard(5)==MPYNN_IO && net.transport.refs[5]==0);
 int closes=net.transport.closes;
 assert(mpynn_tcp_stream_close_all()==MPYNN_IO && net.transport.closes==closes+4);
 assert(net.transport.releases==6);
 for(int i=0;i<4;++i) assert(net.transport.refs[i]==0);
 assert(mpynn_tcp_stream_close_all()==0 && CNetBuffer::live==0);
}
'''

SHUTDOWN_SOURCE = r'''
#include "fake.h"
#include "tcp_stream_bridge.h"
#include "network_bridge.h"
#include "socket_errno_bridge.h"
unsigned level;
int CNetBuffer::live;
int CNetBuffer::allocations;
CNetSubSystem net;
CNetSubSystem *mpynn_network_get() { return &net; }
extern "C" int mpynn_socket_error_from_circle(int r) { return r<0?MPYNN_IO:0; }
int main() {
 static_assert(MPYNN_PIPE==32, "EPIPE ABI");
 auto &t=net.transport;
 uint32_t token=999;
 assert(mpynn_tcp_stream_claim(0,&token)==0);
 char out[16]={}; size_t n=999; unsigned events=999;
 t.incoming=new CNetBuffer(CNetBuffer::TCPSend,6,"abcdef");
 assert(mpynn_tcp_stream_read(token,out,2,&n)==0 && n==2 && !memcmp(out,"ab",2));
 assert(CNetBuffer::live==1);
 // Validation order: invalid mode, task context, then generation lookup.
 assert(mpynn_tcp_stream_shutdown(token,3)==MPYNN_INVAL);
 assert(mpynn_tcp_stream_shutdown(0,UINT32_MAX)==MPYNN_INVAL);
 assert(mpynn_tcp_stream_shutdown(0,0)==MPYNN_BADF);
 level=1;
 assert(mpynn_tcp_stream_shutdown(token,0)==MPYNN_BUSY);
 assert(mpynn_tcp_stream_shutdown(0,1)==MPYNN_BUSY);
 assert(mpynn_tcp_stream_shutdown(token,3)==MPYNN_INVAL);
 assert(mpynn_tcp_stream_close(token)==MPYNN_BUSY);
 level=0;
 assert(t.shutdown_calls==0 && !t.read_shutdown && !t.write_shutdown);
 assert(t.closes==0 && t.releases==0 && t.refs[0]==1 && CNetBuffer::live==1);
 assert(mpynn_tcp_stream_poll(token,5,&events)==0 && events==5);
 // A native error must preserve both directions, cached tail, and ownership.
 t.shutdown_error=-1;
 for(unsigned how=0;how<=2;++how) assert(mpynn_tcp_stream_shutdown(token,how)==MPYNN_IO);
 assert(t.shutdown_calls==3 && !t.read_shutdown && !t.write_shutdown);
 assert(CNetBuffer::live==1 && t.refs[0]==1 && t.closes==0 && t.releases==0);
 assert(mpynn_tcp_stream_read(token,out,1,&n)==0 && n==1 && out[0]=='c');
 assert(mpynn_tcp_stream_write(token,"queued",6,&n)==0 && n==4 && t.sent=="queu");
 t.shutdown_error=0;
 int allocations=CNetBuffer::allocations, statuses=t.status_calls, terminals=t.terminal_calls;
 int reads=t.reads, writes=t.writes;
 assert(mpynn_tcp_stream_shutdown(token,1)==0);
 assert(mpynn_tcp_stream_shutdown(token,1)==0); // Repeat reaches native API.
 assert(t.shutdown_calls==5 && t.shutdown_how==1 && t.shutdown_handle==0);
 assert(!t.read_shutdown && t.write_shutdown && t.connected && t.sent=="queu");
 assert(t.reads==reads && t.writes==writes && t.status_calls==statuses && t.terminal_calls==terminals);
 assert(CNetBuffer::allocations==allocations && CNetBuffer::live==1);
 assert(t.closes==0 && t.releases==0 && t.refs[0]==1);
 n=999;
 assert(mpynn_tcp_stream_write(token,"x",1,&n)==MPYNN_PIPE && n==999);
 assert(mpynn_tcp_stream_write(token,nullptr,0,&n)==MPYNN_PIPE && n==999);
 t.rx_error=-54; t.writable=false;
 assert(mpynn_tcp_stream_write(token,"x",1,&n)==MPYNN_PIPE && n==999);
 assert(t.status_calls==statuses && t.terminal_calls==terminals);
 assert(CNetBuffer::allocations==allocations && t.writes==writes);
 t.rx_error=0; t.writable=true;
 assert(mpynn_tcp_stream_poll(token,5,&events)==0 && events==MPYNN_TCP_POLL_RD);
 assert(mpynn_tcp_stream_poll(token,4,&events)==0 && events==0);
 assert(mpynn_tcp_stream_read(token,out,1,&n)==0 && n==1 && out[0]=='d'); // WR preserves RX tail.
 t.shutdown_error=-1;
 assert(mpynn_tcp_stream_shutdown(token,0)==MPYNN_IO);
 assert(mpynn_tcp_stream_shutdown(token,2)==MPYNN_IO);
 assert(CNetBuffer::live==1 && !t.read_shutdown && t.write_shutdown);
 n=999; assert(mpynn_tcp_stream_write(token,nullptr,0,&n)==MPYNN_PIPE && n==999);
 assert(mpynn_tcp_stream_read(token,out,1,&n)==0 && n==1 && out[0]=='e');
 t.shutdown_error=0;
 allocations=CNetBuffer::allocations; reads=t.reads; writes=t.writes;
 assert(mpynn_tcp_stream_shutdown(token,0)==0 && CNetBuffer::live==0); // Discards final cached f.
 assert(t.read_shutdown && t.write_shutdown);
 assert(mpynn_tcp_stream_shutdown(token,0)==0 && mpynn_tcp_stream_shutdown(token,2)==0);
 assert(t.shutdown_how==2 && t.shutdown_handle==0 && t.connected);
 assert(CNetBuffer::allocations==allocations && t.reads==reads && t.writes==writes);
 t.rx_error=-54;
 terminals=t.terminal_calls; statuses=t.status_calls;
 n=999; assert(mpynn_tcp_stream_read(token,out,16,&n)==0 && n==0);
 n=999; assert(mpynn_tcp_stream_read(token,nullptr,0,&n)==0 && n==0);
 assert(t.terminal_calls==terminals && t.status_calls==statuses && t.reads==reads);
 t.rx_error=0;
 assert(mpynn_tcp_stream_poll(token,5,&events)==0 && events==MPYNN_TCP_POLL_RD);
 assert(mpynn_tcp_stream_poll(token,4,&events)==0 && events==0);
 assert(mpynn_tcp_stream_poll(token,0,&events)==0 && events==0); // No HUP solely from half-close.
 t.connected=false;
 assert(mpynn_tcp_stream_poll(token,5,&events)==0 && events==(MPYNN_TCP_POLL_RD|MPYNN_TCP_POLL_HUP));
 t.connected=true;
 assert(t.closes==0 && t.releases==0 && t.refs[0]==1);
 int calls=t.shutdown_calls;
 level=1; n=999; events=999;
 assert(mpynn_tcp_stream_shutdown(token,2)==MPYNN_BUSY);
 assert(mpynn_tcp_stream_read(token,out,1,&n)==MPYNN_BUSY && n==999);
 assert(mpynn_tcp_stream_write(token,nullptr,0,&n)==MPYNN_BUSY && n==999);
 assert(mpynn_tcp_stream_poll(token,5,&events)==MPYNN_BUSY && events==999);
 level=0;
 assert(t.shutdown_calls==calls);
 assert(mpynn_tcp_stream_close(token)==0);
 assert(t.closes==1 && t.releases==1 && t.refs[0]==0 && CNetBuffer::live==0);
 assert(mpynn_tcp_stream_close(token)==MPYNN_BADF);
 assert(mpynn_tcp_stream_shutdown(token,2)==MPYNN_BADF && t.shutdown_calls==calls);
 n=999; assert(mpynn_tcp_stream_write(token,nullptr,0,&n)==MPYNN_BADF && n==999);
 assert(mpynn_tcp_stream_poll(token,5,&events)==0 && events==MPYNN_TCP_POLL_NVAL);
 // Reclaim same slot with a fresh owner ref; new generation must reset both flags/cache.
 uint32_t next=999;
 t.refs[0]=1; t.read_shutdown=false; t.write_shutdown=false;
 assert(mpynn_tcp_stream_claim(0,&next)==0 && next!=token);
 assert(mpynn_tcp_stream_shutdown(token,0)==MPYNN_BADF && t.shutdown_calls==calls);
 assert(mpynn_tcp_stream_poll(next,5,&events)==0 && events==MPYNN_TCP_POLL_WR);
 n=999; assert(mpynn_tcp_stream_read(next,out,1,&n)==MPYNN_AGAIN && n==999);
 assert(mpynn_tcp_stream_write(next,"ok",2,&n)==0 && n==2 && t.sent=="queuok");
 assert(mpynn_tcp_stream_write(next,nullptr,0,&n)==0 && n==0);
 t.incoming=new CNetBuffer(CNetBuffer::TCPSend,6,"ghijkl");
 assert(mpynn_tcp_stream_read(next,out,2,&n)==0 && n==2 && !memcmp(out,"gh",2));
 t.shutdown_error=-1;
 assert(mpynn_tcp_stream_shutdown(next,2)==MPYNN_IO && CNetBuffer::live==1);
 assert(mpynn_tcp_stream_poll(next,5,&events)==0 && events==5);
 assert(mpynn_tcp_stream_read(next,out,1,&n)==0 && n==1 && out[0]=='i');
 t.shutdown_error=0;
 assert(mpynn_tcp_stream_shutdown(next,0)==0 && CNetBuffer::live==0);
 assert(t.read_shutdown && !t.write_shutdown);
 assert(mpynn_tcp_stream_poll(next,5,&events)==0 && events==5); // RD-only leaves writes ready.
 assert(mpynn_tcp_stream_write(next,"R",1,&n)==0 && n==1);
 t.shutdown_error=-1;
 assert(mpynn_tcp_stream_shutdown(next,2)==MPYNN_IO && !t.write_shutdown);
 assert(mpynn_tcp_stream_read(next,out,1,&n)==0 && n==0);
 assert(mpynn_tcp_stream_write(next,nullptr,0,&n)==0 && n==0);
 t.shutdown_error=0;
 assert(mpynn_tcp_stream_shutdown(next,2)==0 && t.write_shutdown);
 assert(mpynn_tcp_stream_poll(next,5,&events)==0 && events==MPYNN_TCP_POLL_RD);
 assert(t.closes==1 && t.releases==1 && t.refs[0]==1);
 assert(mpynn_tcp_stream_close(next)==0 && t.closes==2 && t.releases==2 && t.refs[0]==0);
 // SHUT_RDWR directly on a clean stream applies both directions together.
 t.refs[0]=1; t.read_shutdown=false; t.write_shutdown=false;
 assert(mpynn_tcp_stream_claim(0,&next)==0);
 t.incoming=new CNetBuffer(CNetBuffer::TCPSend,4,"tail");
 assert(mpynn_tcp_stream_read(next,out,1,&n)==0 && out[0]=='t' && CNetBuffer::live==1);
 assert(mpynn_tcp_stream_shutdown(next,2)==0 && t.read_shutdown && t.write_shutdown && CNetBuffer::live==0);
 n=999; assert(mpynn_tcp_stream_write(next,nullptr,0,&n)==MPYNN_PIPE && n==999);
 assert(mpynn_tcp_stream_read(next,out,1,&n)==0 && n==0);
 assert(mpynn_tcp_stream_poll(next,5,&events)==0 && events==MPYNN_TCP_POLL_RD);
 t.close_error=-1;
 assert(mpynn_tcp_stream_close(next)==MPYNN_IO && t.closes==3 && t.releases==3 && t.refs[0]==0);
 assert(mpynn_tcp_stream_close_all()==0 && CNetBuffer::live==0);
}
'''


class TcpStreamTests(unittest.TestCase):
    def test_receive_tails_send_backpressure_and_close(self):
        self.run_source(SOURCE)

    def test_shutdown_half_close_cache_ownership_and_generation(self):
        self.run_source(SHUTDOWN_SOURCE)

    def run_source(self, source):
        if not CXX.is_file(): self.skipTest('host g++ unavailable')
        env=os.environ.copy()
        env['PATH']=str(CXX.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'fake.h').write_text(FAKE)
            for name in ('net/netsubsystem.h','net/transportlayer.h','net/netbuffer.h','net/in.h','synchronize.h'):
                path=root/'circle'/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('#include "fake.h"\n')
            (root/'test.cpp').write_text('#include <cstring>\n'+source)
            exe=root/'test.exe'
            for cmd in ([str(CXX),'-std=c++17','-Wall','-Wextra','-Werror',
                         '-I'+str(root),'-I'+str(PORT),str(PORT/'tcp_stream_bridge.cpp'),str(root/'test.cpp'),'-o',str(exe)], [str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__': unittest.main()
