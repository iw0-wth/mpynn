# SPDX-License-Identifier: MIT
"""Host contracts for the unmodified Raspberry Pi machine_bridge.cpp.

Run: python -B -m unittest discover -s mpynn/tests/raspberrypi -p test_machine_bridge_host.py -v
Fake Circle headers, a separate C++ harness, binaries and diagnostics live only
in TemporaryDirectory. No firmware build or build output is used. This tests
bridge logic, not real mailbox hardware, Circle integration, ARM ABI or reboot.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2] / "ports/raspberrypi/machine_bridge.cpp"
GXX = Path("E:/msys64/ucrt64/bin/g++.exe")
REBOOT_EXIT_CODE = 73
HEADERS = {
    "circle/bcmpropertytags.h": r"""#pragma once
#include <stdint.h>
#define PROPTAG_GET_BOARD_SERIAL 0x00010004
#define PROPTAG_GET_CLOCK_RATE 0x00030002
#define PROPTAG_GET_CLOCK_RATE_MEASURED 0x00030047
#define CLOCK_ID_ARM 3
struct __attribute__((packed)) TPropertyTag {
    uint32_t nTagId, nValueBufSize, nValueLength;
};
struct __attribute__((packed)) TPropertyTagSerial {
    TPropertyTag Tag;
    uint32_t Serial[2];
};
struct __attribute__((packed)) TPropertyTagClockRate {
    TPropertyTag Tag;
    uint32_t nClockId, nRate;
};
class CBcmPropertyTags {
public:
    bool GetTag(uint32_t id, void *tag, unsigned size, unsigned request_size = 0);
};
""",
    "circle/machineinfo.h": r"""#pragma once
