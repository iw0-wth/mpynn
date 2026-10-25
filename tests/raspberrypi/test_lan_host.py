# SPDX-License-Identifier: MIT
"""Compile and execute the real LAN binding with minimal host MicroPython doubles.

The snapshot/configure bridges are stubs: failures test the binding's errno
translation, not Circle or the real bridge's IRQ implementation. Object allocation,
string/array access, truthiness and exceptions are small test doubles, not a
MicroPython VM. No socket implementation, network traffic or hardware is involved.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "ports/raspberrypi/modnetwork_port.c"
COMPILER = Path("E:/msys64/ucrt64/bin/gcc.exe")

RUNTIME = r"""
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
typedef uintptr_t mp_obj_t;
typedef struct _mp_obj_type_t mp_obj_type_t;
typedef struct { const mp_obj_type_t *type; } mp_obj_base_t;
typedef mp_obj_t (*make_new_t)(const mp_obj_type_t *, size_t, size_t, const mp_obj_t *);
typedef struct { uintptr_t key, value; } mp_rom_map_elem_t;
typedef struct { const mp_rom_map_elem_t *entries; size_t count; } host_dict_t;
struct _mp_obj_type_t { make_new_t make_new; const host_dict_t *locals; const void *protocol; };
#define mp_const_none ((mp_obj_t)2)
#define mp_const_true ((mp_obj_t)4)
#define mp_const_false ((mp_obj_t)6)
#define MP_OBJ_FROM_PTR(p) ((mp_obj_t)(uintptr_t)(p))
#define MP_OBJ_TO_PTR(p) ((void *)(uintptr_t)(p))
#define MP_ROM_QSTR(q) ((uintptr_t)(q))
#define MP_ROM_PTR(p) ((uintptr_t)(p))
#define MP_ERROR_TEXT(t) (t)
#define MP_TYPE_FLAG_NONE 0
#define MP_ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
enum { MP_QSTR_active = 1, MP_QSTR_isconnected, MP_QSTR_ifconfig,
       MP_QSTR_status, MP_QSTR_LAN };
#define MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(name, min, max, fn) \
    const struct { size_t minimum, maximum; mp_obj_t (*fun)(size_t, const mp_obj_t *); } name = {min, max, fn}
#define MP_DEFINE_CONST_FUN_OBJ_1(name, fn) \
    const struct { mp_obj_t (*fun)(mp_obj_t); } name = {fn}
#define MP_DEFINE_CONST_DICT(name, table) \
    const host_dict_t name = {table, MP_ARRAY_SIZE(table)}
#define MP_DEFINE_CONST_OBJ_TYPE(name, qstr, flags, mk, fn, proto, ptr, ld, dict) \
    const mp_obj_type_t name = {fn, dict, ptr}
