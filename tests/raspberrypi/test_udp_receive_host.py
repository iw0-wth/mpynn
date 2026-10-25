# SPDX-License-Identifier: MIT
"""Run extracted PORT UDP receive methods and Circle checksums on the host.

Only hardware-facing buffer/queue/event/IP/config dependencies are doubles.
PacketReceived, ReceiveFrom, GetStatus and their wire/private/status structs are
read from the actual sources, so no receive logic is reimplemented here.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CIRCLE = ROOT / "lib/circle"
SOURCE = ROOT / "ports/raspberrypi/upstream_overrides/circle/lib/net/udpconnection.cpp"
CXX = Path("E:/msys64/ucrt64/bin/g++.exe")


def definition(source, signature):
    """Extract a complete brace-delimited method or struct definition."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


HEADERS = {
    # Circle's ARM size_t typedef conflicts with the host standard library.
    "circle/types.h": r"""
#pragma once
#include <cstddef>
using u8 = unsigned char;
using u16 = unsigned short;
using u32 = unsigned int;
using boolean = bool;
#define TRUE true
#define FALSE false
static_assert(sizeof(u8) == 1 && sizeof(u16) == 2 && sizeof(u32) == 4);
""",
    "circle/util.h": r"""
#pragma once
#define le2be16 __builtin_bswap16
#define be2le16 __builtin_bswap16
""",
    "circle/net/ipaddress.h": r"""
#pragma once
#include <algorithm>
#include <array>
#include <cassert>
#include <circle/types.h>
#define IP_ADDRESS_SIZE 4
struct CIPAddress {
    std::array<u8, IP_ADDRESS_SIZE> bytes{};
    bool valid = false;
    CIPAddress() = default;
    CIPAddress(u8 a, u8 b, u8 c, u8 d) : bytes{a,b,c,d}, valid(true) {}
    void CopyTo(u8 *out) const { std::copy(bytes.begin(), bytes.end(), out); }
    void Set(const u8 *in) { std::copy(in, in + IP_ADDRESS_SIZE, bytes.begin()); valid = true; }
    void Set(const CIPAddress &other) { bytes = other.bytes; valid = other.valid; }
    CIPAddress &operator=(u32 value) {
        bytes = {u8(value), u8(value >> 8), u8(value >> 16), u8(value >> 24)};
        valid = true; return *this;
    }
    void Set(u8 a, u8 b, u8 c, u8 d) { bytes = {a,b,c,d}; valid = true; }
    boolean IsSet() const { return valid; }
    boolean IsNull() const { assert(valid); return bytes == std::array<u8,4>{}; }
    boolean IsBroadcast() const { return bytes == CIPAddress(255,255,255,255).bytes; }
    boolean IsMulticast() const { return bytes[0] >= 224 && bytes[0] <= 239; }
    boolean operator==(const CIPAddress &other) const { return bytes == other.bytes; }
    boolean operator!=(const CIPAddress &other) const { return !(*this == other); }
};
""",
}

