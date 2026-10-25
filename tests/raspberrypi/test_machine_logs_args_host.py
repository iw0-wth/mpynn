# SPDX-License-Identifier: MIT
"""Host contracts for real machine.logs and MicroPython argument parsing.

Run: python -B -m unittest discover -s mpynn/tests/raspberrypi -p test_machine_logs_args_host.py -v

Compile the complete, unchanged py/argcheck.c as a separate translation unit.
Extract require_irqs(), mpynn_logs() and its FUN_OBJ_KW registration verbatim,
plus the real argument types/flags, repr-A tags and registration macros. Only
map lookup, primitive objects, exceptions, vstr/bytes and the log bridge are
host doubles. The harness checks the actual registered signature and calls its
kw pointer after real mp_arg_check_num_sig(); it does not run objfun.c dispatch,
VM/GC, ARM IRQ instructions or the real Circle ring. Peek/consume assertions
check binding routing against a deterministic retained-buffer bridge double.
All generated source, executables and diagnostics live in TemporaryDirectory.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "ports/raspberrypi"
UPSTREAM = ROOT / "lib/micropython"
GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")


def _extract(source, pattern):
    match = re.search(pattern, source, re.M | re.S)
    if match is None:
        raise AssertionError(f"real source fragment not found: {pattern}")
    return match.group() + "\n"


def _macro(source, name):
    lines = source.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if re.match(r"^#define " + re.escape(name) + r"(?:\(|\s)", line):
            end = index + 1
            while lines[end - 1].rstrip().endswith("\\"):
                end += 1
            return "".join(lines[index:end])
    raise AssertionError(f"real macro not found: {name}")


RUNTIME = r'''
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef uintptr_t mp_obj_t;
typedef mp_obj_t mp_const_obj_t;
typedef mp_obj_t mp_rom_obj_t;
typedef intptr_t mp_int_t;
typedef uintptr_t mp_uint_t;
typedef struct { unsigned kind; } mp_obj_type_t;
typedef struct { const mp_obj_type_t *type; } mp_obj_base_t;
typedef struct { mp_obj_t key, value; } mp_map_elem_t;
typedef struct { size_t used; mp_map_elem_t *table; } mp_map_t;
typedef struct { size_t alloc, len; char *buf; } vstr_t;
enum { MP_QSTR_clear = 1, MP_QSTR_limit, MP_QSTR_unknown };
enum { MP_MAP_LOOKUP = 0 };
#define MP_NORETURN _Noreturn
#define MP_ERROR_TEXT(text) (text)
#define MP_ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define MICROPY_ERROR_REPORTING_TERSE 1
#define MICROPY_ERROR_REPORTING 2
#define MICROPY_CPYTHON_COMPAT 0
extern const mp_obj_type_t mp_type_TypeError, mp_type_fun_builtin_var;
/* REAL_DECLARATIONS */
MP_NORETURN void mp_raise_TypeError(const char *text);
MP_NORETURN void mp_raise_ValueError(const char *text);
MP_NORETURN void mp_raise_OSError(int error);
MP_NORETURN void mp_raise_msg_varg(const mp_obj_type_t *type, const char *text, ...);
MP_NORETURN void mp_arg_error_terse_mismatch(void);
mp_map_elem_t *mp_map_lookup(mp_map_t *map, mp_obj_t key, int kind);
void mp_map_init_fixed_table(mp_map_t *map, size_t count, const mp_obj_t *table);
bool mp_obj_is_true(mp_obj_t obj);
mp_int_t mp_obj_get_int(mp_obj_t obj);
void mp_arg_check_num_sig(size_t n_args, size_t n_kw, uint32_t sig);
void mp_arg_parse_all(size_t n_pos, const mp_obj_t *pos, mp_map_t *kws,
    size_t n_allowed, const mp_arg_t *allowed, mp_arg_val_t *out_vals);
void vstr_init_len(vstr_t *buffer, size_t length);
mp_obj_t mp_obj_new_bytes_from_vstr(vstr_t *buffer);
int mpynn_irq_is_enabled(void);
'''

HARNESS = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "py/runtime.h"
#include "py/mperrno.h"
#include "circle_bridge.h"
#include "logs_fragment.h"
#ifdef NDEBUG
#error Host checks require assertions
#endif
#define CHECK(expr) do { if (!(expr)) { \
    fprintf(stderr, "%d: %s\n", __LINE__, #expr); exit(1); \
} } while (0)
#define INT(n) MP_OBJ_NEW_SMALL_INT(n)
#define QSTR(n) MP_OBJ_NEW_QSTR(MP_QSTR_##n)
const mp_obj_type_t mp_type_TypeError = {1}, mp_type_fun_builtin_var = {2};
static const mp_obj_type_t bool_type = {3}, string_type = {4}, bytes_type = {5};
static const struct { mp_obj_base_t base; bool value; } false_obj = {{&bool_type}, false},
    true_obj = {{&bool_type}, true};
static const mp_obj_base_t nonint_obj = {&string_type};
#define FALSE_OBJ ((mp_obj_t)(uintptr_t)&false_obj)
#define TRUE_OBJ ((mp_obj_t)(uintptr_t)&true_obj)
#define NONINT_OBJ ((mp_obj_t)(uintptr_t)&nonint_obj)
static struct { mp_obj_base_t base; size_t len; unsigned char data[16384]; } result;
static unsigned char retained[16384];
static size_t retained_len, expected_limit;
static bool expected_clear;
static int irq = 1, error_kind, error_errno;
static unsigned bridge_calls, allocations, byte_objects;
static const char *error_text;
static jmp_buf exception;

MP_NORETURN void mp_raise_TypeError(const char *text) {
    error_kind = 1; error_text = text; longjmp(exception, 1);
}
MP_NORETURN void mp_raise_ValueError(const char *text) {
    error_kind = 2; error_text = text; longjmp(exception, 1);
}
MP_NORETURN void mp_raise_OSError(int error) {
    error_kind = 3; error_errno = error; longjmp(exception, 1);
}
MP_NORETURN void mp_raise_msg_varg(const mp_obj_type_t *type, const char *text, ...) {
    CHECK(type == &mp_type_TypeError); mp_raise_TypeError(text);
}
mp_map_elem_t *mp_map_lookup(mp_map_t *map, mp_obj_t key, int kind) {
    CHECK(kind == MP_MAP_LOOKUP);
    for (size_t i = 0; i < map->used; ++i) {
        if (map->table[i].key == key) return &map->table[i];
    }
    return NULL;
}
void mp_map_init_fixed_table(mp_map_t *map, size_t count, const mp_obj_t *table) {
    map->used = count; map->table = (mp_map_elem_t *)(void *)table;
}
mp_int_t mp_obj_get_int(mp_obj_t obj) {
    if (mp_obj_is_small_int(obj)) return MP_OBJ_SMALL_INT_VALUE(obj);
    if (obj == FALSE_OBJ) return 0;
    if (obj == TRUE_OBJ) return 1;
    mp_raise_TypeError("expected int");
}
bool mp_obj_is_true(mp_obj_t obj) {
    if (obj == FALSE_OBJ) return false;
    if (obj == TRUE_OBJ) return true;
    if (mp_obj_is_small_int(obj)) return MP_OBJ_SMALL_INT_VALUE(obj) != 0;
    CHECK(obj == NONINT_OBJ); return true;
}
int mpynn_irq_is_enabled(void) { return irq; }
void vstr_init_len(vstr_t *buffer, size_t length) {
    CHECK(length == expected_limit && length >= 1 && length <= 16384);
    ++allocations; buffer->alloc = length; buffer->len = length;
    buffer->buf = malloc(length + 16); CHECK(buffer->buf);
    memset(buffer->buf, 0xa5, length + 16);
}
size_t mpynn_log_read_ex(char *buffer, size_t length, int clear) {
    CHECK(irq && buffer && length == expected_limit && clear == expected_clear);
    ++bridge_calls;
    size_t count = retained_len < length ? retained_len : length;
    memcpy(buffer, retained, count);
    if (clear) {
        memmove(retained, retained + count, retained_len - count);
        retained_len -= count;
    }
    return count;
}
mp_obj_t mp_obj_new_bytes_from_vstr(vstr_t *buffer) {
    CHECK(buffer->len <= buffer->alloc && buffer->alloc == expected_limit);
    for (size_t i = buffer->alloc; i < buffer->alloc + 16; ++i)
        CHECK((unsigned char)buffer->buf[i] == 0xa5);
    ++byte_objects; result.base.type = &bytes_type; result.len = buffer->len;
    memcpy(result.data, buffer->buf, buffer->len); free(buffer->buf);
    buffer->buf = NULL;
    return (mp_obj_t)(uintptr_t)&result;
}
static mp_obj_t invoke(size_t n_pos, const mp_obj_t *pos, mp_map_t *kw) {
    CHECK(mpynn_logs_obj.base.type == &mp_type_fun_builtin_var);
    CHECK(mpynn_logs_obj.sig == MP_OBJ_FUN_MAKE_SIG(0, MP_OBJ_FUN_ARGS_MAX, true));
    CHECK(mpynn_logs_obj.fun.kw == mpynn_logs);
    mp_arg_check_num_sig(n_pos, kw->used, mpynn_logs_obj.sig);
    return mpynn_logs_obj.fun.kw(n_pos, pos, kw);
}
static void seed(size_t length) {
    retained_len = length;
    for (size_t i = 0; i < length; ++i) retained[i] = (unsigned char)i;
}
static void check_bytes(mp_obj_t obj, size_t length, unsigned offset) {
    CHECK(obj == (mp_obj_t)(uintptr_t)&result && result.base.type == &bytes_type);
    CHECK(result.len == length);
    for (size_t i = 0; i < length; ++i) CHECK(result.data[i] == (unsigned char)(i + offset));
    CHECK(bridge_calls == allocations && allocations == byte_objects);
}
#define EXPECT_ERROR(kind, err, expression) do { \
    unsigned old_calls = bridge_calls, old_allocs = allocations, old_bytes = byte_objects; \
    size_t old_len = retained_len; \
    error_kind = 0; error_errno = 0; error_text = NULL; \
    if (setjmp(exception) == 0) { (void)(expression); CHECK(false); } \
    CHECK(error_kind == (kind) && error_errno == (err)); \
    CHECK(bridge_calls == old_calls && allocations == old_allocs && byte_objects == old_bytes); \
    CHECK(retained_len == old_len); \
} while (0)
int main(int argc, char **argv) {
    CHECK(argc == 2);
    mp_map_t empty = {0, NULL};
    expected_limit = 16384; expected_clear = false;
    seed(1100);
    if (!strcmp(argv[1], "default")) {
        for (unsigned i = 0; i < 3; ++i) {
            check_bytes(invoke(0, NULL, &empty), 1100, 0);
            CHECK(retained_len == 1100 && bridge_calls == i + 1);
        }
        // Full-ring repeated inspection must not retain only the first 1KiB.
        seed(16383);
        check_bytes(invoke(0, NULL, &empty), 16383, 0);
        check_bytes(invoke(0, NULL, &empty), 16383, 0);
        CHECK(retained_len == 16383);
        mp_map_elem_t field = {QSTR(clear), TRUE_OBJ};
        mp_map_t consume = {1, &field}; expected_clear = true;
        check_bytes(invoke(0, NULL, &consume), 16383, 0);
        CHECK(retained_len == 0);
        expected_clear = false;
        check_bytes(invoke(0, NULL, &empty), 0, 0);
    } else if (!strcmp(argv[1], "peek")) {
        mp_map_elem_t fields[] = {{QSTR(clear), FALSE_OBJ}, {QSTR(limit), INT(1024)}};
        mp_map_t kw = {2, fields}; expected_limit = 1024;
        for (unsigned i = 0; i < 3; ++i) {
            check_bytes(invoke(0, NULL, &kw), 1024, 0); CHECK(retained_len == 1100);
        }
        fields[0].value = TRUE_OBJ; expected_clear = true;
        check_bytes(invoke(0, NULL, &kw), 1024, 0); CHECK(retained_len == 76);
        check_bytes(invoke(0, NULL, &kw), 76, 1024); CHECK(retained_len == 0);
    } else if (!strcmp(argv[1], "limits")) {
        mp_map_elem_t fields[] = {{QSTR(limit), INT(1)}, {QSTR(clear), TRUE_OBJ}};
        mp_map_t kw = {2, fields}; expected_limit = 1; expected_clear = true;
        check_bytes(invoke(0, NULL, &kw), 1, 0); CHECK(retained_len == 1099);
        seed(16384); fields[0].value = INT(16384); fields[1].value = FALSE_OBJ;
        expected_limit = 16384; expected_clear = false;
        check_bytes(invoke(0, NULL, &kw), 16384, 0); CHECK(retained_len == 16384);
        check_bytes(invoke(0, NULL, &kw), 16384, 0); CHECK(retained_len == 16384);
        fields[1].value = TRUE_OBJ; expected_clear = true;
        check_bytes(invoke(0, NULL, &kw), 16384, 0); CHECK(retained_len == 0);
    } else if (!strcmp(argv[1], "invalid")) {
        mp_map_elem_t field = {QSTR(limit), INT(0)};
        mp_map_t kw = {1, &field};
        const mp_obj_t bad[] = {INT(0), INT(16385), INT(-1)};
        for (size_t i = 0; i < MP_ARRAY_SIZE(bad); ++i) {
            field.value = bad[i]; EXPECT_ERROR(2, 0, invoke(0, NULL, &kw));
            CHECK(!strcmp(error_text, "log limit must be 1..16384"));
        }
        field.value = NONINT_OBJ; EXPECT_ERROR(1, 0, invoke(0, NULL, &kw));
    } else if (!strcmp(argv[1], "positional")) {
        const mp_obj_t pos[] = {FALSE_OBJ, INT(1), INT(2)};
        for (size_t count = 1; count <= MP_ARRAY_SIZE(pos); ++count) {
            EXPECT_ERROR(1, 0, invoke(count, pos, &empty));
            CHECK(!strcmp(error_text, "extra positional arguments given"));
        }
    } else if (!strcmp(argv[1], "unknown")) {
        mp_map_elem_t fields[] = {{QSTR(clear), FALSE_OBJ}, {QSTR(unknown), INT(1)}};
        mp_map_t kw = {2, fields}; EXPECT_ERROR(1, 0, invoke(0, NULL, &kw));
        CHECK(!strcmp(error_text, "extra keyword arguments given"));
    } else if (!strcmp(argv[1], "irq")) {
        irq = 0; EXPECT_ERROR(3, MP_EBUSY, invoke(0, NULL, &empty));
        mp_map_elem_t fields[] = {{QSTR(clear), FALSE_OBJ}, {QSTR(limit), INT(16384)}};
        mp_map_t kw = {2, fields}; EXPECT_ERROR(3, MP_EBUSY, invoke(0, NULL, &kw));
    } else CHECK(false);
    puts("PASS"); return 0;
}
'''


class MachineLogsArgsHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GCC.is_file():
            raise unittest.SkipTest(f"host C compiler not found: {GCC}")
        cls.temp = tempfile.TemporaryDirectory(prefix="mpynn-logs-args-host-")
        def cleanup():
            # Windows can briefly retain an executable handle after exit;
            # TemporaryDirectory may wrap that denial as NotADirectoryError.
            for attempt in range(21):
                try:
                    cls.temp.cleanup()
                    return
                except (PermissionError, NotADirectoryError):
                    if attempt == 20:
                        raise
                    time.sleep(0.1)

        cls.addClassCleanup(cleanup)
        cls.root = Path(cls.temp.name)
        (cls.root / "py").mkdir()
        obj = (UPSTREAM / "py/obj.h").read_text(encoding="utf-8")
        runtime = (UPSTREAM / "py/runtime.h").read_text(encoding="utf-8")
        port = (PORT / "modmachine_port.c").read_text(encoding="utf-8")
        # Take the repr-A block only; otherwise similarly named repr-B/C/D
        # definitions could silently change the object's tagging model.
        tags = obj.split("#if MICROPY_OBJ_REPR == MICROPY_OBJ_REPR_A", 1)[1]
        tags = tags.split("static inline bool mp_obj_is_immediate_obj", 1)[0]
        declarations = tags + _extract(runtime, r"typedef enum \{\s*MP_ARG_BOOL\b.*?\} mp_arg_flag_t;")
        declarations += _extract(runtime, r"typedef union _mp_arg_val_t \{.*?\} mp_arg_val_t;")
        declarations += _extract(runtime, r"typedef struct _mp_arg_t \{.*?\} mp_arg_t;")
        declarations += _extract(obj, r"typedef mp_obj_t \(\*mp_fun_var_t\).*?;")
        declarations += _extract(obj, r"typedef mp_obj_t \(\*mp_fun_kw_t\).*?;")
        declarations += _extract(obj, r"typedef struct _mp_obj_fun_builtin_var_t \{.*?\} mp_obj_fun_builtin_var_t;")
        for name in ("MP_OBJ_FUN_ARGS_MAX", "MP_OBJ_FUN_MAKE_SIG", "MP_DEFINE_CONST_FUN_OBJ_KW"):
            declarations += _macro(obj, name)
        (cls.root / "py/runtime.h").write_text(
            RUNTIME.replace("/* REAL_DECLARATIONS */", declarations), encoding="utf-8")
        # Keep upstream errno values and bridge declarations as well.
        (cls.root / "py/mpconfig.h").write_text("#define MICROPY_USE_INTERNAL_ERRNO 1\n", encoding="utf-8")
        fragment = _extract(port, r"static void require_irqs\(void\) \{.*?^\}")
        fragment += _extract(port, r"static mp_obj_t mpynn_logs\(.*?^static MP_DEFINE_CONST_FUN_OBJ_KW\(mpynn_logs_obj,[^\n]*")
        (cls.root / "logs_fragment.h").write_text(fragment, encoding="utf-8")
        harness = cls.root / "harness.c"
        # Avoid adding PORT to the include search path: its bare-metal
        # setjmp.h shadows the host CRT header and requires ARM assembly.
        harness.write_text(HARNESS.replace('"circle_bridge.h"',
                                           '"' + (PORT / "circle_bridge.h").as_posix() + '"'),
                           encoding="utf-8")
        cls.executable = cls.root / "logs-args.exe"
        cls.env = dict(os.environ)
        cls.env["PATH"] = str(GCC.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        cls.run_process("compile", [str(GCC), "-std=c11", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                                    "-I", str(cls.root), "-I", str(UPSTREAM),
                                    str(UPSTREAM / "py/argcheck.c"), str(harness), "-o", str(cls.executable)])

    @classmethod
    def run_process(cls, name, command):
        stdout = cls.root / (name + ".stdout.txt")
        stderr = cls.root / (name + ".stderr.txt")
        with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
            try:
                process = subprocess.run(command, cwd=cls.root, env=cls.env,
                                         stdout=out, stderr=err, timeout=30, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AssertionError(f"host process failed: {command!r}: {exc}") from exc
        output = stdout.read_text(encoding="utf-8", errors="replace")
        diagnostics = stderr.read_text(encoding="utf-8", errors="replace")
        if process.returncode:
            raise AssertionError(f"host process returned {process.returncode}: {command!r}\n{output}\n{diagnostics}")
        return output

    def run_case(self, name):
        self.assertEqual(self.run_process(name, [str(self.executable), name]).strip(), "PASS")

    def test_default_full_snapshot_repeats_until_explicitly_consumed(self):
        self.run_case("default")

    def test_partial_snapshot_preserves_bytes_then_explicit_clear_consumes(self):
        self.run_case("peek")

    def test_limit_1_and_16384_with_explicit_clear_keywords(self):
        self.run_case("limits")

    def test_invalid_zero_overflow_negative_and_non_integer_limits(self):
        self.run_case("invalid")

    def test_positional_arguments_rejected_by_real_parser(self):
        self.run_case("positional")

    def test_unknown_keyword_rejected_by_real_parser(self):
        self.run_case("unknown")

    def test_irq_disabled_raises_busy_without_bridge_or_allocation(self):
        self.run_case("irq")


if __name__ == "__main__":
    unittest.main()
