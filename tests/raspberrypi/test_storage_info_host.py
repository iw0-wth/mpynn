# SPDX-License-Identifier: MIT
"""Compile the actual storage_info.c against a tiny host VM and SD double.

The fake VM records dictionary keys and boxed signed/unsigned integer values.
It deliberately uses 32-bit mp_int_t/mp_uint_t to catch accidental narrowing of
64-bit counters on the Pi1. This does not model real MicroPython GC/long-int
internals, test the bridge's counter accounting, or access storage/hardware.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

PORT = Path(__file__).resolve().parents[2] / "ports/raspberrypi"

RUNTIME = r"""
#pragma once
#include <stddef.h>
#include <stdint.h>
typedef uintptr_t mp_obj_t;
/* Model the port's integer widths even when host pointers are 64-bit. */
typedef int32_t mp_int_t;
typedef uint32_t mp_uint_t;
enum {
    MP_QSTR_read_requests = 1, MP_QSTR_write_requests,
    MP_QSTR_read_sectors, MP_QSTR_write_sectors, MP_QSTR_failures,
    MP_QSTR_last_block, MP_QSTR_last_length, MP_QSTR_last_status,
    MP_QSTR_last_result, MP_QSTR_last_writing, MP_QSTR_last_stage,
    MP_QSTR_ready
};
#define MP_OBJ_NEW_QSTR(q) ((mp_obj_t)(q))
#define MP_DEFINE_CONST_FUN_OBJ_0(name, fn) \
    const struct { mp_obj_t (*fun)(void); } name = {fn}
mp_obj_t mp_obj_new_dict(size_t capacity);
void mp_obj_dict_store(mp_obj_t dict, mp_obj_t key, mp_obj_t value);
mp_obj_t mp_obj_new_int(mp_int_t value);
mp_obj_t mp_obj_new_int_from_uint(mp_uint_t value);
mp_obj_t mp_obj_new_int_from_ull(unsigned long long value);
_Noreturn void mp_raise_OSError(int error);
"""

HARNESS = r"""
#include <limits.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Include the entire production source unchanged, including its fun object. */
#include "storage_info.c"
#define CHECK(c) do { if (!(c)) { \
    fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); \
} } while (0)
#define FIELD_COUNT 12

typedef struct {
    int negative;
    uint64_t magnitude;
} host_integer_t;
typedef struct {
    size_t count;
    unsigned keys[FIELD_COUNT];
    host_integer_t *values[FIELD_COUNT];
} host_dict_t;
static host_dict_t dictionary;
static host_integer_t integers[FIELD_COUNT];
static unsigned dictionary_calls, integer_calls, store_calls, snapshot_calls;
static int snapshot_status, raised_errno, expecting_exception, mutate_after_snapshot;
static jmp_buf exception;
static mpynn_sd_diagnostics_t bridge_state;

int mpynn_sd_diagnostics(mpynn_sd_diagnostics_t *out) {
    ++snapshot_calls;
    CHECK(out != NULL);
    if (snapshot_status != 0) return snapshot_status; /* Leave out untouched. */
    *out = bridge_state;
    return MPYNN_SD_OK;
}
/* Other bridge functions are intentionally not defined. Any storage I/O,
   readiness probe, sync or block-count call fails the host link. */
