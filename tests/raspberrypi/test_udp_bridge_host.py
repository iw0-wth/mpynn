# SPDX-License-Identifier: MIT
"""Real UDP bridge + fake Circle transport; no socket or physical network."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT/'ports/raspberrypi'
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')
FAKE = r'''
#pragma once
#include <cstdint>
#include <cstring>
#include <string>
#include <cassert>
#define TASK_LEVEL 0
#define IPPROTO_UDP 17
#define MSG_DONTWAIT 1
extern unsigned level;
inline unsigned CurrentExecutionLevel() { return level; }
struct CIPAddress {
    uint8_t bytes[4] = {};
    CIPAddress() = default;
    CIPAddress(const uint8_t *p) { memcpy(bytes,p,4); }
    void CopyTo(uint8_t *p) const { memcpy(p,bytes,4); }
};
struct CNetBuffer {
    enum TPurpose { UDPSend };
    static int live;
    std::string bytes;
    CNetBuffer(TPurpose, size_t n, const void *p) : bytes(n ? std::string((const char*)p,n) : "") { ++live; }
    ~CNetBuffer() { --live; }
    size_t GetLength() const { return bytes.size(); }
    const void *GetPtr() const { return bytes.data(); }
};
struct CTransportLayer {
    int next=0, binds=0, closes=0, sends=0, recvs=0;
    int bind_error=0, close_error=0, send_error=0, recv_error=0;
    int error_takes=0, take_error_override=0;
    int TakeUDPError(int handle) {
        assert(handle>=0 && handle<next); ++error_takes;
        if(take_error_override) return take_error_override;
        int error=recv_error; recv_error=0; return error;
    }
    struct Status { bool bConnected, bRxReady, bTxReady, bException; };
    bool connected=true, exception=false;
    Status GetStatus(int) { return {connected, incoming!=nullptr || recv_error!=0, true, exception}; }
    bool broadcast=false;
    int SetOptionBroadcast(bool value, int) { broadcast=value; return 0; }
    CNetBuffer *incoming=nullptr;
    uint16_t ports[32] = {};
    uint8_t local_ips[32][4] = {};
    int local_address_sets=0, local_address_error=0;
    int SetUDPLocalAddress(const CIPAddress &ip,int handle) {
        assert(handle>=0 && handle<next); ++local_address_sets;
        if(local_address_error) return local_address_error;
        memcpy(local_ips[handle],ip.bytes,4); return 0;
    }
    int Bind(unsigned port,int protocol) {
        assert(protocol==17); ++binds;
        if(bind_error) return bind_error;
        assert(next<32); ports[next]=port ? port : 49152+next; return next++;
    }
    uint16_t GetOwnPort(int handle) { assert(handle>=0 && handle<next); return ports[handle]; }
    int Disconnect(int h) { assert(h>=0); ++closes; return close_error; }
    unsigned GetMSS(int) { return 1472; }
    int peer_error=0; uint16_t peer_port=0;
    int SetUDPPeer(const CIPAddress &,uint16_t port,int) {if(peer_error)return peer_error;peer_port=port;return 0;}
    int Send(CNetBuffer *p,int flags,int) {
        assert(flags==MSG_DONTWAIT && peer_port); ++sends;
        if(send_error)return send_error;
        int n=p->GetLength();delete p;return n;
    }
    int SendTo(CNetBuffer *p,int flags,const CIPAddress &,uint16_t port,int) {
        assert(flags==MSG_DONTWAIT && port); ++sends;
        if(send_error) return send_error;
        int n=p->GetLength(); delete p; return n;
    }
    int ReceiveFrom(CNetBuffer **out,int flags,CIPAddress *ip,uint16_t *port,int) {
        assert(flags==MSG_DONTWAIT); ++recvs;
        if(recv_error) return recv_error;
        *out=incoming; incoming=nullptr;
        if(!*out) return 0;
        const uint8_t peer[4]={192,0,2,1}; *ip=CIPAddress(peer); *port=1234;
        return (*out)->GetLength();
    }
};
struct CNetSubSystem {
    bool running=true;
    CTransportLayer transport;
    bool IsRunning() const { return running; }
    CTransportLayer *GetTransportLayer() { return &transport; }
};
'''
SOURCE = r'''
#include "fake.h"
#include "udp_bridge.h"
#include "network_bridge.h"
#include "socket_errno_bridge.h"
unsigned level;
int CNetBuffer::live;
CNetSubSystem net;
bool present=true;
CNetSubSystem *mpynn_network_get() { return present ? &net : nullptr; }
// Explicit fake error mapping; real mapping is independently tested with real headers.
extern "C" int mpynn_socket_error_from_circle(int r) { return r<0 ? MPYNN_IO : 0; }
int main() {
 uint32_t tokens[8], sentinel=999;
 assert(mpynn_udp_open(nullptr)==MPYNN_INVAL);
 present=false; assert(mpynn_udp_open(&sentinel)==MPYNN_NODEV && sentinel==999);
 present=true; net.running=false; assert(mpynn_udp_open(&sentinel)==MPYNN_NODEV);
 net.running=true; level=1; assert(mpynn_udp_open(&sentinel)==MPYNN_BUSY);
 level=0; net.transport.bind_error=-11;
 assert(mpynn_udp_open(&sentinel)==MPYNN_IO && sentinel==999);
 net.transport.bind_error=0;
 uint32_t bound; uint16_t local=777;
 int before_bind=net.transport.binds;
 assert(mpynn_udp_open_bound(68,&sentinel)==MPYNN_ADDRINUSE && sentinel==999);
 assert(net.transport.binds==before_bind);
 assert(mpynn_udp_open_bound(12345,&bound)==0);
 before_bind=net.transport.binds;
 assert(mpynn_udp_open_bound(12345,&sentinel)==MPYNN_ADDRINUSE && sentinel==999);
 assert(net.transport.binds==before_bind);
 assert(mpynn_udp_local_port(bound,&local)==0 && local==12345);
 const uint8_t local_ip[4]={192,0,2,10};
  int address_sets=net.transport.local_address_sets;
  assert(mpynn_udp_bind_local(bound,nullptr)==MPYNN_INVAL);
  assert(mpynn_udp_bind_local(999,local_ip)==MPYNN_BADF);
  assert(net.transport.local_address_sets==address_sets);
  assert(mpynn_udp_bind_local(bound,local_ip)==0);
  assert(net.transport.local_address_sets==address_sets+1);
  assert(memcmp(net.transport.local_ips[0],local_ip,4)==0);
  level=1; assert(mpynn_udp_bind_local(bound,local_ip)==MPYNN_BUSY);
  assert(net.transport.local_address_sets==address_sets+1);
  level=0; net.transport.local_address_error=-11;
  assert(mpynn_udp_bind_local(bound,local_ip)==MPYNN_IO);
  assert(net.transport.local_address_sets==address_sets+2);
  net.transport.local_address_error=0;
  assert(mpynn_udp_local_port(bound,nullptr)==MPYNN_INVAL);
 level=1; local=777;
 assert(mpynn_udp_local_port(bound,&local)==MPYNN_BUSY && local==777);
 level=0; assert(mpynn_udp_close(bound)==0);
 assert(mpynn_udp_local_port(bound,&local)==MPYNN_BADF && local==777);
 assert(mpynn_udp_open_bound(12345,&bound)==0); // immediately reusable by VM after close
 assert(mpynn_udp_close(bound)==0);
 for(auto &t:tokens) assert(mpynn_udp_open(&t)==0);
 assert(mpynn_udp_local_port(tokens[0],&local)==0 && local>=49152);
 assert(mpynn_udp_open_bound(local,&sentinel)==MPYNN_ADDRINUSE && sentinel==999);
 assert(mpynn_udp_open(&sentinel)==MPYNN_MFILE && sentinel==999);
 assert(mpynn_udp_broadcast(tokens[0],1)==0 && net.transport.broadcast);
 level=1;
 assert(mpynn_udp_broadcast(tokens[0],0)==MPYNN_BUSY && net.transport.broadcast);
 level=0;
 assert(mpynn_udp_broadcast(tokens[0],0)==0 && !net.transport.broadcast);
 unsigned events=999;
 assert(mpynn_udp_poll(tokens[0],1,&events)==0 && events==0);
 assert(mpynn_udp_poll(tokens[0],4,&events)==0 && events==4);
 assert(mpynn_udp_poll(tokens[0],0,nullptr)==MPYNN_INVAL);
 level=1; events=999;
 assert(mpynn_udp_poll(tokens[0],5,&events)==MPYNN_BUSY && events==999);
 level=0; net.running=false;
 assert(mpynn_udp_poll(tokens[0],5,&events)==0 && events==MPYNN_UDP_POLL_ERR);
 net.running=true; net.transport.connected=false;
 assert(mpynn_udp_poll(tokens[0],0,&events)==0 && events==MPYNN_UDP_POLL_HUP);
 net.transport.connected=true;
 const uint8_t ip[4]={192,0,2,2}; char out[4]={}; uint8_t peer[4]={}; uint16_t port=0; size_t n=999;
 assert(mpynn_udp_send(tokens[0],"abc",3)==MPYNN_NOTCONN);
 assert(mpynn_udp_connect(tokens[0],ip,0)==MPYNN_INVAL);
 assert(mpynn_udp_connect(tokens[0],ip,1234)==0);
 uint16_t own_port;assert(mpynn_udp_local_port(tokens[0],&own_port)==0 && own_port==local);
 assert(mpynn_udp_send(tokens[0],"abc",3)==0 && CNetBuffer::live==0);
 assert(mpynn_udp_send(tokens[0],nullptr,0)==0 && CNetBuffer::live==0);
 net.transport.peer_error=-11;
 assert(mpynn_udp_connect(tokens[0],ip,4321)==MPYNN_IO && net.transport.peer_port==1234);
 net.transport.peer_error=0;
 assert(mpynn_udp_sendto(tokens[0],"abc",3,ip,1234)==0 && CNetBuffer::live==0);
 net.transport.send_error=-11;
 assert(mpynn_udp_sendto(tokens[0],"abc",3,ip,1234)==MPYNN_IO && CNetBuffer::live==0);
 net.transport.send_error=0;
 int sends=net.transport.sends;
 assert(mpynn_udp_sendto(tokens[0],"",0,ip,1234)==0 && CNetBuffer::live==0);
 assert(mpynn_udp_sendto(tokens[0],nullptr,0,ip,1234)==0 && CNetBuffer::live==0);
 assert(mpynn_udp_sendto(tokens[0],nullptr,1,ip,1234)==MPYNN_INVAL);
 sends=net.transport.sends;
 assert(mpynn_udp_sendto(tokens[0],"a",1473,ip,1234)==MPYNN_INVAL);
 assert(net.transport.sends==sends);
 assert(mpynn_udp_recvfrom(tokens[0],out,3,&n,peer,&port)==MPYNN_AGAIN && n==999);
 /* queue setup kept before the pending-error tests */
 net.transport.incoming=new CNetBuffer(CNetBuffer::UDPSend,6,"abcdef");
  int pending=999, takes=net.transport.error_takes;
  assert(mpynn_udp_take_error(tokens[0],nullptr)==MPYNN_INVAL);
  uint32_t stale=999;
  assert(mpynn_udp_take_error(stale,&pending)==MPYNN_BADF && pending==999);
  level=1; net.transport.recv_error=-11;
  assert(mpynn_udp_take_error(tokens[0],&pending)==MPYNN_BUSY && pending==999);
  assert(net.transport.error_takes==takes && net.transport.recv_error==-11);
  level=0;
  CNetBuffer *queued=net.transport.incoming;
   int error_recvs=net.transport.recvs;
  queued=net.transport.incoming;
  assert(mpynn_udp_take_error(tokens[0],&pending)==0 && pending==MPYNN_IO);
  assert(mpynn_udp_poll(tokens[0],1,&events)==0 && events==1);
  assert(net.transport.error_takes==takes+1 && net.transport.recvs==error_recvs);
  assert(net.transport.incoming==queued && queued->bytes=="abcdef" && CNetBuffer::live==1);
  assert(mpynn_udp_take_error(tokens[0],&pending)==0 && pending==0);
  /* queue setup kept before the pending-error tests */
  queued=net.transport.incoming;
  assert(mpynn_udp_poll(tokens[0],1,&events)==0 && events==1);
  assert(mpynn_udp_take_error(tokens[0],&pending)==0 && pending==0);
  assert(net.transport.incoming==queued && queued->bytes=="abcdef" && CNetBuffer::live==1);
  int before_recv=net.transport.recvs;
 assert(mpynn_udp_poll(tokens[0],5,&events)==0 && events==5);
 assert(mpynn_udp_poll(tokens[0],4,&events)==0 && events==4);
 assert(net.transport.recvs==before_recv && CNetBuffer::live==1);
 assert(mpynn_udp_recvfrom(tokens[0],out,3,&n,peer,&port)==0);
 assert(n==3 && memcmp(out,"abc",3)==0 && out[3]==0 && port==1234 && peer[3]==1);
 assert(CNetBuffer::live==0);
 assert(mpynn_udp_recvfrom(tokens[0],out,3,&n,peer,&port)==MPYNN_AGAIN);
 net.transport.incoming=new CNetBuffer(CNetBuffer::UDPSend,0,nullptr);
 assert(mpynn_udp_recvfrom(tokens[0],nullptr,0,&n,peer,&port)==0 && n==0);
 level=2; int closes=net.transport.closes;
 assert(mpynn_udp_close_all()==MPYNN_BUSY && net.transport.closes==closes);
 assert(mpynn_udp_close(tokens[0])==MPYNN_BUSY);
 level=0;
 uint32_t old=tokens[0]; assert(mpynn_udp_close(old)==0);
 assert(mpynn_udp_open(&tokens[0])==0 && tokens[0]!=old);
 assert(mpynn_udp_close(old)==MPYNN_BADF);
 assert(mpynn_udp_poll(old,0,&events)==0 && events==MPYNN_UDP_POLL_NVAL);
 assert(mpynn_udp_sendto(old,"a",1,ip,1234)==MPYNN_BADF);
 net.transport.close_error=-11;
 closes=net.transport.closes;
 assert(mpynn_udp_close_all()==MPYNN_IO && net.transport.closes==closes+8);
 assert(mpynn_udp_close_all()==0);
 for(auto t:tokens) assert(mpynn_udp_close(t)==MPYNN_BADF);
 assert(CNetBuffer::live==0);
}
'''

class UdpBridgeTests(unittest.TestCase):
    def test_transport_ownership_tokens_and_cleanup(self):
        if not CXX.is_file():
            self.skipTest('host g++ unavailable')
        env=os.environ.copy()
        env['PATH']=str(CXX.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'fake.h').write_text(FAKE)
            for name in ('circle/net/netsubsystem.h','circle/net/transportlayer.h',
                         'circle/net/netbuffer.h','circle/net/in.h','circle/synchronize.h'):
                p=root/name; p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text('#include "fake.h"\n')
            (root/'main.cpp').write_text(SOURCE)
            exe=root/'test.exe'
            for cmd in ([str(CXX),'-std=c++17','-Wall','-Wextra','-Werror',
                         '-I'+str(root),'-I'+str(PORT),str(PORT/'udp_bridge.cpp'),
                         str(root/'main.cpp'),'-o',str(exe)], [str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':
    unittest.main()
