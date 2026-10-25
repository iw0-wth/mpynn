# SPDX-License-Identifier: MIT
"""Run the complete production Connect definition with host-only Circle doubles.

PtrArray, locking, configuration, IP and connection objects are fakes. Protocol
and error constants and the ephemeral range are production definitions. No real
sockets, Circle build output, firmware, or replacement allocator are involved.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CIRCLE = ROOT / "lib/circle"
SOURCE = ROOT / "ports/raspberrypi/upstream_overrides/circle/lib/net/transportlayer.cpp"
CXX = Path("E:/msys64/ucrt64/bin/g++.exe")


def method(source, signature):
    """Extract the entire actual method, including allocation and native Connect."""
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
static_assert(OWN_PORT_MAX - OWN_PORT_MIN + 1 == 1000);

struct CSpinLock {
    bool held = false;
    unsigned acquires = 0, releases = 0;
    void Acquire() { assert(!held); held = true; ++acquires; }
    void Release() { assert(held); held = false; ++releases; }
};
struct CNetConfig { CSpinLock *lock; };
struct CNetworkLayer {};
struct CIPAddress { unsigned value; };
struct CNetConnection {
    inline static unsigned port_reads = 0, protocol_reads = 0, native_calls = 0;
    inline static int native_result = 0;
    CSpinLock *lock;
    u16 port;
    int protocol;
    bool terminated, retained;
    unsigned foreign_ip = 0;
    u16 foreign_port = 0;
    unsigned connects = 0;
    CNetConnection(CSpinLock *l, u16 p, int proto, bool closed = false)
        : lock(l), port(p), protocol(proto), terminated(closed), retained(closed) {}
    virtual ~CNetConnection() = default;
    u16 GetOwnPort() const { assert(lock->held); ++port_reads; return port; }
    int GetProtocol() const { assert(lock->held); ++protocol_reads; return protocol; }
    bool IsTerminated() const { return terminated; }
    bool HasOwners() const { return retained; }
    virtual int Connect() {
        // The native call can block: it must occur after releasing the lock.
        assert(!lock->held && lock->acquires == lock->releases);
        ++connects; ++native_calls; return native_result;
    }
};
struct CTCPConnection : CNetConnection {
    inline static unsigned allocations = 0;
    CTCPConnection(CNetConfig *config, CNetworkLayer *network,
                   const CIPAddress &ip, u16 remote, u16 own)
        : CNetConnection(config->lock, own, IPPROTO_TCP) {
        assert(config && network && config->lock->held && own != 0);
        foreign_ip = ip.value; foreign_port = remote; ++allocations;
    }
};
struct CUDPConnection : CNetConnection {
    inline static unsigned allocations = 0;
    CUDPConnection(CNetConfig *config, CNetworkLayer *network,
                   const CIPAddress &ip, u16 remote, u16 own)
        : CNetConnection(config->lock, own, IPPROTO_UDP) {
        assert(config && network && config->lock->held && own != 0);
        foreign_ip = ip.value; foreign_port = remote; ++allocations;
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
    int Connect(const CIPAddress &, u16, u16, int);
};
"""

