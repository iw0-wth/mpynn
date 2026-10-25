# SPDX-License-Identifier: MIT
"""Compile and execute the real modsocket address parser and wrappers on host."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODSOCKET = ROOT / "ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c"
FALLBACK_GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")


def extract_function(source, name):
    """Return one complete static C definition, excluding following object macros."""
    match = re.search(
        rf"^static\s+(?:mp_uint_t|mp_obj_t)\s+{re.escape(name)}\s*\(",
        source,
        re.MULTILINE,
    )
    if match is None:
        raise AssertionError(f"Could not find static definition of {name}")
    opening = source.find("{", match.end())
    if opening < 0:
        raise AssertionError(f"Could not find body of {name}")

    depth = 0
    state = "code"
    escaped = False
    index = opening
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == "/" and following == "*":
                state = "block-comment"
                index += 1
            elif char == "/" and following == "/":
                state = "line-comment"
                index += 1
            elif char == '"':
                state = "string"
                escaped = False
            elif char == "'":
                state = "character"
                escaped = False
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return source[match.start() : index + 1]
        elif state == "block-comment":
            if char == "*" and following == "/":
                state = "code"
                index += 1
        elif state == "line-comment":
            if char == "\n":
                state = "code"
        elif state in ("string", "character"):
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif (state == "string" and char == '"') or (state == "character" and char == "'"):
                state = "code"
        index += 1
    raise AssertionError(f"Unterminated C definition of {name}")


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
/* Match the RP2040 MicroPython ABI rather than the host's pointer width. */
typedef uint32_t mp_uint_t;
typedef int32_t mp_int_t;
typedef void *mp_obj_t;
typedef const void *mp_const_obj_t;
#define MP_OBJ_NULL ((mp_obj_t)NULL)
#define MP_OBJ_TO_PTR(obj) ((void *)(obj))
#define MP_OBJ_FROM_PTR(ptr) ((mp_obj_t)(ptr))
#define MP_ERROR_TEXT(message) (message)
#define MP_BUFFER_READ 1
#define MOD_NETWORK_IPADDR_BUF_SIZE 4
#define MOD_NETWORK_SS_CLOSED 3
#define MOD_NETWORK_SS_CONNECTED 2
#define MP_EBADF 9

typedef struct {
    void *buf;
    size_t len;
} mp_buffer_info_t;

typedef struct mod_network_socket_obj_t mod_network_socket_obj_t;
typedef struct {
    int (*bind)(mod_network_socket_obj_t *, byte *, mp_uint_t, int *);
    int (*connect)(mod_network_socket_obj_t *, byte *, mp_uint_t, int *);
    mp_uint_t (*sendto)(mod_network_socket_obj_t *, const byte *, mp_uint_t,
                        byte *, mp_uint_t, int *);
} mod_network_nic_protocol_t;
struct mod_network_socket_obj_t {
    mp_obj_t nic;
    mod_network_nic_protocol_t *nic_protocol;
    int state;
};

enum { VM_VALUE_ERROR = 1, VM_TYPE_ERROR = 2, VM_OS_ERROR = 3 };
static jmp_buf raise_target;
static int raised_kind;
static int raised_code;
static unsigned array_calls, string_calls, integer_calls, buffer_calls;
static unsigned selector_calls, nic_selections;
static unsigned bind_calls, connect_calls, sendto_calls, integer_results;
static uint8_t selected_ip[4], native_ip[4];
static mp_uint_t native_port, native_length;
static const byte *native_data;
static int native_error;

static _Noreturn void raise_vm(int kind, int code) {
    raised_kind = kind;
    raised_code = code;
    longjmp(raise_target, 1);
}
static _Noreturn void mp_raise_ValueError(const char *message) {
    if (message == NULL) abort();
    raise_vm(VM_VALUE_ERROR, 0);
}
static _Noreturn void mp_raise_TypeError(const char *message) {
    if (message == NULL) abort();
    raise_vm(VM_TYPE_ERROR, 0);
}
static _Noreturn void mp_raise_OSError(int code) {
    raise_vm(VM_OS_ERROR, code);
}

enum { OBJ_ARRAY = 1, OBJ_LIST, OBJ_STRING, OBJ_INTEGER, OBJ_OTHER };
typedef struct {
    int kind;
    const char *string;
    size_t length;
    mp_int_t integer;
    size_t count;
    mp_obj_t items[3];
} vm_obj_t;
static vm_obj_t address_obj, host_obj, port_obj, data_obj, bad_data_obj, int_result_obj;
static vm_obj_t none_obj;
const mp_obj_t mp_const_none = &none_obj;
static byte send_buffer[4] = {0x41, 0x42, 0x43, 0x44};
static int default_nic_token, existing_nic_token;
static mod_network_socket_obj_t test_socket;
static mod_network_nic_protocol_t test_protocol;

static void mp_obj_get_array_fixed_n(mp_obj_t obj, size_t n, mp_obj_t **items);
static const char *mp_obj_str_get_data(mp_obj_t obj, size_t *length);
static mp_int_t mp_obj_get_int(mp_obj_t obj);
static void mp_get_buffer_raise(mp_obj_t obj, mp_buffer_info_t *buffer, unsigned flags);
static mp_obj_t mp_obj_new_int(mp_int_t value);
static void socket_select_nic(mod_network_socket_obj_t *self, const byte *ip);

static void mp_obj_get_array_fixed_n(mp_obj_t obj, size_t n, mp_obj_t **items) {
    ++array_calls;
    if (obj == NULL) mp_raise_TypeError("expected address tuple");
    vm_obj_t *array = MP_OBJ_TO_PTR(obj);
    if (array->kind != OBJ_ARRAY && array->kind != OBJ_LIST) {
        mp_raise_TypeError("expected address tuple");
    }
    if (array->count != n) mp_raise_ValueError("wrong address tuple length");
    *items = array->items;
}
static const char *mp_obj_str_get_data(mp_obj_t obj, size_t *length) {
    ++string_calls;
    if (obj == NULL || ((vm_obj_t *)MP_OBJ_TO_PTR(obj))->kind != OBJ_STRING) {
        mp_raise_TypeError("expected string");
    }
    vm_obj_t *string = MP_OBJ_TO_PTR(obj);
    *length = string->length;
    return string->string;
}
static mp_int_t mp_obj_get_int(mp_obj_t obj) {
    ++integer_calls;
    if (obj == NULL || ((vm_obj_t *)MP_OBJ_TO_PTR(obj))->kind != OBJ_INTEGER) {
        mp_raise_TypeError("expected integer");
    }
    return ((vm_obj_t *)MP_OBJ_TO_PTR(obj))->integer;
}
static void mp_get_buffer_raise(mp_obj_t obj, mp_buffer_info_t *buffer, unsigned flags) {
    ++buffer_calls;
    if (obj != MP_OBJ_FROM_PTR(&data_obj) || flags != MP_BUFFER_READ) {
        mp_raise_TypeError("expected readable buffer");
    }
    buffer->buf = send_buffer;
    buffer->len = sizeof(send_buffer);
}
static mp_obj_t mp_obj_new_int(mp_int_t value) {
    ++integer_results;
    int_result_obj.kind = OBJ_INTEGER;
    int_result_obj.integer = value;
    return MP_OBJ_FROM_PTR(&int_result_obj);
}

static int fake_bind(mod_network_socket_obj_t *self, byte *ip, mp_uint_t port, int *error) {
    if (self->nic == MP_OBJ_NULL || self->nic_protocol != &test_protocol || error == NULL) abort();
    ++bind_calls;
    memcpy(native_ip, ip, sizeof(native_ip));
    native_port = port;
    *error = native_error;
    return native_error ? -1 : 0;
}
static int fake_connect(mod_network_socket_obj_t *self, byte *ip, mp_uint_t port, int *error) {
    if (self->nic == MP_OBJ_NULL || self->nic_protocol != &test_protocol || error == NULL) abort();
    ++connect_calls;
    memcpy(native_ip, ip, sizeof(native_ip));
    native_port = port;
    *error = native_error;
    return native_error ? -1 : 0;
}
static mp_uint_t fake_sendto(mod_network_socket_obj_t *self, const byte *data, mp_uint_t length,
                             byte *ip, mp_uint_t port, int *error) {
    if (self->nic == MP_OBJ_NULL || self->nic_protocol != &test_protocol || error == NULL) abort();
    ++sendto_calls;
    native_data = data;
    native_length = length;
    memcpy(native_ip, ip, sizeof(native_ip));
    native_port = port;
    *error = native_error;
    return native_error ? (mp_uint_t)-1 : length;
}
static mod_network_nic_protocol_t test_protocol = {fake_bind, fake_connect, fake_sendto};
static void socket_select_nic(mod_network_socket_obj_t *self, const byte *ip) {
    ++selector_calls;
    if (self->nic == MP_OBJ_NULL) {
        self->nic = MP_OBJ_FROM_PTR(&default_nic_token);
        self->nic_protocol = &test_protocol;
        memcpy(selected_ip, ip, sizeof(selected_ip));
        ++nic_selections;
    }
}

static void reset_socket(void) {
    test_socket.nic = MP_OBJ_NULL;
    test_socket.nic_protocol = NULL;
    test_socket.state = 0;
}
static void set_address_string(const char *host, size_t host_length, mp_int_t port) {
    host_obj.kind = OBJ_STRING;
    host_obj.string = host;
    host_obj.length = host_length;
    port_obj.kind = OBJ_INTEGER;
    port_obj.integer = port;
    address_obj.kind = OBJ_ARRAY;
    address_obj.count = 2;
    address_obj.items[0] = MP_OBJ_FROM_PTR(&host_obj);
    address_obj.items[1] = MP_OBJ_FROM_PTR(&port_obj);
}
static void reset_raises(void) {
    raised_kind = 0;
    raised_code = 0;
}
#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "line %d: %s\n", __LINE__, #condition); \
        exit(1); \
    } \
} while (0)
#define EXPECT_RAISE(kind_, code_, expression_) do { \
    reset_raises(); \
    if (setjmp(raise_target) == 0) { \
        (void)(expression_); \
        CHECK(false); \
    } \
    CHECK(raised_kind == (kind_)); \
    CHECK(raised_code == (code_)); \
} while (0)
"""

