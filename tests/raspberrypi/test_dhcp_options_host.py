# SPDX-License-Identifier: MIT
"""Compile complete production DHCP option/receive methods with host doubles.

The parser, unaligned reader, wire structs, constants and endian macros are read
from production, not copied into the test. Only socket/MAC/device dependencies
are faked. All generated C++ and executables live in a temporary directory.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
OVERRIDE = ROOT / "ports/raspberrypi/upstream_overrides/circle"
SOURCE = OVERRIDE / "lib/net/dhcpclient.cpp"
HEADER = OVERRIDE / "include/circle/net/dhcpclient.h"
UTIL = ROOT / "lib/circle/include/circle/util.h"
WINDOWS_CXX = Path("E:/msys64/ucrt64/bin/g++.exe")
CXX = str(WINDOWS_CXX) if WINDOWS_CXX.is_file() else shutil.which("g++")


def definition(source, signature):
    """Extract a complete brace-delimited production definition."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PREAMBLE = r"""
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
using u8 = unsigned char;
using u16 = unsigned short;
using u32 = unsigned int;
using boolean = bool;
static_assert(sizeof(u8) == 1 && sizeof(u16) == 2 && sizeof(u32) == 4, "wire types");
#define TRUE true
#define FALSE false
#define PACKED __attribute__((packed))
#define BE(value) __builtin_bswap16(value)
#define MAC_ADDRESS_SIZE 6
#define MSG_DONTWAIT 0x40
#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "line %d: %s\n", __LINE__, #c); std::exit(1); } } while (0)
struct CMACAddress {
    std::array<u8, MAC_ADDRESS_SIZE> bytes;
    explicit CMACAddress(const u8 *p) { std::copy_n(p, bytes.size(), bytes.begin()); }
    bool operator!=(const CMACAddress &other) const { return bytes != other.bytes; }
};
struct FakeDevice {
    const u8 address[MAC_ADDRESS_SIZE] = {2, 0, 0, 0, 0, 1};
    CMACAddress mac{address};
    const CMACAddress *GetMACAddress() const { return &mac; }
};
struct CNetSubSystem {
    FakeDevice device;
    FakeDevice *GetNetDeviceLayer() { return &device; }
};
struct FakeSocket {
    std::vector<u8> packet;
    int reported = -1;
    int Receive(void *buffer, unsigned capacity, int flags) {
        CHECK(flags == MSG_DONTWAIT);
        const auto copied = std::min(packet.size(), static_cast<size_t>(capacity));
        if (copied) std::memcpy(buffer, packet.data(), copied);
        return reported;
    }
};
"""

HARNESS = r"""
static constexpr u32 guard = 0xCAFE1234;
static std::array<u32, 10> values(const CDHCPClient &c) {
    return {c.m_nRxYIAddr, c.m_nRxSubnetMask, c.m_nRxRouter, c.m_nRxDNSServer,
            c.m_nRxIPAddressLeaseTime, c.m_nRxOptionsOverload, c.m_nRxMessageType,
            c.m_nRxServerIdentifier, c.m_nRxRenewalTimeValue, c.m_nRxRebindingTimeValue};
}
static boolean scan(CDHCPClient &c, const std::vector<u8> &input) {
    // Exact-size allocation makes accidental reads visible to memory sanitizers.
    // Even a zero-byte scan has a nonnull pointer, as required by production.
    std::unique_ptr<u8[]> bytes(new u8[input.empty() ? 1 : input.size()]);
    if (!input.empty()) std::copy(input.begin(), input.end(), bytes.get());
    const boolean result = c.ScanOptions(bytes.get(), static_cast<unsigned>(input.size()));
    CHECK(c.before == guard && c.after == guard);
    CHECK(input.empty() || std::equal(input.begin(), input.end(), bytes.get()));
    return result;
}
static void rejected_without_extraction(const std::vector<u8> &bytes) {
    CDHCPClient c;
    c.m_nRxSubnetMask = 0x01020304;
    c.m_nRxRouter = 0;  // Exercise first-router extraction on malformed input.
    c.m_nRxDNSServer = 0x21222324;
    c.m_nRxIPAddressLeaseTime = 0x31323334;
    c.m_nRxOptionsOverload = 2;
    c.m_nRxMessageType = 5;
    c.m_nRxServerIdentifier = 0x41424344;
    c.m_nRxRenewalTimeValue = 0x51525354;
    c.m_nRxRebindingTimeValue = 0x61626364;
    const auto original = values(c);
    CHECK(!scan(c, bytes));
    CHECK(values(c) == original);
}
static void correct_values() {
    CDHCPClient c;
    CHECK(scan(c, {
        DHCP_OPTION_SUBNETMASK, 4, 255,255,255,0,
        DHCP_OPTION_ROUTER, 8, 192,0,2,1, 192,0,2,2,
        DHCP_OPTION_DNSSERVER, 8, 198,51,100,1, 198,51,100,2,
        DHCP_OPTION_LEASETIME, 4, 0x12,0x34,0x56,0x78,
        DHCP_OPTION_SERVERID, 4, 192,0,2,254,
        DHCP_OPTION_RENEWALTIME, 4, 0,0,0x10,0x20,
        DHCP_OPTION_REBINDTIME, 4, 0,0,0x30,0x40,
        DHCP_OPTION_MSGTYPE, 1, DHCP_OPTION_MSGTYPE_ACK,
        DHCP_OPTION_END}));
    CHECK(c.m_nRxSubnetMask == 0x00FFFFFF);
    CHECK(c.m_nRxRouter == 0x010200C0);
    CHECK(c.m_nRxDNSServer == 0x016433C6);
    CHECK(c.m_nRxIPAddressLeaseTime == 0x12345678);
    CHECK(c.m_nRxServerIdentifier == 0xFE0200C0);
    CHECK(c.m_nRxRenewalTimeValue == 0x1020);
    CHECK(c.m_nRxRebindingTimeValue == 0x3040);
    CHECK(c.m_nRxMessageType == DHCP_OPTION_MSGTYPE_ACK);
    CHECK(scan(c, {DHCP_OPTION_ROUTER, 4, 203,0,113,1}));
    CHECK(c.m_nRxRouter == 0x010200C0);  // Preserve the first router.
    const u8 unaligned[] = {0, 0x12,0x34,0x56,0x78};
    CHECK(CDHCPClient::GetUnaligned(unaligned + 1) == 0x78563412);
}
static void boundary_options() {
    for (const auto &bytes : std::vector<std::vector<u8>>{
            {}, {DHCP_OPTION_PAD}, {DHCP_OPTION_END},
            {DHCP_OPTION_PAD, DHCP_OPTION_END}, {200,0},
            {200,0,DHCP_OPTION_PAD,DHCP_OPTION_END},
            {200,0,DHCP_OPTION_PAD},
            {DHCP_OPTION_MSGTYPE,1,DHCP_OPTION_MSGTYPE_OFFER},
            {DHCP_OPTION_MSGTYPE,1,DHCP_OPTION_MSGTYPE_OFFER,DHCP_OPTION_END},
            {DHCP_OPTION_END,DHCP_OPTION_ROUTER,255}}) {
        CDHCPClient c;
        CHECK(scan(c, bytes));
    }
    for (unsigned value = 1; value <= 8; ++value) {
        CDHCPClient c;
        CHECK(scan(c, {DHCP_OPTION_MSGTYPE,1,static_cast<u8>(value)}));
        CHECK(c.m_nRxMessageType == value);
    }
    for (unsigned value = 1; value <= 3; ++value) {
        CDHCPClient c;
        CHECK(scan(c, {DHCP_OPTION_OVERLOAD,1,static_cast<u8>(value)}));
        CHECK(c.m_nRxOptionsOverload == value);
    }
    for (unsigned value = 0; value <= 255; ++value) {
        if (value < 1 || value > 8)
            rejected_without_extraction({DHCP_OPTION_MSGTYPE,1,static_cast<u8>(value)});
        if (value < 1 || value > 3)
            rejected_without_extraction({DHCP_OPTION_OVERLOAD,1,static_cast<u8>(value)});
    }
}
static bool valid_width(unsigned code, unsigned length) {
    switch (code) {
    case DHCP_OPTION_SUBNETMASK: case DHCP_OPTION_SERVERID:
    case DHCP_OPTION_LEASETIME: case DHCP_OPTION_RENEWALTIME: case DHCP_OPTION_REBINDTIME:
        return length == 4;
    case DHCP_OPTION_ROUTER: case DHCP_OPTION_DNSSERVER:
        return length >= 4 && length % 4 == 0;
    case DHCP_OPTION_OVERLOAD: case DHCP_OPTION_MSGTYPE:
        return length == 1;
    default: return true;
    }
}
static void malformed_options() {
    const std::array<u8, 10> codes = {
        DHCP_OPTION_SUBNETMASK, DHCP_OPTION_ROUTER, DHCP_OPTION_DNSSERVER,
        DHCP_OPTION_SERVERID, DHCP_OPTION_LEASETIME, DHCP_OPTION_RENEWALTIME,
        DHCP_OPTION_REBINDTIME, DHCP_OPTION_OVERLOAD, DHCP_OPTION_MSGTYPE, 200};
    for (u8 code : codes) {
        const unsigned length = (code == DHCP_OPTION_ROUTER || code == DHCP_OPTION_DNSSERVER)
                                ? 8 : (code == DHCP_OPTION_OVERLOAD || code == DHCP_OPTION_MSGTYPE) ? 1 : 4;
        std::vector<u8> option{code, static_cast<u8>(length)};
        option.insert(option.end(), length, 1);
        for (unsigned prefix = 1; prefix < option.size(); ++prefix)
            rejected_without_extraction(std::vector<u8>(option.begin(), option.begin() + prefix));
        // A huge declaration with only a small payload must not extract even
        // the first router/DNS address, or advance beyond the option region.
        rejected_without_extraction({code,255});
        rejected_without_extraction({code,255,1,2,3,4});
        if (code != 200) {
            for (unsigned width = 0; width <= 255; ++width) {
                if (valid_width(code, width)) continue;
                std::vector<u8> malformed{code,static_cast<u8>(width)};
                malformed.insert(malformed.end(), width, 1);
                rejected_without_extraction(malformed);
            }
        }
    }
    rejected_without_extraction({DHCP_OPTION_ROUTER,8,192,0,2,1});
    rejected_without_extraction({DHCP_OPTION_DNSSERVER,8,192,0,2,1});
    // Unknown options may have any width, including zero and 255, if complete.
    for (unsigned width : {0U, 1U, 6U, 255U}) {
        CDHCPClient c;
        std::vector<u8> option{200,static_cast<u8>(width)};
        option.insert(option.end(), width, 0xA5);
        CHECK(scan(c, option));
        CHECK((values(c) == std::array<u32, 10>{}));
    }
}
// Acceptance oracle only: no production values are extracted or emulated.
static bool accepts(const std::vector<u8> &bytes) {
    size_t position = 0;
    while (position < bytes.size()) {
        const unsigned code = bytes[position++];
        if (code == DHCP_OPTION_PAD) continue;
        if (code == DHCP_OPTION_END) return true;
        if (position == bytes.size()) return false;
        const unsigned length = bytes[position++];
        if (length > bytes.size() - position || !valid_width(code, length)) return false;
        if (code == DHCP_OPTION_OVERLOAD && (bytes[position] < 1 || bytes[position] > 3)) return false;
        if (code == DHCP_OPTION_MSGTYPE && (bytes[position] < 1 || bytes[position] > 8)) return false;
        position += length;
    }
    return true;
}
static void table_fuzz() {
    for (unsigned code = 0; code <= 255; ++code) {
        for (unsigned length = 0; length <= 255; ++length) {
            for (unsigned size = 0; size <= 6; ++size) {
                std::vector<u8> bytes(size, 1);
                if (size) bytes[0] = static_cast<u8>(code);
                if (size > 1) bytes[1] = static_cast<u8>(length);
                CDHCPClient c;
                CHECK(scan(c, bytes) == accepts(bytes));
                // Only 0x01 bytes are available to extract; reject arbitrary
                // outputs from reading past the exact supplied buffer.
                CHECK(c.m_nRxSubnetMask == 0 || c.m_nRxSubnetMask == 0x01010101);
                CHECK(c.m_nRxRouter == 0 || c.m_nRxRouter == 0x01010101);
                CHECK(c.m_nRxDNSServer == 0 || c.m_nRxDNSServer == 0x01010101);
                CHECK(c.m_nRxServerIdentifier == 0 || c.m_nRxServerIdentifier == 0x01010101);
                CHECK(c.m_nRxIPAddressLeaseTime == 0 || c.m_nRxIPAddressLeaseTime == 0x01010101);
                CHECK(c.m_nRxRenewalTimeValue == 0 || c.m_nRxRenewalTimeValue == 0x01010101);
                CHECK(c.m_nRxRebindingTimeValue == 0 || c.m_nRxRebindingTimeValue == 0x01010101);
                CHECK(c.m_nRxOptionsOverload <= 3 && c.m_nRxMessageType <= 8);
            }
        }
    }
}
static void prepare_message(CDHCPClient &c, CNetSubSystem &net, const std::vector<u8> &options) {
    c.m_pNetSubSystem = &net;
    c.m_nXID = 0x12345678;
    c.m_Socket.packet.assign(DHCP_HEADER_SIZE + options.size(), 0);
    auto *message = reinterpret_cast<TDHCPMessage *>(c.m_Socket.packet.data());
    message->OP = DHCP_OP_BOOTREPLY;
    message->HType = DHCP_HTYPE_ETHER;
    message->HLen = MAC_ADDRESS_SIZE;
    message->XID = c.m_nXID;
    message->MagicCookie = DHCP_MAGIC_COOKIE;
    message->YIAddr = 0x2A0200C0;
    std::copy_n(net.device.address, MAC_ADDRESS_SIZE, message->CHAddr);
    if (!options.empty()) std::copy(options.begin(), options.end(), message->Options);
    c.m_Socket.reported = static_cast<int>(c.m_Socket.packet.size());
}
static void receive_messages() {
    static_assert(DHCP_HEADER_SIZE == 240 && DHCP_MAX_MESSAGE_SIZE == 548, "wire limits");
    CNetSubSystem net;
    for (u8 mode : {u8(0), u8(1), u8(2), u8(3)}) {
        CDHCPClient c;
        std::vector<u8> options{DHCP_OPTION_MSGTYPE,1,DHCP_OPTION_MSGTYPE_OFFER};
        if (mode) options.insert(options.end(), {DHCP_OPTION_OVERLOAD,1,mode});
        options.push_back(DHCP_OPTION_END);
        prepare_message(c, net, options);
        auto *m = reinterpret_cast<TDHCPMessage *>(c.m_Socket.packet.data());
        const u8 file[] = {DHCP_OPTION_ROUTER,4,192,0,2,1,DHCP_OPTION_END};
        const u8 sname[] = {DHCP_OPTION_DNSSERVER,4,198,51,100,1,DHCP_OPTION_END};
        std::copy_n(file, sizeof file, m->File);
        std::copy_n(sname, sizeof sname, m->SName);
        CHECK(c.ReceiveMessage());
        CHECK(c.m_nRxYIAddr == 0x2A0200C0);
        CHECK(c.m_nRxMessageType == DHCP_OPTION_MSGTYPE_OFFER);
        CHECK(c.m_nRxRouter == ((mode & 1) ? 0x010200C0U : 0));
        CHECK(c.m_nRxDNSServer == ((mode & 2) ? 0x016433C6U : 0));
    }
    for (u8 mode : {u8(1), u8(2), u8(3)}) {
        for (unsigned field : {1U, 2U}) {
            if (!(mode & field)) continue;
            for (bool at_end : {false, true}) {
                CDHCPClient c;
                prepare_message(c, net, {DHCP_OPTION_OVERLOAD,1,mode,DHCP_OPTION_END});
                auto *m = reinterpret_cast<TDHCPMessage *>(c.m_Socket.packet.data());
                u8 *area = field == 1 ? m->File : m->SName;
                const unsigned size = field == 1 ? sizeof m->File : sizeof m->SName;
                // Either an enormous payload declaration or code missing its
                // length in the final byte of the overloaded field.
                area[at_end ? size - 1 : 0] = DHCP_OPTION_ROUTER;
                if (!at_end) area[1] = 255;
                CHECK(!c.ReceiveMessage());
            }
        }
    }
    for (const auto &options : std::vector<std::vector<u8>>{
            {DHCP_OPTION_ROUTER}, {DHCP_OPTION_ROUTER,8,192,0,2,1},
            {DHCP_OPTION_MSGTYPE,0}, {DHCP_OPTION_OVERLOAD,1,4}}) {
        CDHCPClient c;
        prepare_message(c, net, options);
        CHECK(!c.ReceiveMessage());
    }
    for (unsigned size : {240U, 241U, 548U}) {
        CDHCPClient c;
        prepare_message(c, net, std::vector<u8>(size - DHCP_HEADER_SIZE, DHCP_OPTION_PAD));
        CHECK(c.ReceiveMessage());  // No END, including final-byte PAD.
    }
    for (int size : {-1, 0, 239, 549, 1024}) {
        CDHCPClient c;
        prepare_message(c, net, {DHCP_OPTION_END});
        c.m_Socket.reported = size;
        CHECK(!c.ReceiveMessage());
    }
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    const std::string mode = argv[1];
    if (mode == "values" || mode == "all") correct_values();
    if (mode == "boundary" || mode == "all") boundary_options();
    if (mode == "malformed" || mode == "all") malformed_options();
    if (mode == "fuzz" || mode == "all") table_fuzz();
    if (mode == "receive" || mode == "all") receive_messages();
    CHECK(mode == "values" || mode == "boundary" || mode == "malformed" ||
          mode == "fuzz" || mode == "receive" || mode == "all");
    std::puts("PASS");
}
"""


def translation_unit():
    source = SOURCE.read_text(encoding="utf-8")
    header = HEADER.read_text(encoding="utf-8")
    util = UTIL.read_text(encoding="utf-8")
    if not re.search(r"boolean\s+ScanOptions\s*\(\s*const u8 \*pOptions,\s*unsigned nOptionsSize\s*\)", header):
        raise AssertionError("production header must declare boolean ScanOptions(const u8*, unsigned)")
    # Use the exact production GNU byte-swap/endian aliases.
    endian = []
    for name in ("bswap32", "be2le32"):
        match = re.search(r"^#define\s+" + name + r"\s+[^\n]+", util, re.MULTILINE)
        if not match:
            raise AssertionError("missing production endian macro: " + name)
        endian.append(match.group(0))
    wire = source[source.index("struct TDHCPMessage"):source.index("static const char FromDHCPClient")]
    fields = re.findall(r"^\s*(u32|u8)\s+(m_nRx\w+|m_nXID)\s*;", header, re.MULTILINE)
    if len(fields) != 11:
        raise AssertionError("unexpected production receive field declarations: " + repr(fields))
    fake = "\nclass CDHCPClient {\npublic:\n    u32 before = 0xCAFE1234;\n"
    fake += "    CNetSubSystem *m_pNetSubSystem = nullptr;\n    FakeSocket m_Socket;\n"
    fake += "".join("    %s %s = 0;\n" % field for field in fields)
    fake += """    u32 after = 0xCAFE1234;
    boolean ScanOptions(const u8 *, unsigned);
    boolean ReceiveMessage(void);
    static u32 GetUnaligned(const void *);
};
"""
    methods = "\n".join(definition(source, signature) for signature in (
        "u32 CDHCPClient::GetUnaligned (", "boolean CDHCPClient::ScanOptions (",
        "boolean CDHCPClient::ReceiveMessage ("))
    return PREAMBLE + "\n".join(endian) + "\n" + wire + fake + methods + HARNESS


@unittest.skipUnless(CXX, "host g++ is not installed")
class DhcpOptionsHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-dhcp-options-")

        def cleanup():
            for attempt in range(20):
                try:
                    temporary.cleanup()
                    return
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.1)

        cls.addClassCleanup(cleanup)
        cls.root = Path(temporary.name)
        cls.env = dict(os.environ)
        cls.env["PATH"] = str(Path(CXX).parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        cls.harness = cls.root / "dhcp-options.cpp"
        cls.harness.write_text(translation_unit(), encoding="utf-8")
        cls.executable = cls.root / "dhcp-options.exe"
        cls.compile(cls.harness, cls.executable)

    @classmethod
    def compile(cls, source, executable, extra=()):
        result = subprocess.run(
            [CXX, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", *extra,
             str(source), "-o", str(executable)], cwd=cls.root, env=cls.env,
            capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError("host g++ compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, mode, executable=None):
        result = subprocess.run([str(executable or self.executable), mode],
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_correct_addresses_times_and_first_router(self):
        self.run_scenario("values")

    def test_pad_end_unknown_zero_no_end_and_valid_enum_ranges(self):
        self.run_scenario("boundary")

    def test_every_truncated_prefix_and_invalid_known_width(self):
        self.run_scenario("malformed")

    def test_all_codes_and_lengths_against_zero_to_six_byte_buffers(self):
        self.run_scenario("fuzz")

    def test_receive_propagates_main_file_sname_failures_and_bounds_size(self):
        self.run_scenario("receive")

    def test_optional_undefined_behavior_sanitizer(self):
        # Probe both linking and runtime: some host GCC builds lack libubsan.
        probe = self.root / "ubsan-probe.cpp"
        probe.write_text("int main() { return 0; }\n", encoding="utf-8")
        executable = self.root / "ubsan-probe.exe"
        flags = ("-fsanitize=undefined", "-fno-sanitize-recover=all")
        result = subprocess.run([CXX, *flags, str(probe), "-o", str(executable)],
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, timeout=30)
        if result.returncode:
            self.skipTest("host g++ cannot link UBSan")
        result = subprocess.run([str(executable)], cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            self.skipTest("host UBSan runtime is unavailable")
        sanitized = self.root / "dhcp-options-ubsan.exe"
        self.compile(self.harness, sanitized, flags)
        self.run_scenario("all", sanitized)


if __name__ == "__main__":
    unittest.main()
