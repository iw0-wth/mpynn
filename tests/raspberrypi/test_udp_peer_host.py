# SPDX-License-Identifier: MIT
"""Run extracted PORT UDP peer methods with host connection/queue/IP doubles.

SetPeer and SetUDPPeer come directly from the override sources. Circle's error
and protocol headers supply the real constants; no firmware or network is used.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "ports/raspberrypi"
CIRCLE = ROOT / "lib/circle"
OVERRIDES = PORT / "upstream_overrides/circle/lib/net"
CXX = Path("E:/msys64/ucrt64/bin/g++.exe")


def definition(source, signature):
    """Extract the complete production method, without replacing its logic."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


FAKE = r"""
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <limits>
#include <string>
#include <vector>
#include <circle/net/error.h>
#include <circle/net/in.h>
using u16 = uint16_t;
using boolean = bool;
#define TRUE true
#define FALSE false

struct CIPAddress {
    std::array<uint8_t, 4> bytes;
    unsigned sets = 0;
    CIPAddress(uint8_t a = 0, uint8_t b = 0, uint8_t c = 0, uint8_t d = 0)
        : bytes{a, b, c, d} {}
    boolean IsNull() const { return bytes == std::array<uint8_t, 4>{}; }
    void Set(const CIPAddress &other) { bytes = other.bytes; ++sets; }
    boolean operator==(const CIPAddress &other) const { return bytes == other.bytes; }
};
struct CNetBuffer {
    inline static int live = 0;
    inline static std::vector<int> destroyed;
    const int id;
    std::vector<uint8_t> bytes;
    explicit CNetBuffer(int value) : id(value), bytes{uint8_t(value), 0xa5, 0x5a} {
        ++live;
    }
    ~CNetBuffer() { --live; destroyed.push_back(id); }
};
struct CNetBufferQueue {
    std::deque<CNetBuffer *> packets;
    unsigned enqueues = 0, dequeues = 0;
    ~CNetBufferQueue() { assert(packets.empty()); }
    void Enqueue(CNetBuffer *packet) {
        assert(packet); packets.push_back(packet); ++enqueues;
    }
    CNetBuffer *Dequeue() {
        ++dequeues;
        if (packets.empty()) return nullptr;
        auto *packet = packets.front(); packets.pop_front(); return packet;
    }
};
struct CNetConnection {
    const int protocol;
    mutable unsigned protocol_queries = 0;
    CIPAddress m_ForeignIP{198, 51, 100, 7};
    u16 m_nForeignPort = 9000, m_nOwnPort = 60001;
    explicit CNetConnection(int value) : protocol(value) {}
    int GetProtocol() const { ++protocol_queries; return protocol; }
};
struct CUDPConnection : CNetConnection {
    boolean m_bOpen = TRUE, m_bActiveOpen = FALSE, m_bBroadcastsAllowed = FALSE;
    int m_nErrno = -NET_ERROR_DESTINATION_UNREACHABLE;
    unsigned m_nReceiveTimeout = 12345;
    CNetBufferQueue m_RxQueue;
    CUDPConnection() : CNetConnection(IPPROTO_UDP) {}
    int SetPeer(const CIPAddress &, u16);
};
// This is a separate TCP type, with no SetPeer or UDP queue/state interface.
struct CTCPConnection : CNetConnection {
    const std::array<uint8_t, 128> canary{};
    CTCPConnection() : CNetConnection(IPPROTO_TCP) {}
};
struct CConnectionTable {
    std::vector<void *> connections;
    mutable unsigned accesses = 0;
    unsigned GetCount() const { return unsigned(connections.size()); }
    void *operator[](int index) const {
        assert(index >= 0 && unsigned(index) < GetCount());
        ++accesses;
        return connections[size_t(index)];
    }
};
struct CTransportLayer {
    CConnectionTable m_pConnection;
    int SetUDPPeer(const CIPAddress &, u16, int);
};
"""

