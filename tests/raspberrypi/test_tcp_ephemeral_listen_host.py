# SPDX-License-Identifier: MIT
"""Run the complete override Listen method with host-only Circle doubles.

The PtrArray, spinlock and TCP constructor are fakes; protocol/error constants
and the ephemeral range come from production. No firmware or sockets are used.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
CIRCLE = ROOT / "lib/circle"
SOURCE = ROOT / "ports/raspberrypi/upstream_overrides/circle/lib/net/transportlayer.cpp"
CXX = Path("E:/msys64/ucrt64/bin/g++.exe")


def method(source, signature):
    """Extract the entire production definition, not a rewritten allocator."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


FAKE = r"""
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
#include <circle/net/in.h>
#include <circle/net/error.h>
using u16 = unsigned short;
using boolean = bool;
#define TRUE true
#define FALSE false
static_assert(sizeof(u16) == 2);

struct CSpinLock {
    bool held = false;
    unsigned acquires = 0, releases = 0;
    void Acquire() { assert(!held); held = true; ++acquires; }
    void Release() { assert(held); held = false; ++releases; }
};
struct CNetConfig { CSpinLock *lock; };
struct CNetworkLayer {};
struct CNetConnection {
    inline static unsigned port_reads = 0, protocol_reads = 0;
    CSpinLock *lock;
    u16 port;
    int protocol;
    bool terminated, retained;
    CNetConnection(CSpinLock *l, u16 p, int proto, bool closed = false)
        : lock(l), port(p), protocol(proto), terminated(closed), retained(closed) {}
    virtual ~CNetConnection() = default;
    u16 GetOwnPort() const { assert(lock->held); ++port_reads; return port; }
    int GetProtocol() const { assert(lock->held); ++protocol_reads; return protocol; }
    bool IsTerminated() const { return terminated; }
    bool HasOwners() const { return retained; }
};
struct CTCPConnection : CNetConnection {
    inline static unsigned allocations = 0;
    CTCPConnection(CNetConfig *config, CNetworkLayer *network, u16 port)
        : CNetConnection(config->lock, port, IPPROTO_TCP) {
        // Preserve the native constructor's locking context on successful Listen.
        assert(config && network && config->lock->held && port != 0);
        ++allocations;
    }
};
struct CPtrArray {
    CSpinLock *lock;
    std::vector<void *> entries;
    unsigned appends = 0;
    explicit CPtrArray(CSpinLock *l) : lock(l) {}
    unsigned GetCount() const { return unsigned(entries.size()); }
    void *&operator[](unsigned index) {
        assert(index < entries.size()); return entries[index];
    }
    unsigned Append(void *entry) {
        assert(lock->held && entry == nullptr);
        unsigned index = GetCount(); entries.push_back(entry); ++appends; return index;
    }
};
struct CTransportLayer {
    CSpinLock m_SpinLock;
    CPtrArray m_pConnection{&m_SpinLock};
    CNetConfig config{&m_SpinLock};
    CNetworkLayer network;
    CNetConfig *m_pNetConfig = &config;
    CNetworkLayer *m_pNetworkLayer = &network;
    u16 m_nOwnPort = OWN_PORT_MIN;
    ~CTransportLayer() {
        assert(!m_SpinLock.held && m_SpinLock.acquires == m_SpinLock.releases);
        for (void *entry : m_pConnection.entries) delete static_cast<CNetConnection *>(entry);
    }
    void seed(u16 port, int protocol, bool retained_closed = false) {
        m_pConnection.entries.push_back(
            new CNetConnection(&m_SpinLock, port, protocol, retained_closed));
    }
    void hole() { m_pConnection.entries.push_back(nullptr); }
    int Listen(u16, int);
};
"""