#include <stdint.h>
class CMachineInfo {
public:
    static CMachineInfo *Get();
    uint32_t GetRevisionRaw() const;
    unsigned GetRAMSize() const;
    const char *GetMachineName() const;
    unsigned GetClockRate(uint32_t id) const;
};
""",
    "circle/startup.h": "#pragma once\nvoid reboot(void);\n",
}

HARNESS = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <circle/bcmpropertytags.h>
#include <circle/machineinfo.h>
#include <circle/startup.h>
#include "machine_bridge.h"

#ifdef NDEBUG
#error Host tests must not disable production assertions
#endif
#define CHECK(expr) do { if (!(expr)) { \
    std::fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #expr); \
    std::exit(1); \
} } while (0)

static_assert(sizeof(TPropertyTagSerial) == 20, "serial tag layout");
static_assert(sizeof(TPropertyTagClockRate) == 20, "clock tag layout");
static bool serial_ok;
static uint32_t serial_low, serial_high;
static unsigned serial_calls, clock_calls, machine_calls;
struct Reply { uint32_t id; bool ok; uint32_t rate; };
static Reply replies[2];
static unsigned reply_count;
static uint32_t revision_value;
static unsigned ram_value;
static const char *name_value;
static unsigned revision_calls, ram_calls, name_calls;

bool CBcmPropertyTags::GetTag(uint32_t id, void *raw, unsigned size,
                              unsigned request_size) {
    CHECK(raw != nullptr);
    if (id == PROPTAG_GET_BOARD_SERIAL) {
        CHECK(reply_count == 0 && serial_calls == 0);
        ++serial_calls;
        CHECK(size == sizeof(TPropertyTagSerial));
        CHECK(request_size == 0);
        auto *tag = static_cast<TPropertyTagSerial *>(raw);
        CHECK(tag->Serial[0] == 0 && tag->Serial[1] == 0);
        // Even a failed mailbox transaction may dirty its temporary tag.
        tag->Serial[0] = serial_low;
        tag->Serial[1] = serial_high;
        return serial_ok;
    }
    CHECK(serial_calls == 0);
    CHECK(clock_calls < reply_count);
    const Reply reply = replies[clock_calls++];
    CHECK(id == reply.id);
    CHECK(size == sizeof(TPropertyTagClockRate));
    CHECK(request_size == 4);
    auto *tag = static_cast<TPropertyTagClockRate *>(raw);
    CHECK(tag->nClockId == CLOCK_ID_ARM);
    CHECK(tag->nRate == 0);
    CHECK(tag->Tag.nTagId == 0 && tag->Tag.nValueBufSize == 0
          && tag->Tag.nValueLength == 0);
    // Poison the complete response so fallback must initialize a fresh request.
    tag->Tag.nTagId = 0xdeadbeef;
    tag->Tag.nValueBufSize = 0xffffffff;
    tag->Tag.nValueLength = 0xffffffff;
    tag->nClockId = 0xffffffff;
    tag->nRate = reply.rate;
    return reply.ok;
}

CMachineInfo *CMachineInfo::Get() {
    static CMachineInfo info;
    ++machine_calls;
    return &info;
}
uint32_t CMachineInfo::GetRevisionRaw() const {
    ++revision_calls;
    return revision_value;
}
unsigned CMachineInfo::GetRAMSize() const {
    ++ram_calls;
    return ram_value;
}
const char *CMachineInfo::GetMachineName() const {
    ++name_calls;
    return name_value;
}
unsigned CMachineInfo::GetClockRate(uint32_t) const {
    // Circle's generic helper can assert; this bridge must never call it.
    std::fputs("forbidden generic GetClockRate helper called\n", stderr);
    std::exit(2);
}
void reboot(void) {
    // Host-only stub: never invoke an OS or hardware reset.
    std::exit(73);
}

static void serial_case(bool ok, uint32_t low, uint32_t high,
                        const unsigned char expected[8]) {
    serial_ok = ok;
    serial_low = low;
    serial_high = high;
    unsigned char buffer[24], original[24];
    std::memset(buffer, 0xa5, sizeof(buffer));
    std::memcpy(original, buffer, sizeof(buffer));
    const int status = mpynn_machine_serial(buffer + 8);
    CHECK(status == (ok ? 0 : -1));
    CHECK(serial_calls == 1 && clock_calls == 0 && machine_calls == 0);
    if (ok) {
        // Literal expectations do not duplicate the production shift algorithm.
        CHECK(std::memcmp(buffer + 8, expected, 8) == 0);
        CHECK(std::memcmp(buffer, original, 8) == 0);
        CHECK(std::memcmp(buffer + 16, original + 16, 8) == 0);
    } else {
        CHECK(std::memcmp(buffer, original, sizeof(buffer)) == 0);
    }
}
static void frequency_case(bool measured_ok, uint32_t measured_rate,
                           bool fallback_ok, uint32_t fallback_rate,
                           uint32_t expected, unsigned expected_calls) {
    replies[0] = {PROPTAG_GET_CLOCK_RATE_MEASURED, measured_ok, measured_rate};
    replies[1] = {PROPTAG_GET_CLOCK_RATE, fallback_ok, fallback_rate};
    reply_count = expected_calls;
    CHECK(mpynn_machine_frequency() == expected);
    CHECK(clock_calls == expected_calls);
    CHECK(serial_calls == 0 && machine_calls == 0);
}
static void board_info_case() {
    revision_value = 0x80a020d3u;
    ram_value = 8192;
    name_value = "stub Raspberry Pi board";
    CHECK(mpynn_machine_revision() == revision_value);
    CHECK(mpynn_machine_ram_mb() == ram_value);
    CHECK(mpynn_machine_name() == name_value);
    CHECK(std::strcmp(mpynn_machine_name(), "stub Raspberry Pi board") == 0);
    CHECK(revision_calls == 1 && ram_calls == 1 && name_calls == 2);
    CHECK(machine_calls == 4);
    // Change the stubs to detect hard-coded results and unintended caching.
    revision_value = 0;
    ram_value = 0;
    name_value = "second stub";
    CHECK(mpynn_machine_revision() == 0);
    CHECK(mpynn_machine_ram_mb() == 0);
    CHECK(mpynn_machine_name() == name_value);
    CHECK(revision_calls == 2 && ram_calls == 2 && name_calls == 3);
    CHECK(machine_calls == 7 && serial_calls == 0 && clock_calls == 0);
}
int main(int argc, char **argv) {
    CHECK(argc >= 2);
    if (!std::strcmp(argv[1], "serial_layout")) {
        const unsigned char expected[8] = {0x89, 0xab, 0xcd, 0xef, 0x01, 0x23, 0x45, 0x67};
        serial_case(true, 0x01234567u, 0x89abcdefu, expected);
    } else if (!std::strcmp(argv[1], "serial_zero")) {
        const unsigned char expected[8] = {};
        serial_case(true, 0, 0, expected);
    } else if (!std::strcmp(argv[1], "serial_failure")) {
        serial_case(false, 0x01234567u, 0x89abcdefu, nullptr);
    } else if (!std::strcmp(argv[1], "frequency")) {
        CHECK(argc == 8);
        frequency_case(std::strtoul(argv[2], nullptr, 10) != 0,
                       static_cast<uint32_t>(std::strtoul(argv[3], nullptr, 10)),
                       std::strtoul(argv[4], nullptr, 10) != 0,
                       static_cast<uint32_t>(std::strtoul(argv[5], nullptr, 10)),
                       static_cast<uint32_t>(std::strtoul(argv[6], nullptr, 10)),
                       static_cast<unsigned>(std::strtoul(argv[7], nullptr, 10)));
    } else if (!std::strcmp(argv[1], "board_info")) {
        board_info_case();
    } else if (!std::strcmp(argv[1], "reset")) {
        mpynn_machine_reset();
    } else {
        CHECK(false);
    }
    std::puts("PASS");
    return 0;
}
'''


class MachineBridgeHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GXX.is_file():
            raise unittest.SkipTest(f"host C++ compiler not found: {GXX}")
        cls.temp = tempfile.TemporaryDirectory(prefix="mpynn-machine-host-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        for name, content in HEADERS.items():
            header = cls.root / name
            header.parent.mkdir(parents=True, exist_ok=True)
            header.write_text(content, encoding="utf-8")
        harness = cls.root / "harness.cpp"
        harness.write_text(HARNESS, encoding="utf-8")
        cls.executable = cls.root / "machine-host.exe"
        cls.environment = dict(os.environ)
        cls.environment["PATH"] = str(GXX.parent) + os.pathsep + os.environ.get("PATH", "")
        cls.environment["TMP"] = cls.environment["TEMP"] = cls.environment["TMPDIR"] = str(cls.root)
        # Pass the real source as a separate translation unit; never copy,
        # rewrite or include the production .cpp in the harness.
        cls.run_process("compile", [str(GXX), "-std=c++11", "-Wall", "-Wextra", "-Werror",
                                    "-UNDEBUG", "-I", str(cls.root), "-I", str(SOURCE.parent),
                                    str(SOURCE), str(harness), "-o", str(cls.executable)])

    @classmethod
    def run_process(cls, name, command, expected_returncode=0):
        stdout_path = cls.root / (name + ".stdout.txt")
        stderr_path = cls.root / (name + ".stderr.txt")
        error = None
        result = None
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            try:
                result = subprocess.run(command, cwd=cls.root, env=cls.environment,
                                        stdout=stdout, stderr=stderr, timeout=30, check=False)
            except (subprocess.TimeoutExpired, OSError) as exc:
                error = exc
        out = stdout_path.read_text(encoding="utf-8", errors="replace")
        err = stderr_path.read_text(encoding="utf-8", errors="replace")
        diagnostics = f"command: {command!r}\nstdout:\n{out}\nstderr:\n{err}"
        if error is not None:
            raise AssertionError(f"host process failed: {error}\n{diagnostics}") from error
        if result.returncode != expected_returncode:
            raise AssertionError(f"host process returned {result.returncode}, expected "
                                 f"{expected_returncode}\n{diagnostics}")
        return out

    def run_case(self, name, *args):
        command = [str(self.executable), name, *(str(arg) for arg in args)]
        self.assertEqual(self.run_process(name, command).strip(), "PASS")

    def test_serial_exactly_eight_bytes_high_word_then_low_word_big_endian(self):
        self.run_case("serial_layout")

    def test_serial_zero_is_success_and_writes_all_eight_bytes(self):
        self.run_case("serial_zero")

    def test_serial_mailbox_failure_leaves_output_and_guards_unchanged(self):
        self.run_case("serial_failure")

    def test_frequency_prefers_measured_and_does_not_query_fallback(self):
        self.run_case("frequency", 1, 1234567890, 1, 987654321, 1234567890, 1)

    def test_frequency_zero_measured_falls_back(self):
        self.run_case("frequency", 1, 0, 1, 987654321, 987654321, 2)

    def test_frequency_failed_measured_ignores_dirty_value_and_falls_back(self):
        self.run_case("frequency", 0, 1234567890, 1, 987654321, 987654321, 2)

    def test_frequency_both_mailbox_failures_return_zero_without_assert(self):
        self.run_case("frequency", 0, 1234567890, 0, 987654321, 0, 2)

    def test_frequency_success_failure_and_zero_rate_matrix(self):
        for measured_ok in (0, 1):
            for measured_rate in (0, 0xffffffff):
                for fallback_ok in (0, 1):
                    for fallback_rate in (0, 0x87654321):
                        with self.subTest(measured_ok=measured_ok, measured_rate=measured_rate,
                                          fallback_ok=fallback_ok, fallback_rate=fallback_rate):
                            if measured_ok and measured_rate:
                                expected, calls = measured_rate, 1
                            else:
                                expected, calls = fallback_rate if fallback_ok else 0, 2
                            self.run_case("frequency", measured_ok, measured_rate,
                                          fallback_ok, fallback_rate, expected, calls)

    def test_board_info_getters_return_current_stub_values(self):
        self.run_case("board_info")

    def test_reset_calls_only_fake_reboot_in_child_process(self):
        output = self.run_process("reset", [str(self.executable), "reset"], REBOOT_EXIT_CODE)
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
