# SPDX-License-Identifier: MIT
"""Compile the real setsockopt and NIC-selection wrappers with a tiny NLR VM.

No firmware build, hardware, network, or production-source copy is modified.
Only an unavailable host compiler skips; compiler and scenario failures fail.
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
FALLBACK_GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")


def extract_function(source, name):
    """Keep the complete actual definition, ignoring comment/string braces."""
    match = re.search(rf"^static\s+(?:void|mp_obj_t|mp_int_t)\s+{re.escape(name)}\s*\(",
                      source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"Missing static definition of {name}")
    opening = source.find("{", match.end())
    if opening < 0:
        raise AssertionError(f"Missing body of {name}")
    depth, state, escaped = 0, "code", False
    index = opening
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
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
                if depth == 0:
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
    raise AssertionError(f"Unterminated definition of {name}")


def cleanup_with_retry(temporary):
    """Allow bounded Windows executable-lock release without hiding failures."""
    for attempt in range(5):
        try:
            temporary.cleanup()
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


PRELUDE = r"""
#include <limits.h>
#include <setjmp.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char byte;
typedef intptr_t mp_int_t;
typedef uintptr_t mp_uint_t;
typedef void *mp_obj_t;
#define MP_OBJ_NULL ((mp_obj_t)NULL)
#define MP_OBJ_TO_PTR(obj) ((void *)(obj))
#define MP_OBJ_FROM_PTR(ptr) ((mp_obj_t)(ptr))
#define MP_BUFFER_READ 1
#define MICROPY_PY_SOCKET_EXTENDED_STATE 1
#define MOD_NETWORK_AF_INET 2
#define MOD_NETWORK_SOCK_STREAM 1
#define MOD_NETWORK_SOCK_DGRAM 2
#define MOD_NETWORK_SS_NEW 0
#define MOD_NETWORK_SS_CONNECTED 2
#define MOD_NETWORK_SS_CLOSED 3
#define MP_EBADF 9
#define MP_ENOMEM 12
#define MP_EINVAL 22
#define MP_EOPNOTSUPP 95
#define MP_EAFNOSUPPORT 97
#define MP_ENETDOWN 100
#define HOST_TYPE_ERROR (-1001)
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)

typedef struct nlr_buf_t { jmp_buf jb; void *ret_val; struct nlr_buf_t *prev; } nlr_buf_t;
static nlr_buf_t *nlr_top;
#define nlr_push(n) (((n)->prev = nlr_top), (nlr_top = (n)), setjmp((n)->jb))
static void nlr_pop(void) { CHECK(nlr_top != NULL); nlr_top = nlr_top->prev; }
static _Noreturn void nlr_jump(void *value) {
    nlr_buf_t *n = nlr_top; CHECK(n != NULL);
    nlr_top = n->prev; n->ret_val = value; longjmp(n->jb, 1);
}
static _Noreturn void mp_raise_OSError(int code) { nlr_jump((void *)(intptr_t)code); }

typedef struct mod_network_socket_obj_t mod_network_socket_obj_t;
typedef struct {
    int (*socket)(mod_network_socket_obj_t *, int *);
    int (*setsockopt)(mod_network_socket_obj_t *, mp_uint_t, mp_uint_t, const void *, mp_uint_t, int *);
    int (*settimeout)(mod_network_socket_obj_t *, mp_uint_t, int *);
    void (*close)(mod_network_socket_obj_t *);
} mod_network_nic_protocol_t;
struct mod_network_socket_obj_t {
    mp_obj_t nic;
    mod_network_nic_protocol_t *nic_protocol;
    int domain, type, proto, state;
    bool bound;
    int32_t timeout;
    void *_private;
    mp_obj_t callback;
};
typedef struct { const mod_network_nic_protocol_t *protocol; } mp_obj_type_t;
#define MP_OBJ_TYPE_GET_SLOT(type, slot) ((type)->slot)
typedef struct { void *buf; size_t len; int typecode; } mp_buffer_info_t;
enum { OBJ_INT, OBJ_BOOL, OBJ_BUFFER, OBJ_NONBUFFER, OBJ_NONE, OBJ_POISON };
typedef struct {
    int kind;
    mp_int_t integer;
    mp_uint_t low_bits;
    bool truncated_only;
    mp_buffer_info_t buffer;
} host_obj_t;
static host_obj_t level_obj, option_obj, value_obj, poison_obj = {.kind=OBJ_POISON};
static host_obj_t none_obj = {.kind=OBJ_NONE};
static const mp_obj_t mp_const_none = &none_obj;
static unsigned level_conversions, option_conversions, value_conversions, integer_checks, buffers;
static unsigned checked_value_conversions, truncated_value_conversions;
static unsigned finds, types, sockets, allocations, callbacks[2], timeouts, closes;
static int socket_error, callback_error, timeout_error;
static mod_network_socket_obj_t self;
static mp_obj_t args[4] = {&self, &level_obj, &option_obj, &value_obj};
static mod_network_nic_protocol_t default_protocol, existing_protocol;
static const mp_obj_type_t default_type = {&default_protocol}, existing_type = {&existing_protocol};
static byte default_nic, existing_nic, callback_sentinel;
static mp_obj_t expected_nic;
static mod_network_nic_protocol_t *expected_protocol;
static byte selected_ip[4];
static mp_int_t expected_value;
static const void *original_buffer;
static bool mutate_input_on_creation;
static unsigned expected_value_conversions, expected_buffers;
static struct { bool broadcast, nodelay; int32_t send_timeout, receive_timeout; } native_options;
_Alignas(mp_int_t) static byte buffer_storage[sizeof(mp_int_t) + 8 + 2];