HARNESS = r"""
static const CIPAddress peer{0xC000022A};
static const u16 peer_port = 443;
static void balanced(const CTransportLayer &tr, unsigned calls) {
    assert(!tr.m_SpinLock.held);
    assert(tr.m_SpinLock.acquires == calls && tr.m_SpinLock.releases == calls);
}
static void allocated(int protocol, unsigned count) {
    assert(CTCPConnection::allocations == (protocol == IPPROTO_TCP ? count : 0));
    assert(CUDPConnection::allocations == (protocol == IPPROTO_UDP ? count : 0));
    assert(CNetConnection::native_calls == count);
}
static CNetConnection *connection(CTransportLayer &tr, int handle, u16 port, int protocol) {
    assert(handle >= 0 && unsigned(handle) < tr.m_pConnection.GetCount());
    auto *entry = static_cast<CNetConnection *>(tr.m_pConnection[handle]);
    assert(entry && entry->port == port && entry->protocol == protocol);
    assert(protocol == IPPROTO_TCP ? dynamic_cast<CTCPConnection *>(entry) != nullptr
                                  : dynamic_cast<CUDPConnection *>(entry) != nullptr);
    assert(entry->foreign_ip == peer.value && entry->foreign_port == peer_port);
    assert(entry->connects == 1);
    return entry;
}
int main(int argc, char **argv) {
    assert(argc == 3);
    const std::string scenario = argv[1], protocol_name = argv[2];
    assert(protocol_name == "tcp" || protocol_name == "udp");
    const int protocol = protocol_name == "tcp" ? IPPROTO_TCP : IPPROTO_UDP;
    const int opposite = protocol == IPPROTO_TCP ? IPPROTO_UDP : IPPROTO_TCP;
    CTransportLayer tr;
    if (scenario == "free") {
        // Honor the shared current cursor, including successful native results.
        tr.m_nOwnPort = OWN_PORT_MIN + 421;
        assert(tr.Connect(peer, peer_port, 0, protocol) == 0);
        connection(tr, 0, OWN_PORT_MIN + 421, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 422);
        CNetConnection::native_result = 73;
        assert(tr.Connect(peer, peer_port, 0, protocol) == 1);
        connection(tr, 1, OWN_PORT_MIN + 422, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 423);
        allocated(protocol, 2); balanced(tr, 2);
    } else if (scenario == "collisions") {
        tr.m_nOwnPort = OWN_PORT_MIN + 41;
        tr.seed(OWN_PORT_MIN + 42, protocol, true); // closed but retained handle
        tr.hole(); // insertion hole must not stop the collision scan
        tr.seed(OWN_PORT_MIN + 41, protocol);
        tr.seed(OWN_PORT_MIN + 43, opposite); // independent protocol namespace
        const auto old_entries = tr.m_pConnection.entries;
        assert(tr.Connect(peer, peer_port, 0, protocol) == 1);
        connection(tr, 1, OWN_PORT_MIN + 43, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 44);
        assert(tr.m_pConnection.appends == 0 && tr.m_pConnection.GetCount() == 4);
        for (unsigned i : {0u, 2u, 3u}) assert(tr.m_pConnection[i] == old_entries[i]);
        allocated(protocol, 1); balanced(tr, 1);
    } else if (scenario == "wrap") {
        tr.m_nOwnPort = OWN_PORT_MAX;
        tr.seed(OWN_PORT_MAX, protocol);
        tr.seed(OWN_PORT_MIN, protocol, true);
        assert(tr.Connect(peer, peer_port, 0, protocol) == 2);
        connection(tr, 2, OWN_PORT_MIN + 1, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 2);
        allocated(protocol, 1); balanced(tr, 1);
    } else if (scenario == "boundary-free") {
        tr.m_nOwnPort = OWN_PORT_MAX;
        assert(tr.Connect(peer, peer_port, 0, protocol) == 0);
        connection(tr, 0, OWN_PORT_MAX, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN);
        assert(tr.Connect(peer, peer_port, 0, protocol) == 1);
        connection(tr, 1, OWN_PORT_MIN, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 1);
        allocated(protocol, 2); balanced(tr, 2);
    } else if (scenario == "exhausted" || scenario == "last-free") {
        const u16 start = OWN_PORT_MIN + 500, last = start - 1;
        tr.m_nOwnPort = start;
        for (unsigned port = OWN_PORT_MIN; port <= OWN_PORT_MAX; ++port) {
            if (scenario == "last-free" && port == last) continue;
            tr.seed(u16(port), protocol, port % 2 == 0);
        }
        const auto old_entries = tr.m_pConnection.entries;
        if (scenario == "last-free") {
            assert(tr.Connect(peer, peer_port, 0, protocol) == 999);
            connection(tr, 999, last, protocol); // candidate 1000 is still tested
            assert(tr.m_nOwnPort == start);
            assert(CNetConnection::protocol_reads == 999);
            for (unsigned i = 0; i < old_entries.size(); ++i)
                assert(tr.m_pConnection[i] == old_entries[i]);
            allocated(protocol, 1); balanced(tr, 1);
        } else {
            for (unsigned call = 1; call <= 2; ++call) {
                assert(tr.Connect(peer, peer_port, 0, protocol) == -NET_ERROR_INVALID_VALUE);
                allocated(protocol, 0);
                assert(tr.m_nOwnPort == start); // one complete pass, including retry
                assert(CNetConnection::protocol_reads == call * 1000);
                assert(tr.m_pConnection.GetCount() == 1001);
                assert(tr.m_pConnection[1000] == nullptr); // allowed pre-scan append
                for (unsigned i = 0; i < old_entries.size(); ++i)
                    assert(tr.m_pConnection[i] == old_entries[i]);
                balanced(tr, call);
            }
            assert(tr.m_pConnection.appends == 1); // second call reuses the hole
        }
    } else if (scenario == "explicit") {
        tr.m_nOwnPort = OWN_PORT_MIN + 777;
        // Keep the native nonzero-port behavior, including duplicate own ports.
        tr.seed(OWN_PORT_MIN, protocol);
        tr.hole();
        unsigned calls = 0;
        for (u16 port : {u16(OWN_PORT_MIN), u16(80), u16(65535)}) {
            int handle = tr.Connect(peer, peer_port, port, protocol);
            assert(handle == int(++calls));
            connection(tr, handle, port, protocol);
            assert(tr.m_nOwnPort == OWN_PORT_MIN + 777);
            assert(CNetConnection::port_reads == 0 && CNetConnection::protocol_reads == 0);
            allocated(protocol, calls); balanced(tr, calls);
        }
    } else {
        assert(scenario == "native-failure");
        tr.hole();
        // Failure must propagate unchanged after unlocking; the constructed
        // connection remains in the table, matching the existing native policy.
        CNetConnection::native_result = -NET_ERROR_CONNECTION_REFUSED;
        assert(tr.Connect(peer, peer_port, 0, protocol) == -NET_ERROR_CONNECTION_REFUSED);
        auto *failed = connection(tr, 0, OWN_PORT_MIN, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 1);
        allocated(protocol, 1); balanced(tr, 1);
        CNetConnection::native_result = -NET_ERROR_IO;
        assert(tr.Connect(peer, peer_port, 8080, protocol) == -NET_ERROR_IO);
        connection(tr, 1, 8080, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 1 && tr.m_pConnection[0] == failed);
        allocated(protocol, 2); balanced(tr, 2);
        CNetConnection::native_result = 0;
        assert(tr.Connect(peer, peer_port, 0, protocol) == 2);
        connection(tr, 2, OWN_PORT_MIN + 1, protocol);
        assert(tr.m_nOwnPort == OWN_PORT_MIN + 2 && tr.m_pConnection[0] == failed);
        allocated(protocol, 3); balanced(tr, 3);
    }
    puts("PASS");
}
"""


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class ConnectPortExhaustionHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text(encoding="utf-8")
        definitions = "\n".join(re.search(
            rf"^#define {name}\s+\d+", source, re.M).group()
            for name in ("OWN_PORT_MIN", "OWN_PORT_MAX"))
        connect = method(source, "int CTransportLayer::Connect (")
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-connect-port-exhaustion-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        harness = cls.root / "test.cpp"
        harness.write_text(definitions + "\n" + FAKE + "\n" + connect + "\n" + HARNESS,
                           encoding="utf-8")
        cls.executable = cls.root / "test.exe"
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(CXX.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror",
             # Circle's bare-metal assert.h must not shadow the host assert.h.
             "-idirafter", str(CIRCLE / "include"), str(harness), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host g++ compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, scenario):
        for protocol in ("tcp", "udp"):
            with self.subTest(protocol=protocol):
                result = subprocess.run(
                    [str(self.executable), scenario, protocol], cwd=self.root, env=self.env,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("PASS", result.stdout)

    def test_free_ports_start_at_current_cursor_and_advance(self):
        self.run_scenario("free")

    def test_skip_collisions_and_retained_closed_allow_opposite_protocol(self):
        self.run_scenario("collisions")

    def test_wrap_skips_collisions_at_both_ends(self):
        self.run_scenario("wrap")

    def test_free_boundary_ports_wrap_cursor(self):
        self.run_scenario("boundary-free")

    def test_full_exhaustion_twice_preserves_cursor_allocates_nothing_and_unlocks(self):
        self.run_scenario("exhausted")

    def test_last_candidate_in_full_range_can_succeed(self):
        self.run_scenario("last-free")

    def test_explicit_nonzero_ports_preserve_native_behavior(self):
        self.run_scenario("explicit")

    def test_native_connect_failure_propagates_after_unlock_and_retains_object(self):
        self.run_scenario("native-failure")


if __name__ == "__main__":
    unittest.main()
