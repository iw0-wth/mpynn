# SPDX-License-Identifier: MIT
"""Execute the real lazy socket constructor with its actual five-bit fields.

Only VM argument conversion, argument-count checking and object allocation are
faked. The complete port-owned constructor (and any static helper it calls) and
the socket object typedef are extracted unchanged from production sources.
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
MODSOCKET = ROOT / "ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c"
NETWORK_HEADER = ROOT / "lib/micropython/extmod/modnetwork.h"
WINDOWS_GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")


def extract_function(source, name):
    """Find a full definition, balancing braces outside comments and literals."""
    match = re.search(rf"^static\s+[^;{{\n]+\b{re.escape(name)}\s*\(", source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"Missing production definition: {name}")
    opening = source.index("{", match.end())
    depth, state, escaped = 0, "code", False
    index = opening
    while index < len(source):
        char = source[index]
        following = source[index + 1:index + 2]
        if state == "code":
            if char == "/" and following in ("*", "/"):
                state = "block" if following == "*" else "line"
                index += 1
            elif char in ('"', "'"):
                state, escaped = char, False
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if not depth:
                    return source[match.start():index + 1]
        elif state == "block" and char == "*" and following == "/":
            state = "code"
            index += 1
        elif state == "line" and char == "\n":
            state = "code"
        elif state in ('"', "'"):
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == state:
                state = "code"
        index += 1
    raise AssertionError(f"Unterminated production definition: {name}")


def constructor_definitions(source):
    """Include real static validation helpers, never a replacement constructor."""
    names = set(re.findall(r"^static\s+[^;{\n]+\b(\w+)\s*\(", source, re.MULTILINE))
    emitted, definitions = set(), []

    def visit(name):
        if name in emitted:
            return
        emitted.add(name)
        definition = extract_function(source, name)
        for called in re.findall(r"\b(\w+)\s*\(", definition[definition.index("{"):]):
            if called in names:
                visit(called)
        definitions.append(definition)

    visit("socket_make_new")
    return "\n\n".join(definitions)


def socket_layout(header):
    match = re.search(r"typedef struct _mod_network_socket_obj_t\s*\{.*?"
                      r"\}\s*mod_network_socket_obj_t;", header, re.DOTALL)
    if match is None:
        raise AssertionError("Missing production socket object typedef")
    return match.group()


def production_constants(header):
    constants = []
    for name in ("MOD_NETWORK_AF_INET", "MOD_NETWORK_AF_INET6",
                 "MOD_NETWORK_SOCK_STREAM", "MOD_NETWORK_SS_NEW"):
        match = re.search(rf"^#define\s+{name}\s+\(?\s*(\d+)\s*\)?(?:\s|$)",
                          header, re.MULTILINE)
        if match is None:
            raise AssertionError(f"Missing production constant: {name}")
        constants.append(f"#define {name} ({match.group(1)})")
    return "\n".join(constants)


PRELUDE = r"""
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)
typedef void *mp_obj_t;
typedef intptr_t mp_int_t;
typedef struct { unsigned sentinel; } mp_obj_type_t;
typedef struct { const mp_obj_type_t *type; } mp_obj_base_t;
typedef struct { unsigned unused; } mod_network_nic_protocol_t;
#define MICROPY_PY_SOCKET_EXTENDED_STATE 1
#define MP_OBJ_NULL ((mp_obj_t)NULL)
#define MP_OBJ_FROM_PTR(p) ((mp_obj_t)(p))
#define MP_OBJ_TO_PTR(o) ((void *)(o))
#define MP_ERROR_TEXT(s) (s)
static const mp_obj_type_t socket_type = {123};
static jmp_buf raise_target;
enum { VALUE_ERROR = 1, TYPE_ERROR };
static unsigned raised_kind, allocations, conversions, count_checks;
static size_t active_count, checked_keywords;
static const mp_obj_t *active_args;
static size_t seen_indices[6];
static _Noreturn void mp_raise_ValueError(const char *message) {
    CHECK(message && *message); raised_kind = VALUE_ERROR; longjmp(raise_target, 1);
}
static void mp_arg_check_num(size_t n_args, size_t n_kw,
                             size_t minimum, size_t maximum, bool allow_kw) {
    ++count_checks; checked_keywords = n_kw;
    CHECK(!allocations && !conversions && minimum == 0 && maximum == 3 && !allow_kw);
    if (n_args < minimum || n_args > maximum || (n_kw && !allow_kw)) {
        raised_kind = TYPE_ERROR; longjmp(raise_target, 1);
    }
}
static mp_int_t mp_obj_get_int(mp_obj_t object) {
    CHECK(count_checks == 1 && active_count && conversions < 2 * active_count);
    // Production may convert again for assignment after its validation pass.
    // Only a complete validation pass is allowed before that allocation.
    CHECK(conversions < active_count ? !allocations : allocations == 1);
    size_t index = conversions % active_count;
    // Signed values are preserved through conversion, not pre-narrowed by a fake.
    CHECK(object == active_args[index]);
    seen_indices[conversions++] = index;
    return *(const mp_int_t *)object;
}
"""

ALLOCATOR = r"""
static mod_network_socket_obj_t storage;
static void *host_malloc_with_finaliser(size_t size, const mp_obj_type_t *type) {
    CHECK(count_checks == 1 && allocations == 0 && conversions == active_count);
    CHECK(size == sizeof(storage) && type == &socket_type);
    ++allocations;
    // Poison memory: assertions must prove constructor initialization, not calloc.
    memset(&storage, 0xA5, sizeof(storage));
    storage.base.type = type;
    return &storage;
}
#define mp_obj_malloc_with_finaliser(object_type, type) \
    ((object_type *)host_malloc_with_finaliser(sizeof(object_type), (type)))