static mp_int_t mp_obj_get_int(mp_obj_t obj) {
    if (obj == &level_obj) ++level_conversions;
    else if (obj == &option_obj) ++option_conversions;
    else { CHECK(obj == &value_obj); ++value_conversions; ++checked_value_conversions; }
    const host_obj_t *o = obj;
    if (o->kind != OBJ_INT && o->kind != OBJ_BOOL)
        nlr_jump((void *)(intptr_t)HOST_TYPE_ERROR);
    CHECK(!o->truncated_only); return o->integer;
}
static bool mp_obj_is_integer(mp_obj_t obj) {
    ++integer_checks; CHECK(obj != &poison_obj);
    const host_obj_t *o = obj;
    return o->kind == OBJ_INT || o->kind == OBJ_BOOL;
}
static mp_int_t mp_obj_get_int_truncated(mp_obj_t obj) {
    CHECK(obj == &value_obj); ++value_conversions; ++truncated_value_conversions;
    CHECK(value_obj.kind == OBJ_INT || value_obj.kind == OBJ_BOOL);
    // Model the VM's native-word truncation, not range-checked get_int().
    mp_int_t result; memcpy(&result, &value_obj.low_bits, sizeof(result)); return result;
}
static void mp_get_buffer_raise(mp_obj_t obj, mp_buffer_info_t *info, unsigned flags) {
    ++buffers; CHECK(flags == MP_BUFFER_READ && obj != &poison_obj);
    const host_obj_t *o = obj;
    if (o->kind != OBJ_BUFFER) nlr_jump((void *)(intptr_t)HOST_TYPE_ERROR);
    *info = o->buffer;
}
static void parsing_finished(void) {
    CHECK(level_conversions == 1 && option_conversions == 1 && integer_checks == 1);
    CHECK(value_conversions == expected_value_conversions && buffers == expected_buffers);
}
static mp_obj_t mod_network_find_nic(const byte *ip) {
    parsing_finished(); CHECK(ip != NULL); ++finds;
    memcpy(selected_ip, ip, sizeof(selected_ip)); return &default_nic;
}
static const mp_obj_type_t *mp_obj_get_type(mp_obj_t obj) {
    ++types; CHECK(obj == &default_nic || obj == &existing_nic);
    return obj == &default_nic ? &default_type : &existing_type;
}
static void check_dispatch(mod_network_socket_obj_t *s, int *error) {
    CHECK(s == &self && error != NULL);
    CHECK(s->nic == expected_nic && s->nic_protocol == expected_protocol);
}
static int fake_socket(mod_network_socket_obj_t *s, int *error) {
    parsing_finished(); check_dispatch(s, error); ++sockets;
    CHECK(!s->_private && s->state == MOD_NETWORK_SS_NEW);
    *error = socket_error;
    if (socket_error) return -1;
    ++allocations; s->_private = &native_options;
    if (mutate_input_on_creation) {
        CHECK(original_buffer == buffer_storage + 1);
        memset(buffer_storage + 1, 0xA5, value_obj.buffer.len);
    }
    return 0;
}
static int fake_settimeout(mod_network_socket_obj_t *s, mp_uint_t value, int *error) {
    check_dispatch(s, error); ++timeouts;
    CHECK(s->_private == &native_options && value == (mp_uint_t)s->timeout);
    *error = timeout_error; return timeout_error ? -1 : 0;
}
static void fake_close(mod_network_socket_obj_t *s) {
    CHECK(s == &self && s->_private == &native_options); ++closes; s->_private = NULL;
}
static int fake_setsockopt(unsigned identity, mod_network_socket_obj_t *s,
                          mp_uint_t level, mp_uint_t option, const void *value,
                          mp_uint_t length, int *error) {
    parsing_finished(); check_dispatch(s, error); ++callbacks[identity];
    CHECK(identity == (unsigned)(expected_nic == &existing_nic));
    CHECK(s->_private == &native_options);
    CHECK(level == (mp_uint_t)level_obj.integer && option == (mp_uint_t)option_obj.integer);
    CHECK(value != NULL && length == sizeof(mp_int_t));
    CHECK((uintptr_t)value % _Alignof(mp_int_t) == 0);
    CHECK(value != original_buffer); // An unaligned caller buffer must be copied.
    CHECK(!memcmp(value, &expected_value, sizeof(expected_value)));
    mp_int_t received; memcpy(&received, value, sizeof(received));
    *error = callback_error;
    if (callback_error) return -1;
    if (option == MOD_NETWORK_SO_SNDTIMEO) native_options.send_timeout = (int32_t)received;
    else if (option == MOD_NETWORK_SO_RCVTIMEO) native_options.receive_timeout = (int32_t)received;
    else if (s->type == MOD_NETWORK_SOCK_DGRAM) native_options.broadcast = received != 0;
    else native_options.nodelay = received != 0;
    return 0;
}
static int default_setsockopt(mod_network_socket_obj_t *s, mp_uint_t l, mp_uint_t o,
                             const void *v, mp_uint_t n, int *e) {
    return fake_setsockopt(0, s, l, o, v, n, e);
}
static int existing_setsockopt(mod_network_socket_obj_t *s, mp_uint_t l, mp_uint_t o,
                              const void *v, mp_uint_t n, int *e) {
    return fake_setsockopt(1, s, l, o, v, n, e);
}
static mod_network_nic_protocol_t default_protocol = {
    fake_socket, default_setsockopt, fake_settimeout, fake_close};
