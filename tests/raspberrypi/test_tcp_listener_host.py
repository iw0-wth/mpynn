# SPDX-License-Identifier: MIT
"""Real listener C++ with strict fake Circle: no firmware, TCP timers or hardware."""
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
#include <cassert>
#include <vector>
#define TASK_LEVEL 0
#define IPPROTO_TCP 6
extern unsigned level;
inline unsigned CurrentExecutionLevel() { return level; }
struct CIPAddress {
    uint8_t bytes[4]={192,0,2,7};
    const uint8_t *Get() const { return bytes; }
};
struct CTransportLayer {
    struct Entry { int refs=0, state=0, terminal=0, close_error=0, release_error=0; bool closed=false; uint16_t port=0; };
    std::vector<Entry> entries;
    int listens=0, accepts=0, releases=0, closes=0, retain_fail=-1, listen_fail=-1;
    int pending=-1;
    uint16_t external_port=0;
    bool IsPortInUse(uint16_t port,int protocol) {
        assert(protocol==IPPROTO_TCP);
        if (port==external_port) return true;
        // Closed test-double entries model slots already removed by Process.
        for (const auto &entry : entries) if (!entry.closed && entry.port==port) return true;
        return false;
    }
    int Listen(uint16_t port,int protocol) {
        assert(level==0 && protocol==IPPROTO_TCP && pending==-1);
        if (++listens==listen_fail) return -42;
        entries.emplace_back(); pending=int(entries.size())-1; entries[pending].port=port?port:60001; return pending;
    }
    uint16_t GetOwnPort(int h) {assert(entries[h].refs==1);return entries[h].port;}
    int RetainConnection(int h) {
        assert(pending==h); pending=-1;
        if (h==retain_fail) return -43;
        assert(entries[h].refs==0); ++entries[h].refs; return 0;
    }
    int Disconnect(int h) {
        assert(pending==-1 && !entries[h].closed); ++closes;
        entries[h].closed=true; return entries[h].close_error;
    }
    int ReleaseConnection(int h) {
        assert(entries[h].closed && entries[h].refs==1); --entries[h].refs;
        ++releases; return entries[h].release_error;
    }
    int GetTerminalError(int h) { assert(entries[h].refs==1); return entries[h].terminal; }
    bool IsAcceptReady(int h) {
        assert(entries[h].refs==1);
        return entries[h].terminal==0 && entries[h].state>=2;
    }
    int Accept(CIPAddress *ip,uint16_t *port,int h) {
        assert(IsAcceptReady(h)); ++accepts;
        *ip=CIPAddress(); *port=4567; return 0; // status, NEVER a new handle
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
#include "tcp_listener_bridge.h"
#include "socket_errno_bridge.h"
unsigned level=0;
CNetSubSystem net;
bool present=true;
CNetSubSystem *mpynn_network_get() { return present ? &net : nullptr; }
extern "C" int mpynn_socket_error_from_circle(int r) {
    return r==-42 ? MPYNN_MFILE : r==-43 ? MPYNN_NOTCONN : r<0 ? MPYNN_IO : 0;
}
int claim_error=0, claimed=-1;
extern "C" int mpynn_tcp_stream_claim(int h,uint32_t *token) {
    assert(net.transport.entries[h].refs==1);
    if (claim_error) return claim_error;
    claimed=h; *token=1234; return 0;
}
#include "tcp_listener_bridge.cpp"
void stale(uint32_t t) {
    unsigned ready=99; uint32_t stream=99; uint8_t ip[4]={9,9,9,9}; uint16_t port=99;
    assert(mpynn_tcp_listener_poll(t,&ready)==MPYNN_BADF && ready==99);
    assert(mpynn_tcp_listener_accept(t,&stream,ip,&port)==MPYNN_BADF);
    assert(stream==99 && ip[0]==9 && port==99);
    assert(mpynn_tcp_listener_close(t)==MPYNN_BADF);
}
int main() {
    auto &tr=net.transport;
    uint32_t t=999,u=999,v=999,stream=99; unsigned ready=99;
    uint8_t ip[4]={9,9,9,9}; uint16_t port=99;

    assert(mpynn_tcp_listener_open(80,0,&t)==MPYNN_INVAL);
    assert(mpynn_tcp_listener_open(80,5,&t)==MPYNN_INVAL);
    assert(mpynn_tcp_listener_open(80,1,nullptr)==MPYNN_INVAL);
    present=false; assert(mpynn_tcp_listener_open(80,1,&t)==MPYNN_NODEV); present=true;
    net.running=false; assert(mpynn_tcp_listener_open(80,1,&t)==MPYNN_NODEV); net.running=true;
    assert(t==999 && tr.listens==0); stale(0); stale(UINT32_MAX);
    tr.external_port=80;
    assert(mpynn_tcp_listener_open(80,4,&t)==MPYNN_ADDRINUSE && t==999);
    assert(tr.listens==0 && tr.closes==0 && tr.releases==0);
    tr.external_port=0;
    // Third backlog candidate fails: rollback every prior owner, preserving error.
    tr.listen_fail=3;
    assert(mpynn_tcp_listener_open(80,4,&t)==MPYNN_MFILE && t==999);
    assert(tr.closes==2 && tr.releases==2);
    tr.listen_fail=-1; tr.retain_fail=int(tr.entries.size())+1;
    assert(mpynn_tcp_listener_open(80,4,&t)==MPYNN_NOTCONN);
    assert(tr.closes==4 && tr.releases==3); // failed retain: disconnect, no release
    tr.retain_fail=-1;
    assert(mpynn_tcp_listener_open(80,4,&t)==0);
    assert(mpynn_tcp_listener_open(80,1,&u)==MPYNN_ADDRINUSE);
    assert(mpynn_tcp_listener_open(81,1,&u)==0);
    assert(mpynn_tcp_listener_open(82,1,&v)==MPYNN_MFILE);
    int calls=tr.listens;
    assert(mpynn_tcp_listener_open(80,1,&v)==MPYNN_ADDRINUSE && tr.listens==calls);
    assert(mpynn_tcp_listener_poll(t,nullptr)==MPYNN_INVAL);
    assert(mpynn_tcp_listener_accept(t,nullptr,ip,&port)==MPYNN_INVAL);
    assert(mpynn_tcp_listener_accept(t,&stream,nullptr,&port)==MPYNN_INVAL);
    assert(mpynn_tcp_listener_accept(t,&stream,ip,nullptr)==MPYNN_INVAL);
    for (unsigned irq : {1u,2u}) {
        level=irq;
        assert(mpynn_tcp_listener_open(82,1,&v)==MPYNN_BUSY);
        assert(mpynn_tcp_listener_poll(t,&ready)==MPYNN_BUSY && ready==99);
        assert(mpynn_tcp_listener_accept(t,&stream,ip,&port)==MPYNN_BUSY);
        assert(mpynn_tcp_listener_close(t)==MPYNN_BUSY);
        assert(mpynn_tcp_listener_close_all()==MPYNN_BUSY);
    }
    level=0;
    int h=listeners[t&1].candidates[0];
    assert(mpynn_tcp_listener_poll(t,&ready)==0 && ready==0);
    assert(mpynn_tcp_listener_accept(t,&stream,ip,&port)==MPYNN_AGAIN);
    tr.entries[h].state=1; // SYN received: generic connected/queued != accept-ready
    assert(mpynn_tcp_listener_poll(t,&ready)==0 && ready==0);
    assert(mpynn_tcp_listener_accept(t,&stream,ip,&port)==MPYNN_AGAIN && tr.accepts==0);
    tr.entries[h].state=2;
    assert(mpynn_tcp_listener_poll(t,&ready)==0 && ready==1);
    claim_error=MPYNN_MFILE;
    assert(mpynn_tcp_listener_accept(t,&stream,ip,&port)==MPYNN_MFILE);
    assert(stream==99 && ip[0]==9 && port==99 && tr.entries[h].refs==1);
    assert(listeners[t&1].candidates[0]==h && !tr.entries[h].closed);
    claim_error=0; tr.listen_fail=tr.listens+1;
    assert(mpynn_tcp_listener_accept(t,&stream,ip,&port)==0);
    assert(stream==1234 && claimed==h && ip[0]==192 && ip[3]==7 && port==4567);
    assert(listeners[t&1].candidates[0]==-1 && tr.entries[h].refs==1);
    tr.listen_fail=tr.listens+1;
    assert(mpynn_tcp_listener_poll(t,&ready)==MPYNN_MFILE);
    tr.listen_fail=-1;
    assert(mpynn_tcp_listener_poll(t,&ready)==0 && ready==0);
    int replacement=listeners[t&1].candidates[0]; assert(replacement!=h);
    tr.entries[replacement].terminal=-43; tr.entries[replacement].close_error=-42;
    assert(mpynn_tcp_listener_poll(t,&ready)==MPYNN_NOTCONN);
    assert(tr.entries[replacement].closed && tr.entries[replacement].refs==0);
    replacement=listeners[t&1].candidates[0];
    assert(mpynn_tcp_listener_poll(t,&ready)==0 && ready==0);
    // Ready candidate wins over a different candidate's refill error.
    tr.entries[replacement].state=3; // completed handshake then peer FIN
    int bad=listeners[t&1].candidates[1]; tr.entries[bad].terminal=-43;
    tr.listen_fail=tr.listens+1;
    assert(mpynn_tcp_listener_poll(t,&ready)==0 && ready==1);
    tr.listen_fail=-1;
    assert(mpynn_tcp_listener_accept(t,&stream,ip,&port)==0 && claimed==replacement);
    tr.Disconnect(replacement); tr.ReleaseConnection(replacement); // stream owner
    int first=listeners[t&1].candidates[0];
    tr.entries[first].close_error=-43; tr.entries[first].release_error=-42;
    tr.entries[listeners[t&1].candidates[1]].close_error=-42;
    assert(mpynn_tcp_listener_close_all()==MPYNN_NOTCONN);
    stale(t); stale(u);
    assert(tr.entries[h].refs==1 && !tr.entries[h].closed); // accepted independent
    tr.Disconnect(h); tr.ReleaseConnection(h);
    assert(mpynn_tcp_listener_close_all()==0);
    assert(mpynn_tcp_listener_open(80,1,&v)==0 && v!=t); stale(t);
    assert(mpynn_tcp_listener_close(v)==0);
    assert(mpynn_tcp_listener_open(0,4,&v)==0);
    uint16_t local=999;assert(mpynn_tcp_listener_local_port(v,&local)==0 && local==60001);
    for(int candidate:listeners[v&1].candidates) assert(tr.entries[candidate].port==local);
    assert(mpynn_tcp_listener_open(local,1,&u)==MPYNN_ADDRINUSE);
    level=1;local=999;
    assert(mpynn_tcp_listener_local_port(v,&local)==MPYNN_BUSY && local==999);
    level=0;assert(mpynn_tcp_listener_close(v)==0);
    assert(mpynn_tcp_listener_local_port(v,&local)==MPYNN_BADF && local==999);
    for (const auto &e : tr.entries) assert(e.refs==0 && e.closed);
    listeners[0].generation=max_generation; listeners[1].generation=max_generation;
    assert(mpynn_tcp_listener_open(80,1,&v)==MPYNN_MFILE); // no token wrap
}
'''


class TcpListenerBridgeTests(unittest.TestCase):
    def test_listener_candidates_ownership_and_context(self):
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
                         'net/in.h', 'synchronize.h'):
                target = root / 'circle' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('#include "fake.h"\n')
            (root / 'main.cpp').write_text(SOURCE)
            (root / 'abi.c').write_text('#include "tcp_listener_bridge.h"\n'
                                       'int check(void) { return mpynn_tcp_listener_close_all(); }\n')
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