"""

TESTS = r"""
static mp_int_t values[4];
static mp_obj_t args[4];
static void reset(size_t count) {
    CHECK(count <= 4);
    allocations = conversions = count_checks = raised_kind = 0;
    checked_keywords = 0;
    active_count = count;
    active_args = args;
    for (size_t i = 0; i < 4; ++i) args[i] = &values[i];
    for (size_t i = 0; i < 6; ++i) seen_indices[i] = SIZE_MAX;
}
static void check_success(size_t count, mp_int_t domain, mp_int_t kind, mp_int_t proto) {
    reset(count);
    CHECK(setjmp(raise_target) == 0);
    mp_obj_t object = socket_make_new(&socket_type, count, 0, count ? args : NULL);
    mod_network_socket_obj_t *s = MP_OBJ_TO_PTR(object);
    CHECK(s == &storage && allocations == 1 && count_checks == 1);
    CHECK(conversions == count || conversions == 2 * count);
    CHECK(!raised_kind && !checked_keywords);
    CHECK(s->base.type == &socket_type);
    CHECK(s->domain == domain && s->type == kind && s->proto == proto);
    CHECK(s->nic == MP_OBJ_NULL && s->nic_protocol == NULL && s->_private == NULL);
    CHECK(s->state == MOD_NETWORK_SS_NEW && s->timeout == -1);
    CHECK(!s->bound && s->fileno == -1 && s->callback == MP_OBJ_NULL);
    for (size_t i = 0; i < conversions; ++i) CHECK(seen_indices[i] == i % count);
}
static void test_defaults(void) {
    CHECK(MOD_NETWORK_AF_INET == 2 && MOD_NETWORK_SOCK_STREAM == 1);
    CHECK(MOD_NETWORK_AF_INET6 == 10);
    check_success(0, 2, 1, 0);
    values[0] = 10;
    check_success(1, 10, 1, 0); // AF_INET6 remains a legal, lazy constructor value.
    values[1] = 31;
    check_success(2, 10, 31, 0);
    values[2] = 31;
    check_success(3, 10, 31, 31);
}
static void test_representable(void) {
    // Exhaust every representable triple, including unsupported transport kinds.
    // Constructor validates storage width, not adapter protocol support.
    for (mp_int_t domain = 0; domain <= 31; ++domain) {
        values[0] = domain;
        check_success(1, domain, 1, 0);
        for (mp_int_t kind = 0; kind <= 31; ++kind) {
            values[1] = kind;
            check_success(2, domain, kind, 0);
            for (mp_int_t proto = 0; proto <= 31; ++proto) {
                values[2] = proto;
                check_success(3, domain, kind, proto);
            }
        }
    }
}
static void test_invalid(void) {
    static const mp_int_t bad[] = {-1, -32, INT_MIN, 32, 33, INT_MAX};
    // Test each supplied position, with and without following valid arguments.
    for (size_t position = 0; position < 3; ++position) {
        for (size_t count = position + 1; count <= 3; ++count) {
            for (size_t b = 0; b < sizeof(bad) / sizeof(bad[0]); ++b) {
                values[0] = 2; values[1] = 1; values[2] = 0;
                values[position] = bad[b];
                reset(count);
                if (setjmp(raise_target) == 0) {
                    (void)socket_make_new(&socket_type, count, 0, args);
                    CHECK(false);
                }
                CHECK(raised_kind == VALUE_ERROR && allocations == 0 && count_checks == 1);
                // Inline or helper validation may reject immediately or after
                // remaining conversions, but must never allocate first.
                CHECK(conversions >= position + 1 && conversions <= count);
                for (size_t i = 0; i < conversions; ++i) CHECK(seen_indices[i] == i);
            }
        }
    }
}
static void test_counts(void) {
    for (size_t count = 0; count <= 4; ++count) {
        for (size_t keywords = 0; keywords <= 2; ++keywords) {
            if (count <= 3 && !keywords) continue;
            // Deliberately invalid values: argument-count rejection must win.
            values[0] = -1; values[1] = 32; values[2] = INT_MAX; values[3] = -1;
            reset(count);
            if (setjmp(raise_target) == 0) {
                (void)socket_make_new(&socket_type, count, keywords, args);
                CHECK(false);
            }
            CHECK(raised_kind == TYPE_ERROR && count_checks == 1);
            CHECK(checked_keywords == keywords && !conversions && !allocations);
        }
    }
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    if (!strcmp(argv[1], "defaults")) test_defaults();
    else if (!strcmp(argv[1], "representable")) test_representable();
    else if (!strcmp(argv[1], "invalid")) test_invalid();
    else if (!strcmp(argv[1], "counts")) test_counts();
    else CHECK(false);
    puts("PASS");
    return 0;
}
"""


class SocketConstructorSourceTests(unittest.TestCase):
    def test_actual_model_has_five_bit_unsigned_fields(self):
        layout = socket_layout(NETWORK_HEADER.read_text(encoding="utf-8"))
        for name in ("domain", "type", "proto"):
            self.assertRegex(layout, rf"uint32_t\s+{name}\s*:\s*5\s*;")
        self.assertIn("void *_private;", layout)

    def test_extracted_source_has_signed_range_checks_and_value_error(self):
        definitions = constructor_definitions(MODSOCKET.read_text(encoding="utf-8"))
        self.assertIn("mp_raise_ValueError", definitions)
        self.assertRegex(definitions, r"<\s*0\b")
        self.assertRegex(definitions, r">\s*31\b")
        self.assertNotRegex(definitions, r"\b(?:socket_select_nic|mod_network_find_nic)\s*\(")


class SocketConstructorHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("gcc")
        if compiler is None and WINDOWS_GCC.is_file():
            compiler = str(WINDOWS_GCC)
        if compiler is None:
            raise unittest.SkipTest("host GCC unavailable")
        source = MODSOCKET.read_text(encoding="utf-8")
        header = NETWORK_HEADER.read_text(encoding="utf-8")
        program = (production_constants(header) + "\n" + PRELUDE + "\n"
                   + socket_layout(header) + "\n" + ALLOCATOR + "\n"
                   + constructor_definitions(source) + "\n" + TESTS)
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-socket-constructor-")
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
        root = Path(temporary.name)
        c_file = root / "constructor.c"
        cls.executable = root / "constructor.exe"
        c_file.write_text(program, encoding="utf-8")
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(Path(compiler).parent) + os.pathsep + cls.env.get("PATH", "")
        result = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                                 str(c_file), "-o", str(cls.executable)],
                                env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("strict GCC compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, name):
        result = subprocess.run([str(self.executable), name], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_defaults_partial_arguments_and_lazy_ipv6(self):
        self.run_scenario("defaults")

    def test_every_representable_triple_survives_actual_bitfields_exactly(self):
        self.run_scenario("representable")

    def test_out_of_range_each_position_raises_value_error_before_allocation(self):
        self.run_scenario("invalid")

    def test_argument_and_keyword_counts_reject_before_conversion_or_allocation(self):
        self.run_scenario("counts")


if __name__ == "__main__":
    unittest.main()
