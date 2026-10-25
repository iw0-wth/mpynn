# SPDX-License-Identifier: MIT
"""Host tests for the production UDP pending-error methods.

The harness extracts the native methods from the override sources verbatim;
only Circle object storage, IP/config, and event dependencies are doubles.
No native traffic or firmware is used.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
CIRCLE = ROOT / "lib/circle"
OVERRIDES = ROOT / "ports/raspberrypi/upstream_overrides/circle"
CXX = Path("E:/msys64/ucrt64/bin/g++.exe")


def definition(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


FAKE = r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <string>
#include <vector>
#include <circle/net/error.h>
#include <circle/net/in.h>
enum TICMPNotificationType {
    ICMPNotificationDestUnreach,
    ICMPNotificationTimeExceed,
    ICMPNotificationParamProblem,
    ICMPNotificationUnknown
};
using u8 = uint8_t;
using u16 = uint16_t;
using boolean = bool;
#define TRUE true
#define FALSE false
struct CIPAddress {
    u8 bytes[4]{};
    boolean valid = FALSE;
    CIPAddress() = default;
    CIPAddress(u8 a,u8 b,u8 c,u8 d) : bytes{a,b,c,d}, valid(TRUE) {}
    boolean IsSet() const { return valid; }
    boolean IsNull() const { assert(valid); return *this == CIPAddress(0,0,0,0); }
    bool operator==(const CIPAddress &other) const {
        assert(valid && other.valid);
        for (unsigned i=0; i<4; ++i) if (bytes[i] != other.bytes[i]) return false;
        return true;
    }
    bool operator!=(const CIPAddress &other) const { return !(*this == other); }
};
struct CNetConfig {
    CIPAddress own{192,0,2,10};
    const CIPAddress *GetIPAddress() const { return &own; }
};
struct CNetBuffer {
    int id;
    explicit CNetBuffer(int value) : id(value) { ++live; }
    ~CNetBuffer() { --live; }
    inline static int live = 0;
};
struct CNetBufferQueue {
    std::deque<CNetBuffer *> packets;
    CNetBuffer *Dequeue() {
        if (packets.empty()) return nullptr;
        auto *p = packets.front(); packets.pop_front(); return p;
    }
    unsigned size() const { return unsigned(packets.size()); }
};
struct CSynchronizationEvent {
    unsigned sets = 0;
    void Set() { ++sets; }
};
struct CNetConnection {
    int protocol;
    explicit CNetConnection(int value) : protocol(value) {}
    int GetProtocol() const { return protocol; }
};
struct CUDPConnection : CNetConnection {
    boolean m_bOpen = TRUE, m_bActiveOpen = TRUE;
    CIPAddress m_LocalIP;  // Default construction represents an unset wildcard.
    CIPAddress m_ForeignIP{198,51,100,7};
    u16 m_nForeignPort = 9000, m_nOwnPort = 60001;
    CNetConfig *m_pNetConfig;
    int m_nErrno = 0;
    CNetBufferQueue m_RxQueue;
    CSynchronizationEvent m_Event;
    CUDPConnection(CNetConfig *config) : CNetConnection(IPPROTO_UDP), m_pNetConfig(config) {}
    int TakePendingError(void);
    int NotificationReceived(TICMPNotificationType, CIPAddress &, CIPAddress &, u16, u16, int);
};
struct CConnectionTable {
    std::vector<CNetConnection *> values;
    unsigned GetCount() const { return unsigned(values.size()); }
    CNetConnection *operator[](int index) const {
        assert(index >= 0 && unsigned(index) < values.size());
        return values[size_t(index)];
    }
};
struct CTransportLayer {
    CConnectionTable m_pConnection;
    int TakeUDPError(int);
};
"""


