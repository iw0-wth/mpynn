# SPDX-License-Identifier: MIT
"""Compile actual Circle TCP option parsing with only numeric connection doubles.

Wire structs, parser and relevant macros come from production. Circle's real
sizes/error/in headers are included after the host system include search path.
No firmware build, library changes, network I/O or copied parser is involved.
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
SOURCE = OVERRIDE / "lib/net/tcpconnection.cpp"
HEADER = OVERRIDE / "include/circle/net/tcpconnection.h"
INCLUDE = ROOT / "lib/circle/include"
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


def macro(source, name):
    match = re.search(r"^#define\s+" + re.escape(name) + r"(?:\([^\n]*?\))?\s+[^\n]+",
                      source, re.MULTILINE)
    if not match:
        raise AssertionError("missing production macro: " + name)
    return match.group(0)


PREAMBLE = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
// Windows RPC also declares boolean; keep that host-only name distinct.
#define boolean windows_boolean
#include <windows.h>
#undef boolean
#elif defined(__unix__) || defined(__APPLE__)
#include <sys/mman.h>
#include <unistd.h>
#endif
#include <circle/net/sizes.h>
#include <circle/net/error.h>
#include <circle/net/in.h>
using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using boolean = bool;
#ifndef TRUE
#define TRUE true
#endif
#ifndef FALSE
#define FALSE false
#endif
#define PACKED __attribute__((packed))
#define ASSERT_STATIC(c) static_assert(c, #c)
#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "line %d: %s\n", __LINE__, #c); std::exit(1); } } while (0)
'''

HARNESS = r'''
static_assert(sizeof(TTCPHeader) == 20 && sizeof(TTCPOption) == 2, "production wire sizes");
static_assert(offsetof(TTCPHeader, Options) == TCP_HEADER_LEN, "production options offset");
static_assert(offsetof(TTCPHeader, nDataOffsetFlags) == 12, "production flags offset");
static_assert(IPPROTO_TCP == 6 && NET_ERROR_INVALID_VALUE > 0, "actual Circle constants");
static constexpr u32 guard = 0xCAFE1234;
static bool guarded = false;

// Put the exact declared header extent immediately before an inaccessible page.
// malloc/new exact-size storage is also used in non-guarded runs (sanitizer ready).
class GuardPages {
    u8 *base = nullptr;
    size_t page = 0;
public:
    GuardPages() {
#if defined(_WIN32)
        SYSTEM_INFO info;
        GetSystemInfo(&info);
        page = info.dwPageSize;
        base = static_cast<u8 *>(VirtualAlloc(nullptr, page * 2, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
        if (base) {
            DWORD old;
            if (!VirtualProtect(base + page, page, PAGE_NOACCESS, &old)) {
                VirtualFree(base, 0, MEM_RELEASE);
                base = nullptr;
            }
        }
#elif defined(__unix__) || defined(__APPLE__)
        const long size = sysconf(_SC_PAGESIZE);
        if (size <= 0) return;
        page = static_cast<size_t>(size);
        void *allocation = mmap(nullptr, page * 2, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (allocation == MAP_FAILED) return;
        base = static_cast<u8 *>(allocation);
        if (mprotect(base + page, page, PROT_NONE)) {
            munmap(base, page * 2);
            base = nullptr;
        }
#endif
    }
    ~GuardPages() {
#if defined(_WIN32)
        if (base) VirtualFree(base, 0, MEM_RELEASE);
#elif defined(__unix__) || defined(__APPLE__)
        if (base) munmap(base, page * 2);
#endif
    }
    bool available() const { return base != nullptr; }
    u8 *packet(size_t size) { CHECK(base && size <= page); return base + page - size; }
};

static std::array<u32, 4> values(const CTCPConnection &c) {
    return {c.m_nSND_MSS, c.m_nMSS, c.m_nIW, c.m_nCWND};
}
static boolean scan(CTCPConnection &c, const std::vector<u8> &options,
                    unsigned flags = TCP_FLAG_SYN, int offset_words = -1) {
    // Match the allocation to the encoded data offset: TCP options are word sized.
    CHECK(options.size() <= 40 && options.size() % 4 == 0);
    const size_t size = TCP_HEADER_LEN + options.size();
    std::unique_ptr<u8[]> owned;
    std::unique_ptr<GuardPages> pages;
    u8 *bytes;
    if (guarded) {
        pages.reset(new GuardPages);
        CHECK(pages->available());
        bytes = pages->packet(size);
    } else {
        owned.reset(new u8[size]);
        bytes = owned.get();
    }
    std::memset(bytes, 0, size);
    auto *header = reinterpret_cast<TTCPHeader *>(bytes);
    const unsigned words = offset_words < 0 ? static_cast<unsigned>(size / 4)
                                           : static_cast<unsigned>(offset_words);
    header->nDataOffsetFlags = static_cast<u16>((words << TCP_DATA_OFFSET_SHIFT) | flags);
    if (!options.empty()) std::copy(options.begin(), options.end(), bytes + TCP_HEADER_LEN);
    const std::vector<u8> original(bytes, bytes + size);
    const boolean result = c.ScanOptions(header);
    CHECK(c.before == guard && c.after == guard);
    CHECK(std::equal(original.begin(), original.end(), bytes));
    return result;
}
static void preserved(const std::vector<u8> &options, bool accepted,
                      unsigned flags = TCP_FLAG_SYN) {
    CTCPConnection c;
    const auto original = values(c);
    CHECK(scan(c, options, flags) == accepted);
    CHECK(values(c) == original);
}
static std::vector<u8> padded(std::vector<u8> bytes) {
    while (bytes.size() % 4) bytes.push_back(TCP_OPTION_END_OF_LIST);
    return bytes;
}
static void boundaries() {
    // Every useful option extent 0..40, with legal word padding where needed.
    for (unsigned size = 0; size <= 40; ++size) {
        std::vector<u8> nops(size, TCP_OPTION_NOP);
        preserved(padded(nops), true);
        if (size) {
            nops.back() = TCP_OPTION_END_OF_LIST;
            preserved(padded(nops), true);
        }
    }
    // EOL and NOP need no length byte, including the actual final allocated byte.
    for (unsigned size = 4; size <= 40; size += 4) {
        std::vector<u8> bytes(size, TCP_OPTION_NOP);
        preserved(bytes, true);
        bytes.back() = TCP_OPTION_END_OF_LIST;
        preserved(bytes, true);
        bytes.back() = 200;
        preserved(bytes, false);  // Kind alone cannot expose a length byte.
    }
    preserved({0, 200, 0, 255}, true);  // EOL ignores malformed following padding.
    for (unsigned size = 4; size <= 40; size += 4) {
        std::vector<u8> unknown(size, 0xA5);
        unknown[0] = 200;
        unknown[1] = static_cast<u8>(size);
        preserved(unknown, true);  // Unknown option ending exactly at the boundary.
    }
    preserved({200, 2, 1, 0}, true);
    preserved({200, 3, 0xA5, 1}, true);
    for (int words = 0; words < 5; ++words) {
        CTCPConnection c;
        const auto original = values(c);
        CHECK(!scan(c, {}, TCP_FLAG_SYN, words));
        CHECK(values(c) == original);
    }
}
static void malformed() {
    for (u8 kind : {u8(2), u8(3), u8(200), u8(255)}) {
        for (u8 length : {u8(0), u8(1), u8(5), u8(255)}) {
            preserved({kind, length, 1, 1}, false);
            preserved({2, 4, 5, 180, kind, length, 1, 1}, false);
            preserved({2, 4, 5, 180, kind, length, 1, 1}, false, TCP_FLAG_ACK);
        }
    }
    // Known MSS must be exactly four bytes, not merely a well-bounded TLV.
    for (u8 length : {u8(2), u8(3), u8(6), u8(8)}) {
        preserved({2, length, 1, 1, 1, 1, 1, 1}, false);
        preserved({2, 4, 5, 180, 2, length, 1, 1, 1, 1, 1, 1}, false);
    }
    // Every truncated MSS prefix at the end of a word-sized options area.
    preserved({1, 1, 1, 2}, false);
    preserved({1, 1, 2, 4}, false);
    preserved({1, 2, 4, 5}, false);
    preserved({2, 4, 5, 180, 1, 1, 1, 2}, false);
    preserved({2, 4, 5, 180, 1, 1, 2, 4}, false);
    preserved({2, 4, 5, 180, 1, 2, 4, 5}, false);
    preserved({2, 4, 5, 180, 1, 1, 1, 200}, false);
}
static std::vector<u8> mss(unsigned value) {
    return {TCP_OPTION_MSS, 4, static_cast<u8>(value >> 8), static_cast<u8>(value)};
}
static void negotiated(const std::vector<u8> &options, unsigned expected_mss,
                       unsigned expected_window) {
    CTCPConnection c;
    CHECK(scan(c, options));
    CHECK((values(c) == std::array<u32, 4>{expected_mss, expected_mss, expected_window, expected_window}));
}
static void negotiation() {
    negotiated(mss(1460), 1460, 4380);
    negotiated(mss(1461), 1460, 4380);
    negotiated(mss(65535), 1460, 4380);
    negotiated(mss(1095), 1095, 4380);
    negotiated(mss(1096), 1096, 3288);
    negotiated(mss(536), 536, 2144);
    negotiated(mss(10), 10, 40);
    for (unsigned value = 0; value < 10; ++value) preserved(mss(value), true);
    for (unsigned value : {0U, 9U, 10U, 536U, 1096U, 1460U, 65535U}) {
        preserved(mss(value), true, 0);
        preserved(mss(value), true, TCP_FLAG_ACK | TCP_FLAG_PUSH);
    }
    negotiated({200, 2, 1, 1, 2, 4, 5, 180}, 1460, 4380);
    negotiated({2, 4, 5, 180, 200, 2, 1, 0}, 1460, 4380);
    negotiated({2, 4, 5, 180, 0, 2, 0, 255}, 1460, 4380);
    // Preserve the existing duplicate policy: the last parsed MSS wins.
    negotiated({2, 4, 5, 180, 2, 4, 2, 24}, 536, 2144);
    negotiated({2, 4, 2, 24, 2, 4, 5, 180}, 1460, 4380);
    negotiated({2, 4, 0, 9, 2, 4, 2, 24}, 536, 2144);
    preserved({2, 4, 5, 180, 2, 4, 0, 9}, true);
    negotiated({2, 4, 2, 24, 0, 2, 4, 255}, 536, 2144);
}
static void exhaustive() {
    // All 65,536 kind/length combinations, three endings, one executable.
    // The four-byte shape gives a closed-form acceptance oracle, not a parser.
    for (unsigned kind = 0; kind <= 255; ++kind) {
        for (unsigned length = 0; length <= 255; ++length) {
            const bool accepted = kind == 0 || (kind == 1 && length <= 1) ||
                (kind >= 2 && length >= 2 && length <= 4 && (kind != 2 || length == 4));
            for (const auto &tail : std::array<std::array<u8, 2>, 3>{{{0, 0}, {1, 0}, {1, 1}}}) {
                const std::vector<u8> bytes{static_cast<u8>(kind), static_cast<u8>(length), tail[0], tail[1]};
                CTCPConnection c;
                const auto original = values(c);
                CHECK(scan(c, bytes) == accepted);
                if (accepted && kind == 2 && length == 4 && tail[0] == 1) {
                    const unsigned value = 256 + tail[1];
                    CHECK((values(c) == std::array<u32, 4>{value, value, 4 * value, 4 * value}));
                } else {
                    CHECK(values(c) == original);
                }
            }
        }
    }
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    const std::string mode = argv[1];
    if (mode == "guard") {
        GuardPages probe;
        if (!probe.available()) { std::puts("SKIP guard pages unavailable"); return 0; }
        guarded = true;
    }
    if (mode == "boundary" || mode == "guard") boundaries();
    if (mode == "malformed" || mode == "guard") malformed();
    if (mode == "negotiation" || mode == "guard") negotiation();
    if (mode == "exhaustive") exhaustive();
    CHECK(mode == "boundary" || mode == "malformed" || mode == "negotiation" ||
          mode == "exhaustive" || mode == "guard");
    std::puts("PASS");
}
'''


def translation_unit():
    source = SOURCE.read_text(encoding="utf-8")
    header = HEADER.read_text(encoding="utf-8")
    if not re.search(r"boolean\s+ScanOptions\s*\(\s*TTCPHeader\s*\*\s*pHeader\s*\)", header):
        raise AssertionError("production header must declare boolean ScanOptions(TTCPHeader*)")
    wire = "\n".join(definition(source, "struct " + name) + "\nPACKED;"
                     for name in ("TTCPHeader", "TTCPOption"))
    network = (INCLUDE / "circle/net/networklayer.h").read_text(encoding="utf-8")
    constants = "\n".join((macro(source, "TCP_MSS_S"), macro(source, "min"),
                            macro(network, "IP_OPTION_SIZE")))
    # Copy the actual field types too, including the inherited effective MSS.
    base = (INCLUDE / "circle/net/netconnection.h").read_text(encoding="utf-8")
    fields = []
    for name, initial in (("m_nSND_MSS", 536), ("m_nMSS", 537),
                          ("m_nIW", 2144), ("m_nCWND", 8192)):
        match = re.search(r"\b(u16|u32)\s+" + name + r"\s*;", header + "\n" + base)
        if not match:
            raise AssertionError("missing production field: " + name)
        fields.append("    %s %s = %d;" % (match.group(1), name, initial))
    fake = "\nstruct CTCPConnection {\n    u32 before = 0xCAFE1234;\n"
    fake += "\n".join(fields)
    fake += "\n    u32 after = 0xCAFE1234;\n    boolean ScanOptions(TTCPHeader *);\n};\n"
    parser = definition(source, "boolean CTCPConnection::ScanOptions (")
    return PREAMBLE + wire + "\n" + constants + fake + parser + HARNESS


@unittest.skipUnless(CXX, "host g++ is not installed")
class TcpOptionsHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-tcp-options-")

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
        source = cls.root / "tcp-options.cpp"
        source.write_text(translation_unit(), encoding="utf-8")
        cls.executable = cls.root / "tcp-options.exe"
        result = subprocess.run(
            [CXX, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-idirafter",
             str(INCLUDE), str(source), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError("host g++ compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, mode):
        result = subprocess.run([str(self.executable), mode], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if result.stdout.startswith("SKIP"):
            self.skipTest(result.stdout.strip())
        self.assertIn("PASS", result.stdout)

    def test_zero_to_forty_option_bytes_final_eol_nop_and_unknown_bounds(self):
        self.run_scenario("boundary")

    def test_malformed_and_truncated_options_preserve_all_negotiated_fields(self):
        self.run_scenario("malformed")

    def test_syn_only_mss_clamp_duplicate_policy_tiny_mss_and_window_formula(self):
        self.run_scenario("negotiation")

    def test_all_256_by_256_kind_length_pairs_terminate_and_match_acceptance(self):
        self.run_scenario("exhaustive")

    def test_optional_guard_pages_prevent_reads_past_declared_header(self):
        self.run_scenario("guard")


if __name__ == "__main__":
    unittest.main()
