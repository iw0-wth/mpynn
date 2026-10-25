# SPDX-License-Identifier: MIT
"""Compile the real bridge against fake Circle; no firmware or real network.

The fake registers tasks at construction without running them. A Connect hook
simulates another task executing while the worker is blocked. Run return and
later scheduler deletion are separate, detecting self-deletion and stale job
references. This is not an ARM context-switch, TCP timer, or kernel GC test.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'ports/raspberrypi'
FAKE = r'''
#pragma once
#include <cstdint>
#include <cstring>
#include <cassert>
#include <vector>
#include <functional>
#define TASK_LEVEL 0
#define IPPROTO_TCP 6
extern unsigned level;
inline unsigned CurrentExecutionLevel() { return level; }
struct CIPAddress {
    uint8_t bytes[4];
    explicit CIPAddress(const uint8_t *p) { memcpy(bytes, p, 4); }
};
struct CTask {
    static std::vector<CTask *> ready, dead;
    static CTask *current;
    static int created, destroyed;
    CTask() { ready.push_back(this); ++created; }
    virtual ~CTask() { assert(current != this); ++destroyed; }
    virtual void Run() = 0;
};
struct CScheduler {
    static bool active;
    static bool IsActive() { return active; }
    static void step() {
        assert(!CTask::current && !CTask::ready.empty());
        CTask *task = CTask::ready.front();
        CTask::ready.erase(CTask::ready.begin());
        CTask::current = task;
        task->Run(); // TaskEntry still needs the worker alive here.
        assert(CTask::current == task);
        CTask::dead.push_back(task);
        CTask::current = nullptr;
    }
    static void reap() {
        assert(!CTask::current);
        for (CTask *task : CTask::dead) delete task;
        CTask::dead.clear();
    }
    static void drain() { while (!CTask::ready.empty()) step(); reap(); }
};
struct CTransportLayer {
    int connects=0, next=0, result=0, close_error=0;
    uint16_t occupied_port=0;
    int queries=0;
    bool IsPortInUse(uint16_t port,int protocol) {assert(level==TASK_LEVEL && protocol==IPPROTO_TCP);++queries;return port && port==occupied_port;}
    std::vector<int> owned, closed, retained;
    int retains=0, releases=0;
    int RetainConnection(int handle) {
        assert(!owned.empty() && owned.back()==handle);
        retained.push_back(handle); ++retains; return 0;
    }
    int ReleaseConnection(int handle) {
        assert(!closed.empty() && closed.back()==handle);
        auto it=retained.begin();
        while (it!=retained.end() && *it!=handle) ++it;
        assert(it!=retained.end()); retained.erase(it); ++releases; return 0;
    }
    std::function<void()> during_connect;
    uint8_t last_ip[4] = {};
    unsigned last_port=0, last_own=0;
    int Connect(const CIPAddress &ip, uint16_t port, uint16_t own, int protocol) {
        assert(CTask::current && level==TASK_LEVEL && protocol==IPPROTO_TCP);
        ++connects; memcpy(last_ip,ip.bytes,4); last_port=port; last_own=own;
        if (during_connect) during_connect();
        if (result<0) return result;
        int handle=next++; owned.push_back(handle); return handle;
    }
    int Disconnect(int handle) {
        assert(level==TASK_LEVEL);
        auto it=owned.begin();
        while (it!=owned.end() && *it!=handle) ++it;
        assert(it!=owned.end()); owned.erase(it); closed.push_back(handle);
        return close_error;
    }
};
struct CNetSubSystem {
    bool running=true;
    CTransportLayer transport;
    bool IsRunning() const { return running; }
    bool transport_present=true;
    CTransportLayer *GetTransportLayer() { return transport_present ? &transport : nullptr; }
};
'''
SOURCE = r'''
#include "fake.h"
#include "tcp_connect_bridge.h"
#include "socket_errno_bridge.h"
unsigned level=0;
std::vector<CTask *> CTask::ready, CTask::dead;
CTask *CTask::current=nullptr;
int CTask::created=0, CTask::destroyed=0;
bool CScheduler::active=true;
CNetSubSystem net;
bool present=true;
int network_gets=0, maps=0;
CNetSubSystem *mpynn_network_get() { ++network_gets; return present ? &net : nullptr; }
// Mapper is a link seam, not a replacement errno header. Verify result routing.
extern "C" int mpynn_socket_error_from_circle(int r) {
    ++maps; return r == -42 ? MPYNN_NOTCONN : r<0 ? MPYNN_IO : 0;
}
int claim_error=0, claimed_handle=-1;
extern "C" int mpynn_tcp_stream_claim(int handle, uint32_t *token) {
    if (claim_error) return claim_error;
    claimed_handle=handle; *token=1234; return 0;
}
// Include actual production implementation, also enabling deterministic testing
// of generation retirement without billions of iterations or a production hook.
#include "tcp_connect_bridge.cpp"
const uint8_t ip[4]={192,0,2,1};
void snapshot(uint32_t t,unsigned expected,int expected_error=0) {
    unsigned state=99; int error=99;
    int gets=network_gets, calls=net.transport.connects, created=CTask::created;
    assert(mpynn_tcp_connect_poll(t,&state,&error)==0);
    assert(state==expected && error==expected_error);
    assert(network_gets==gets && net.transport.connects==calls && CTask::created==created);
}
void stale(uint32_t t) {
    unsigned s=99; int e=99,h=99;
    assert(mpynn_tcp_connect_poll(t,&s,&e)==MPYNN_BADF && s==99 && e==99);
    assert(mpynn_tcp_connect_take(t,&h)==MPYNN_BADF && h==99);
    assert(mpynn_tcp_connect_cancel(t)==MPYNN_BADF);
}
int main() {
    uint32_t t=999; unsigned s=99; int e=99,h=99;
    // Explicit bind query is context-safe, non-mutating, and preserves output on errors.
    unsigned occupied=99;
    int gets=network_gets;
    for (unsigned irq : {1u,2u}) {
        level=irq;
        assert(mpynn_tcp_port_in_use(4321,&occupied)==MPYNN_BUSY && occupied==99);
        assert(net.transport.queries==0 && network_gets==gets);
    }
    level=0;
    assert(mpynn_tcp_port_in_use(0,&occupied)==MPYNN_INVAL && occupied==99);
    assert(mpynn_tcp_port_in_use(4321,nullptr)==MPYNN_INVAL);
    present=false;
    assert(mpynn_tcp_port_in_use(4321,&occupied)==MPYNN_NODEV && occupied==99);
    present=true; net.running=false;
    assert(mpynn_tcp_port_in_use(4321,&occupied)==MPYNN_NODEV && occupied==99);
    net.running=true; net.transport_present=false;
    assert(mpynn_tcp_port_in_use(4321,&occupied)==MPYNN_NODEV && occupied==99);
    net.transport_present=true;
    assert(mpynn_tcp_port_in_use(4321,&occupied)==0 && occupied==0);
    net.transport.occupied_port=4321;
    assert(mpynn_tcp_port_in_use(4321,&occupied)==0 && occupied==1);
    assert(mpynn_tcp_port_in_use(4322,&occupied)==0 && occupied==0);
    assert(net.transport.queries==3 && !net.transport.connects && !CTask::created);
    assert(net.transport.owned.empty() && net.transport.retained.empty());
    net.transport.occupied_port=0;
    assert(mpynn_tcp_connect_start(nullptr,80,&t)==MPYNN_INVAL);
    assert(mpynn_tcp_connect_start(ip,80,nullptr)==MPYNN_INVAL);
    assert(mpynn_tcp_connect_start(ip,0,&t)==MPYNN_INVAL);
    assert(mpynn_tcp_connect_start(ip,65536,&t)==MPYNN_INVAL);
    for (uint8_t first : {0,224,239,240,255}) {
        uint8_t bad[4]={first,0,0,1};
        assert(mpynn_tcp_connect_start(bad,80,&t)==MPYNN_INVAL);
    }
    assert(t==999 && CTask::created==0);
    present=false; assert(mpynn_tcp_connect_start(ip,80,&t)==MPYNN_NODEV);
    present=true; net.running=false;
    assert(mpynn_tcp_connect_start(ip,80,&t)==MPYNN_NODEV);
    net.running=true; CScheduler::active=false;
    assert(mpynn_tcp_connect_start(ip,80,&t)==MPYNN_NODEV);
    CScheduler::active=true;
    stale(0); stale(UINT32_MAX);
    uint8_t copied[4]={192,0,2,1};
    assert(mpynn_tcp_connect_start(copied,65535,&t)==0);
    copied[3]=77;
    assert(net.transport.connects==0);
    snapshot(t,MPYNN_TCP_CONNECT_PENDING);
    assert(mpynn_tcp_connect_take(t,&h)==MPYNN_AGAIN && h==99);
    assert(mpynn_tcp_connect_poll(t,nullptr,&e)==MPYNN_INVAL);
    assert(mpynn_tcp_connect_poll(t,&s,nullptr)==MPYNN_INVAL);
    assert(mpynn_tcp_connect_take(t,nullptr)==MPYNN_INVAL);
    for (unsigned irq : {1u,2u}) {
        level=irq; uint32_t out=999;
        assert(mpynn_tcp_connect_start(ip,80,&out)==MPYNN_BUSY && out==999);
        assert(mpynn_tcp_connect_poll(t,&s,&e)==MPYNN_BUSY && s==99 && e==99);
        assert(mpynn_tcp_connect_take(t,&h)==MPYNN_BUSY && h==99);
        assert(mpynn_tcp_connect_cancel(t)==MPYNN_BUSY);
    }
    level=0; CScheduler::step();
    assert(net.transport.last_ip[3]==1 && net.transport.last_port==65535 && net.transport.last_own==0);
    snapshot(t,MPYNN_TCP_CONNECT_SUCCEEDED);
    assert(mpynn_tcp_connect_take(t,&h)==0 && h==0);
    stale(t); assert(net.transport.closed.empty());
    assert(net.transport.retains==1 && net.transport.releases==0);
    net.transport.Disconnect(h); // caller, not bridge, owns taken handle
    net.transport.ReleaseConnection(h);
    CScheduler::reap();

    uint32_t stream=999;
    assert(mpynn_tcp_connect_start(ip,80,&t)==0);
    assert(mpynn_tcp_connect_finish(t,&stream)==MPYNN_AGAIN && stream==999);
    CScheduler::step();
    claim_error=MPYNN_MFILE;
    assert(mpynn_tcp_connect_finish(t,&stream)==MPYNN_MFILE && stream==999);
    snapshot(t,MPYNN_TCP_CONNECT_SUCCEEDED);
    claim_error=0;
    assert(mpynn_tcp_connect_finish(t,&stream)==0 && stream==1234);
    stale(t);
    net.transport.Disconnect(claimed_handle);
    net.transport.ReleaseConnection(claimed_handle);
    CScheduler::reap();

    // Queued cancellation retains all four bounded slots until workers run.
    uint32_t tokens[4];
    for (auto &token : tokens) assert(mpynn_tcp_connect_start(ip,80,&token)==0);
    assert(mpynn_tcp_connect_start(ip,80,&t)==MPYNN_MFILE);
    for (auto token : tokens) {
        assert(mpynn_tcp_connect_cancel(token)==0);
        assert(mpynn_tcp_connect_cancel(token)==0);
        snapshot(token,MPYNN_TCP_CONNECT_ABANDONED);
        assert(mpynn_tcp_connect_take(token,&h)==MPYNN_AGAIN);
    }
    assert(mpynn_tcp_connect_start(ip,80,&t)==MPYNN_MFILE);
    int calls=net.transport.connects;
    CScheduler::drain(); assert(net.transport.connects==calls);
    for (auto token : tokens) stale(token);

    // Cancellation while Connect is blocked; both late success and failure.
    for (int result : {0,-42}) {
        net.transport.result=result;
        assert(mpynn_tcp_connect_start(ip,80,&t)==0);
        auto closes=net.transport.closed.size();
        net.transport.during_connect=[&] {
            snapshot(t,MPYNN_TCP_CONNECT_PENDING);
            assert(mpynn_tcp_connect_cancel(t)==0);
            snapshot(t,MPYNN_TCP_CONNECT_ABANDONED);
            // Fill the other slots while worker still holds its slot.
            for (int i=0;i<3;++i) assert(mpynn_tcp_connect_start(ip,80,&tokens[i])==0);
            uint32_t out=999;
            assert(mpynn_tcp_connect_start(ip,80,&out)==MPYNN_MFILE && out==999);
            for (int i=0;i<3;++i) assert(mpynn_tcp_connect_cancel(tokens[i])==0);
        };
        CScheduler::step(); net.transport.during_connect={};
        stale(t);
        assert(net.transport.closed.size()==closes+(result==0 ? 1 : 0));
        // Reuse released slot BEFORE old worker destruction; destructor must
        // not clobber the replacement generation or delete its data.
        uint32_t replacement;
        assert(mpynn_tcp_connect_start(ip,80,&replacement)==0 && replacement!=t);
        CScheduler::reap(); snapshot(replacement,MPYNN_TCP_CONNECT_PENDING);
        assert(mpynn_tcp_connect_cancel(replacement)==0); CScheduler::drain();
    }
    net.transport.result=-42;
    assert(mpynn_tcp_connect_start(ip,80,&t)==0); CScheduler::drain();
    snapshot(t,MPYNN_TCP_CONNECT_FAILED,MPYNN_NOTCONN);
    h=99; assert(mpynn_tcp_connect_take(t,&h)==MPYNN_NOTCONN && h==99);
    assert(mpynn_tcp_connect_cancel(t)==0); stale(t);
    net.transport.result=0;
    // Completed success also occupies a slot until consumed/cancelled.
    for (auto &token : tokens) assert(mpynn_tcp_connect_start(ip,80,&token)==0);
    CScheduler::drain(); assert(mpynn_tcp_connect_start(ip,80,&t)==MPYNN_MFILE);
    for (auto token : tokens) {
        snapshot(token,MPYNN_TCP_CONNECT_SUCCEEDED);
        assert(mpynn_tcp_connect_cancel(token)==0); stale(token);
    }
    assert(mpynn_tcp_connect_start(ip,80,&t)==0); CScheduler::drain();
    net.transport.close_error=-42;
    assert(mpynn_tcp_connect_cancel(t)==MPYNN_NOTCONN); stale(t);
    net.transport.close_error=0;
    assert(mpynn_tcp_connect_start(ip,80,&t)==0);
    net.running=false; calls=net.transport.connects; CScheduler::drain();
    snapshot(t,MPYNN_TCP_CONNECT_FAILED,MPYNN_NODEV);
    assert(net.transport.connects==calls); assert(mpynn_tcp_connect_cancel(t)==0);
    net.running=true;
    // Reset cleanup handles both completed and still-queued workers.
    assert(mpynn_tcp_connect_start(ip,80,&tokens[0])==0);
    CScheduler::step();
    assert(mpynn_tcp_connect_start(ip,80,&tokens[1])==0);
    level=1; assert(mpynn_tcp_connect_cancel_all()==MPYNN_BUSY);
    level=0; snapshot(tokens[0],MPYNN_TCP_CONNECT_SUCCEEDED);
    net.transport.close_error=-42;
    assert(mpynn_tcp_connect_cancel_all()==MPYNN_NOTCONN);
    stale(tokens[0]); snapshot(tokens[1],MPYNN_TCP_CONNECT_ABANDONED);
    net.transport.close_error=0;
    CScheduler::drain(); stale(tokens[1]);
    assert(mpynn_tcp_connect_cancel_all()==0);
    for (unsigned local : {0u,4321u,65535u}) {
        int calls=net.transport.connects;
        assert(mpynn_tcp_connect_start_bound(ip,80,(uint16_t)local,&t)==0);
        assert(net.transport.connects==calls); // still worker-only native connect
        CScheduler::step();snapshot(t,MPYNN_TCP_CONNECT_SUCCEEDED);
        assert(net.transport.last_own==local && net.transport.last_port==80);
        assert(mpynn_tcp_connect_cancel(t)==0);CScheduler::reap();stale(t);
    }
    t=999;net.transport.occupied_port=4321;
    calls=net.transport.connects;int created=CTask::created;
    assert(mpynn_tcp_connect_start_bound(ip,80,4321,&t)==MPYNN_ADDRINUSE && t==999);
    assert(net.transport.connects==calls && CTask::created==created);
    net.transport.occupied_port=0;
    assert(mpynn_tcp_connect_start_bound(ip,80,4321,&tokens[0])==0);
    assert(mpynn_tcp_connect_start_bound(ip,81,4321,&t)==MPYNN_ADDRINUSE && t==999);
    assert(mpynn_tcp_connect_cancel(tokens[0])==0);
    assert(mpynn_tcp_connect_start_bound(ip,81,4321,&t)==MPYNN_ADDRINUSE); // abandoned retains slot
    CScheduler::drain();
    assert(mpynn_tcp_connect_start_bound(ip,80,4321,&tokens[0])==0);
    net.transport.occupied_port=4321;calls=net.transport.connects;
    CScheduler::step();snapshot(tokens[0],MPYNN_TCP_CONNECT_FAILED,MPYNN_ADDRINUSE);
    assert(net.transport.connects==calls);
    assert(mpynn_tcp_connect_cancel(tokens[0])==0);CScheduler::reap();
    net.transport.occupied_port=0;
    // Force the last available generation in each empty slot, then retire it.
    for (auto &job : jobs) { assert(!job.transport); job.generation=max_generation-1; }
    for (auto &token : tokens) assert(mpynn_tcp_connect_start(ip,80,&token)==0);
    for (unsigned i=0;i<4;++i) assert(tokens[i]==((max_generation<<2)|i));
    CScheduler::drain();
    for (auto token : tokens) assert(mpynn_tcp_connect_cancel(token)==0);
    for (auto token : tokens) stale(token);
    t=999; assert(mpynn_tcp_connect_start(ip,80,&t)==MPYNN_MFILE && t==999);
    assert(net.transport.owned.empty() && CTask::ready.empty() && CTask::dead.empty());
    assert(net.transport.retained.empty() && net.transport.retains==net.transport.releases);
    assert(CTask::created==CTask::destroyed && maps>0);
}
'''


class TcpConnectBridgeTests(unittest.TestCase):
    def test_jobs_ownership_cancellation_and_context(self):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            fallback = Path('E:/msys64/ucrt64/bin/g++.exe')
            if fallback.is_file():
                compiler = str(fallback)
        if not compiler:
            self.skipTest('host C++ compiler unavailable')
        env = os.environ.copy()
        env['PATH'] = str(Path(compiler).parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'fake.h').write_text(FAKE)
            for name in ('net/netsubsystem.h', 'net/transportlayer.h', 'net/ipaddress.h',
                         'net/in.h', 'sched/task.h', 'sched/scheduler.h', 'synchronize.h'):
                target = root / 'circle' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('#include "fake.h"\n')
            (root / 'main.cpp').write_text(SOURCE)
            # C ABI header must also compile in C, with no Circle/Python headers.
            (root / 'abi.c').write_text('#include "tcp_connect_bridge.h"\n'
                                       'int check(void) { return MPYNN_TCP_CONNECT_PENDING; }\n')
            exe = root / ('test.exe' if os.name == 'nt' else 'test')
            commands = [
                [compiler, '-x', 'c', '-std=c11', '-Wall', '-Wextra', '-Werror',
                 '-fsyntax-only', '-I' + str(PORT), str(root / 'abi.c')],
                [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                 '-I' + str(root), '-I' + str(PORT), str(root / 'main.cpp'), '-o', str(exe)],
                [str(exe)],
            ]
            for cmd in commands:
                result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