HARNESS = r"""
static void clear(CUDPConnection &udp) {
    while (auto *p = udp.m_RxQueue.Dequeue()) delete p;
}
static void check_local_destination(const std::string &binding) {
    CNetConfig config;
    CUDPConnection udp(&config);
    assert(!udp.m_LocalIP.IsSet());
    if (binding == "current") udp.m_LocalIP = config.own;
    else if (binding == "null") udp.m_LocalIP = CIPAddress(0,0,0,0);
    else assert(binding == "unset");
    assert(udp.m_LocalIP.IsSet() == (binding != "unset"));
    if (udp.m_LocalIP.IsSet()) assert(udp.m_LocalIP.IsNull() == (binding == "null"));
    auto *packet = new CNetBuffer(42);
    udp.m_RxQueue.packets.push_back(packet);
    CIPAddress sender = udp.m_ForeignIP;
    CIPAddress receiver = config.own;
    CIPAddress wrong_destination{192,0,2,11};
    udp.m_nErrno = -NET_ERROR_PROTOCOL_ERROR;
    assert(udp.NotificationReceived(ICMPNotificationDestUnreach, sender, wrong_destination,
                                    udp.m_nForeignPort, udp.m_nOwnPort, IPPROTO_UDP) == 0);
    assert(udp.m_nErrno == -NET_ERROR_PROTOCOL_ERROR && udp.m_Event.sets == 0);
    assert(udp.m_RxQueue.size() == 1 && udp.m_RxQueue.packets.front() == packet);
    assert(CNetBuffer::live == 1 && packet->id == 42);
    assert(udp.NotificationReceived(ICMPNotificationDestUnreach, sender, receiver,
                                    udp.m_nForeignPort, udp.m_nOwnPort, IPPROTO_UDP) == 1);
    assert(udp.m_nErrno == -NET_ERROR_DESTINATION_UNREACHABLE && udp.m_Event.sets == 1);
    assert(udp.m_RxQueue.size() == 1 && udp.m_RxQueue.packets.front() == packet);
    assert(CNetBuffer::live == 1 && packet->id == 42);
    // A wrong destination must not overwrite even the newly saved error.
    assert(udp.NotificationReceived(ICMPNotificationTimeExceed, sender, wrong_destination,
                                    udp.m_nForeignPort, udp.m_nOwnPort, IPPROTO_UDP) == 0);
    assert(udp.m_nErrno == -NET_ERROR_DESTINATION_UNREACHABLE && udp.m_Event.sets == 1);
    assert(udp.m_RxQueue.size() == 1 && udp.m_RxQueue.packets.front() == packet);
    assert(udp.TakePendingError() == -NET_ERROR_DESTINATION_UNREACHABLE);
    assert(udp.m_nErrno == 0 && udp.m_RxQueue.size() == 1);
    clear(udp);
    assert(CNetBuffer::live == 0);
    puts("PASS");
}
int main(int argc, char **argv) {
    if (argc == 2) {
        check_local_destination(argv[1]);
        return 0;
    }
    assert(argc == 1);
    CNetConfig config;
    CIPAddress sender{198,51,100,7};
    CIPAddress receiver = config.own;
    CUDPConnection udp(&config);
    udp.m_RxQueue.packets.push_back(new CNetBuffer(1));
    udp.m_nErrno = -NET_ERROR_DESTINATION_UNREACHABLE;
    assert(udp.NotificationReceived(ICMPNotificationDestUnreach, sender, receiver,
                                    udp.m_nForeignPort, udp.m_nOwnPort, IPPROTO_UDP) == 1);
    assert(udp.m_nErrno == -NET_ERROR_DESTINATION_UNREACHABLE);
    assert(udp.m_Event.sets == 1 && udp.m_RxQueue.size() == 1);
    assert(udp.TakePendingError() == -NET_ERROR_DESTINATION_UNREACHABLE);
    assert(udp.m_nErrno == 0 && udp.m_RxQueue.size() == 1);
    assert(udp.TakePendingError() == 0 && udp.m_RxQueue.size() == 1);

    udp.m_nErrno = -NET_ERROR_PROTOCOL_ERROR;
    assert(udp.NotificationReceived(ICMPNotificationTimeExceed, sender, receiver,
                                    udp.m_nForeignPort, udp.m_nOwnPort, IPPROTO_TCP) == 0);
    assert(udp.TakePendingError() == -NET_ERROR_PROTOCOL_ERROR);
    assert(udp.m_Event.sets == 1 && udp.m_RxQueue.size() == 1);

    CNetConnection tcp(IPPROTO_TCP);
    CTransportLayer transport;
    transport.m_pConnection.values = {&udp, &tcp, nullptr};
    assert(transport.TakeUDPError(-1) == -NET_ERROR_INVALID_VALUE);
    assert(transport.TakeUDPError(3) == -NET_ERROR_INVALID_VALUE);
    assert(transport.TakeUDPError(2) == -NET_ERROR_INVALID_VALUE);
    assert(transport.TakeUDPError(1) == -NET_ERROR_PROTOCOL_NOT_SUPPORTED);
    udp.m_nErrno = -NET_ERROR_PROTOCOL_ERROR;
    assert(transport.TakeUDPError(0) == -NET_ERROR_PROTOCOL_ERROR);
    assert(transport.TakeUDPError(0) == 0);
    clear(udp);
    assert(CNetBuffer::live == 0);
    puts("PASS");
}
"""


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class UdpPendingErrorHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        udp_source = (OVERRIDES / "lib/net/udpconnection.cpp").read_text(encoding="utf-8")
        transport_source = (OVERRIDES / "lib/net/transportlayer.cpp").read_text(encoding="utf-8")
        methods = "\n".join([
            definition(udp_source, "int CUDPConnection::TakePendingError ("),
            definition(udp_source, "int CUDPConnection::NotificationReceived ("),
            definition(transport_source, "int CTransportLayer::TakeUDPError ("),
        ])
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-udp-pending-")
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
        source = cls.root / "test.cpp"
        source.write_text(FAKE + "\n" + methods + "\n" + HARNESS, encoding="utf-8")
        cls.exe = cls.root / "test.exe"
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(CXX.parent) + os.pathsep + cls.env.get("PATH", "")
        result = subprocess.run(
            [str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror",
             "-idirafter", str(CIRCLE / "include"), str(source), "-o", str(cls.exe)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host g++ compile failed:\n" + result.stdout + result.stderr)

    def test_native_notification_take_and_transport_dispatch(self):
        result = subprocess.run([str(self.exe)], cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_local_destination_match_and_wrong_destination_preserve_queue(self):
        for binding in ("unset", "null", "current"):
            with self.subTest(binding=binding):
                result = subprocess.run([str(self.exe), binding], cwd=self.root, env=self.env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
