# SPDX-License-Identifier: MIT
"""Exercise complete override Send/SendTo methods on the host, not firmware.

The connection/buffer/network are doubles; the UDP header, constants, and
checksum calculator come from Circle. Network Send consumes the outgoing copy
even on failure; UDP retains the original caller packet on every error.
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


def method(source, signature):
    """Extract the entire definition, rather than reimplement its send logic."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


HEADERS = {
    # Circle's size_t typedef is ARM-specific and conflicts with host headers.
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
#include <array>
#include <algorithm>
#include <cassert>
#include <circle/types.h>
#define IP_ADDRESS_SIZE 4
struct CIPAddress {
    std::array<u8, IP_ADDRESS_SIZE> bytes{};
    boolean valid = FALSE;
    CIPAddress() = default;
    CIPAddress(u8 a, u8 b, u8 c, u8 d) : bytes{a, b, c, d}, valid(TRUE) {}
    boolean IsSet() const { return valid; }
    boolean IsNull() const { assert(valid); return bytes == CIPAddress(0,0,0,0).bytes; }
    void CopyTo(u8 *out) const {
        assert(valid); std::copy(bytes.begin(), bytes.end(), out);
    }
    boolean IsBroadcast() const {
        assert(valid); return bytes == CIPAddress(255,255,255,255).bytes;
    }
    boolean operator==(const CIPAddress &other) const {
        assert(valid && other.valid); return bytes == other.bytes;
    }
    boolean operator!=(const CIPAddress &other) const { return !(*this == other); }
};
""",
}

FAKE = r"""
#include <cassert>
#include <cstdio>
#include <cstring>
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
    enum TPurpose { UDPSend };
    inline static int live = 0, destroyed = 0, copies = 0;
    std::vector<u8> bytes;
    unsigned headers = 0;
    CNetBuffer(TPurpose, size_t length = 0, const void *data = nullptr) : bytes(length) {
        if (length && data) std::memcpy(bytes.data(), data, length);
        ++live;
    }
    CNetBuffer(const CNetBuffer &other) : bytes(other.bytes), headers(other.headers) {
        ++live; ++copies;
    }
    ~CNetBuffer() { --live; ++destroyed; }
    size_t GetLength() const { return bytes.size(); }
    void *GetPtr() const { return const_cast<u8 *>(bytes.data()); }
    void *AddHeader(size_t length) {
        ++headers;
        bytes.insert(bytes.begin(), length, 0);
        return bytes.data();
    }
};
struct CNetConfig {
    CIPAddress own{192,0,2,10}, broadcast{192,0,2,255};
    boolean current_available = TRUE;
    const CIPAddress *GetIPAddress() const { return current_available ? &own : nullptr; }
    const CIPAddress *GetBroadcastAddress() const { return &broadcast; }
};
struct CNetworkLayer {
    unsigned sends = 0;
    boolean succeed = TRUE;
    CIPAddress destination;
    int protocol = 0;
    std::vector<u8> datagram;
    boolean Send(const CIPAddress &ip, CNetBuffer *packet, int proto,
                 boolean router_alert = FALSE) {
        assert(!router_alert && packet && packet->headers == 1);
        ++sends;
        destination = ip;
        protocol = proto;
        datagram = packet->bytes;
        // Real networklayer.cpp consumes the buffer even when returning FALSE.
        delete packet;
        return succeed;
    }
};
struct CUDPConnection {
    int m_nErrno = 0;
    boolean m_bActiveOpen = TRUE, m_bBroadcastsAllowed = FALSE;
    CIPAddress m_LocalIP;  // Default construction represents an unset wildcard.
    CIPAddress m_ForeignIP{198,51,100,7};
    u16 m_nOwnPort = 0x1234, m_nForeignPort = 0x5678;
    CNetConfig *m_pNetConfig;
    CNetworkLayer *m_pNetworkLayer;
    CChecksumCalculator m_Checksum;
    CUDPConnection(CNetConfig *config, CNetworkLayer *network)
        : m_pNetConfig(config), m_pNetworkLayer(network),
          m_Checksum(*config->GetIPAddress(), IPPROTO_UDP) {}
    int Send(CNetBuffer *, int);
    int SendTo(CNetBuffer *, int, const CIPAddress &, u16);
};
"""

HARNESS = r"""
// Independent network-byte-order checksum oracle, including the pseudoheader.
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
static void check_datagram(const CNetConfig &config, const CNetworkLayer &network,
                           const CIPAddress &destination, u16 port,
                           const std::vector<u8> &payload) {
    const auto &packet = network.datagram;
    assert(network.sends == 1 && network.protocol == IPPROTO_UDP);
    assert(network.destination == destination);
    assert(packet.size() == UDP_HEADER_LEN + payload.size());
    assert(wire_word(packet, 0) == 0x1234 && wire_word(packet, 2) == port);
    assert(wire_word(packet, 4) == packet.size());
    assert(std::vector<u8>(packet.begin() + UDP_HEADER_LEN, packet.end()) == payload);
    auto blank = packet;
    blank[6] = blank[7] = 0;
    const u16 expected = checksum(config.own, destination, blank);
    assert(expected != 0 && wire_word(packet, 6) == expected);
    assert(checksum(config.own, destination, packet) == 0);
}
int main(int argc, char **argv) {
    assert(argc == 5);
    const std::string api = argv[1], scenario = argv[2];
    const int length = std::stoi(argv[3]), flags = std::stoi(argv[4]);
    assert(api == "send" || api == "sendto" || api == "connected-sendto");
    CNetConfig config;
    CNetworkLayer network;
    CUDPConnection connection(&config, &network);
    connection.m_bActiveOpen = api != "sendto";
    CIPAddress target{203,0,113,9};
    const u16 target_port = 0x9abc;
    std::vector<u8> payload(length);
    for (int i = 0; i < length; ++i) payload[i] = u8(i * 71 + 3);
    auto *packet = new CNetBuffer(CNetBuffer::UDPSend, payload.size(), payload.data());
    const int destroyed_before = CNetBuffer::destroyed;
    int expected = length;
    boolean caller_owns = FALSE;
    if (scenario == "permission-global" || scenario == "allowed-global") {
        target = CIPAddress(255,255,255,255);
    } else if (scenario == "permission-directed" || scenario == "allowed-directed") {
        target = config.broadcast;
    }
    if (api == "send") connection.m_ForeignIP = target;
    if (scenario.find("permission-") == 0) {
        expected = -NET_ERROR_PERMISSION_DENIED; caller_owns = TRUE;
    } else if (scenario.find("allowed-") == 0) {
        connection.m_bBroadcastsAllowed = TRUE;
    } else if (scenario == "native-error") {
        connection.m_nErrno = expected = -NET_ERROR_DESTINATION_UNREACHABLE;
        caller_owns = TRUE;
    } else if (scenario == "bad-flags" || scenario == "oversize") {
        expected = -NET_ERROR_INVALID_VALUE; caller_owns = TRUE;
    } else if (scenario == "inactive") {
        assert(api == "send"); connection.m_bActiveOpen = FALSE;
        expected = -NET_ERROR_OPERATION_NOT_SUPPORTED; caller_owns = TRUE;
    } else if (scenario == "network-error") {
        network.succeed = FALSE; expected = -NET_ERROR_IO; caller_owns = TRUE;
    } else if (scenario == "local-current") {
        connection.m_LocalIP = config.own;
    } else if (scenario == "local-null") {
        connection.m_LocalIP = CIPAddress(0,0,0,0);
    } else if (scenario == "local-stale" || scenario == "local-config-unset"
               || scenario == "local-config-missing") {
        connection.m_LocalIP = config.own;
        if (scenario == "local-stale") config.own = CIPAddress(192,0,2,11);
        else if (scenario == "local-config-unset") config.own = CIPAddress();
        else config.current_available = FALSE;
        // Local preflight must not consume an already saved native error either.
        connection.m_nErrno = -NET_ERROR_DESTINATION_UNREACHABLE;
        expected = -NET_ERROR_NOT_CONNECTED; caller_owns = TRUE;
    } else assert(scenario == "success");
    assert(connection.m_LocalIP.IsSet() == (scenario.find("local-") == 0));
    if (connection.m_LocalIP.IsSet()) {
        assert(connection.m_LocalIP.IsNull() == (scenario == "local-null"));
    }
    const CIPAddress original_peer = connection.m_ForeignIP;
    const u16 original_peer_port = connection.m_nForeignPort;
    const auto call = [&]() {
        return api == "send" ? connection.Send(packet, flags)
            : connection.SendTo(packet, flags, target, target_port);
    };
    assert(call() == expected);
    assert(connection.m_ForeignIP == original_peer && connection.m_nForeignPort == original_peer_port);
    if (caller_owns) {
        const boolean network_failed = scenario == "network-error";
        assert(network.sends == unsigned(network_failed) && CNetBuffer::live == 1);
        assert(CNetBuffer::destroyed == destroyed_before + int(network_failed));
        assert(CNetBuffer::copies == int(network_failed));
        assert(packet->headers == 0 && packet->bytes == payload);
        if (expected == -NET_ERROR_NOT_CONNECTED) {
            assert(connection.m_nErrno == -NET_ERROR_DESTINATION_UNREACHABLE);
            assert(network.datagram.empty());
        }
        if (network_failed) {
            check_datagram(config, network,
                api != "send" ? target : connection.m_ForeignIP,
                api != "send" ? target_port : connection.m_nForeignPort, payload);
        }
        if (scenario == "native-error") {
            // Pending native error is consumed once; retry sends this same packet.
            assert(connection.m_nErrno == 0 && call() == length);
            check_datagram(config, network,
                api != "send" ? target : connection.m_ForeignIP,
                api != "send" ? target_port : connection.m_nForeignPort, payload);
        } else delete packet;
    } else {
        check_datagram(config, network,
            api != "send" ? target : connection.m_ForeignIP,
            api != "send" ? target_port : connection.m_nForeignPort, payload);
    }
    const int expected_copies = (!caller_owns || scenario == "native-error"
                                 || scenario == "network-error") ? 1 : 0;
    assert(CNetBuffer::copies == expected_copies);
    assert(CNetBuffer::live == 0);
    assert(CNetBuffer::destroyed == destroyed_before + 1 + expected_copies);
    puts("PASS");
}
"""


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class UdpEmptySendHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text(encoding="utf-8")
        methods = "\n".join(method(source, signature) for signature in (
            "int CUDPConnection::Send (", "int CUDPConnection::SendTo ("))
        header_start = source.index("struct TUDPHeader")
        header_end = source.index("ASSERT_STATIC", header_start)
        header_end = source.index(";", header_end) + 1
        udp_header = source[header_start:header_end]
        # Use the real frame bound without pulling in hardware device headers.
        netdevice = (CIRCLE / "include/circle/netdevice.h").read_text(encoding="utf-8")
        frame_size = re.search(r"^#define FRAME_BUFFER_SIZE\s+\d+", netdevice, re.M).group()
        cls.frame_size = int(frame_size.split()[-1])
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-udp-empty-send-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        for name, content in HEADERS.items():
            target = cls.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        harness = cls.root / "test.cpp"
        harness.write_text(FAKE + "\n" + frame_size + "\n" + udp_header
                           + "\n" + methods + "\n" + HARNESS, encoding="utf-8")
        cls.executable = cls.root / "test.exe"
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(CXX.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror",
             # Keep Circle's bare-metal assert.h behind the host C runtime.
             "-I", str(cls.root), "-idirafter", str(CIRCLE / "include"), str(harness),
             str(CIRCLE / "lib/net/checksumcalculator.cpp"), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host g++ compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, api, scenario, length=0, flags=0):
        result = subprocess.run(
            [str(self.executable), api, scenario, str(length), str(flags)],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_empty_payload_emits_eight_byte_checksummed_datagram(self):
        for api in ("send", "sendto", "connected-sendto"):
            for flags in (0, 0x40, 0x8000, 0x8040):
                with self.subTest(api=api, flags=flags):
                    self.run_scenario(api, "success", flags=flags)

    def test_nonempty_payload_return_value_and_wire_bytes_unchanged(self):
        for api in ("send", "sendto", "connected-sendto"):
            for length in (1, 5, 16):
                with self.subTest(api=api, length=length):
                    self.run_scenario(api, "success", length)

    def test_broadcast_permission_retains_caller_packet_and_opt_in_sends(self):
        for api in ("send", "sendto", "connected-sendto"):
            for scenario in ("permission-global", "permission-directed",
                             "allowed-global", "allowed-directed"):
                for length in (0, 5):
                    with self.subTest(api=api, scenario=scenario, length=length):
                        self.run_scenario(api, scenario, length)

    def test_native_preflight_errors_retain_caller_packet(self):
        for api in ("send", "sendto", "connected-sendto"):
            for length in (0, 5):
                for scenario, flags in (("native-error", 0), ("bad-flags", 1)):
                    with self.subTest(api=api, scenario=scenario, length=length):
                        self.run_scenario(api, scenario, length, flags)
            with self.subTest(api=api, scenario="oversize"):
                self.run_scenario(api, "oversize", self.frame_size - 8 + 1)
        self.run_scenario("send", "inactive")

    def test_local_current_and_null_bindings_send_empty_and_payload_datagrams(self):
        for api in ("send", "sendto", "connected-sendto"):
            for scenario in ("local-current", "local-null"):
                for length in (0, 5):
                    with self.subTest(api=api, scenario=scenario, length=length):
                        self.run_scenario(api, scenario, length)

    def test_stale_or_unavailable_local_config_retains_source_and_pending_error(self):
        for api in ("send", "sendto", "connected-sendto"):
            for scenario in ("local-stale", "local-config-unset", "local-config-missing"):
                for length in (0, 5):
                    with self.subTest(api=api, scenario=scenario, length=length):
                        self.run_scenario(api, scenario, length)

    def test_network_failure_consumes_copy_but_retains_caller_packet(self):
        for api in ("send", "sendto", "connected-sendto"):
            for length in (0, 5):
                with self.subTest(api=api, length=length):
                    self.run_scenario(api, "network-error", length)


if __name__ == "__main__":
    unittest.main()