#define mp_obj_malloc(t, type) ((t *)host_alloc(sizeof(t), type))
void *host_alloc(size_t size, const mp_obj_type_t *type);
void mp_arg_check_num(size_t n, size_t kw, size_t min, size_t max, bool allow_kw);
bool mp_obj_is_true(mp_obj_t obj);
mp_obj_t mp_obj_new_bool(bool value);
mp_obj_t mp_obj_new_int(int value);
mp_obj_t mp_obj_new_str(const char *text, size_t length);
mp_obj_t mp_obj_new_tuple(size_t count, const mp_obj_t *items);
bool mp_obj_is_str(mp_obj_t obj);
const char *mp_obj_str_get_data(mp_obj_t obj, size_t *length);
void mp_obj_get_array(mp_obj_t obj, size_t *count, mp_obj_t **items);
void mp_obj_get_array_fixed_n(mp_obj_t obj, size_t count, mp_obj_t **items);
_Noreturn void mp_raise_TypeError(const char *message);
_Noreturn void mp_raise_OSError(int error);
_Noreturn void mp_raise_NotImplementedError(const char *message);
_Noreturn void mp_raise_ValueError(const char *message);
"""
HEADERS = {
    "extmod/modnetwork.h": '#pragma once\n#include "py/runtime.h"\ntypedef struct { int unused; } mod_network_nic_protocol_t;\nvoid mod_network_register_nic(mp_obj_t nic);\n',
    "py/runtime.h": RUNTIME,
    "py/objtuple.h": '#pragma once\n#include "runtime.h"\n',
    "py/mperrno.h": "#pragma once\n#define MP_EBUSY 16\n#define MP_ENODEV 19\n#define MP_EINVAL 22\n",
}

HARNESS = r"""
/* The binding and its bridge/type declarations are the real production files. */
#include "modnetwork_port.c"
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)
enum { OS_ERROR = 1, NOT_IMPLEMENTED, VALUE_ERROR, TYPE_ERROR };
static jmp_buf exception;
static int raised_kind, raised_errno;
static bool catching, irq_enabled = true;
static int snapshot_error;
static unsigned snapshot_calls, object_calls, configure_calls;
static int configure_error;
static bool configured_dhcp;
static mpynn_network_state_t state, configured_state;
static void *allocated[256];
static size_t allocations;
const mod_network_nic_protocol_t mpynn_udp_nic_protocol = {0};
static mp_obj_t registered;
void mod_network_register_nic(mp_obj_t nic) { registered = nic; }
enum { HOST_STRING = 1, HOST_TUPLE, HOST_LIST, HOST_BYTES };
typedef struct { unsigned kind; size_t length; char text[64]; } host_string_t;
typedef struct { unsigned kind; size_t count; mp_obj_t items[5]; } host_tuple_t;
static _Noreturn void raise_host(int kind, int error) {
    CHECK(catching);
    raised_kind = kind;
    raised_errno = error;
    longjmp(exception, 1);
}
#define EXPECT_RAISE(kind, error, expr) do { \
    catching = true; \
    if (setjmp(exception) == 0) { (void)(expr); CHECK(!"expected exception"); } \
    else { CHECK(raised_kind == (kind)); CHECK(raised_errno == (error)); } \
    catching = false; \
} while (0)
_Noreturn void mp_raise_OSError(int error) { raise_host(OS_ERROR, error); }
_Noreturn void mp_raise_NotImplementedError(const char *message) {
    CHECK(strcmp(message, "LAN cannot be deactivated") == 0);
    raise_host(NOT_IMPLEMENTED, 0);
}
_Noreturn void mp_raise_ValueError(const char *message) {
    CHECK(message != NULL);
    raise_host(VALUE_ERROR, 0);
}
_Noreturn void mp_raise_TypeError(const char *message) {
    CHECK(message != NULL);
    raise_host(TYPE_ERROR, 0);
}
static void *allocate(size_t size) {
    CHECK(allocations < MP_ARRAY_SIZE(allocated));
    void *p = calloc(1, size);
    CHECK(p != NULL);
    allocated[allocations++] = p;
    return p;
}
void *host_alloc(size_t size, const mp_obj_type_t *type) {
    mp_obj_base_t *p = allocate(size);
    p->type = type;
    return p;
}
void mp_arg_check_num(size_t n, size_t kw, size_t min, size_t max, bool allow_kw) {
    if (n < min || n > max || (kw && !allow_kw)) raise_host(TYPE_ERROR, 0);
}
bool mp_obj_is_true(mp_obj_t obj) {
    CHECK(obj == mp_const_none || obj == mp_const_false || obj == mp_const_true);
    return obj == mp_const_true;
}
mp_obj_t mp_obj_new_bool(bool value) {
    ++object_calls;
    return value ? mp_const_true : mp_const_false;
}
mp_obj_t mp_obj_new_int(int value) {
    ++object_calls;
    CHECK(value == 0 || value == 1);
    return (mp_obj_t)(value * 2 + 1); /* distinguish integer 0/1 from bool */
}
mp_obj_t mp_obj_new_str(const char *text, size_t length) {
    ++object_calls;
    host_string_t *s = allocate(sizeof(*s));
    CHECK(length < sizeof(s->text));
    s->kind = HOST_STRING;
    s->length = length;
    memcpy(s->text, text, length);
    s->text[length] = '\0';
    return MP_OBJ_FROM_PTR(s);
}
mp_obj_t mp_obj_new_tuple(size_t count, const mp_obj_t *items) {
    ++object_calls;
    host_tuple_t *t = allocate(sizeof(*t));
    CHECK(count <= MP_ARRAY_SIZE(t->items));
    t->kind = HOST_TUPLE;
    t->count = count;
    memcpy(t->items, items, count * sizeof(*items));
    return MP_OBJ_FROM_PTR(t);
}
bool mp_obj_is_str(mp_obj_t obj) {
    return obj > mp_const_false && !(obj & 1) &&
        ((host_string_t *)MP_OBJ_TO_PTR(obj))->kind == HOST_STRING;
}
const char *mp_obj_str_get_data(mp_obj_t obj, size_t *length) {
    CHECK(mp_obj_is_str(obj));
    host_string_t *s = MP_OBJ_TO_PTR(obj);
    *length = s->length;
    return s->text;
}
void mp_obj_get_array(mp_obj_t obj, size_t *count, mp_obj_t **items) {
    if (obj <= mp_const_false || (obj & 1)) mp_raise_TypeError("expected tuple/list");
    host_tuple_t *t = MP_OBJ_TO_PTR(obj);
    if (t->kind != HOST_TUPLE && t->kind != HOST_LIST) mp_raise_TypeError("expected tuple/list");
    *count = t->count;
    *items = t->items;
}
void mp_obj_get_array_fixed_n(mp_obj_t obj, size_t count, mp_obj_t **items) {
    size_t actual;
    mp_obj_get_array(obj, &actual, items);
    if (actual != count) mp_raise_ValueError("tuple/list has wrong length");
}
int mpynn_network_configure(const mpynn_network_state_t *requested) {
    ++configure_calls;
    configured_dhcp = requested == NULL;
    if (requested) configured_state = *requested;
    return configure_error;
}
int mpynn_network_snapshot(mpynn_network_state_t *out) {
    ++snapshot_calls;
    CHECK(out != NULL);
    if (!irq_enabled) return -3;
    if (snapshot_error) return snapshot_error;
    *out = state;
    return 0;
}
static void test_constructor(void) {
    mp_obj_t obj = mp_network_lan_type.make_new(&mp_network_lan_type, 0, 0, NULL);
    CHECK(((mp_obj_base_t *)MP_OBJ_TO_PTR(obj))->type == &mp_network_lan_type);
    CHECK(registered == obj && mp_network_lan_type.protocol == &mpynn_udp_nic_protocol);
    CHECK(snapshot_calls == 0);
    mp_obj_t arg = mp_const_none;
    EXPECT_RAISE(TYPE_ERROR, 0, lan_make_new(&mp_network_lan_type, 1, 0, &arg));
    EXPECT_RAISE(TYPE_ERROR, 0, lan_make_new(&mp_network_lan_type, 0, 1, &arg));
    CHECK(allocations == 0);
    for (unsigned i=0; i<100; ++i) {
        CHECK(lan_make_new(&mp_network_lan_type, 0, 0, NULL) == obj);
    }
    registered = 0; // fake reset of per-VM NIC registry, not physical hardware
    CHECK(lan_make_new(&mp_network_lan_type, 0, 0, NULL) == obj);
    CHECK(registered == obj && allocations == 0);
    const host_dict_t *dict = mp_network_lan_type.locals;
    CHECK(dict->count == 4);
    const uintptr_t keys[] = {MP_QSTR_active, MP_QSTR_isconnected, MP_QSTR_ifconfig, MP_QSTR_status};
    const uintptr_t values[] = {MP_ROM_PTR(&lan_active_obj), MP_ROM_PTR(&lan_isconnected_obj),
        MP_ROM_PTR(&lan_ifconfig_obj), MP_ROM_PTR(&lan_status_obj)};
    for (size_t i = 0; i < dict->count; ++i) {
        CHECK(dict->entries[i].key == keys[i] && dict->entries[i].value == values[i]);
    }
    CHECK(lan_active_obj.minimum == 1 && lan_active_obj.maximum == 2);
    CHECK(lan_status_obj.minimum == 1 && lan_status_obj.maximum == 2);
    CHECK(lan_ifconfig_obj.minimum == 1 && lan_ifconfig_obj.maximum == 2);
}
static void test_active(void) {
    mp_obj_t args[] = {mp_const_none, mp_const_true};
    for (unsigned initialized = 0; initialized <= 1; ++initialized) {
        state.initialized = initialized;
        CHECK(lan_active_obj.fun(1, args) == (initialized ? mp_const_true : mp_const_false));
        args[1] = mp_const_true;
        if (initialized) CHECK(lan_active_obj.fun(2, args) == mp_const_none);
        else { EXPECT_RAISE(OS_ERROR, MP_ENODEV, lan_active_obj.fun(2, args)); }
        args[1] = mp_const_false;
        EXPECT_RAISE(NOT_IMPLEMENTED, 0, lan_active_obj.fun(2, args));
        args[1] = mp_const_none;
        EXPECT_RAISE(NOT_IMPLEMENTED, 0, lan_active_obj.fun(2, args));
    }
    CHECK(snapshot_calls == 8);
}
static void test_connected_and_status(void) {
    mp_obj_t args[] = {mp_const_none, mp_const_none};
    const unsigned flags[] = {0, 1, 7};
    for (size_t i = 0; i < MP_ARRAY_SIZE(flags); ++i) {
        for (size_t j = 0; j < MP_ARRAY_SIZE(flags); ++j) {
            state.initialized = flags[i];
            state.running = flags[j];
            CHECK(lan_isconnected_obj.fun(args[0]) ==
                (state.initialized && state.running ? mp_const_true : mp_const_false));
            CHECK(lan_status_obj.fun(1, args) == (state.running ? 3u : 1u));
        }
    }
    CHECK(snapshot_calls == 18);
    EXPECT_RAISE(VALUE_ERROR, 0, lan_status_obj.fun(2, args));
    CHECK(snapshot_calls == 18); /* unsupported key rejected before snapshot */
}
static void check_addresses(const char *const expected[4]) {
    const mp_obj_t args[] = {mp_const_none};
    host_tuple_t *tuple = MP_OBJ_TO_PTR(lan_ifconfig_obj.fun(1, args));
    CHECK(tuple->count == 4);
    for (size_t i = 0; i < 4; ++i) {
        host_string_t *s = MP_OBJ_TO_PTR(tuple->items[i]);
        CHECK(s->length == strlen(expected[i]));
        CHECK(strcmp(s->text, expected[i]) == 0);
    }
}
static void test_ifconfig(void) {
    const char *zero[] = {"0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0"};
    check_addresses(zero);
    state = (mpynn_network_state_t){.initialized = 1, .running = 1,
        .ip = {192, 168, 0, 10}, .netmask = {255, 255, 255, 255},
        .gateway = {10, 0, 128, 1}, .dns = {8, 8, 4, 4}};
    const char *expected[] = {"192.168.0.10", "255.255.255.255", "10.0.128.1", "8.8.4.4"};
    check_addresses(expected);
    CHECK(snapshot_calls == 2 && object_calls == 10);
}
static mp_obj_t make_config(void) {
    const char *text[] = {"192.168.1.50", "255.255.255.0", "192.168.1.1", "8.8.8.8"};
    mp_obj_t items[4];
    for (size_t i = 0; i < 4; ++i) items[i] = mp_obj_new_str(text[i], strlen(text[i]));
    return mp_obj_new_tuple(4, items);
}
static void test_ifconfig_setter(void) {
    mp_obj_t args[] = {mp_const_none, mp_obj_new_str("dhcp", 4)};
    CHECK(lan_ifconfig_obj.fun(2, args) == mp_const_none);
    CHECK(configure_calls == 1 && configured_dhcp && snapshot_calls == 0);
    args[1] = make_config();
    const uint8_t expected[][4] = {{192,168,1,50}, {255,255,255,0}, {192,168,1,1}, {8,8,8,8}};
    CHECK(lan_ifconfig_obj.fun(2, args) == mp_const_none);
    CHECK(configure_calls == 2 && !configured_dhcp && snapshot_calls == 0);
    CHECK(!memcmp(configured_state.ip, expected[0], 4));
    CHECK(!memcmp(configured_state.netmask, expected[1], 4));
    CHECK(!memcmp(configured_state.gateway, expected[2], 4));
    CHECK(!memcmp(configured_state.dns, expected[3], 4));
    CHECK(configured_state.dhcp == 0);
    host_tuple_t *list = MP_OBJ_TO_PTR(args[1]);
    list->kind = HOST_LIST;
    list->items[0] = mp_obj_new_str("000.001.002.255", 15);
    CHECK(lan_ifconfig_obj.fun(2, args) == mp_const_none);
    CHECK(configure_calls == 3 && !configured_dhcp);
    const uint8_t decimal[] = {0,1,2,255};
    CHECK(!memcmp(configured_state.ip, decimal, 4));
    /* A successful mode request need not have changed the getter snapshot yet. */
    const char *zero[] = {"0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0"};
    check_addresses(zero);
    CHECK(snapshot_calls == 1);
}
static void reject_setter(int kind, mp_obj_t value) {
    const mp_obj_t args[] = {mp_const_none, value};
    unsigned calls_before = configure_calls, snapshots_before = snapshot_calls;
    EXPECT_RAISE(kind, 0, lan_ifconfig_obj.fun(2, args));
    CHECK(configure_calls == calls_before && snapshot_calls == snapshots_before);
}
static void test_ifconfig_invalid(void) {
    const char *modes[] = {"", "DHCP", "Dhcp", "dhcp ", " dhcp", "192.168.1.50", "dhcp\0ignored"};
    for (size_t i = 0; i < MP_ARRAY_SIZE(modes); ++i) {
        size_t length = i == MP_ARRAY_SIZE(modes) - 1 ? sizeof("dhcp\0ignored") - 1 : strlen(modes[i]);
        reject_setter(VALUE_ERROR, mp_obj_new_str(modes[i], length));
    }
    reject_setter(TYPE_ERROR, mp_const_none);
    reject_setter(TYPE_ERROR, mp_const_true);
    reject_setter(TYPE_ERROR, mp_obj_new_int(1));
    mp_obj_t bytes = mp_obj_new_str("dhcp", 4);
    ((host_string_t *)MP_OBJ_TO_PTR(bytes))->kind = HOST_BYTES;
    reject_setter(TYPE_ERROR, bytes);
    mp_obj_t config = make_config();
    host_tuple_t *tuple = MP_OBJ_TO_PTR(config);
    for (size_t count = 0; count <= 5; ++count) {
        if (count == 4) continue;
        tuple->count = count;
        reject_setter(VALUE_ERROR, config);
    }
    tuple->count = 4;
    for (size_t i = 0; i < 4; ++i) {
        mp_obj_t saved = tuple->items[i];
        tuple->items[i] = mp_const_none;
        reject_setter(TYPE_ERROR, config);
        tuple->items[i] = bytes;
        reject_setter(TYPE_ERROR, config);
        tuple->items[i] = saved;
    }
    const char *bad[] = {"", " ", "1.2.3", "1.2.3.4.5", ".1.2.3", "1..2.3",
        "1.2.3.", "256.2.3.4", "1.256.3.4", "1.2.256.4", "1.2.3.256",
        "-1.2.3.4", "+1.2.3.4", "0x1.2.3.4", "1e0.2.3.4", "1.2.3.4 ",
        " 1.2.3.4", "1. 2.3.4", "1.2.3.4\n", "1.2.3.4\t", "1.2.3.\xff",
        "0000.1.2.3", "9999999999999999999.1.2.3"};
    mp_obj_t saved = tuple->items[3];
    for (size_t i = 0; i < MP_ARRAY_SIZE(bad); ++i) {
        tuple->items[3] = mp_obj_new_str(bad[i], strlen(bad[i]));
        reject_setter(VALUE_ERROR, config);
    }
    const char embedded[] = "1.2.3.4\0junk";
    tuple->items[3] = mp_obj_new_str(embedded, sizeof(embedded) - 1);
    reject_setter(VALUE_ERROR, config);
    const char interior[] = "1.2\0.3.4";
    tuple->items[3] = mp_obj_new_str(interior, sizeof(interior) - 1);
    reject_setter(VALUE_ERROR, config);
    tuple->items[3] = saved;
    CHECK(configure_calls == 0 && snapshot_calls == 0);
}
static void test_ifconfig_configure_failure(void) {
    mp_obj_t modes[] = {mp_obj_new_str("dhcp", 4), make_config()};
    const int errors[] = {MP_EBUSY, MP_ENODEV, MP_EINVAL};
    for (size_t mode = 0; mode < MP_ARRAY_SIZE(modes); ++mode) {
        const mp_obj_t args[] = {mp_const_none, modes[mode]};
        for (size_t i = 0; i < MP_ARRAY_SIZE(errors); ++i) {
            configure_error = errors[i];
            unsigned before = configure_calls;
            EXPECT_RAISE(OS_ERROR, errors[i], lan_ifconfig_obj.fun(2, args));
            CHECK(configure_calls == before + 1 && configured_dhcp == (mode == 0));
        }
    }
    /* Semantic validation belongs to the native bridge, not the text parser. */
    host_tuple_t *tuple = MP_OBJ_TO_PTR(modes[1]);
    tuple->items[1] = mp_obj_new_str("255.0.255.0", 11);
    const mp_obj_t args[] = {mp_const_none, modes[1]};
    configure_error = MP_EINVAL;
    EXPECT_RAISE(OS_ERROR, MP_EINVAL, lan_ifconfig_obj.fun(2, args));
    CHECK(configure_calls == 7 && snapshot_calls == 0);
    const uint8_t mask[] = {255,0,255,0};
    CHECK(!memcmp(configured_state.netmask, mask, 4));
    configure_error = 0;
    CHECK(lan_ifconfig_obj.fun(2, args) == mp_const_none);
}
static void check_busy(void) {
    mp_obj_t args[] = {mp_const_none, mp_const_true};
    unsigned before = snapshot_calls, objects_before = object_calls;
    EXPECT_RAISE(OS_ERROR, MP_EBUSY, lan_active_obj.fun(1, args));
    EXPECT_RAISE(OS_ERROR, MP_EBUSY, lan_active_obj.fun(2, args));
    args[1] = mp_const_false;
    EXPECT_RAISE(OS_ERROR, MP_EBUSY, lan_active_obj.fun(2, args));
    args[1] = mp_const_none;
    EXPECT_RAISE(OS_ERROR, MP_EBUSY, lan_active_obj.fun(2, args));
    EXPECT_RAISE(OS_ERROR, MP_EBUSY, lan_isconnected_obj.fun(args[0]));
    EXPECT_RAISE(OS_ERROR, MP_EBUSY, lan_ifconfig_obj.fun(1, args));
    EXPECT_RAISE(OS_ERROR, MP_EBUSY, lan_status_obj.fun(1, args));
    CHECK(snapshot_calls == before + 7 && object_calls == objects_before);
}
static void test_snapshot_failure(void) {
    state.initialized = state.running = 1;
    irq_enabled = false;
    check_busy();
    irq_enabled = true;
    snapshot_error = -2;
    check_busy();
    snapshot_error = 0;
    CHECK(lan_isconnected_obj.fun(mp_const_none) == mp_const_true);
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    if (!strcmp(argv[1], "constructor")) test_constructor();
    else if (!strcmp(argv[1], "active")) test_active();
    else if (!strcmp(argv[1], "connected-status")) test_connected_and_status();
    else if (!strcmp(argv[1], "ifconfig")) test_ifconfig();
    else if (!strcmp(argv[1], "ifconfig-setter")) test_ifconfig_setter();
    else if (!strcmp(argv[1], "ifconfig-invalid")) test_ifconfig_invalid();
    else if (!strcmp(argv[1], "ifconfig-configure-failure")) test_ifconfig_configure_failure();
    else if (!strcmp(argv[1], "snapshot-failure")) test_snapshot_failure();
    else CHECK(!"unknown scenario");
    CHECK(!catching);
    for (size_t i = 0; i < allocations; ++i) free(allocated[i]);
    puts("PASS");
    return 0;
}
"""


class LANHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not COMPILER.is_file():
            raise unittest.SkipTest(f"host GCC unavailable: {COMPILER}")
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-lan-host-")
        # Windows scanners may briefly retain the just-executed binary.
        # Retry cleanup, but still fail if the temporary files stay locked.
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
        for name, content in HEADERS.items():
            target = cls.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        harness = cls.root / "harness.c"
        harness.write_text(HARNESS, encoding="utf-8")
        cls.executable = cls.root / "lan-host.exe"
        cls.env = dict(os.environ)
        cls.env["PATH"] = str(COMPILER.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [str(COMPILER), "-std=c11", "-Wall", "-Wextra", "-Werror",
             # The real lan_make_new currently leaves its args parameter unused.
             "-Wno-unused-parameter", "-I", str(cls.root),
             # Avoid shadowing the host <setjmp.h> with the port's header.
             "-iquote", str(SOURCE.parent), str(harness), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host GCC compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, name):
        result = subprocess.run([str(self.executable), name], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_constructor_and_registered_methods(self):
        self.run_scenario("constructor")

    def test_active_query_true_and_rejected_false_or_none(self):
        self.run_scenario("active")

    def test_isconnected_boolean_and_status_integer(self):
        self.run_scenario("connected-status")

    def test_ifconfig_ipv4_tuple_order_and_maximum_length(self):
        self.run_scenario("ifconfig")

    def test_ifconfig_dhcp_and_static_tuple_or_list_setters(self):
        self.run_scenario("ifconfig-setter")

    def test_ifconfig_invalid_inputs_never_configure(self):
        self.run_scenario("ifconfig-invalid")

    def test_ifconfig_native_positive_errno_propagates(self):
        self.run_scenario("ifconfig-configure-failure")

    def test_irq_disabled_and_other_snapshot_failures_raise_ebusy(self):
        self.run_scenario("snapshot-failure")


if __name__ == "__main__":
    unittest.main()