HARNESS = r"""
static void balanced(const CTransportLayer &tr, unsigned calls) {
    assert(!tr.m_SpinLock.held);
    assert(tr.m_SpinLock.acquires == calls && tr.m_SpinLock.releases == calls);
}
static void listener(CTransportLayer &tr, int handle, u16 port) {
    assert(handle >= 0 && unsigned(handle) < tr.m_pConnection.GetCount());
    auto *connection = static_cast<CNetConnection *>(tr.m_pConnection[handle]);
    assert(dynamic_cast<CTCPConnection *>(connection));
    assert(connection->port == port && connection->protocol == IPPROTO_TCP);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string scenario = argv[1];
    CTransportLayer tr;
    if (scenario == "free") {
        // Start at the CURRENT cursor, rather than always starting at range min.
        tr.m_nOwnPort = 60421;
        assert(tr.Listen(0, IPPROTO_TCP) == 0);
        listener(tr, 0, 60421);
        assert(tr.m_nOwnPort == 60422 && CTCPConnection::allocations == 1);
        assert(tr.Listen(0, IPPROTO_TCP) == 1);
        listener(tr, 1, 60422);
        assert(tr.m_nOwnPort == 60423 && CTCPConnection::allocations == 2);
        balanced(tr, 2);
    } else if (scenario == "collisions") {
        tr.m_nOwnPort = 60041;
        tr.seed(60042, IPPROTO_TCP, true); // terminated, retained native handle
        tr.hole(); // destination slot is not the end of the collision scan
        tr.seed(60041, IPPROTO_TCP); // connected TCP, not necessarily a listener
        tr.seed(60043, IPPROTO_UDP); // same numeric port is permitted for UDP
        auto old_entries = tr.m_pConnection.entries;
        assert(tr.Listen(0, IPPROTO_TCP) == 1);
        listener(tr, 1, 60043);
        assert(tr.m_nOwnPort == 60044 && CTCPConnection::allocations == 1);
        assert(tr.m_pConnection.appends == 0 && tr.m_pConnection.GetCount() == 4);
        for (unsigned i : {0u, 2u, 3u}) assert(tr.m_pConnection[i] == old_entries[i]);
        balanced(tr, 1);
    } else if (scenario == "wrap") {
        tr.m_nOwnPort = OWN_PORT_MAX;
        tr.seed(OWN_PORT_MAX, IPPROTO_TCP);
        tr.seed(OWN_PORT_MIN, IPPROTO_TCP, true);
        assert(tr.Listen(0, IPPROTO_TCP) == 2);
        listener(tr, 2, OWN_PORT_MIN + 1);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 2);
        balanced(tr, 1);
    } else if (scenario == "boundary-free") {
        tr.m_nOwnPort = OWN_PORT_MAX;
        assert(tr.Listen(0, IPPROTO_TCP) == 0);
        listener(tr, 0, OWN_PORT_MAX);
        assert(tr.m_nOwnPort == OWN_PORT_MIN);
        assert(tr.Listen(0, IPPROTO_TCP) == 1);
        listener(tr, 1, OWN_PORT_MIN);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 1);
        balanced(tr, 2);
    } else if (scenario == "exhausted" || scenario == "last-free") {
        const u16 start = 60500, last = 60499;
        tr.m_nOwnPort = start;
        for (unsigned port = OWN_PORT_MIN; port <= OWN_PORT_MAX; ++port) {
            if (scenario == "last-free" && port == last) continue;
            tr.seed(u16(port), IPPROTO_TCP, port % 2 == 0);
        }
        const auto old_entries = tr.m_pConnection.entries;
        if (scenario == "last-free") {
            assert(tr.Listen(0, IPPROTO_TCP) == 999);
            listener(tr, 999, last); // the 1000th candidate must still be tested
            assert(tr.m_nOwnPort == start && CTCPConnection::allocations == 1);
            assert(CNetConnection::protocol_reads == 999);
            balanced(tr, 1);
        } else {
            for (unsigned call = 1; call <= 2; ++call) {
                assert(tr.Listen(0, IPPROTO_TCP) == -NET_ERROR_INVALID_VALUE);
                assert(CTCPConnection::allocations == 0);
                assert(tr.m_nOwnPort == start);
                // Each matching TCP reports its protocol exactly once per pass.
                assert(CNetConnection::protocol_reads == call * 1000);
                assert(tr.m_pConnection.GetCount() == 1001);
                assert(tr.m_pConnection[1000] == nullptr); // not an owned handle
                for (unsigned i = 0; i < old_entries.size(); ++i)
                    assert(tr.m_pConnection[i] == old_entries[i]);
                balanced(tr, call);
            }
            assert(tr.m_pConnection.appends == 1); // retry reuses the empty slot
        }
    } else if (scenario == "explicit") {
        tr.m_nOwnPort = 60777;
        // Explicit ports keep the native sharing behavior used by TCP backlog.
        tr.seed(60000, IPPROTO_TCP);
        tr.hole();
        for (u16 port : {u16(60000), u16(80), u16(65535)}) {
            int handle = tr.Listen(port, IPPROTO_TCP);
            listener(tr, handle, port);
            assert(tr.m_nOwnPort == 60777);
            assert(CNetConnection::port_reads == 0 && CNetConnection::protocol_reads == 0);
        }
        assert(CTCPConnection::allocations == 3);
        balanced(tr, 3);
    } else {
        assert(scenario == "invalid-protocol");
        unsigned calls = 0;
        for (int protocol : {IPPROTO_UDP, IPPROTO_ICMP, -1}) {
            for (u16 port : {u16(0), u16(8080)}) {
                assert(tr.Listen(port, protocol) == -NET_ERROR_PROTOCOL_NOT_SUPPORTED);
                assert(CTCPConnection::allocations == 0);
                for (void *entry : tr.m_pConnection.entries) assert(entry == nullptr);
                balanced(tr, ++calls);
            }
        }
    }
    puts("PASS");
}
"""


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class TcpEphemeralListenHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text(encoding="utf-8")
        definitions = "\n".join(re.search(
            rf"^#define {name}\s+\d+", source, re.M).group()
            for name in ("OWN_PORT_MIN", "OWN_PORT_MAX"))
        listen = method(source, "int CTransportLayer::Listen (")
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-tcp-ephemeral-listen-")
        def cleanup():
            for attempt in range(21):
                try:
                    temporary.cleanup()
                    return
                except PermissionError:
                    if attempt == 20:
                        raise
                    time.sleep(0.1)
        cls.addClassCleanup(cleanup)
        cls.root = Path(temporary.name)
        harness = cls.root / "test.cpp"
        harness.write_text(definitions + "\n" + FAKE + "\n" + listen + "\n" + HARNESS,
                           encoding="utf-8")
        cls.executable = cls.root / "test.exe"
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(CXX.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror",
             # Do not shadow the host assert.h with Circle's bare-metal header.
             "-idirafter", str(CIRCLE / "include"), str(harness), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host g++ compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run(
            [str(self.executable), scenario], cwd=self.root, env=self.env,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_free_ports_start_at_cursor_and_advance(self):
        self.run_scenario("free")

    def test_skip_all_live_tcp_including_retained_closed_but_allow_udp(self):
        self.run_scenario("collisions")

    def test_wrap_skips_tcp_collisions_at_both_ends(self):
        self.run_scenario("wrap")

    def test_free_boundary_ports_wrap_cursor(self):
        self.run_scenario("boundary-free")

    def test_full_exhaustion_is_bounded_allocates_no_tcp_and_unlocks(self):
        self.run_scenario("exhausted")

    def test_final_candidate_in_full_range_can_succeed(self):
        self.run_scenario("last-free")

    def test_explicit_ports_preserve_native_behavior_and_cursor(self):
        self.run_scenario("explicit")

    def test_invalid_protocol_never_constructs_tcp_and_balances_lock(self):
        self.run_scenario("invalid-protocol")


if __name__ == "__main__":
    unittest.main()