FAKE = r"""
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <vector>
#include <circle/macros.h>
#include <circle/net/error.h>
#include <circle/net/in.h>
#include <circle/net/sizes.h>
#include <circle/net/checksumcalculator.h>
#include <circle/util.h>
#define ASSERT_STATIC(condition) static_assert(condition)

struct CNetBuffer {
    inline static int live = 0, destroyed = 0;
    std::vector<u8> storage;
    size_t head = 0, length;
    alignas(u16) u8 metadata[20]{};
    size_t metadata_length = 0;
    std::vector<std::string> operations;
    explicit CNetBuffer(const std::vector<u8> &bytes)
        : storage(bytes), length(bytes.size()) { ++live; }
    ~CNetBuffer() { --live; ++destroyed; }
    size_t GetLength() const { return length; }
    void *GetPtr() const { return const_cast<u8 *>(storage.data()) + head; }
    void *RemoveHeader(size_t count) {
        assert(count <= length);
        operations.push_back("header");
        head += count; length -= count;
        return GetPtr();
    }
    void RemoveTrailer(size_t count) {
        assert(count <= length);
        operations.push_back("trailer");
        length -= count;
    }
    void SetPrivateData(const void *data, size_t count) {
        assert(data && count <= sizeof metadata);
        operations.push_back("private");
        std::memcpy(metadata, data, count); metadata_length = count;
    }
    void *AddHeader(size_t count) {
        storage.insert(storage.begin(), count, 0); length += count; head = 0;
        operations.push_back("add-header"); return storage.data();
    }
    const void *GetPrivateData() const { return metadata_length ? metadata : nullptr; }
    size_t GetPrivateDataLength() const { return metadata_length; }
    std::vector<u8> payload() const {
        return std::vector<u8>(storage.begin() + head, storage.begin() + head + length);
    }
};
struct CNetBufferQueue {
    std::deque<CNetBuffer *> packets;
    unsigned enqueues = 0, dequeues = 0;
    ~CNetBufferQueue() { assert(packets.empty()); }
    boolean IsEmpty() const { return packets.empty(); }
    void Enqueue(CNetBuffer *packet) {
        assert(packet); ++enqueues; packets.push_back(packet);
    }
    CNetBuffer *Dequeue() {
        ++dequeues;
        if (IsEmpty()) return nullptr;
        auto *packet = packets.front(); packets.pop_front(); return packet;
    }
};
struct CSynchronizationEvent {
    unsigned sets = 0, clears = 0, waits = 0, timed_waits = 0;
    void Set() { ++sets; }
    void Clear() { ++clears; }
    // Never let an accidental blocking receive hang the host test process.
    void Wait() { ++waits; std::abort(); }
    boolean WaitWithTimeout(unsigned timeout) {
        assert(timeout > 0); ++timed_waits; return TRUE;
    }
};
struct CNetConfig {
    CIPAddress own{192,0,2,10}, broadcast{192,0,2,255};
    const CIPAddress *GetIPAddress() const { return &own; }
    const CIPAddress *GetBroadcastAddress() const { return &broadcast; }
};
struct CNetworkLayer {
    unsigned sends = 0;
    boolean Send(const CIPAddress &, CNetBuffer *packet, int) {
        ++sends; delete packet; return TRUE;
    }
};
enum TICMPNotificationType { ICMPNotificationDestUnreach, ICMPNotificationOther };
"""

CONNECTION = r"""
struct CUDPConnection : CNetConnection {
    boolean m_bOpen = TRUE, m_bActiveOpen = FALSE, m_bBroadcastsAllowed = FALSE;
    int m_nErrno = 0;
    unsigned m_nReceiveTimeout = 0;
    CIPAddress m_ForeignIP{198,51,100,7};
    CIPAddress m_LocalIP;
    u16 m_nOwnPort = 0x1234, m_nForeignPort = 0x5678;
    CIPAddress *m_pHostGroup = nullptr;
    CNetConfig *m_pNetConfig;
    CNetworkLayer network;
    CNetworkLayer *m_pNetworkLayer = &network;
    CNetBufferQueue m_RxQueue;
    CSynchronizationEvent m_Event;
    CChecksumCalculator m_Checksum;
    explicit CUDPConnection(CNetConfig *config)
        : m_pNetConfig(config), m_Checksum(*config->GetIPAddress(), IPPROTO_UDP) {}
    int SetLocalAddress(const CIPAddress &);
    int Send(CNetBuffer *, int);
    int SendTo(CNetBuffer *, int, const CIPAddress &, u16);
    int PacketReceived(CNetBuffer *, CIPAddress &, CIPAddress &, int);
    int NotificationReceived(TICMPNotificationType, CIPAddress &, CIPAddress &, u16, u16, int);
    int ReceiveFrom(CNetBuffer **, int, CIPAddress *, u16 *);
    TStatus GetStatus() const;
};
"""

