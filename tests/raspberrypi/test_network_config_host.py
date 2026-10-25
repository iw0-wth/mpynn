# SPDX-License-Identifier: MIT
"""Execute production Circle configuration/DHCP overrides with a fake scheduler.

Host-only: exercises cancellation at socket-internal Yield and DHCP waits,
static/DHCP/static/DHCP transitions, persistent worker, runtime flags, broadcast
updates and actual inline ARP/route invalidation. No real Ethernet/ARM emulation.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'ports/raspberrypi'
OVERLAY = PORT / 'upstream_overrides/circle'
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')
STUBS = {
'assert.h': '#include_next <assert.h>\n',
'circle/types.h': r'''
#pragma once
#include <cstdint>
#include <cstddef>
using u8=uint8_t; using u16=uint16_t; using u32=uint32_t;
using uintptr=uintptr_t; using boolean=bool;
#define TRUE true
#define FALSE false
#define HZ 100
''',
'circle/macros.h': r'''
#pragma once
#define PACKED __attribute__((packed))
#define ASSERT_STATIC(x) static_assert(x)
#define BE(x) ((uint16_t)(((x)<<8)|((x)>>8)))
''',
'circle/net/sizes.h': r'''
#pragma once
#define MAC_ADDRESS_SIZE 6
#define IP_ADDRESS_SIZE 4
#define ETH_HEADER_LEN 14
#define IP_HEADER_LEN 20
''',
'circle/net/ipaddress.h': r'''
#pragma once
#include <circle/types.h>
#include <circle/net/sizes.h>
#include <cstring>
class CString;
class CIPAddress {
public:
 u8 bytes[4]={};
 void Set(const u8 *p) { memcpy(bytes,p,4); }
 void Set(u32 n) { memcpy(bytes,&n,4); }
 void SetBroadcast() { memset(bytes,255,4); }
 const u8 *Get() const { return bytes; }
 void CopyTo(u8 *p) const { memcpy(p,bytes,4); }
 bool IsNull() const { return !(bytes[0]|bytes[1]|bytes[2]|bytes[3]); }
 bool operator!=(u32 n) const { return memcmp(bytes,&n,4)!=0; }
 bool operator!=(const u8 *p) const { return memcmp(bytes,p,4)!=0; }
 void Format(CString *) const {}
};
''',
'circle/macaddress.h': r'''
#pragma once
#include <circle/types.h>
#include <cstring>
class CMACAddress {
 u8 bytes[6]={2,3,4,5,6,7};
public:
 CMACAddress()=default;
 CMACAddress(const u8 *p) { memcpy(bytes,p,6); }
 const u8 *Get() const { return bytes; }
 void CopyTo(u8 *p) const { memcpy(p,bytes,6); }
 bool operator!=(const CMACAddress &v) const { return memcmp(bytes,v.bytes,6)!=0; }
};
''',
'circle/string.h': r'''
#pragma once
#include <string>
class CString {
 std::string value;
public:
 CString(const char *s=""):value(s){}
 unsigned GetLength() const { return value.size(); }
 operator const char *() const { return value.c_str(); }
};
''',
'circle/spinlock.h': r'''
#pragma once
class CSpinLock { public: void Acquire() {} void Release() {} };
''',
'circle/net/netbuffer.h': r'''
#pragma once
class CNetBuffer {};
''',
'circle/net/netbufferqueue.h': r'''
#pragma once
class CNetBufferQueue {
public:
 unsigned flushes=0;
 CNetBufferQueue(bool=false) {}
 void Flush() { ++flushes; }
};
''',
'circle/net/netqueue.h': r'''
#pragma once
class CNetQueue { public: unsigned flushes=0; void Flush() { ++flushes; } };
''',
'circle/net/routecache.h': r'''
#pragma once
class CRouteCache { public: unsigned flushes=0; void Flush() { ++flushes; } };
''',
'circle/net/icmphandler.h': r'''
#pragma once
class CICMPHandler {};
enum TICMPNotificationType { Notice };
''',
'circle/net/igmphandler.h': r'''
#pragma once
class CIGMPHandler {};
''',
'circle/net/netdevlayer.h': r'''
#pragma once
#include <circle/macaddress.h>
class CNetConfig;
enum TNetDeviceType { NetDeviceTypeEthernet };
class CNetDeviceLayer {
 CMACAddress mac;
public:
 bool running=true;
 CNetDeviceLayer(CNetConfig *,TNetDeviceType) {}
 bool Initialize(bool) { return true; }
 bool IsRunning() const { return running; }
 void Process() {}
 const CMACAddress *GetMACAddress() const { return &mac; }
};
''',
'circle/net/transportlayer.h': r'''
#pragma once
class CNetConfig; class CNetworkLayer;
class CTransportLayer {
public:
 CTransportLayer(CNetConfig *,CNetworkLayer *) {}
 bool Initialize() { return true; }
 void Process() {}
};
''',
'circle/sched/task.h': r'''
#pragma once
class CTask { public: virtual ~CTask()=default; void SetName(const char *) {} };
''',
'circle/net/nettask.h': r'''
#pragma once
class CNetSubSystem;
class CNetTask { public: CNetTask(CNetSubSystem *) {} };
''',
'circle/timer.h': r'''
#pragma once
#include <circle/types.h>
using TKernelTimerHandle=unsigned;
extern unsigned test_ms;
class CTimer {
public:
 unsigned cancelled=0;
 static CTimer *Get() { static CTimer v; return &v; }
 unsigned GetUptime() const { return test_ms/1000; }
 unsigned GetTicks() const { return test_ms/10; }
 unsigned GetClockTicks() const { return test_ms*1000; }
 void CancelKernelTimer(unsigned) { ++cancelled; }
};
''',
'circle/sched/scheduler.h': r'''
#pragma once
#include <circle/timer.h>
extern void (*on_yield)();
class CScheduler {
public:
 static CScheduler *Get() { static CScheduler v; return &v; }
 void Yield() { test_ms+=10; if(on_yield) on_yield(); }
 void MsSleep(unsigned n) { test_ms+=n; if(on_yield) on_yield(); }
};
''',
'circle/logger.h': r'''
#pragma once
#include <cstdarg>
enum { LogError,LogWarning,LogNotice,LogDebug };
class CLogger {
public:
 static CLogger *Get() { static CLogger v; return &v; }
 void Write(const char *,int,const char *,...) {}
};
''',
'circle/util.h': '#pragma once\n#include <cstring>\ninline u32 be2le32(u32 n) { return __builtin_bswap32(n); }\n',
'circle/net/in.h': '#pragma once\n#define IPPROTO_UDP 17\n#define MSG_DONTWAIT 64\n',
'circle/net/socket.h': r'''
#pragma once
#include <circle/types.h>
#include <circle/net/ipaddress.h>
#include <circle/sched/scheduler.h>
#include <cstring>
class CNetSubSystem;
extern bool reply_enabled, connect_error;
extern unsigned send_count, socket_count, renewal_changes;
class CSocket {
 u8 reply[548]={};
 bool pending=false;
public:
 CSocket(CNetSubSystem *,int) { ++socket_count; }
 int Bind(unsigned) { return 0; }
 int Connect(const CIPAddress &,unsigned) { pending=false; return connect_error?-1:0; }
 int SetOptionBroadcast(bool) { return 0; }
 int Send(const void *p,unsigned n,int) {
  ++send_count;
  memcpy(reply,p,n);
  reply[0]=2; // BOOTREPLY
  reply[16]=10; reply[17]=0; reply[18]=0; reply[19]=80; // yiaddr
  const u8 msg=reply[242]==1 ? 2 : 5; // discover -> offer; request -> ACK
  const u8 options[]={53,1,msg,1,4,255,255,255,0,3,4,10,0,0,1,
                     6,4,1,1,1,1,51,4,0,0,0,8,54,4,10,0,0,1,
                     58,4,0,0,0,2,59,4,0,0,0,4,255};
  memset(reply+240,0,308); memcpy(reply+240,options,sizeof options);
  if (renewal_changes & 1) reply[19]=81; // IP only
   if (renewal_changes & 2) reply[247]=254; // mask only (/23)
   if (renewal_changes & 4) reply[254]=2; // gateway only
   if (renewal_changes & 8) reply[260]=2; // DNS only
   pending=reply_enabled;
  CScheduler::Get()->Yield(); // real Circle Send also yields for UDP
  return n;
 }
 int Receive(void *p,unsigned n,int) {
  if(!pending) return 0;
  pending=false; memcpy(p,reply,n); return n;
 }
};
''',
}
SOURCE = r'''
#include <string>
#include <cstring>
#include <cassert>
#define private public
#include <circle/net/netsubsystem.h>
#include <circle/net/dhcpclient.h>
#undef private
#include <circle/sched/scheduler.h>
unsigned test_ms=0,send_count=0,socket_count=0,renewal_changes=0;
bool reply_enabled=true,connect_error=false;
void (*on_yield)()=nullptr;

// Use production header cache-reset methods with simple host constructors.
CARPHandler::CARPHandler(CNetConfig *c,CNetDeviceLayer *d,CLinkLayer *l,CNetBufferQueue *q)
 :m_pNetConfig(c),m_pNetDevLayer(d),m_pLinkLayer(l),m_pRxQueue(q),m_nEntries(0),m_nTicksLastCleanup(0) {}
CARPHandler::~CARPHandler() {}
CLinkLayer::CLinkLayer(CNetConfig *c,CNetDeviceLayer *d)
 :m_pNetConfig(c),m_pNetDevLayer(d),m_pNetworkLayer(nullptr),m_pARPHandler(nullptr),m_nRawProtocolType(0) {}
CLinkLayer::~CLinkLayer() {}
bool CLinkLayer::Initialize() { return true; }
void CLinkLayer::AttachLayer(CNetworkLayer *p) { m_pNetworkLayer=p; }
void CLinkLayer::Process() {}
CNetworkLayer::CNetworkLayer(CNetConfig *c,CLinkLayer *l)
 :m_pNetConfig(c),m_pLinkLayer(l),m_pICMPHandler(nullptr),m_pIGMPHandler(nullptr),m_pICMPRxQueue2(nullptr) {}
CNetworkLayer::~CNetworkLayer() {}
bool CNetworkLayer::Initialize() { return true; }
void CNetworkLayer::Process() {}

const u8 ip[]={192,168,5,9}, mask[]={255,255,255,0}, gateway[]={192,168,5,1}, dns[]={8,8,4,4};
CNetSubSystem *net;
CDHCPClient *worker;
void set_static() { net->Configure(ip,mask,gateway,dns); on_yield=nullptr; }
void restart_dhcp() { net->Configure(); on_yield=nullptr; }
void static_then_dhcp() { net->Configure(ip,mask,gateway,dns); net->Configure(); on_yield=nullptr; }
unsigned cancel_at_send=0, yield_calls=0;
void cancel_ack_send() { if(send_count==cancel_at_send) set_static(); }
void cancel_receive_wait() { if(++yield_calls==2) set_static(); }
struct Stop {};
unsigned phase=0, paused_ms=0;
void run_modes() {
 if (phase==0 && worker->IsBound()) {
  paused_ms=test_ms; set_static(); on_yield=run_modes; phase=1;
 } else if (phase==1) {
  assert(test_ms-paused_ms<=100);
  assert(!worker->IsBound() && net->IsRunning() && !net->GetConfig()->IsDHCPUsed());
  net->Configure(); phase=2;
 } else if (phase==2 && worker->IsBound()) {
  phase=3; throw Stop{};
 }
}
void stop_in_backoff() {
 if(test_ms>600) { assert(!worker->IsBound()); throw Stop{}; }
}
int main() {
 CNetSubSystem subsystem;
 net=&subsystem;
 assert(!net->IsRunning() && net->GetConfig()->IsDHCPUsed());
 auto *transport=net->GetTransportLayer();
 net->Configure(ip,mask,gateway,dns);
 assert(net->IsRunning() && !net->GetConfig()->IsDHCPUsed());
 assert(net->GetConfig()->GetBroadcastAddress()->bytes[3]==255);
 assert(!memcmp(net->GetConfig()->GetIPAddress()->bytes,ip,4));
 assert(!memcmp(net->GetConfig()->GetDefaultGateway()->bytes,gateway,4));
 assert(!memcmp(net->GetConfig()->GetDNSServer()->bytes,dns,4));
 net->GetNetDeviceLayer()->running=false; assert(!net->IsRunning());
 net->GetNetDeviceLayer()->running=true;
 net->Configure(); assert(!net->IsRunning() && net->GetConfig()->IsDHCPUsed());
 net->Process(); worker=net->m_pDHCPClient;
 assert(worker && socket_count==1);

 // Socket-internal Yield cancellation must stop an obsolete OFFER/ACK exchange.
 on_yield=set_static;
 assert(worker->SelectAndRequest()==DHCPStatusTimeout);
 assert(!worker->IsBound() && net->IsRunning());
 worker->HaltNetwork(); // obsolete lease reset is forbidden
 assert(!memcmp(net->GetConfig()->GetIPAddress()->bytes,ip,4));
 unsigned sends=send_count;
 assert(!worker->SendAndReceive(false) && send_count==sends);
 net->Configure(); worker->m_nActiveGeneration=worker->m_nRequestedGeneration;
 on_yield=static_then_dhcp;
 assert(worker->SelectAndRequest()==DHCPStatusTimeout);
 assert(!worker->IsBound() && net->GetConfig()->GetIPAddress()->IsNull());
 worker->m_nActiveGeneration=worker->m_nRequestedGeneration;
 assert(worker->SelectAndRequest()==DHCPStatusSuccess && worker->IsBound());
 assert(net->GetConfig()->GetIPAddress()->bytes[3]==80 && net->IsRunning());
 // Reach REQUEST/ACK then change modes inside its socket Send Yield.
 net->Configure(); worker->m_nActiveGeneration=worker->m_nRequestedGeneration;
 cancel_at_send=send_count+2; on_yield=cancel_ack_send;
 assert(worker->SelectAndRequest()==DHCPStatusTimeout);
 assert(!worker->IsBound() && !memcmp(net->GetConfig()->GetIPAddress()->bytes,ip,4));

 // Cancel while waiting for offer, sleeping for retry, and renewing a lease.
 net->Configure(); worker->m_nActiveGeneration=worker->m_nRequestedGeneration;
 reply_enabled=false; on_yield=cancel_receive_wait; yield_calls=0;
 assert(!worker->SendAndReceive(false) && yield_calls==2);
 net->Configure(); worker->m_nActiveGeneration=worker->m_nRequestedGeneration;
 on_yield=set_static; assert(!worker->SleepCurrent(60));
 net->Configure(); worker->m_nActiveGeneration=worker->m_nRequestedGeneration;
 reply_enabled=true; assert(worker->SelectAndRequest()==DHCPStatusSuccess);
 worker->m_nBoundSince=test_ms/1000; on_yield=set_static;
 assert(worker->RenewOrRebind(true,4)==DHCPStatusCancelled);
 worker->HaltNetwork(); assert(net->IsRunning());

 // Renew and rebind must reject any changed config field, not only all four.
 for (bool renew : {false,true}) {
  for (unsigned change : {0u,1u,2u,4u,8u,15u}) {
   renewal_changes=0;
   net->Configure(); worker->m_nActiveGeneration=worker->m_nRequestedGeneration;
   assert(worker->SelectAndRequest()==DHCPStatusSuccess);
   worker->m_nBoundSince=test_ms/1000;
   auto original_ip=net->GetConfig()->GetIPAddress()->bytes[3];
   auto original_dns=net->GetConfig()->GetDNSServer()->bytes[3];
   renewal_changes=change;
   assert(worker->RenewOrRebind(renew,8)==(change ? DHCPStatusConfigChanged : DHCPStatusSuccess));
   assert(net->GetConfig()->GetIPAddress()->bytes[3]==original_ip);
   assert(net->GetConfig()->GetDNSServer()->bytes[3]==original_dns);
   if(change) {
    worker->HaltNetwork();
    assert(!worker->IsBound() && !net->IsRunning());
    assert(net->GetConfig()->GetIPAddress()->IsNull());
    renewal_changes=0;
    assert(worker->SelectAndRequest()==DHCPStatusSuccess && net->IsRunning());
   }
  }
 }
 renewal_changes=0;
 // Run permanent worker through DHCP -> static -> DHCP; no new task/socket.
 net->Configure(); on_yield=run_modes;
 try { worker->Run(); assert(false); } catch(Stop &) {}
 on_yield=nullptr;
 assert(phase==3 && worker==net->m_pDHCPClient && socket_count==1);
 assert(net->GetTransportLayer()==transport);
 // Fatal connect failures now retry instead of returning/deleting this CTask.
 net->Configure(); connect_error=true; test_ms=0; on_yield=stop_in_backoff;
 try { worker->Run(); assert(false); } catch(Stop &) {}
 on_yield=nullptr; connect_error=false;
 assert(worker==net->m_pDHCPClient && socket_count==1);

 // Execute actual ARP Flush against each state and pending-frame queue.
 CARPHandler arp(net->GetConfig(),net->GetNetDeviceLayer(),net->GetLinkLayer(),&net->m_LinkLayer.m_ARPRxQueue);
 CNetBufferQueue queues[5];
 arp.m_nEntries=5;
 for(unsigned i=0;i<5;++i) { arp.m_Entry[i].State=static_cast<TARPState>(i); arp.m_Entry[i].pTxQueue=&queues[i]; arp.m_Entry[i].hTimer=i+1; }
 net->m_LinkLayer.m_pARPHandler=&arp;
 unsigned cancelled=CTimer::Get()->cancelled;
 unsigned routes=net->m_NetworkLayer.m_RouteCache.flushes;
 net->Configure(ip,mask,gateway,dns);
 assert(CTimer::Get()->cancelled==cancelled+1); // only RequestSent has live timer
 for(unsigned i=0;i<5;++i) { assert(arp.m_Entry[i].State==ARPStateFreeSlot && queues[i].flushes==1); }
 assert(net->m_NetworkLayer.m_RouteCache.flushes==routes+1);
 assert(net->m_LinkLayer.m_ARPRxQueue.flushes && net->m_LinkLayer.m_IPRxQueue.flushes);
 assert(net->m_NetworkLayer.m_RxQueue.flushes && net->m_NetworkLayer.m_ICMPNotificationQueue.flushes);
 assert(net->GetTransportLayer()==transport);
}
'''


class NativeNetworkConfigurationTests(unittest.TestCase):
    def test_runtime_config_and_dhcp_cancellation(self):
        if not CXX.is_file():
            self.skipTest('host g++ unavailable')
        env = os.environ.copy()
        env['PATH'] = str(CXX.parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, text in STUBS.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            (root/'circle/net/netconfig.h').write_text(
                (ROOT/'lib/circle/include/circle/net/netconfig.h').read_text())
            (root/'main.cpp').write_text(SOURCE)
            exe = root/'test.exe'
            commands = [
                [str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                 '-I'+str(root), '-I'+str(OVERLAY/'include'),
                 str(OVERLAY/'lib/net/netsubsystem.cpp'), str(OVERLAY/'lib/net/dhcpclient.cpp'),
                 str(ROOT/'lib/circle/lib/net/netconfig.cpp'), str(root/'main.cpp'), '-o', str(exe)],
                [str(exe)]]
            for command in commands:
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, str(command)+'\n'+result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