static mod_network_nic_protocol_t existing_protocol = {
    fake_socket, existing_setsockopt, fake_settimeout, fake_close};
static void reset(bool selected, bool stream) {
    self = (mod_network_socket_obj_t){.domain=MOD_NETWORK_AF_INET,
        .type=stream ? MOD_NETWORK_SOCK_STREAM : MOD_NETWORK_SOCK_DGRAM,
        .timeout=-1, .callback=&callback_sentinel};
    expected_nic = selected ? &existing_nic : &default_nic;
    expected_protocol = selected ? &existing_protocol : &default_protocol;
    if (selected) {
        self.nic = expected_nic; self.nic_protocol = expected_protocol;
        self._private = &native_options;
    }
    level_obj = (host_obj_t){.kind=OBJ_INT,
        .integer=stream ? MPYNN_SOCKET_IPPROTO_TCP : MOD_NETWORK_SOL_SOCKET};
    option_obj = (host_obj_t){.kind=OBJ_INT,
        .integer=stream ? MPYNN_SOCKET_TCP_NODELAY : MOD_NETWORK_SO_BROADCAST};
    value_obj = (host_obj_t){.kind=OBJ_INT, .low_bits=1};
    args[1] = &level_obj; args[2] = &option_obj; args[3] = &value_obj;
    level_conversions = option_conversions = value_conversions = integer_checks = buffers = 0;
    finds = types = sockets = allocations = callbacks[0] = callbacks[1] = timeouts = closes = 0;
    socket_error = callback_error = timeout_error = 0;
    native_options.broadcast = native_options.nodelay = false;
    native_options.send_timeout = native_options.receive_timeout = 0;
    checked_value_conversions = truncated_value_conversions = 0;
    expected_value = 1; expected_value_conversions = 1; expected_buffers = 0;
    original_buffer = NULL; mutate_input_on_creation = false;
    memset(selected_ip, 0xA5, sizeof(selected_ip));
    CHECK(nlr_top == NULL);
}
#define EXPECT_RAISE(code, expression) do { \
    nlr_buf_t outer; \
    if (nlr_push(&outer) == 0) { (void)(expression); nlr_pop(); CHECK(false); } \
    else CHECK(outer.ret_val == (void *)(intptr_t)(code)); \
    CHECK(nlr_top == NULL); \
} while (0)
"""

TESTS = r"""
static void no_network(bool selected) {
    CHECK(!finds && !types && !sockets && !allocations && !callbacks[0] && !callbacks[1]);
    CHECK(!timeouts && !closes && self.callback == &callback_sentinel);
    CHECK(self.nic == (selected ? &existing_nic : MP_OBJ_NULL));
    CHECK(self.nic_protocol == (selected ? &existing_protocol : NULL));
    CHECK(self._private == (selected ? &native_options : NULL));
    CHECK(!native_options.broadcast && !native_options.nodelay);
    CHECK(!native_options.send_timeout && !native_options.receive_timeout);
}
static void no_value(void) { CHECK(!integer_checks && !value_conversions && !buffers); }
static void test_closed_and_family(void) {
    for (unsigned selected = 0; selected < 2; ++selected) {
        reset(selected, false); self.state = MOD_NETWORK_SS_CLOSED;
        self.domain = 99; self.type = 99; self.proto = 99;
        args[1] = args[2] = args[3] = &poison_obj;
        EXPECT_RAISE(MP_EBADF, socket_setsockopt(4, args));
        CHECK(!level_conversions && !option_conversions); no_value(); no_network(selected);
        CHECK(self.state == MOD_NETWORK_SS_CLOSED);
        self.state = MOD_NETWORK_SS_NEW;
        EXPECT_RAISE(MP_EAFNOSUPPORT, socket_setsockopt(4, args));
        CHECK(!level_conversions && !option_conversions); no_value(); no_network(selected);
    }
}
static void test_unsupported(void) {
    static const int invalid[][4] = {
        {MOD_NETWORK_SOCK_DGRAM, 6, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST},
        {MOD_NETWORK_SOCK_DGRAM, -1, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST},
        {MOD_NETWORK_SOCK_DGRAM, 17, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY},
        {MOD_NETWORK_SOCK_DGRAM, 0, 0, MOD_NETWORK_SO_BROADCAST},
        {MOD_NETWORK_SOCK_DGRAM, 0, MOD_NETWORK_SOL_SOCKET, 20},
        {MOD_NETWORK_SOCK_DGRAM, 0, MOD_NETWORK_SOL_SOCKET, -1},
        {MOD_NETWORK_SOCK_STREAM, 17, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY},
        {MOD_NETWORK_SOCK_STREAM, -1, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY},
        {MOD_NETWORK_SOCK_STREAM, 6, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST},
        {MOD_NETWORK_SOCK_STREAM, 0, 0, MPYNN_SOCKET_TCP_NODELAY},
        {MOD_NETWORK_SOCK_STREAM, 0, MPYNN_SOCKET_IPPROTO_TCP, 20},
        {MOD_NETWORK_SOCK_STREAM, 0, MPYNN_SOCKET_IPPROTO_TCP, -1},
        {99, 0, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST},
        {99, 0, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY},
    };
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (size_t i = 0; i < sizeof(invalid)/sizeof(invalid[0]); ++i) {
            reset(selected, false);
            self.type = invalid[i][0]; self.proto = invalid[i][1];
            level_obj.integer = invalid[i][2]; option_obj.integer = invalid[i][3];
            args[3] = &poison_obj;
            EXPECT_RAISE(MP_EOPNOTSUPP, socket_setsockopt(4, args));
            CHECK(level_conversions == 1 && option_conversions == 1);
            no_value(); no_network(selected);
        }
    }
}
static void test_level_option_parsing(void) {
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned stream = 0; stream < 2; ++stream) {
            reset(selected, stream); level_obj.kind = OBJ_NONBUFFER; args[3] = &poison_obj;
            EXPECT_RAISE(HOST_TYPE_ERROR, socket_setsockopt(4, args));
            CHECK(level_conversions == 1 && !option_conversions); no_value(); no_network(selected);
            reset(selected, stream); option_obj.kind = OBJ_NONBUFFER; args[3] = &poison_obj;
            EXPECT_RAISE(HOST_TYPE_ERROR, socket_setsockopt(4, args));
            CHECK(level_conversions == 1 && option_conversions == 1); no_value(); no_network(selected);
        }
    }
}
static void set_buffer(mp_int_t value) {
    memcpy(buffer_storage + 1, &value, sizeof(value));
    value_obj = (host_obj_t){.kind=OBJ_BUFFER,
        .buffer={buffer_storage + 1, sizeof(mp_int_t), 'B'}};
    expected_value = value; original_buffer = buffer_storage + 1;
    expected_value_conversions = 0; expected_buffers = 1;
    CHECK((uintptr_t)original_buffer % _Alignof(mp_int_t) != 0);
}
static void test_bad_values(void) {
    const size_t lengths[] = {0, 1, sizeof(mp_int_t)-1, sizeof(mp_int_t)+1, 2*sizeof(mp_int_t)};
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned stream = 0; stream < 2; ++stream) {
            for (size_t i = 0; i <= sizeof(lengths)/sizeof(lengths[0]); ++i) {
                reset(selected, stream); set_buffer(1);
                if (i == sizeof(lengths)/sizeof(lengths[0])) value_obj.buffer.buf = NULL;
                else value_obj.buffer.len = lengths[i];
                EXPECT_RAISE(MP_EINVAL, socket_setsockopt(4, args));
                CHECK(integer_checks == 1 && buffers == 1 && !value_conversions);
                no_network(selected);
            }
            reset(selected, stream); value_obj.kind = OBJ_NONBUFFER;
            // An object convertible to int is not an integer and must request a buffer.
            value_obj.integer = 1;
            EXPECT_RAISE(HOST_TYPE_ERROR, socket_setsockopt(4, args));
            CHECK(integer_checks == 1 && buffers == 1 && !value_conversions); no_network(selected);
            reset(selected, stream); args[3] = mp_const_none;
            EXPECT_RAISE(HOST_TYPE_ERROR, socket_setsockopt(4, args));
            CHECK(integer_checks == 1 && buffers == 1 && !value_conversions); no_network(selected);
        }
    }
}
static void successful_dispatch(bool selected, bool stream) {
    CHECK(socket_setsockopt(4, args) == mp_const_none);
    CHECK(finds == !selected && types == !selected && sockets == !selected && allocations == !selected);
    CHECK(callbacks[selected] == 1 && callbacks[!selected] == 0 && !timeouts && !closes);
    CHECK(self.nic == expected_nic && self.nic_protocol == expected_protocol);
    CHECK(self._private == &native_options && self.callback == &callback_sentinel);
    CHECK(self.state == MOD_NETWORK_SS_NEW && !self.bound && self.timeout == -1);
    if (option_obj.integer == MOD_NETWORK_SO_SNDTIMEO || option_obj.integer == MOD_NETWORK_SO_RCVTIMEO) {
        CHECK((option_obj.integer == MOD_NETWORK_SO_SNDTIMEO ? native_options.send_timeout
            : native_options.receive_timeout) == expected_value);
        CHECK(!(option_obj.integer == MOD_NETWORK_SO_SNDTIMEO ? native_options.receive_timeout
            : native_options.send_timeout));
        CHECK(!native_options.broadcast && !native_options.nodelay);
    } else {
        CHECK((stream ? native_options.nodelay : native_options.broadcast) == (expected_value != 0));
        CHECK(!(stream ? native_options.broadcast : native_options.nodelay));
        CHECK(!native_options.send_timeout && !native_options.receive_timeout);
    }
    if (!selected) CHECK(!memcmp(selected_ip, (byte[4]){0}, sizeof(selected_ip)));
    CHECK(nlr_top == NULL);
}
static void test_integer_dispatch(void) {
    const mp_uint_t bits[] = {0, 1, 2, UINTPTR_MAX, (mp_uint_t)INTPTR_MAX,
        (mp_uint_t)INTPTR_MAX + 1};
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned stream = 0; stream < 2; ++stream) {
            for (unsigned explicit_proto = 0; explicit_proto < 2; ++explicit_proto) {
                for (size_t i = 0; i < sizeof(bits)/sizeof(bits[0]); ++i) {
                    reset(selected, stream); self.proto = explicit_proto ? (stream ? 6 : 17) : 0;
                    value_obj.low_bits = bits[i]; value_obj.truncated_only = true;
                    memcpy(&expected_value, &bits[i], sizeof(expected_value));
                    successful_dispatch(selected, stream);
                    CHECK(value_conversions == 1 && !buffers);
                }
                for (unsigned boolean = 0; boolean < 2; ++boolean) {
                    reset(selected, stream); self.proto = explicit_proto ? (stream ? 6 : 17) : 0;
                    value_obj.kind = OBJ_BOOL; value_obj.low_bits = boolean; expected_value = boolean;
                    successful_dispatch(selected, stream);
                    CHECK(value_conversions == 1 && !buffers);
                }
            }
        }
    }
}
static void test_buffer_dispatch(void) {
    const mp_int_t values[] = {0, 1, -1, INTPTR_MIN, INTPTR_MAX};
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned stream = 0; stream < 2; ++stream) {
            for (unsigned explicit_proto = 0; explicit_proto < 2; ++explicit_proto) {
                for (size_t i = 0; i < sizeof(values)/sizeof(values[0]); ++i) {
                    reset(selected, stream); self.proto = explicit_proto ? (stream ? 6 : 17) : 0;
                    set_buffer(values[i]);
                    successful_dispatch(selected, stream);
                    CHECK(buffers == 1 && !value_conversions);
                    CHECK(!memcmp(original_buffer, &expected_value, sizeof(expected_value)));
                }
            }
            // Creation may call into the VM/NIC: copy before it can change the caller buffer.
            if (!selected) {
                reset(false, stream); set_buffer(-1); mutate_input_on_creation = true;
                successful_dispatch(false, stream);
                CHECK(memcmp(original_buffer, &expected_value, sizeof(expected_value)) != 0);
            }
        }
    }
}
static void test_callback_failure(void) {
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned stream = 0; stream < 2; ++stream) {
            reset(selected, stream);
            native_options.broadcast = true; native_options.nodelay = true;
            self.bound = selected; self.state = selected ? MOD_NETWORK_SS_CONNECTED : MOD_NETWORK_SS_NEW;
            value_obj.low_bits = 0; expected_value = 0; callback_error = MP_ENETDOWN;
            EXPECT_RAISE(MP_ENETDOWN, socket_setsockopt(4, args));
            CHECK(native_options.broadcast && native_options.nodelay);
            CHECK(callbacks[selected] == 1 && finds == !selected && sockets == !selected);
            CHECK(self.nic == expected_nic && self.nic_protocol == expected_protocol);
            CHECK(self._private == &native_options && !closes && self.bound == selected);
            CHECK(self.state == (selected ? MOD_NETWORK_SS_CONNECTED : MOD_NETWORK_SS_NEW));
            callback_error = 0;
            // Reset only parsing observations, retaining the same created/existing NIC.
            level_conversions = option_conversions = integer_checks = value_conversions = buffers = 0;
            CHECK(socket_setsockopt(4, args) == mp_const_none);
            CHECK(callbacks[selected] == 2 && finds == !selected && sockets == !selected);
            CHECK(!(stream ? native_options.nodelay : native_options.broadcast));
            CHECK(stream ? native_options.broadcast : native_options.nodelay);
        }
    }
}
static void test_creation_failure(void) {
    for (unsigned stream = 0; stream < 2; ++stream) {
        reset(false, stream); socket_error = MP_ENOMEM;
        EXPECT_RAISE(MP_ENOMEM, socket_setsockopt(4, args));
        CHECK(finds == 1 && types == 1 && sockets == 1 && !allocations);
        CHECK(!callbacks[0] && !callbacks[1] && !self._private && !closes);
        CHECK(self.nic == MP_OBJ_NULL && self.nic_protocol == NULL && self.state == MOD_NETWORK_SS_NEW);
        socket_error = 0;
        level_conversions = option_conversions = integer_checks = value_conversions = buffers = 0;
        CHECK(socket_setsockopt(4, args) == mp_const_none);
        CHECK(finds == 2 && types == 2 && sockets == 2 && allocations == 1 && callbacks[0] == 1);
        CHECK(self.nic == &default_nic && self.nic_protocol == &default_protocol);
        CHECK(self._private == &native_options && !closes);
    }
}
static void reset_timeout(bool selected, bool stream, unsigned explicit_proto, unsigned receive) {
    reset(selected, stream);
    self.proto = explicit_proto ? (stream ? 6 : 17) : 0;
    level_obj.integer = MOD_NETWORK_SOL_SOCKET;
    option_obj.integer = receive ? MOD_NETWORK_SO_RCVTIMEO : MOD_NETWORK_SO_SNDTIMEO;
}
static void set_timeout_integer(mp_int_t value) {
    value_obj.integer = value;
    // Deliberately different truncation bits prove get_int(), not truncated(), was used.
    value_obj.low_bits = 123456;
    expected_value = value;
}
static void set_timeout_buffer(const int32_t *words, unsigned count, mp_int_t expected) {
    memcpy(buffer_storage + 1, words, count * sizeof(*words));
    value_obj = (host_obj_t){.kind=OBJ_BUFFER,
        .buffer={buffer_storage + 1, count * sizeof(*words), 'B'}};
    expected_value = expected; original_buffer = buffer_storage + 1;
    expected_value_conversions = 0; expected_buffers = 1;
    CHECK((uintptr_t)original_buffer % _Alignof(mp_int_t) != 0);
}
static void test_timeout_unsupported(void) {
    static const int invalid[][3] = {
        {MOD_NETWORK_SOCK_DGRAM, 6, MOD_NETWORK_SOL_SOCKET},
        {MOD_NETWORK_SOCK_DGRAM, -1, MOD_NETWORK_SOL_SOCKET},
        {MOD_NETWORK_SOCK_STREAM, 17, MOD_NETWORK_SOL_SOCKET},
        {MOD_NETWORK_SOCK_STREAM, -1, MOD_NETWORK_SOL_SOCKET},
        {99, 0, MOD_NETWORK_SOL_SOCKET},
        {MOD_NETWORK_SOCK_DGRAM, 17, MPYNN_SOCKET_IPPROTO_TCP},
        {MOD_NETWORK_SOCK_STREAM, 6, MPYNN_SOCKET_IPPROTO_TCP},
        {MOD_NETWORK_SOCK_DGRAM, 0, 0}, {MOD_NETWORK_SOCK_STREAM, 0, 0},
    };
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned receive = 0; receive < 2; ++receive) {
            for (size_t i = 0; i < sizeof(invalid)/sizeof(invalid[0]); ++i) {
                reset_timeout(selected, false, 0, receive);
                self.type = invalid[i][0]; self.proto = invalid[i][1];
                level_obj.integer = invalid[i][2]; args[3] = &poison_obj;
                EXPECT_RAISE(MP_EOPNOTSUPP, socket_setsockopt(4, args));
                no_value(); no_network(selected);
            }
        }
    }
}
static void test_timeout_integers(void) {
    const mp_int_t values[] = {0, 1, 999, 1000, INT32_MAX};
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned stream = 0; stream < 2; ++stream) {
            for (unsigned explicit_proto = 0; explicit_proto < 2; ++explicit_proto) {
                for (unsigned receive = 0; receive < 2; ++receive) {
                    for (size_t i = 0; i < sizeof(values)/sizeof(values[0]); ++i) {
                        reset_timeout(selected, stream, explicit_proto, receive);
                        set_timeout_integer(values[i]);
                        successful_dispatch(selected, stream);
                        CHECK(checked_value_conversions == 1 && !truncated_value_conversions && !buffers);
                    }
                    for (unsigned boolean = 0; boolean < 2; ++boolean) {
                        reset_timeout(selected, stream, explicit_proto, receive);
                        set_timeout_integer(boolean); value_obj.kind = OBJ_BOOL;
                        successful_dispatch(selected, stream);
                        CHECK(checked_value_conversions == 1 && !truncated_value_conversions);
                    }
                }
            }
        }
    }
}
static void test_timeout_buffers(void) {
    static const struct { int32_t words[2]; unsigned count; mp_int_t expected; } cases[] = {
        {{0}, 1, 0}, {{1}, 1, 1}, {{INT32_MAX}, 1, INT32_MAX},
        {{0, 0}, 2, 0}, {{0, 1}, 2, 1}, {{0, 999}, 2, 1},
        {{0, 1000}, 2, 1}, {{0, 1001}, 2, 2}, {{0, 999999}, 2, 1000},
        {{1, 1}, 2, 1001}, {{2147483, 646001}, 2, INT32_MAX},
        {{2147483, 647000}, 2, INT32_MAX},
    };
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned stream = 0; stream < 2; ++stream) {
            for (unsigned explicit_proto = 0; explicit_proto < 2; ++explicit_proto) {
                for (unsigned receive = 0; receive < 2; ++receive) {
                    for (size_t i = 0; i < sizeof(cases)/sizeof(cases[0]); ++i) {
                        reset_timeout(selected, stream, explicit_proto, receive);
                        set_timeout_buffer(cases[i].words, cases[i].count, cases[i].expected);
                        mutate_input_on_creation = !selected;
                        successful_dispatch(selected, stream);
                        CHECK(buffers == 1 && !checked_value_conversions && !truncated_value_conversions);
                        if (selected) CHECK(!memcmp(original_buffer, cases[i].words, value_obj.buffer.len));
                        else CHECK(memcmp(original_buffer, cases[i].words, value_obj.buffer.len) != 0);
                    }
                }
            }
        }
    }
}
static void test_timeout_bad_values(void) {
    const mp_int_t integers[] = {-1, INTPTR_MIN,
        #if INTPTR_MAX > INT32_MAX
        (mp_int_t)INT32_MAX + 1, (mp_int_t)UINT32_MAX + 1, INTPTR_MAX,
        #endif
    };
    static const struct { int32_t words[2]; unsigned count; } bad[] = {
        {{-1}, 1}, {{INT32_MIN}, 1}, {{-1, 0}, 2}, {{0, -1}, 2},
        {{0, 1000000}, 2}, {{0, INT32_MAX}, 2}, {{INT32_MAX, 0}, 2},
        {{2147484, 0}, 2}, {{2147483, 647001}, 2},
    };
    const size_t lengths[] = {0, 1, 2, 3, 5, 6, 7, 9, 16};
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned stream = 0; stream < 2; ++stream) {
            for (unsigned receive = 0; receive < 2; ++receive) {
                for (size_t i = 0; i < sizeof(integers)/sizeof(integers[0]); ++i) {
                    reset_timeout(selected, stream, 0, receive); set_timeout_integer(integers[i]);
                    EXPECT_RAISE(MP_EINVAL, socket_setsockopt(4, args));
                    CHECK(checked_value_conversions == 1 && !truncated_value_conversions && !buffers);
                    no_network(selected);
                }
                for (size_t i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) {
                    reset_timeout(selected, stream, 0, receive);
                    set_timeout_buffer(bad[i].words, bad[i].count, 0);
                    EXPECT_RAISE(MP_EINVAL, socket_setsockopt(4, args));
                    CHECK(buffers == 1 && !value_conversions); no_network(selected);
                }
                for (size_t i = 0; i < sizeof(lengths)/sizeof(lengths[0]) + 2; ++i) {
                    reset_timeout(selected, stream, 0, receive);
                    set_timeout_buffer((int32_t[2]){0, 0}, 2, 0);
                    if (i < sizeof(lengths)/sizeof(lengths[0])) value_obj.buffer.len = lengths[i];
                    else { value_obj.buffer.buf = NULL; value_obj.buffer.len = i % 2 ? 4 : 8; }
                    EXPECT_RAISE(MP_EINVAL, socket_setsockopt(4, args));
                    CHECK(buffers == 1 && !value_conversions); no_network(selected);
                }
                for (unsigned none = 0; none < 2; ++none) {
                    reset_timeout(selected, stream, 0, receive);
                    value_obj.kind = OBJ_NONBUFFER; if (none) args[3] = mp_const_none;
                    EXPECT_RAISE(HOST_TYPE_ERROR, socket_setsockopt(4, args));
                    CHECK(buffers == 1 && !value_conversions); no_network(selected);
                }
            }
        }
    }
}
static void test_timeout_independent_and_failure(void) {
    for (unsigned stream = 0; stream < 2; ++stream) {
        reset_timeout(true, stream, 1, 0); set_timeout_integer(123);
        CHECK(socket_setsockopt(4, args) == mp_const_none);
        CHECK(native_options.send_timeout == 123 && !native_options.receive_timeout);
        level_conversions = option_conversions = integer_checks = value_conversions = buffers = 0;
        option_obj.integer = MOD_NETWORK_SO_RCVTIMEO; set_timeout_integer(456);
        CHECK(socket_setsockopt(4, args) == mp_const_none);
        CHECK(native_options.send_timeout == 123 && native_options.receive_timeout == 456);
        level_conversions = option_conversions = integer_checks = value_conversions = buffers = 0;
        set_timeout_integer(0); callback_error = MP_ENETDOWN;
        EXPECT_RAISE(MP_ENETDOWN, socket_setsockopt(4, args));
        CHECK(native_options.send_timeout == 123 && native_options.receive_timeout == 456);
        level_conversions = option_conversions = integer_checks = value_conversions = buffers = 0;
        callback_error = 0;
        CHECK(socket_setsockopt(4, args) == mp_const_none);
        CHECK(native_options.send_timeout == 123 && !native_options.receive_timeout);
        CHECK(!finds && !sockets && !timeouts && !closes && callbacks[1] == 4);
        CHECK(self.timeout == -1 && !native_options.broadcast && !native_options.nodelay);
    }
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    if (!strcmp(argv[1], "closed-family")) test_closed_and_family();
    else if (!strcmp(argv[1], "unsupported")) test_unsupported();
    else if (!strcmp(argv[1], "level-option")) test_level_option_parsing();
    else if (!strcmp(argv[1], "bad-values")) test_bad_values();
    else if (!strcmp(argv[1], "integers")) test_integer_dispatch();
    else if (!strcmp(argv[1], "buffers")) test_buffer_dispatch();
    else if (!strcmp(argv[1], "callback-failure")) test_callback_failure();
    else if (!strcmp(argv[1], "creation-failure")) test_creation_failure();
    else if (!strcmp(argv[1], "timeout-unsupported")) test_timeout_unsupported();
    else if (!strcmp(argv[1], "timeout-integers")) test_timeout_integers();
    else if (!strcmp(argv[1], "timeout-buffers")) test_timeout_buffers();
    else if (!strcmp(argv[1], "timeout-bad-values")) test_timeout_bad_values();
    else if (!strcmp(argv[1], "timeout-independent-failure")) test_timeout_independent_and_failure();
    else CHECK(false);
    puts("PASS"); return 0;
}
"""


class SocketSetsockoptHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("gcc")
        if compiler is None and FALLBACK_GCC.is_file():
            compiler = str(FALLBACK_GCC)
        if compiler is None:
            raise unittest.SkipTest("host GCC unavailable")
        source = MODSOCKET.read_text(encoding="utf-8")
        definitions = "\n\n".join(extract_function(source, name)
                                  for name in ("socket_select_nic", "socket_timeout_buffer_ms", "socket_setsockopt"))
        # Use production option constants rather than independent test inventions.
        constants = []
        for path, names in (
            (ROOT / "lib/micropython/extmod/modnetwork.h",
             ("MOD_NETWORK_SOL_SOCKET", "MOD_NETWORK_SO_BROADCAST",
               "MOD_NETWORK_SO_SNDTIMEO", "MOD_NETWORK_SO_RCVTIMEO")),
            (ROOT / "ports/raspberrypi/socket_port.h",
             ("MPYNN_SOCKET_IPPROTO_TCP", "MPYNN_SOCKET_TCP_NODELAY")),
        ):
            header = path.read_text(encoding="utf-8")
            for name in names:
                match = re.search(rf"^#define\s+{name}\s+.+$", header, re.MULTILINE)
                if match is None:
                    raise AssertionError(f"Missing production constant {name}")
                constants.append(match.group())
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-setsockopt-host-")
        cls.addClassCleanup(cleanup_with_retry, temporary)
        root = Path(temporary.name)
        c_file = root / "setsockopt.c"
        cls.executable = root / "setsockopt.exe"
        c_file.write_text("\n".join(constants) + "\n" + PRELUDE + "\n" + definitions + "\n" + TESTS,
                          encoding="utf-8")
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(Path(compiler).parent) + os.pathsep + cls.env.get("PATH", "")
        result = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                                 str(c_file), "-o", str(cls.executable)],
                                env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host GCC compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, name):
        result = subprocess.run([str(self.executable), name], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_closed_and_wrong_family_precede_poison_argument_parsing(self):
        self.run_scenario("closed-family")

    def test_unsupported_type_proto_level_option_precede_value_and_nic(self):
        self.run_scenario("unsupported")

    def test_level_and_option_use_vm_integer_conversion_before_nic(self):
        self.run_scenario("level-option")

    def test_bad_buffer_length_null_nonbuffer_and_none_precede_nic(self):
        self.run_scenario("bad-values")

    def test_integer_truncation_and_booleans_dispatch_both_nics_and_protocols(self):
        self.run_scenario("integers")

    def test_unaligned_native_buffers_are_copied_before_nic_selection(self):
        self.run_scenario("buffers")

    def test_callback_failure_retains_old_options_and_selected_nic_for_retry(self):
        self.run_scenario("callback-failure")

    def test_creation_failure_rolls_back_selection_and_retries_creation(self):
        self.run_scenario("creation-failure")

    def test_timeout_type_protocol_and_level_rejected_before_value_or_nic(self):
        self.run_scenario("timeout-unsupported")

    def test_timeout_integer_milliseconds_do_not_truncate_and_allow_zero_and_max(self):
        self.run_scenario("timeout-integers")

    def test_timeout_unaligned_int32_and_timeval_buffers_round_up_before_nic(self):
        self.run_scenario("timeout-buffers")

    def test_timeout_negative_overflow_bad_size_null_and_timeval_range_precede_nic(self):
        self.run_scenario("timeout-bad-values")

    def test_timeout_options_independent_of_each_other_and_vm_timeout_on_callback_failure(self):
        self.run_scenario("timeout-independent-failure")


if __name__ == "__main__":
    unittest.main()