HARNESS = r"""
// Independent big-endian checksum oracle; packet generation does not call Circle.
static u16 wire_word(const std::vector<u8> &bytes, size_t offset) {
    return (u16(bytes[offset]) << 8) | bytes[offset + 1];
}
static u16 checksum(const CIPAddress &source, const CIPAddress &destination,
                    const std::vector<u8> &packet) {
    std::vector<u8> bytes(source.bytes.begin(), source.bytes.end());
    bytes.insert(bytes.end(), destination.bytes.begin(), destination.bytes.end());
    bytes.push_back(0); bytes.push_back(IPPROTO_UDP);
    bytes.push_back(u8(packet.size() >> 8)); bytes.push_back(u8(packet.size()));
    bytes.insert(bytes.end(), packet.begin(), packet.end());
    if (bytes.size() & 1) bytes.push_back(0);
    u32 sum = 0;
    for (size_t i = 0; i < bytes.size(); i += 2) sum += wire_word(bytes, i);
    while (sum >> 16) sum = (sum & 0xffff) + (sum >> 16);
    return u16(~sum);
}
static void sign(std::vector<u8> &bytes, const CIPAddress &sender,
                 const CIPAddress &receiver) {
    auto *header = reinterpret_cast<TUDPHeader *>(bytes.data());
    header->nChecksum = 0;
    u16 value = checksum(sender, receiver, bytes);
    if (value == 0) value = 0xffff;  // zero is the IPv4 no-checksum sentinel
    header->nChecksum = le2be16(value);
    assert(checksum(sender, receiver, bytes) == 0);
}
static void status(const CUDPConnection &connection, bool ready, bool open = true) {
    const auto result = connection.GetStatus();
    assert(result.bConnected == open && result.bRxReady == ready);
    assert(result.bTxReady == open && !result.bException);
}
static void empty_receive(CUDPConnection &connection, int flags) {
    CIPAddress ip{203,0,113,88};
    const CIPAddress sentinel = ip;
    u16 port = 0xabcd;
    CNetBuffer sentinel_buffer(std::vector<u8>{0xa5});
    CNetBuffer *out = &sentinel_buffer;  // empty dequeue must overwrite a nonnull output
    assert(connection.ReceiveFrom(&out, flags, &ip, &port) == 0);
    assert(out == nullptr && ip == sentinel && port == 0xabcd);
    assert(connection.m_Event.waits == 0 && connection.m_Event.timed_waits == 0);
    assert(connection.m_Event.clears == 0);
    status(connection, false);
}
int main(int argc, char **argv) {
    assert(argc == 4);
    const std::string scenario = argv[1];
    const int value = std::stoi(argv[2]), flags = std::stoi(argv[3]);
    CNetConfig config;
    CUDPConnection connection(&config);
    status(connection, false);
    if (scenario == "status-error") {
        connection.m_nErrno = -NET_ERROR_DESTINATION_UNREACHABLE;
        status(connection, true);
        CNetBuffer *out = nullptr;  // error path does not assign *ppNetBuffer
        CIPAddress ip{203,0,113,88};
        u16 port = 0xabcd;
        assert(connection.ReceiveFrom(&out, flags, &ip, &port)
               == -NET_ERROR_DESTINATION_UNREACHABLE);
        assert(out == nullptr && ip == CIPAddress(203,0,113,88) && port == 0xabcd);
        assert(connection.m_nErrno == 0 && connection.m_RxQueue.dequeues == 0);
        empty_receive(connection, MSG_DONTWAIT);
        connection.m_bOpen = FALSE;
        connection.m_nErrno = -1;
        status(connection, false, false);
        puts("PASS"); return 0;
    }
    if (scenario == "local-api") {
        assert(!connection.m_LocalIP.IsSet());
        CIPAddress invalid{192,0,2,11};
        assert(connection.SetLocalAddress(invalid) == -NET_ERROR_INVALID_VALUE);
        assert(!connection.m_LocalIP.IsSet());
        CIPAddress requested = config.own;
        assert(connection.SetLocalAddress(requested) == 0);
        assert(connection.m_LocalIP == config.own);
        requested.Set(192,0,2,77);  // the connection retained a copy
        assert(connection.m_LocalIP == config.own);
        CIPAddress sender{198,51,100,7}, other{192,0,2,99};
        assert(connection.NotificationReceived(ICMPNotificationDestUnreach,
            sender, other, 0, 0x1234, IPPROTO_UDP) == 0);
        assert(connection.m_nErrno == 0);
        config.own.Set(192,0,2,99);  // a reconfigured interface must not be used
        assert(connection.NotificationReceived(ICMPNotificationDestUnreach,
            sender, requested, 0, 0x1234, IPPROTO_UDP) == 0);
        CIPAddress original_local{192,0,2,10};
        assert(connection.NotificationReceived(ICMPNotificationDestUnreach,
            sender, original_local, 0, 0x1234, IPPROTO_UDP) == 1);
        assert(connection.m_nErrno == -NET_ERROR_DESTINATION_UNREACHABLE);
        connection.m_nErrno = 0;
        connection.m_bActiveOpen = TRUE;
        CNetBuffer *stale_send = new CNetBuffer(std::vector<u8>{1,2,3});
        assert(connection.Send(stale_send, MSG_DONTWAIT) == -NET_ERROR_NOT_CONNECTED);
        assert(stale_send->payload() == std::vector<u8>({1,2,3}));
        assert(stale_send->operations.empty() && connection.network.sends == 0);
        delete stale_send;
        CNetBuffer *stale_sendto = new CNetBuffer(std::vector<u8>{4,5});
        assert(connection.SendTo(stale_sendto, MSG_DONTWAIT, sender, 99)
               == -NET_ERROR_NOT_CONNECTED);
        assert(stale_sendto->payload() == std::vector<u8>({4,5}));
        assert(stale_sendto->operations.empty() && connection.network.sends == 0);
        delete stale_sendto;
        CIPAddress wildcard;
        assert(connection.SetLocalAddress(wildcard) == 0);
        assert(connection.m_LocalIP.IsSet() && connection.m_LocalIP.IsNull());
        connection.m_bOpen = FALSE;
        assert(connection.SetLocalAddress(CIPAddress(192,0,2,10))
               == -NET_ERROR_INVALID_VALUE);
        assert(connection.network.sends == 0 && CNetBuffer::live == 0);
        puts("PASS"); return 0;
    }
    if (scenario == "timeout") {
        connection.m_nReceiveTimeout = 17;
        CNetBuffer *out = nullptr;
        assert(connection.ReceiveFrom(&out, 0, nullptr, nullptr) == -1);
        assert(out == nullptr && connection.m_nErrno == 0);
        assert(connection.m_Event.clears == 1 && connection.m_Event.timed_waits == 1);
        assert(connection.m_Event.waits == 0 && CNetBuffer::live == 0);
        status(connection, false);
        puts("PASS"); return 0;
    }
    empty_receive(connection, MSG_DONTWAIT | (flags & MSG_MORE));
    CIPAddress sender = connection.m_ForeignIP, receiver = config.own;
    CIPAddress group{239,1,2,3};
    int protocol = IPPROTO_UDP, expected = 1;
    bool queued = true;
    size_t payload_length = size_t(value);
    if (scenario == "short-header" || scenario == "bad-length"
        || scenario == "oversize-declared") payload_length = 0;
    if (scenario.find("active-") == 0) connection.m_bActiveOpen = TRUE;
    if (scenario == "active-wrong-ip") sender = CIPAddress(198,51,100,8);
    if (scenario == "sender-multicast") sender = group;
    if (scenario.find("broadcast-global-") == 0) receiver = CIPAddress(255,255,255,255);
    if (scenario.find("broadcast-directed-") == 0) receiver = config.broadcast;
    if (scenario.find("broadcast-") == 0) {
        connection.m_bBroadcastsAllowed = scenario.find("allowed") != std::string::npos;
        queued = connection.m_bBroadcastsAllowed;
    }
    if (scenario.find("multicast-") == 0) {
        receiver = group;
        if (scenario == "multicast-joined") connection.m_pHostGroup = &group;
        else { expected = 0; queued = false; }
    }
    if (scenario == "wrong-protocol") protocol = IPPROTO_TCP;
    if (scenario.find("local-") == 0) {
        assert(connection.SetLocalAddress(config.own) == 0);
        if (scenario == "local-wrong-destination") receiver = CIPAddress(192,0,2,11);
        if (scenario == "local-broadcast" || scenario == "local-broadcast-global") {
            connection.m_bBroadcastsAllowed = TRUE;
            receiver = scenario == "local-broadcast" ? config.broadcast
                                                        : CIPAddress(255,255,255,255);
        }
        if (scenario == "local-multicast") receiver = group;
    }
    if (scenario == "wrong-protocol" || scenario == "wrong-dest-port"
        || scenario == "active-wrong-port" || scenario == "active-wrong-ip"
        || scenario == "local-wrong-destination" || scenario == "local-broadcast"
        || scenario == "local-broadcast-global" || scenario == "local-multicast") {
        expected = 0; queued = false;
    }
    if (scenario == "short-header" || scenario == "bad-length"
        || scenario == "oversize-declared" || scenario == "bad-checksum"
        || scenario == "padding-checksum-full" || scenario == "sender-multicast") {
        expected = -1; queued = false;
    }
    std::vector<u8> payload(payload_length);
    for (size_t i = 0; i < payload.size(); ++i) payload[i] = u8(i * 71 + 3);
    std::vector<u8> bytes(UDP_HEADER_LEN + payload.size());
    auto *header = reinterpret_cast<TUDPHeader *>(bytes.data());
    header->nSourcePort = le2be16(scenario == "active-wrong-port" ? 0x5679 : 0x5678);
    header->nDestPort = le2be16(scenario == "wrong-dest-port" ? 0x1235 : 0x1234);
    header->nLength = le2be16(bytes.size());
    std::copy(payload.begin(), payload.end(), bytes.begin() + UDP_HEADER_LEN);
    sign(bytes, sender, receiver);
    const size_t declared_length = bytes.size();
    const bool padded = scenario.find("padding") == 0;
    if (padded) {
        bytes.insert(bytes.end(), {0x93, 0x27, 0xa5, 0x6d, 0xe1});
        assert(checksum(sender, receiver, bytes) != 0);
        if (scenario == "padding-checksum-full") {
            sign(bytes, sender, receiver);
            const std::vector<u8> declared(bytes.begin(), bytes.begin() + declared_length);
            assert(checksum(sender, receiver, declared) != 0);
        }
    }
    header = reinterpret_cast<TUDPHeader *>(bytes.data());  // insert may relocate
    if (scenario == "no-checksum" || scenario == "padding-none") header->nChecksum = 0;
    if (scenario == "bad-checksum") {
        bytes[6] ^= 1;
        assert(header->nChecksum != 0 && checksum(sender, receiver, bytes) != 0);
    }
    if (scenario == "bad-length" || scenario == "oversize-declared")
        header->nLength = le2be16(value);
    if (scenario == "short-header") bytes.resize(size_t(value));
    auto *packet = new CNetBuffer(bytes);
    const int destroyed_before = CNetBuffer::destroyed;
    assert(connection.PacketReceived(packet, sender, receiver, protocol) == expected);
    assert(connection.m_Event.sets == unsigned(queued));
    assert(connection.m_RxQueue.enqueues == unsigned(queued));
    status(connection, queued);
    if (queued) {
        // Queue owns this same buffer, including when its payload length is zero.
        assert(CNetBuffer::live == 1 && CNetBuffer::destroyed == destroyed_before);
        assert(connection.m_RxQueue.packets.front() == packet);
        assert(packet->GetLength() == payload.size() && packet->payload() == payload);
        const std::vector<std::string> operations = padded
            ? std::vector<std::string>{"trailer", "header", "private"}
            : std::vector<std::string>{"header", "private"};
        assert(packet->operations == operations);
        assert(packet->head == UDP_HEADER_LEN);
        assert(packet->GetPrivateDataLength() == sizeof(TUDPPrivateData));
        const auto *metadata = static_cast<const TUDPPrivateData *>(packet->GetPrivateData());
        CIPAddress metadata_ip; metadata_ip.Set(metadata->SourceAddress);
        assert(metadata_ip == sender && metadata->nSourcePort == 0x5678);
        CNetBuffer *out = nullptr;
        CIPAddress ip{203,0,113,88};
        u16 port = 0xabcd;
        CIPAddress *ip_output = scenario == "null-ip" || scenario == "null-both" ? nullptr : &ip;
        u16 *port_output = scenario == "null-port" || scenario == "null-both" ? nullptr : &port;
        assert(connection.ReceiveFrom(&out, flags, ip_output, port_output) == int(payload.size()));
        assert(out != nullptr && out == packet && out->payload() == payload);
        // Actual ReceiveFrom updates peer outputs only when BOTH are supplied.
        if (ip_output && port_output) assert(ip == sender && port == 0x5678);
        else assert(ip == CIPAddress(203,0,113,88) && port == 0xabcd);
        assert(connection.m_Event.waits == 0 && connection.m_Event.clears == 0);
        status(connection, false);
        assert(CNetBuffer::destroyed == destroyed_before);
        delete out;  // ReceiveFrom transfers ownership even when its result is 0.
    } else if (expected == 0) {
        assert(CNetBuffer::live == 1 && CNetBuffer::destroyed == destroyed_before);
        assert(packet->storage == bytes && packet->head == 0 && packet->GetLength() == bytes.size());
        assert(packet->operations.empty() && packet->GetPrivateDataLength() == 0);
        delete packet;  // Not-to-me returns leave ownership with the caller.
    } else {
        // Malformed packets and disallowed broadcasts are consumed, not queued.
        assert(CNetBuffer::live == 0 && CNetBuffer::destroyed == destroyed_before + 1);
    }
    assert(CNetBuffer::live == 0 && CNetBuffer::destroyed == destroyed_before + 1);
    empty_receive(connection, MSG_DONTWAIT | (flags & MSG_MORE));
    puts("PASS");
}
"""


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class UdpReceiveHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text(encoding="utf-8")
        methods = "\n".join(definition(source, signature) for signature in (
            "int CUDPConnection::SetLocalAddress (",
            "int CUDPConnection::Send (",
            "int CUDPConnection::SendTo (",
            "int CUDPConnection::PacketReceived (",
            "int CUDPConnection::NotificationReceived (",
            "int CUDPConnection::ReceiveFrom (",
            "CNetConnection::TStatus CUDPConnection::GetStatus ("))
        header_start = source.index("struct TUDPHeader")
        header_end = source.index("ASSERT_STATIC", header_start)
        header_end = source.index(";", header_end) + 1
        udp_header = source[header_start:header_end]
        private_data = definition(source, "struct TUDPPrivateData") + ";"
        netconnection = (CIRCLE / "include/circle/net/netconnection.h").read_text(encoding="utf-8")
        status_struct = definition(netconnection, "struct TStatus") + ";"
        netdevice = (CIRCLE / "include/circle/netdevice.h").read_text(encoding="utf-8")
        frame_size = re.search(r"^#define FRAME_BUFFER_SIZE\s+\d+", netdevice, re.M).group()
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-udp-receive-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        for name, content in HEADERS.items():
            target = cls.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        harness = cls.root / "test.cpp"
        harness.write_text(
            FAKE + "\n" + frame_size + "\n" + udp_header + "\n" + private_data
            + "\nstruct CNetConnection {\n" + status_struct + "\n};\n"
            + CONNECTION + "\n" + methods + "\n" + HARNESS, encoding="utf-8")
        cls.executable = cls.root / "test.exe"
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(CXX.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror",
             # Circle's bare-metal assert.h must follow the host C runtime.
             "-I", str(cls.root), "-idirafter", str(CIRCLE / "include"), str(harness),
             str(CIRCLE / "lib/net/checksumcalculator.cpp"), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host g++ compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, scenario, value=0, flags=0x40):
        result = subprocess.run(
            [str(self.executable), scenario, str(value), str(flags)],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_header_only_datagram_is_ready_nonnull_and_has_peer(self):
        for flags in (0, 0x40, 0x8000, 0x8040):
            with self.subTest(flags=flags):
                self.run_scenario("valid", flags=flags)

    def test_nonempty_and_no_checksum_datagrams(self):
        for scenario in ("valid", "no-checksum"):
            for length in (0, 1, 5, 16):
                with self.subTest(scenario=scenario, length=length):
                    self.run_scenario(scenario, length)

    def test_short_header_and_invalid_declared_lengths_are_deleted(self):
        for scenario in ("short-header", "bad-length"):
            for length in range(8):
                with self.subTest(scenario=scenario, length=length):
                    self.run_scenario(scenario, length)
        for length in (9, 16, 65535):
            with self.subTest(declared=length):
                self.run_scenario("oversize-declared", length)

    def test_padding_excluded_from_checksum_and_payload_and_stripped_first(self):
        for scenario in ("padding", "padding-none", "padding-checksum-full"):
            for length in (0, 1, 5, 16):
                with self.subTest(scenario=scenario, length=length):
                    self.run_scenario(scenario, length)

    def test_bad_checksum_rejected_and_deleted(self):
        for length in (0, 1, 5, 16):
            with self.subTest(length=length):
                self.run_scenario("bad-checksum", length)

    def test_local_binding_api_notification_filter_and_stale_sends(self):
        self.run_scenario("local-api")

    def test_explicit_local_binding_filters_destination_broadcast_and_multicast(self):
        self.run_scenario("local-match", 5)
        for scenario in ("local-wrong-destination", "local-broadcast",
                         "local-broadcast-global", "local-multicast"): 
            for length in (0, 5):
                with self.subTest(scenario=scenario, length=length):
                    self.run_scenario(scenario, length)

    def test_active_peer_match_and_not_to_me_leave_caller_ownership(self):
        for scenario in ("active-match", "active-wrong-port", "active-wrong-ip",
                         "wrong-dest-port", "wrong-protocol"): 
            for length in (0, 5):
                with self.subTest(scenario=scenario, length=length):
                    self.run_scenario(scenario, length)

    def test_broadcast_gate_consumes_blocked_and_queues_allowed(self):
        for kind in ("global", "directed"):
            for permission in ("blocked", "allowed"):
                for length in (0, 5):
                    with self.subTest(kind=kind, permission=permission, length=length):
                        self.run_scenario(f"broadcast-{kind}-{permission}", length)

    def test_multicast_sender_and_membership_ownership(self):
        for scenario in ("sender-multicast", "multicast-unjoined", "multicast-joined"):
            for length in (0, 5):
                with self.subTest(scenario=scenario, length=length):
                    self.run_scenario(scenario, length)

    def test_optional_peer_outputs_are_only_updated_as_pair(self):
        for scenario in ("null-ip", "null-port", "null-both"):
            for length in (0, 5):
                with self.subTest(scenario=scenario, length=length):
                    self.run_scenario(scenario, length)

    def test_status_error_consumed_once_and_closed_status_not_ready(self):
        self.run_scenario("status-error")

    def test_receive_timeout_does_not_fabricate_a_packet(self):
        self.run_scenario("timeout")


if __name__ == "__main__":
    unittest.main()