mp_obj_t mp_obj_new_dict(size_t capacity) {
    CHECK(snapshot_calls == 1 && snapshot_status == MPYNN_SD_OK);
    CHECK(capacity >= FIELD_COUNT);
    ++dictionary_calls;
    CHECK(dictionary_calls == 1);
    if (mutate_after_snapshot) memset(&bridge_state, 0, sizeof bridge_state);
    return (mp_obj_t)(uintptr_t)&dictionary;
}
static mp_obj_t box(int negative, uint64_t magnitude) {
    CHECK(integer_calls < FIELD_COUNT);
    host_integer_t *value = &integers[integer_calls++];
    value->negative = negative;
    value->magnitude = magnitude;
    return (mp_obj_t)(uintptr_t)value;
}
mp_obj_t mp_obj_new_int(mp_int_t value) {
    return box(value < 0, value < 0 ? (uint64_t)(-(int64_t)value) : (uint64_t)value);
}
mp_obj_t mp_obj_new_int_from_uint(mp_uint_t value) { return box(0, value); }
mp_obj_t mp_obj_new_int_from_ull(unsigned long long value) { return box(0, value); }
void mp_obj_dict_store(mp_obj_t dict, mp_obj_t key, mp_obj_t value) {
    CHECK(dict == (mp_obj_t)(uintptr_t)&dictionary);
    CHECK(key >= MP_QSTR_read_requests && key <= MP_QSTR_ready);
    CHECK(dictionary.count < FIELD_COUNT);
    for (size_t i = 0; i < dictionary.count; ++i) CHECK(dictionary.keys[i] != key);
    size_t index = dictionary.count++;
    dictionary.keys[index] = (unsigned)key;
    dictionary.values[index] = (host_integer_t *)(uintptr_t)value;
    ++store_calls;
}
_Noreturn void mp_raise_OSError(int error) {
    CHECK(expecting_exception);
    raised_errno = error;
    longjmp(exception, 1);
}
static void reset(void) {
    memset(&dictionary, 0, sizeof dictionary);
    memset(integers, 0, sizeof integers);
    memset(&bridge_state, 0, sizeof bridge_state);
    dictionary_calls = integer_calls = store_calls = snapshot_calls = 0;
    snapshot_status = raised_errno = expecting_exception = mutate_after_snapshot = 0;
}
static void expect_value(unsigned key, int negative, uint64_t magnitude) {
    for (size_t i = 0; i < dictionary.count; ++i) {
        if (dictionary.keys[i] == key) {
            CHECK(dictionary.values[i]->negative == negative);
            CHECK(dictionary.values[i]->magnitude == magnitude);
            return;
        }
    }
    CHECK(!"missing dictionary field");
}
static void expect_snapshot(const mpynn_sd_diagnostics_t *expected) {
    /* Call through the real zero-argument function object. */
    mp_obj_t result = mpynn_storage_info_obj.fun();
    CHECK(result == (mp_obj_t)(uintptr_t)&dictionary);
    CHECK(snapshot_calls == 1 && dictionary_calls == 1);
    CHECK(dictionary.count == FIELD_COUNT);
    CHECK(integer_calls == FIELD_COUNT && store_calls == FIELD_COUNT);
    expect_value(MP_QSTR_read_requests, 0, expected->read_requests);
    expect_value(MP_QSTR_write_requests, 0, expected->write_requests);
    expect_value(MP_QSTR_read_sectors, 0, expected->read_sectors);
    expect_value(MP_QSTR_write_sectors, 0, expected->write_sectors);
    expect_value(MP_QSTR_failures, 0, expected->failures);
    expect_value(MP_QSTR_last_block, 0, expected->last_block);
    expect_value(MP_QSTR_last_length, 0, expected->last_length);
    expect_value(MP_QSTR_last_status, expected->last_status < 0,
        expected->last_status < 0 ? (uint64_t)(-(int64_t)expected->last_status) : (uint64_t)expected->last_status);
    expect_value(MP_QSTR_last_result, expected->last_result < 0,
        expected->last_result < 0 ? (uint64_t)(-(int64_t)expected->last_result) : (uint64_t)expected->last_result);
    expect_value(MP_QSTR_last_writing, 0, expected->last_writing);
    expect_value(MP_QSTR_last_stage, 0, expected->last_stage);
    expect_value(MP_QSTR_ready, 0, expected->ready);
}
static void test_wide(void) {
    reset();
    bridge_state.read_requests = UINT64_C(0x100000001);
    bridge_state.write_requests = UINT64_C(0x200000002);
    bridge_state.read_sectors = UINT64_C(0x8000000000000003);
    bridge_state.write_sectors = UINT64_MAX - 1;
    bridge_state.failures = UINT64_C(0x400000005);
    bridge_state.last_block = UINT64_MAX;
    bridge_state.last_length = SIZE_MAX;
    bridge_state.last_status = MPYNN_SD_IO;
    bridge_state.last_result = INT_MIN;
    bridge_state.last_writing = 1;
    bridge_state.last_stage = 2;
    bridge_state.ready = 1;
    mpynn_sd_diagnostics_t before = bridge_state;
    expect_snapshot(&before);
    CHECK(memcmp(&before, &bridge_state, sizeof before) == 0);
}
static void test_stages(void) {
    for (unsigned stage = 0; stage <= 2; ++stage) {
        reset();
        bridge_state.last_stage = stage;
        bridge_state.last_status = stage == 0 ? MPYNN_SD_INVALID : MPYNN_SD_IO;
        bridge_state.last_result = stage == 2 ? 511 : 0;
        bridge_state.last_writing = stage == 1;
        bridge_state.ready = 1;
        mpynn_sd_diagnostics_t before = bridge_state;
        /* Allocation may allow bridge state to change, but all values must
           come from the single already-copied snapshot. */
        mutate_after_snapshot = 1;
        expect_snapshot(&before);
    }
}
static void test_unready(void) {
    reset();
    mpynn_sd_diagnostics_t before = bridge_state;
    expect_snapshot(&before); /* ready == 0 is data, not an exception. */
}
static void test_failure(void) {
    /* Every positive nonzero enum, plus an unexpected negative return. */
    static const int failures[] = {
        MPYNN_SD_NOT_READY, MPYNN_SD_INVALID, MPYNN_SD_RANGE,
        MPYNN_SD_IO, MPYNN_SD_BUSY, MPYNN_SD_CONTEXT, -1
    };
    for (size_t i = 0; i < sizeof failures / sizeof failures[0]; ++i) {
        reset();
        snapshot_status = failures[i];
        expecting_exception = 1;
        if (setjmp(exception) == 0) {
            (void)mpynn_storage_info_obj.fun();
            CHECK(!"expected OSError");
        }
        CHECK(raised_errno == MP_EBUSY && snapshot_calls == 1);
        CHECK(dictionary_calls == 0 && integer_calls == 0 && store_calls == 0);
    }
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    if (!strcmp(argv[1], "wide")) test_wide();
    else if (!strcmp(argv[1], "stages")) test_stages();
    else if (!strcmp(argv[1], "unready")) test_unready();
    else if (!strcmp(argv[1], "failure")) test_failure();
    else CHECK(!"unknown scenario");
    puts("PASS");
    return 0;
}
"""


class StorageInfoHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = next((candidate for candidate in (
            "E:/msys64/ucrt64/bin/gcc.exe", shutil.which("gcc")
        ) if candidate and Path(candidate).is_file()), None)
        if compiler is None:
            raise unittest.SkipTest("host GCC unavailable")
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-storage-info-")

        def cleanup():
            # Windows may briefly keep the just-exited executable open.
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
        (cls.root / "py").mkdir()
        (cls.root / "py/runtime.h").write_text(RUNTIME, encoding="utf-8")
        (cls.root / "py/mperrno.h").write_text(
            "#pragma once\n#define MP_EBUSY 16\n", encoding="utf-8")
        harness = cls.root / "harness.c"
        harness.write_text(HARNESS, encoding="utf-8")
        cls.executable = cls.root / "storage-info-host.exe"
        cls.env = dict(os.environ)
        cls.env["PATH"] = str(Path(compiler).parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(cls.root),
             # Keep the port's setjmp.h out of the host system include path.
             "-iquote", str(PORT), str(harness), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host GCC compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, name):
        result = subprocess.run([str(self.executable), name], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_all_fields_and_untruncated_unsigned_64bit_integers(self):
        self.run_scenario("wide")

    def test_sticky_failure_stage_values_and_single_snapshot(self):
        self.run_scenario("stages")

    def test_unready_zero_snapshot_is_still_a_dictionary(self):
        self.run_scenario("unready")

    def test_nonzero_snapshot_raises_ebusy_before_any_dictionary_or_integer(self):
        self.run_scenario("failure")


if __name__ == "__main__":
    unittest.main()
