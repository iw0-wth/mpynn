# SPDX-License-Identifier: MIT
"""Compile real DNS bridge with fake Circle; no network or Python/GC in workers.

Resolve's hook simulates cancellation during a cooperative sleep. Task return
and deferred deletion are separate; this does not test ARM switching or Circle's
untrusted DNS response parser. The production header records upstream risks.
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
#include <string>
#define TASK_LEVEL 0
extern unsigned level;
inline unsigned CurrentExecutionLevel() { return level; }
struct CIPAddress {
    uint8_t bytes[4] = {192, 0, 2, 77};
    const uint8_t *Get() const { return bytes; }
};
struct CTask {
    static std::vector<CTask *> ready, dead;
    static CTask *current;
    static unsigned created, destroyed;
    CTask() { ready.push_back(this); ++created; }
    virtual ~CTask() { assert(current != this); ++destroyed; }
    virtual void Run() = 0;
};
struct CScheduler {
    static bool active;
    static bool IsActive() { return active; }
    static void step() {
        assert(!CTask::current && !CTask::ready.empty());
        auto task = CTask::ready.front();
        CTask::ready.erase(CTask::ready.begin());
        CTask::current = task;
        task->Run();
        assert(CTask::current == task);
        CTask::dead.push_back(task);
        CTask::current = nullptr;
    }
    static void reap() {
        assert(!CTask::current);
        for (auto task : CTask::dead) delete task;
        CTask::dead.clear();
    }
    static void drain() { while (!CTask::ready.empty()) step(); reap(); }
};
struct CNetSubSystem {
    bool running = true;
    bool IsRunning() const { return running; }
};
struct CDNSClient {
    static unsigned calls;
    static bool result;
    static std::string last_name;
    static std::function<void()> during;
    explicit CDNSClient(CNetSubSystem *net) { assert(net && net->running); }
    bool Resolve(const char *name, CIPAddress *ip) {
        assert(CTask::current && level == TASK_LEVEL && ip);
        ++calls; last_name = name;
        if (during) during();
        assert(last_name == name); // copied name survives a yielding resolver
        return result;
    }
};
'''
SOURCE = r'''
#include "fake.h"
#include "dns_bridge.h"
#include "socket_errno_bridge.h"
unsigned level = 0;
std::vector<CTask *> CTask::ready, CTask::dead;
CTask *CTask::current = nullptr;
unsigned CTask::created = 0, CTask::destroyed = 0;
bool CScheduler::active = true;
unsigned CDNSClient::calls = 0;
bool CDNSClient::result = true;
std::string CDNSClient::last_name;
std::function<void()> CDNSClient::during;
CNetSubSystem net, other;
CNetSubSystem *attached = &net;
unsigned network_gets = 0;
CNetSubSystem *mpynn_network_get() { ++network_gets; return attached; }
// Include actual implementation to test generation retirement without a public hook.
#include "dns_bridge.cpp"
int start(uint32_t *t) { return mpynn_dns_start("example.test", 12, t); }
void unchanged(uint32_t t, int error) {
    uint8_t ip[4] = {9, 8, 7, 6};
    unsigned calls = CDNSClient::calls, before = network_gets, created = CTask::created;
    assert(mpynn_dns_finish(t, ip) == error);
    assert(ip[0] == 9 && ip[1] == 8 && ip[2] == 7 && ip[3] == 6);
    assert(calls == CDNSClient::calls && before == network_gets && created == CTask::created);
}
void stale(uint32_t t) {
    unchanged(t, MPYNN_BADF);
    assert(mpynn_dns_cancel(t) == MPYNN_BADF);
}
int main() {
    uint32_t t = 999, u = 999;
    assert(mpynn_dns_start(nullptr, 1, &t) == MPYNN_INVAL);
    assert(mpynn_dns_start("a", 1, nullptr) == MPYNN_INVAL);
    assert(mpynn_dns_start("a", SIZE_MAX, &t) == MPYNN_INVAL);
    std::vector<std::string> invalid = {"", ".", "..", ".a", "a..b", "a..",
        "-a", "a-", "a-.b", "a.-b", "a_b", "a/b", "a b", "a\n", "a:80",
        std::string("a\0b", 3), std::string("a\x80", 2), std::string(64, 'a'),
        std::string(63, 'a') + "." + std::string(64, 'b')};
    std::string maxname = std::string(63, 'a') + "." + std::string(63, 'b') +
                          "." + std::string(63, 'c') + "." + std::string(61, 'd');
    assert(maxname.size() == 253);
    invalid.push_back(maxname + ".");
    for (const auto &name : invalid)
        assert(mpynn_dns_start(name.data(), name.size(), &t) == MPYNN_INVAL);
    assert(t == 999 && CTask::created == 0);
    attached = nullptr; assert(start(&t) == MPYNN_NODEV); attached = &net;
    net.running = false; assert(start(&t) == MPYNN_NODEV); net.running = true;
    CScheduler::active = false; assert(start(&t) == MPYNN_NODEV);
    CScheduler::active = true; stale(0); stale(UINT32_MAX);
    // Explicit unterminated byte span; copy is independent of caller lifetime.
    char name[] = {'a', '.', 'b'};
    assert(mpynn_dns_start(name, sizeof name, &t) == 0);
    name[0] = 'z'; unchanged(t, MPYNN_AGAIN);
    assert(CDNSClient::calls == 0);
    assert(mpynn_dns_finish(t, nullptr) == MPYNN_INVAL);
    for (unsigned irq : {1u, 2u}) {
        level = irq;
        assert(start(&u) == MPYNN_BUSY && u == 999);
        unchanged(t, MPYNN_BUSY);
        assert(mpynn_dns_cancel(t) == MPYNN_BUSY);
        assert(mpynn_dns_cancel_all() == MPYNN_BUSY);
    }
    level = 0; CScheduler::step();
    assert(CDNSClient::last_name == "a.b");
    uint8_t ip[4] = {};
    assert(mpynn_dns_finish(t, ip) == 0);
    assert(ip[0] == 192 && ip[1] == 0 && ip[2] == 2 && ip[3] == 77);
    stale(t);
    assert(start(&u) == 0 && u != t);
    CScheduler::reap(); unchanged(u, MPYNN_AGAIN);
    assert(mpynn_dns_cancel(u) == 0); CScheduler::drain(); stale(u);
    // Accepted boundaries, ASCII cases and one terminal dot.
    for (const auto &s : std::vector<std::string>{"a", "A-9.test.", "localhost",
            "192.0.2.1", std::string(63, 'a'), maxname, maxname.substr(0,252) + "."}) {
        assert(mpynn_dns_start(s.data(), s.size(), &t) == 0);
        CScheduler::drain(); assert(CDNSClient::last_name == s);
        assert(mpynn_dns_finish(t, ip) == 0); stale(t);
    }
    uint32_t tokens[2];
    for (auto &token : tokens) assert(start(&token) == 0);
    t = 999; assert(start(&t) == MPYNN_MFILE && t == 999);
    unsigned calls = CDNSClient::calls;
    for (auto token : tokens) {
        assert(mpynn_dns_cancel(token) == 0);
        assert(mpynn_dns_cancel(token) == 0);
        unchanged(token, MPYNN_AGAIN);
    }
    assert(start(&t) == MPYNN_MFILE);
    CScheduler::drain(); assert(calls == CDNSClient::calls);
    for (auto token : tokens) stale(token);
    // Cancel during Resolve, covering both late success and late failure.
    for (bool result : {true, false}) {
        CDNSClient::result = result;
        assert(start(&t) == 0);
        CDNSClient::during = [&] {
            unchanged(t, MPYNN_AGAIN);
            assert(mpynn_dns_cancel(t) == 0);
            assert(mpynn_dns_cancel(t) == 0);
            unchanged(t, MPYNN_AGAIN);
            assert(start(&u) == 0);
            uint32_t extra = 999;
            assert(start(&extra) == MPYNN_MFILE && extra == 999);
            assert(mpynn_dns_cancel_all() == 0);
        };
        CScheduler::step(); CDNSClient::during = {};
        stale(t); unchanged(u, MPYNN_AGAIN);
        uint32_t replacement;
        assert(start(&replacement) == 0 && replacement != t);
        CScheduler::reap(); unchanged(replacement, MPYNN_AGAIN);
        assert(mpynn_dns_cancel_all() == 0); CScheduler::drain();
        stale(u); stale(replacement);
    }
    // Failure finish consumes the job; false has no NXDOMAIN specificity.
    assert(start(&t) == 0); CScheduler::drain();
    unchanged(t, MPYNN_IO); stale(t);
    assert(start(&t) == 0); CScheduler::drain();
    assert(mpynn_dns_cancel(t) == 0); stale(t);
    CDNSClient::result = true;
    // Completed slots remain bounded, including until late cancellation.
    for (auto &token : tokens) assert(start(&token) == 0);
    CScheduler::drain(); assert(start(&t) == MPYNN_MFILE);
    assert(mpynn_dns_cancel_all() == 0);
    for (auto token : tokens) stale(token);
    // Queued worker checks absent, stopped and replaced network.
    for (unsigned failure = 0; failure < 3; ++failure) {
        assert(start(&t) == 0); calls = CDNSClient::calls;
        if (failure == 0) attached = nullptr;
        if (failure == 1) net.running = false;
        if (failure == 2) attached = &other;
        CScheduler::drain(); unchanged(t, MPYNN_NODEV); stale(t);
        assert(calls == CDNSClient::calls);
        attached = &net; net.running = true;
    }
    assert(start(&tokens[0]) == 0); CScheduler::step();
    assert(start(&tokens[1]) == 0);
    assert(mpynn_dns_cancel_all() == 0); stale(tokens[0]);
    unchanged(tokens[1], MPYNN_AGAIN); CScheduler::drain(); stale(tokens[1]);
    assert(mpynn_dns_cancel_all() == 0);
    for (auto &job : jobs) { assert(!job.net); job.generation = max_generation-1; }
    for (auto &token : tokens) assert(start(&token) == 0);
    for (unsigned i = 0; i < 2; ++i) assert(tokens[i] == ((max_generation<<1)|i));
    CScheduler::drain(); assert(mpynn_dns_cancel_all() == 0);
    for (auto token : tokens) stale(token);
    t = 999; assert(start(&t) == MPYNN_MFILE && t == 999);
    assert(CTask::ready.empty() && CTask::dead.empty());
    assert(CTask::created == CTask::destroyed);
}
'''


class DnsBridgeTests(unittest.TestCase):
    def test_jobs_names_cancellation_errors_and_context(self):
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
            for name in ('net/netsubsystem.h', 'net/dnsclient.h', 'net/ipaddress.h',
                         'sched/task.h', 'sched/scheduler.h', 'synchronize.h'):
                target = root / 'circle' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('#include "fake.h"\n')
            (root / 'main.cpp').write_text(SOURCE)
            (root / 'abi.c').write_text('#include "dns_bridge.h"\n'
                'int check(const char *s, size_t n, uint32_t *t) { '
                'return mpynn_dns_start(s, n, t); }\n')
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