HARNESS = r"""
struct Snapshot {
    const CIPAddress ip;
    const unsigned ip_sets;
    const u16 foreign_port, own_port;
    const boolean open, active, broadcast;
    const int error, protocol, live;
    const unsigned timeout, queries, enqueues, dequeues;
    const std::deque<CNetBuffer *> packets;
    const std::vector<int> destroyed;
    std::vector<std::vector<uint8_t>> payloads;
    explicit Snapshot(const CUDPConnection &c)
        : ip(c.m_ForeignIP), ip_sets(c.m_ForeignIP.sets),
          foreign_port(c.m_nForeignPort), own_port(c.m_nOwnPort),
          open(c.m_bOpen), active(c.m_bActiveOpen), broadcast(c.m_bBroadcastsAllowed),
          error(c.m_nErrno), protocol(c.protocol), live(CNetBuffer::live),
          timeout(c.m_nReceiveTimeout), queries(c.protocol_queries),
          enqueues(c.m_RxQueue.enqueues), dequeues(c.m_RxQueue.dequeues),
          packets(c.m_RxQueue.packets), destroyed(CNetBuffer::destroyed) {
        for (const auto *packet : packets) payloads.push_back(packet->bytes);
    }
    void unchanged(const CUDPConnection &c, unsigned extra_queries = 0) const {
        assert(c.m_ForeignIP == ip && c.m_ForeignIP.sets == ip_sets);
        assert(c.m_nForeignPort == foreign_port && c.m_nOwnPort == own_port);
        assert(c.m_bOpen == open && c.m_bActiveOpen == active);
        assert(c.m_bBroadcastsAllowed == broadcast && c.m_nErrno == error);
        assert(c.protocol == protocol && c.protocol_queries == queries + extra_queries);
        assert(c.m_nReceiveTimeout == timeout && c.m_RxQueue.packets == packets);
        assert(c.m_RxQueue.enqueues == enqueues && c.m_RxQueue.dequeues == dequeues);
        assert(CNetBuffer::live == live && CNetBuffer::destroyed == destroyed);
        for (size_t i = 0; i < packets.size(); ++i) assert(packets[i]->bytes == payloads[i]);
    }
};
static void enqueue(CUDPConnection &c, int count) {
    for (int i = 0; i < count; ++i) c.m_RxQueue.Enqueue(new CNetBuffer(i + 1));
}
static void clean(CUDPConnection &c) {
    while (auto *packet = c.m_RxQueue.Dequeue()) delete packet;
    assert(CNetBuffer::live == 0);
}
static void changed(const CUDPConnection &c, const Snapshot &before,
                    const CIPAddress &peer, u16 port, unsigned extra_queries = 0) {
    assert(c.m_ForeignIP == peer && c.m_ForeignIP.sets == before.ip_sets + 1);
    assert(c.m_nForeignPort == port && c.m_bActiveOpen && c.m_nErrno == 0);
    assert(c.m_nOwnPort == before.own_port && c.m_bOpen == before.open);
    assert(c.m_bBroadcastsAllowed == before.broadcast);
    assert(c.m_nReceiveTimeout == before.timeout && c.protocol == before.protocol);
    assert(c.protocol_queries == before.queries + extra_queries);
    assert(c.m_RxQueue.packets.empty() && c.m_RxQueue.enqueues == before.enqueues);
    assert(c.m_RxQueue.dequeues == before.dequeues + before.packets.size() + 1);
    assert(CNetBuffer::live == before.live - int(before.packets.size()));
    std::vector<int> expected = before.destroyed;
    // Destruction identities establish that every old buffer was deleted once.
    for (size_t i = 0; i < before.packets.size(); ++i) expected.push_back(int(i + 1));
    assert(CNetBuffer::destroyed == expected);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string scenario = argv[1];
    CIPAddress peer{203, 0, 113, 9};
    for (boolean broadcast : {FALSE, TRUE}) {
        for (boolean active : {FALSE, TRUE}) {
            for (int count : {0, 1, 3}) {
                CUDPConnection c;
                c.m_bBroadcastsAllowed = broadcast;
                c.m_bActiveOpen = active;
                enqueue(c, count);
                if (scenario == "success") {
                    const Snapshot before(c);
                    assert(c.SetPeer(peer, 65535) == 0);
                    changed(c, before, peer, 65535);
                    peer.bytes[3] = 10; // SetPeer must copy, rather than retain an alias.
                    assert(c.m_ForeignIP == CIPAddress(203, 0, 113, 9));
                    peer.bytes[3] = 9;
                } else if (scenario == "invalid" || scenario == "closed") {
                    if (scenario == "closed") c.m_bOpen = FALSE;
                    const Snapshot before(c);
                    const int error = c.m_bOpen ? -NET_ERROR_INVALID_VALUE : -NET_ERROR_NOT_CONNECTED;
                    for (u16 port : {u16(0), u16(1), u16(65535)}) {
                        for (const CIPAddress &ip : {CIPAddress(), peer}) {
                            if (c.m_bOpen && port && !ip.IsNull()) continue;
                            assert(c.SetPeer(ip, port) == error);
                            before.unchanged(c);
                        }
                    }
                    clean(c);
                } else if (scenario == "repeat") {
                    // Both selecting the same peer and reconnecting to another
                    // peer clear native errors and all newly queued stale data.
                    for (int iteration = 0; iteration < 3; ++iteration) {
                        CIPAddress target = iteration < 2 ? peer : CIPAddress(192, 0, 2, 44);
                        u16 port = iteration < 2 ? 8000 : 8001;
                        c.m_nErrno = -NET_ERROR_PROTOCOL_ERROR;
                        const Snapshot before(c);
                        assert(c.SetPeer(target, port) == 0);
                        changed(c, before, target, port);
                        if (iteration < 2) enqueue(c, count);
                    }
                } else if (scenario == "transport") {
                    CTCPConnection tcp;
                    CTransportLayer transport;
                    transport.m_pConnection.connections = {&c, &tcp, nullptr};
                    const Snapshot before(c);
                    for (int handle : {-1, std::numeric_limits<int>::min(), 3, 99,
                                       std::numeric_limits<int>::max()}) {
                        const unsigned accesses = transport.m_pConnection.accesses;
                        assert(transport.SetUDPPeer(peer, 80, handle) == -NET_ERROR_INVALID_VALUE);
                        assert(transport.m_pConnection.accesses == accesses);
                        before.unchanged(c);
                    }
                    assert(transport.SetUDPPeer(peer, 80, 2) == -NET_ERROR_INVALID_VALUE);
                    before.unchanged(c);
                    assert(transport.SetUDPPeer(peer, 80, 1) == -NET_ERROR_PROTOCOL_NOT_SUPPORTED);
                    assert(tcp.protocol_queries == 1 && tcp.m_ForeignIP.sets == 0);
                    assert(tcp.m_ForeignIP == CIPAddress(198, 51, 100, 7));
                    assert(tcp.m_nForeignPort == 9000 && tcp.m_nOwnPort == 60001);
                    assert((tcp.canary == std::array<uint8_t, 128>{}));
                    before.unchanged(c);
                    assert(transport.SetUDPPeer(CIPAddress(), 80, 0) == -NET_ERROR_INVALID_VALUE);
                    before.unchanged(c, 1);
                    assert(transport.SetUDPPeer(peer, 0, 0) == -NET_ERROR_INVALID_VALUE);
                    before.unchanged(c, 2);
                    c.m_bOpen = FALSE;
                    const Snapshot closed(c);
                    assert(transport.SetUDPPeer(peer, 80, 0) == -NET_ERROR_NOT_CONNECTED);
                    closed.unchanged(c, 1);
                    c.m_bOpen = TRUE;
                    const Snapshot ready(c);
                    assert(transport.SetUDPPeer(peer, 80, 0) == 0);
                    changed(c, ready, peer, 80, 1);
                } else {
                    assert(false && "unknown scenario");
                }
                assert(c.m_RxQueue.packets.empty() && CNetBuffer::live == 0);
            }
        }
    }
    puts("PASS");
}
"""


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class UdpPeerHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        methods = []
        for filename, signature in (
                ("udpconnection.cpp", "int CUDPConnection::SetPeer ("),
                ("transportlayer.cpp", "int CTransportLayer::SetUDPPeer (")):
            source = (OVERRIDES / filename).read_text(encoding="utf-8")
            methods.append(definition(source, signature))
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-udp-peer-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        harness = cls.root / "test.cpp"
        harness.write_text(FAKE + "\n" + "\n".join(methods) + "\n" + HARNESS,
                           encoding="utf-8")
        cls.executable = cls.root / "test.exe"
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(CXX.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror",
             # Use host assert.h while retaining Circle's real error/protocol headers.
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

    def test_peer_update_preserves_local_port_broadcast_and_drains_queue(self):
        self.run_scenario("success")

    def test_invalid_peer_preserves_state_error_and_queued_buffers(self):
        self.run_scenario("invalid")

    def test_closed_connection_rejects_peer_before_mutation_or_validation(self):
        self.run_scenario("closed")

    def test_repeated_and_changed_peers_clear_new_stale_errors_and_buffers(self):
        self.run_scenario("repeat")

    def test_transport_validates_handles_and_protocol_before_udp_dispatch(self):
        self.run_scenario("transport")


if __name__ == "__main__":
    unittest.main()
