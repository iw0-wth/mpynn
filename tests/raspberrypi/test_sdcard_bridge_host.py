# SPDX-License-Identifier: MIT
"""Compile the real SD bridge against a host-only Circle device double."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "ports/raspberrypi/sdcard_bridge.cpp"
HEADERS = {
    "circle/logger.h": """#pragma once
#define LogError 1
class CLogger { public:
static CLogger *Get() { static CLogger logger; return &logger; }
void Write(const char *, unsigned, const char *, ...) {}
};
""",
    "SDCard/emmc.h": """#pragma once
#include <stddef.h>
#include <stdint.h>
class CEMMCDevice {
public:
    uint64_t GetSize() const;
    uint64_t Seek(uint64_t offset);
    int Read(void *buffer, size_t length);
    int Write(const void *buffer, size_t length);
};
""",
    "circle/synchronize.h": """#pragma once
#define TASK_LEVEL 0
unsigned CurrentExecutionLevel(void);
""",
}
HARNESS = r"""
#include <SDCard/emmc.h>
#include <circle/synchronize.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include "sdcard_bridge.h"
#include "sdcard_transfer.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)
static uint64_t bytes = 8 * 512, last_seek;
static unsigned level, seeks, reads, writes;
static int bad_seek, short_read, short_write, recurse;
static unsigned char disk[8 * 512];
unsigned CurrentExecutionLevel() { return level; }
uint64_t CEMMCDevice::GetSize() const { return bytes; }
uint64_t CEMMCDevice::Seek(uint64_t offset) {
    ++seeks;
    last_seek = offset;
    if (recurse) {
        CHECK(mpynn_sd_sync() == MPYNN_SD_BUSY);
        mpynn_sd_diagnostics_t snapshot;
        std::memset(&snapshot, 0xa5, sizeof(snapshot));
        mpynn_sd_diagnostics_t prior = snapshot;
        CHECK(mpynn_sd_diagnostics(&snapshot) == MPYNN_SD_BUSY);
        CHECK(std::memcmp(&snapshot, &prior, sizeof(snapshot)) == 0);
    }
    return bad_seek ? UINT64_MAX : offset;
}
int CEMMCDevice::Read(void *buf, size_t n) {
    ++reads;
    CHECK(n == 512 && last_seek + n <= sizeof(disk));
    CHECK(reinterpret_cast<uintptr_t>(buf) % 32 == 0);
    std::memcpy(buf, disk + last_seek, short_read ? 256 : n);
    return short_read ? 256 : int(n);
}
int CEMMCDevice::Write(const void *buf, size_t n) {
    ++writes;
    CHECK(n == 512 && last_seek + n <= sizeof(disk));
    CHECK(reinterpret_cast<uintptr_t>(buf) % 32 == 0);
    if (!short_write) std::memcpy(disk + last_seek, buf, n);
    return short_write ? 256 : int(n);
}
int main() {
    CEMMCDevice card;
    unsigned char input[1026], output[1026];
    std::memset(input, 0x59, sizeof(input));
    std::memset(output, 0xa5, sizeof(output));
    uint64_t count = 99;
    CHECK(!mpynn_sd_ready());
    CHECK(mpynn_sd_block_count(&count) == MPYNN_SD_NOT_READY && !count);
    CHECK(mpynn_sd_read(0, output, 512) == MPYNN_SD_NOT_READY);
    CHECK(mpynn_sd_sync() == MPYNN_SD_NOT_READY);
    mpynn_sd_attach(nullptr, 1);
    CHECK(!mpynn_sd_ready());
    mpynn_sd_attach(&card, 0);
    CHECK(!mpynn_sd_ready());
    mpynn_sd_attach(&card, 1);
    CHECK(mpynn_sd_ready());
    mpynn_sd_diagnostics_t stats;
    CHECK(mpynn_sd_diagnostics(nullptr) == MPYNN_SD_INVALID);
    CHECK(mpynn_sd_diagnostics(&stats) == MPYNN_SD_OK && stats.ready == 1);
    CHECK(stats.read_requests == 1 && stats.failures == 1 && stats.read_sectors == 0);
    CHECK(mpynn_sd_block_count(nullptr) == MPYNN_SD_INVALID);
    CHECK(mpynn_sd_block_count(&count) == MPYNN_SD_OK && count == 8);
    CHECK(mpynn_sd_write(1, input + 1, 1024) == MPYNN_SD_OK);
    CHECK(seeks == 2 && writes == 2 && last_seek == 1024);
    CHECK(mpynn_sd_read(1, output + 1, 1024) == MPYNN_SD_OK);
    CHECK(seeks == 4 && reads == 2);
    CHECK(std::memcmp(input + 1, output + 1, 1024) == 0);
    CHECK(output[0] == 0xa5 && output[1025] == 0xa5);
    CHECK(mpynn_sd_diagnostics(&stats) == MPYNN_SD_OK);
    CHECK(stats.write_requests == 1 && stats.write_sectors == 2 && stats.read_sectors == 2);
    CHECK(mpynn_sd_read(0, nullptr, 512) == MPYNN_SD_INVALID);
    CHECK(mpynn_sd_write(0, nullptr, 512) == MPYNN_SD_INVALID);
    CHECK(mpynn_sd_read(0, output, 0) == MPYNN_SD_INVALID);
    CHECK(mpynn_sd_read(0, output, 513) == MPYNN_SD_INVALID);
    const unsigned before = seeks;
    CHECK(mpynn_sd_read(8, output, 512) == MPYNN_SD_RANGE);
    CHECK(mpynn_sd_read(7, output, 1024) == MPYNN_SD_RANGE);
    CHECK(mpynn_sd_read(UINT64_MAX, output, 512) == MPYNN_SD_RANGE);
    CHECK(mpynn_sd_read(UINT32_MAX + uint64_t(1), output, 512) == MPYNN_SD_RANGE);
    CHECK(mpynn_sd_read(0, output, std::numeric_limits<size_t>::max()) == MPYNN_SD_INVALID);
    CHECK(seeks == before);
    bytes = (uint64_t(UINT32_MAX) + 2) * 512;
    CHECK(mpynn_sd_transfer_in_range(UINT32_MAX, 512, bytes / 512));
    CHECK(!mpynn_sd_transfer_in_range(UINT32_MAX, 1024, bytes / 512));
    CHECK(mpynn_sd_read(UINT32_MAX, output, 1024) == MPYNN_SD_RANGE);
    bytes = 8 * 512;
    bad_seek = 1;
    CHECK(mpynn_sd_read(0, output, 512) == MPYNN_SD_IO && reads == 2);
    CHECK(mpynn_sd_diagnostics(&stats) == MPYNN_SD_OK && stats.last_stage == 1 && stats.last_status == MPYNN_SD_IO);
    CHECK(stats.last_block == 0 && stats.last_length == 512 && stats.last_writing == 0);
    bad_seek = 0;
    short_read = 1;
    std::memset(output, 0xa5, sizeof(output));
    CHECK(mpynn_sd_read(0, output, 1024) == MPYNN_SD_IO && reads == 3);
    CHECK(output[0] == 0xa5 && output[255] == 0xa5);
    short_read = 0;
    short_write = 1;
    CHECK(mpynn_sd_write(0, input, 1024) == MPYNN_SD_IO && writes == 3);
    CHECK(mpynn_sd_diagnostics(&stats) == MPYNN_SD_OK && stats.last_stage == 2 && stats.last_writing == 1);
    CHECK(stats.last_result == 256 && stats.write_sectors == 2);
    uint64_t failed_count = stats.failures;
    short_write = 0;
    recurse = 1;
    CHECK(mpynn_sd_read(0, output, 512) == MPYNN_SD_OK);
    CHECK(mpynn_sd_diagnostics(&stats) == MPYNN_SD_OK && stats.failures == failed_count);
    CHECK(stats.last_stage == 2 && stats.last_result == 256 && stats.last_writing == 1); // sticky
    recurse = 0;
    level = 1;
    CHECK(mpynn_sd_read(0, output, 512) == MPYNN_SD_CONTEXT);
    CHECK(mpynn_sd_block_count(&count) == MPYNN_SD_CONTEXT);
    CHECK(mpynn_sd_sync() == MPYNN_SD_CONTEXT);
    mpynn_sd_diagnostics_t prior = stats;
    CHECK(mpynn_sd_diagnostics(&stats) == MPYNN_SD_CONTEXT);
    CHECK(memcmp(&stats, &prior, sizeof(stats)) == 0);
    level = 0;
    bytes = UINT64_MAX;
    CHECK(mpynn_sd_block_count(&count) == MPYNN_SD_NOT_READY && !count);
    bytes = 513;
    CHECK(mpynn_sd_read(0, output, 512) == MPYNN_SD_NOT_READY);
    bytes = 4096;
    CHECK(mpynn_sd_sync() == MPYNN_SD_OK);
    std::puts("PASS");
}
"""


class SDCardBridgeHostTests(unittest.TestCase):
    def test_real_bridge_against_fake_circle(self):
        compiler = next((candidate for candidate in (
            shutil.which("g++"), "E:/msys64/ucrt64/bin/g++.exe"
        ) if candidate and Path(candidate).is_file()), None)
        if compiler is None:
            self.skipTest("host C++ compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="mpynn-sdcard-host-") as directory:
            root = Path(directory)
            for name, content in HEADERS.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            harness = root / "harness.cpp"
            harness.write_text(HARNESS, encoding="utf-8")
            executable = root / "sdcard-host.exe"
            env = dict(os.environ)
            env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
            env["TMP"] = env["TEMP"] = env["TMPDIR"] = directory
            compile_result = subprocess.run(
                [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(root),
                 "-I", str(SOURCE.parent), str(SOURCE), str(harness), "-o", str(executable)],
                cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            result = subprocess.run([str(executable)], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "PASS")


if __name__ == "__main__":
    unittest.main()