TESTS = r"""
static void parser_success(const char *host, size_t length, mp_int_t port,
                           const byte expected[4]) {
    set_address_string(host, length, port);
    byte output[4] = {0xA5, 0xA5, 0xA5, 0xA5};
    mp_uint_t parsed_port = socket_parse_address(MP_OBJ_FROM_PTR(&address_obj), output);
    CHECK(parsed_port == (mp_uint_t)port);
    CHECK(memcmp(output, expected, 4) == 0);
}
static void parser_failure(mp_obj_t address, int kind) {
    byte output[4] = {0xA5, 0x5A, 0xC3, 0x3C};
    static const byte sentinel[4] = {0xA5, 0x5A, 0xC3, 0x3C};
    EXPECT_RAISE(kind, 0, socket_parse_address(address, output));
    CHECK(memcmp(output, sentinel, sizeof(sentinel)) == 0);
}
static void test_parser_valid(void) {
    static const byte zero[4] = {0, 0, 0, 0};
    static const byte max[4] = {255, 255, 255, 255};
    static const byte leading[4] = {1, 2, 3, 4};
    static const byte mixed[4] = {255, 0, 1, 255};
    parser_success("0.0.0.0", 7, 0, zero);
    parser_success("255.255.255.255", 15, 65535, max);
    parser_success("001.002.003.004", 15, 42, leading);
    parser_success("255.000.001.255", 15, 0, mixed);
    parser_success("", 0, 65535, zero); // Empty host is the wildcard.
}
static void test_parser_invalid_syntax(void) {
    static const char embedded_nul[] = {'1','.','2','.','3','.','4','\0','x'};
    static const char *const invalid[] = {
        "1.2.3", "1.2.3.", "1.2.3.4.5", "256.1.1.1", "1.2.999.4",
        "0000.0.0.0", "1..3.4", ".1.2.3.4", "1.2.3.-4", "+1.2.3.4",
        "1.2.3.4x", "1.2.3.4 ", " 1.2.3.4", "1.2.3.4\n"
    };
    for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        set_address_string(invalid[i], strlen(invalid[i]), 80);
        parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_VALUE_ERROR);
    }
    set_address_string(embedded_nul, sizeof(embedded_nul), 80);
    parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_VALUE_ERROR);
}
static void test_parser_invalid_shape_and_types(void) {
    set_address_string("1.2.3.4", 7, 80);
    address_obj.count = 1;
    parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_VALUE_ERROR);
    address_obj.count = 3;
    parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_VALUE_ERROR);

    address_obj.kind = OBJ_INTEGER;
    parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_TYPE_ERROR);
    parser_failure(MP_OBJ_NULL, VM_TYPE_ERROR);

    set_address_string("1.2.3.4", 7, 80);
    host_obj.kind = OBJ_INTEGER;
    parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_TYPE_ERROR);
    set_address_string("1.2.3.4", 7, 80);
    address_obj.items[0] = MP_OBJ_NULL;
    parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_TYPE_ERROR);
    set_address_string("1.2.3.4", 7, 80);
    address_obj.items[1] = MP_OBJ_NULL;
    parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_TYPE_ERROR);
    set_address_string("1.2.3.4", 7, 80);
    port_obj.kind = OBJ_STRING;
    port_obj.string = "80";
    port_obj.length = 2;
    parser_failure(MP_OBJ_FROM_PTR(&address_obj), VM_TYPE_ERROR);
}
static void test_parser_invalid_ports(void) {
    static const byte sentinel[4] = {0xA5, 0x5A, 0xC3, 0x3C};
    static const mp_int_t invalid_ports[] = {-1, 65536, INT32_MIN, INT32_MAX};
    for (size_t i = 0; i < sizeof(invalid_ports) / sizeof(invalid_ports[0]); ++i) {
        set_address_string("192.0.2.1", 9, invalid_ports[i]);
        byte output[4] = {0xA5, 0x5A, 0xC3, 0x3C};
        EXPECT_RAISE(VM_VALUE_ERROR, 0,
                     socket_parse_address(MP_OBJ_FROM_PTR(&address_obj), output));
        CHECK(memcmp(output, sentinel, sizeof(sentinel)) == 0);
    }
}
static void assert_no_native_effects(unsigned old_selector, unsigned old_selection,
                                     unsigned old_bind, unsigned old_connect,
                                     unsigned old_sendto) {
    CHECK(selector_calls == old_selector);
    CHECK(nic_selections == old_selection);
    CHECK(bind_calls == old_bind && connect_calls == old_connect && sendto_calls == old_sendto);
}
static void wrapper_reject(int operation, int kind) {
    reset_socket();
    unsigned old_selector = selector_calls, old_selection = nic_selections;
    unsigned old_bind = bind_calls, old_connect = connect_calls, old_sendto = sendto_calls;
    if (operation == 0) {
        EXPECT_RAISE(kind, 0, socket_bind(MP_OBJ_FROM_PTR(&test_socket), MP_OBJ_FROM_PTR(&address_obj)));
    } else if (operation == 1) {
        EXPECT_RAISE(kind, 0, socket_connect(MP_OBJ_FROM_PTR(&test_socket), MP_OBJ_FROM_PTR(&address_obj)));
    } else {
        EXPECT_RAISE(kind, 0, socket_sendto(MP_OBJ_FROM_PTR(&test_socket),
            MP_OBJ_FROM_PTR(&data_obj), MP_OBJ_FROM_PTR(&address_obj)));
    }
    assert_no_native_effects(old_selector, old_selection, old_bind, old_connect, old_sendto);
    CHECK(test_socket.nic == MP_OBJ_NULL && test_socket.nic_protocol == NULL);
}
static void test_wrappers_reject_without_network(void) {
    static const char embedded_nul[] = {'1','.','2','.','3','.','4','\0','x'};
    static const char *const invalid[] = {
        "1.2.3", "256.2.3.4", "1.2.3.4suffix", "-1.2.3.4"
    };
    for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        set_address_string(invalid[i], strlen(invalid[i]), 80);
        wrapper_reject((int)(i % 3), VM_VALUE_ERROR);
    }
    set_address_string(embedded_nul, sizeof(embedded_nul), 80);
    wrapper_reject(2, VM_VALUE_ERROR);
    set_address_string("1.2.3.4", 7, -1);
    wrapper_reject(0, VM_VALUE_ERROR);
    set_address_string("1.2.3.4", 7, 65536);
    wrapper_reject(1, VM_VALUE_ERROR);
    set_address_string("1.2.3.4", 7, 80);
    address_obj.count = 1;
    wrapper_reject(2, VM_VALUE_ERROR);
    set_address_string("1.2.3.4", 7, 80);
    host_obj.kind = OBJ_INTEGER;
    wrapper_reject(0, VM_TYPE_ERROR);
    set_address_string("1.2.3.4", 7, 80);
    port_obj.kind = OBJ_OTHER;
    wrapper_reject(1, VM_TYPE_ERROR);
}
static void test_wrappers_success_and_nic_state(void) {
    static const byte bind_ip[4] = {255, 0, 1, 255};
    static const byte connect_ip[4] = {1, 2, 3, 4};
    static const byte wildcard[4] = {0, 0, 0, 0};
    reset_socket();
    set_address_string("255.000.001.255", 15, 0);
    CHECK(socket_bind(MP_OBJ_FROM_PTR(&test_socket), MP_OBJ_FROM_PTR(&address_obj)) == mp_const_none);
    CHECK(bind_calls == 1 && native_port == 0 && memcmp(native_ip, bind_ip, 4) == 0);
    CHECK(selector_calls == 1 && nic_selections == 1 && memcmp(selected_ip, bind_ip, 4) == 0);
    CHECK(test_socket.nic == MP_OBJ_FROM_PTR(&default_nic_token));
    CHECK(test_socket.nic_protocol == &test_protocol);

    set_address_string("001.002.003.004", 15, 65535);
    CHECK(socket_connect(MP_OBJ_FROM_PTR(&test_socket), MP_OBJ_FROM_PTR(&address_obj)) == mp_const_none);
    CHECK(connect_calls == 1 && native_port == 65535 && memcmp(native_ip, connect_ip, 4) == 0);
    CHECK(selector_calls == 2 && nic_selections == 1);
    CHECK(test_socket.nic == MP_OBJ_FROM_PTR(&default_nic_token));

    set_address_string("", 0, 0);
    data_obj.kind = OBJ_OTHER;
    CHECK(MP_OBJ_TO_PTR(socket_sendto(MP_OBJ_FROM_PTR(&test_socket),
        MP_OBJ_FROM_PTR(&data_obj), MP_OBJ_FROM_PTR(&address_obj))) == &int_result_obj);
    CHECK(sendto_calls == 1 && native_port == 0 && memcmp(native_ip, wildcard, 4) == 0);
    CHECK(native_data == send_buffer && native_length == sizeof(send_buffer));
    CHECK(selector_calls == 3 && nic_selections == 1);
    CHECK(((vm_obj_t *)MP_OBJ_TO_PTR(&int_result_obj))->integer == (mp_int_t)sizeof(send_buffer));

    // A preselected NIC stays intact; parsing still supplies its exact IP and port.
    test_socket.nic = MP_OBJ_FROM_PTR(&existing_nic_token);
    test_socket.nic_protocol = &test_protocol;
    set_address_string("192.0.2.1", 9, 65535);
    CHECK(socket_bind(MP_OBJ_FROM_PTR(&test_socket), MP_OBJ_FROM_PTR(&address_obj)) == mp_const_none);
    CHECK(test_socket.nic == MP_OBJ_FROM_PTR(&existing_nic_token));
    CHECK(test_socket.nic_protocol == &test_protocol);
    CHECK(nic_selections == 1 && selector_calls == 4);
    CHECK(bind_calls == 2 && native_port == 65535);
    CHECK(native_ip[0] == 192 && native_ip[1] == 0 && native_ip[2] == 2 && native_ip[3] == 1);
}
static void test_closed_socket_precedes_arguments(void) {
    unsigned old_arrays = array_calls, old_strings = string_calls, old_integers = integer_calls;
    unsigned old_buffers = buffer_calls;
    unsigned old_selector = selector_calls, old_selection = nic_selections;
    unsigned old_bind = bind_calls, old_connect = connect_calls, old_sendto = sendto_calls;
    reset_socket();
    test_socket.state = MOD_NETWORK_SS_CLOSED;
    address_obj.kind = OBJ_OTHER; // Every operation must reject before inspecting it.
    address_obj.count = 0;
    bad_data_obj.kind = OBJ_OTHER;
    EXPECT_RAISE(VM_OS_ERROR, MP_EBADF,
        socket_bind(MP_OBJ_FROM_PTR(&test_socket), MP_OBJ_FROM_PTR(&address_obj)));
    EXPECT_RAISE(VM_OS_ERROR, MP_EBADF,
        socket_connect(MP_OBJ_FROM_PTR(&test_socket), MP_OBJ_NULL));
    EXPECT_RAISE(VM_OS_ERROR, MP_EBADF,
        socket_sendto(MP_OBJ_FROM_PTR(&test_socket), MP_OBJ_FROM_PTR(&bad_data_obj), MP_OBJ_NULL));
    CHECK(array_calls == old_arrays && string_calls == old_strings && integer_calls == old_integers);
    CHECK(buffer_calls == old_buffers);
    assert_no_native_effects(old_selector, old_selection, old_bind, old_connect, old_sendto);
}
int main(void) {
    test_parser_valid();
    test_parser_invalid_syntax();
    test_parser_invalid_shape_and_types();
    test_parser_invalid_ports();
    test_wrappers_reject_without_network();
    test_wrappers_success_and_nic_state();
    test_closed_socket_precedes_arguments();
    return 0;
}
"""


class SocketAddressHostTests(unittest.TestCase):
    def test_real_parser_and_address_wrappers(self):
        compiler = shutil.which("gcc")
        if compiler is None and FALLBACK_GCC.is_file():
            compiler = str(FALLBACK_GCC)
        if compiler is None:
            self.skipTest("host GCC unavailable")

        source = MODSOCKET.read_text(encoding="utf-8")
        definitions = "\n\n".join(
            extract_function(source, name)
            for name in ("socket_parse_address", "socket_bind", "socket_connect", "socket_sendto")
        )
        program = PRELUDE + "\n" + definitions + "\n" + TESTS
        env = os.environ.copy()
        env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            c_file = root / "test_socket_address_host.c"
            executable = root / "test_socket_address_host.exe"
            c_file.write_text(program, encoding="utf-8")
            compile_result = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c_file), "-o", str(executable)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            run_result = subprocess.run(
                [str(executable)], capture_output=True, text=True, timeout=30
            )
            self.assertEqual(run_result.returncode, 0, run_result.stdout + run_result.stderr)


if __name__ == "__main__":
    unittest.main()
