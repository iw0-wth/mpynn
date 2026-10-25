# SPDX-License-Identifier: MIT
"""Compile complete production listen/selection wrappers with a minimal host VM."""
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
    """Extract the full static definition, ignoring braces in comments/strings."""
    match = re.search(rf"^static\s+(?:void|mp_obj_t)\s+{re.escape(name)}\s*\(",
                      source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"Could not find static definition of {name}")
    opening = source.find("{", match.end())
    if opening < 0:
        raise AssertionError(f"Could not find body of {name}")
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
typedef int32_t mp_int_t;
typedef uint32_t mp_uint_t;
typedef void *mp_obj_t;
#define MP_OBJ_NULL ((mp_obj_t)NULL)
#define MP_OBJ_TO_PTR(obj) ((void *)(obj))
#define MP_OBJ_FROM_PTR(ptr) ((mp_obj_t)(ptr))
#define MICROPY_PY_SOCKET_EXTENDED_STATE 1
#define MOD_NETWORK_AF_INET 2
#define MOD_NETWORK_SOCK_STREAM 1
#define MOD_NETWORK_SOCK_DGRAM 2
#define MOD_NETWORK_SS_NEW 0
#define MOD_NETWORK_SS_LISTENING 1
#define MOD_NETWORK_SS_CONNECTED 2
#define MOD_NETWORK_SS_CLOSED 3
#define MP_EBADF 9
#define MP_EINVAL 22
#define MP_ENOMEM 12
#define MP_EOPNOTSUPP 95
#define MP_EAFNOSUPPORT 97
#define MP_ENETDOWN 100
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)

typedef struct mod_network_socket_obj_t mod_network_socket_obj_t;
typedef struct {
    int (*socket)(mod_network_socket_obj_t *, int *);
    int (*listen)(mod_network_socket_obj_t *, mp_int_t, int *);
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
};
typedef struct { const mod_network_nic_protocol_t *protocol; } mp_obj_type_t;
#define MP_OBJ_TYPE_GET_SLOT(type, slot) ((type)->slot)
static mod_network_nic_protocol_t default_protocol, existing_protocol;
static mp_obj_type_t default_type = {&default_protocol};
static mp_obj_type_t existing_type = {&existing_protocol};
static byte default_nic, existing_nic, none, private_sentinel;
static const mp_obj_t mp_const_none = &none;
static jmp_buf raise_target;
enum { VM_OS_ERROR = 1, VM_TYPE_ERROR = 2 };
static int raised_kind, raised_code;
static unsigned conversions, finds, types, sockets, listens, timeouts, closes;
static byte selected_ip[4];
static mp_int_t received_backlog;
static int socket_error, listen_error, timeout_error;
static int failure_state = MOD_NETWORK_SS_NEW;
static mod_network_socket_obj_t self;
static mp_obj_t expected_nic;
static mod_network_nic_protocol_t *expected_protocol;
static struct { bool integer; mp_int_t value; } backlog;
static mp_obj_t args[2] = {&self, &backlog};

static _Noreturn void mp_raise_OSError(int code) {
    raised_kind = VM_OS_ERROR; raised_code = code; longjmp(raise_target, 1);
}
static mp_int_t mp_obj_get_int(mp_obj_t obj) {
    ++conversions;
    if (obj != &backlog || !backlog.integer) {
        raised_kind = VM_TYPE_ERROR; raised_code = 0; longjmp(raise_target, 1);
    }
    return backlog.value;
}
static mp_obj_t mod_network_find_nic(const byte *ip) {
    CHECK(ip != NULL); ++finds; memcpy(selected_ip, ip, sizeof(selected_ip));
    return &default_nic;
}
static const mp_obj_type_t *mp_obj_get_type(mp_obj_t obj) {
    ++types;
    CHECK(obj == &default_nic || obj == &existing_nic);
    return obj == &default_nic ? &default_type : &existing_type;
}
static void check_dispatch(mod_network_socket_obj_t *s, int *error) {
    CHECK(s == &self && error != NULL);
    CHECK(s->nic == expected_nic && s->nic_protocol == expected_protocol);
}
static int fake_socket(mod_network_socket_obj_t *s, int *error) {
    check_dispatch(s, error); ++sockets;
    CHECK(s->state == MOD_NETWORK_SS_NEW && !s->bound && !s->_private);
    *error = socket_error;
    if (!socket_error) s->_private = &private_sentinel;
    return socket_error ? -1 : 0;
}
static int fake_timeout(mod_network_socket_obj_t *s, mp_uint_t value, int *error) {
    check_dispatch(s, error); ++timeouts;
    CHECK(s->_private == &private_sentinel && value == (mp_uint_t)s->timeout);
    *error = timeout_error; return timeout_error ? -1 : 0;
}
static void fake_close(mod_network_socket_obj_t *s) {
    CHECK(s == &self && s->_private == &private_sentinel); ++closes;
    s->_private = NULL;
}
static int fake_listen(mod_network_socket_obj_t *s, mp_int_t value, int *error) {
    check_dispatch(s, error); ++listens; received_backlog = value;
    CHECK(s->_private == &private_sentinel);
    *error = listen_error;
    if (listen_error) s->state = failure_state;
    // Success deliberately leaves self.state untouched: the real wrapper owns it.
    return listen_error ? -1 : 0;
}
static mod_network_nic_protocol_t default_protocol = {fake_socket, fake_listen, fake_timeout, fake_close};
static mod_network_nic_protocol_t existing_protocol = {fake_socket, fake_listen, fake_timeout, fake_close};
static void reset(bool selected) {
    self = (mod_network_socket_obj_t){.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM, .timeout=-1};
    expected_nic = selected ? &existing_nic : &default_nic;
    expected_protocol = selected ? &existing_protocol : &default_protocol;
    if (selected) {
        self.nic = expected_nic; self.nic_protocol = expected_protocol;
        self._private = &private_sentinel;
    }
    backlog.integer = true; backlog.value = 2;
    conversions = finds = types = sockets = listens = timeouts = closes = 0;
    socket_error = listen_error = timeout_error = raised_kind = raised_code = 0;
    failure_state = MOD_NETWORK_SS_NEW;
    memset(selected_ip, 0xA5, sizeof(selected_ip));
}
#define EXPECT_RAISE(kind, code, expression) do { \
    raised_kind = raised_code = 0; \
    if (setjmp(raise_target) == 0) { (void)(expression); CHECK(false); } \
    CHECK(raised_kind == (kind) && raised_code == (code)); \
} while (0)
"""

TESTS = r"""
static void no_network(bool selected) {
    CHECK(!finds && !types && !sockets && !listens && !timeouts && !closes);
    CHECK(self.nic == (selected ? &existing_nic : MP_OBJ_NULL));
    CHECK(self.nic_protocol == (selected ? &existing_protocol : NULL));
    CHECK(self._private == (selected ? &private_sentinel : NULL));
}
static void test_closed(void) {
    for (unsigned selected = 0; selected < 2; ++selected) {
        reset(selected); self.state = MOD_NETWORK_SS_CLOSED;
        self.domain = 99; self.type = MOD_NETWORK_SOCK_DGRAM; self.proto = 17;
        backlog.integer = false;
        EXPECT_RAISE(VM_OS_ERROR, MP_EBADF, socket_listen(2, args));
        CHECK(!conversions && self.state == MOD_NETWORK_SS_CLOSED);
        no_network(selected);
        EXPECT_RAISE(VM_OS_ERROR, MP_EBADF, socket_listen(1, args));
        CHECK(!conversions); no_network(selected);
    }
}
static void test_validation(void) {
    for (unsigned selected = 0; selected < 2; ++selected) {
        reset(selected); self.domain = 99; self.type = MOD_NETWORK_SOCK_DGRAM;
        backlog.integer = false;
        EXPECT_RAISE(VM_OS_ERROR, MP_EAFNOSUPPORT, socket_listen(2, args));
        CHECK(!conversions); no_network(selected);
        self.domain = MOD_NETWORK_AF_INET;
        EXPECT_RAISE(VM_OS_ERROR, MP_EOPNOTSUPP, socket_listen(2, args));
        CHECK(!conversions); no_network(selected);
        self.type = MOD_NETWORK_SOCK_STREAM; self.proto = 17;
        EXPECT_RAISE(VM_OS_ERROR, MP_EOPNOTSUPP, socket_listen(2, args));
        CHECK(!conversions); no_network(selected);
        self.proto = 6;
        EXPECT_RAISE(VM_TYPE_ERROR, 0, socket_listen(2, args));
        CHECK(conversions == 1 && self.state == MOD_NETWORK_SS_NEW);
        no_network(selected);
    }
}
static void test_dispatch(void) {
    static const mp_int_t values[] = {INT32_MIN, -1, 0, 1, 4, 99, INT32_MAX};
    static const byte wildcard[4] = {0};
    for (unsigned selected = 0; selected < 2; ++selected) {
        for (unsigned proto = 0; proto < 2; ++proto) {
            for (size_t index = 0; index <= sizeof(values)/sizeof(values[0]); ++index) {
                reset(selected); self.proto = proto ? 6 : 0;
                bool defaults = index == sizeof(values)/sizeof(values[0]);
                backlog.integer = !defaults; // Omitted backlog must not be converted.
                if (!defaults) backlog.value = values[index];
                CHECK(socket_listen(defaults ? 1 : 2, args) == mp_const_none);
                CHECK(received_backlog == (defaults ? MICROPY_PY_SOCKET_LISTEN_BACKLOG_DEFAULT
                    : values[index] < 0 ? 0 : values[index]));
                CHECK(conversions == (defaults ? 0u : 1u) && listens == 1);
                CHECK(finds == !selected && types == !selected && sockets == !selected);
                CHECK(!timeouts && !closes && self.nic == expected_nic);
                CHECK(self.nic_protocol == expected_protocol && self._private == &private_sentinel);
                CHECK(self.state == MOD_NETWORK_SS_LISTENING && !self.bound);
                if (!selected) CHECK(!memcmp(selected_ip, wildcard, sizeof(wildcard)));
            }
        }
    }
}
static void test_callback_failure(void) {
    for (unsigned selected = 0; selected < 2; ++selected) {
        reset(selected); listen_error = MP_ENETDOWN;
        EXPECT_RAISE(VM_OS_ERROR, MP_ENETDOWN, socket_listen(2, args));
        CHECK(self.state == MOD_NETWORK_SS_NEW && !self.bound);
        CHECK(self.nic == expected_nic && self.nic_protocol == expected_protocol);
        CHECK(self._private == &private_sentinel && listens == 1 && conversions == 1);
        CHECK(finds == !selected && sockets == !selected && !closes);
        listen_error = 0;
        CHECK(socket_listen(1, args) == mp_const_none);
        CHECK(listens == 2 && finds == !selected && sockets == !selected);
        CHECK(self.state == MOD_NETWORK_SS_LISTENING);

        reset(selected); self.bound = selected; failure_state = MOD_NETWORK_SS_CLOSED;
        listen_error = MP_EBADF;
        EXPECT_RAISE(VM_OS_ERROR, MP_EBADF, socket_listen(2, args));
        CHECK(self.state == MOD_NETWORK_SS_CLOSED && self.bound == selected);
        CHECK(self.nic == expected_nic && self.nic_protocol == expected_protocol);
        CHECK(self._private == &private_sentinel && !closes);
    }
}
static void test_selection_failure(void) {
    reset(false); socket_error = MP_ENOMEM;
    EXPECT_RAISE(VM_OS_ERROR, MP_ENOMEM, socket_listen(2, args));
    CHECK(conversions == 1 && finds == 1 && types == 1 && sockets == 1);
    CHECK(!listens && !timeouts && !closes && !self._private);
    CHECK(self.nic == MP_OBJ_NULL && self.nic_protocol == NULL && self.state == MOD_NETWORK_SS_NEW);
    socket_error = 0;
    CHECK(socket_listen(2, args) == mp_const_none);
    CHECK(conversions == 2 && finds == 2 && types == 2 && sockets == 2 && listens == 1);
    CHECK(self.state == MOD_NETWORK_SS_LISTENING);

    reset(false); self.timeout = 0;
    CHECK(socket_listen(1, args) == mp_const_none);
    CHECK(sockets == 1 && timeouts == 1 && listens == 1 && !closes);
    reset(false); self.timeout = 20; timeout_error = MP_ENETDOWN;
    EXPECT_RAISE(VM_OS_ERROR, MP_ENETDOWN, socket_listen(2, args));
    CHECK(conversions == 1 && sockets == 1 && timeouts == 1 && closes == 1 && !listens);
    CHECK(!self._private && self.nic == MP_OBJ_NULL && self.nic_protocol == NULL);
    CHECK(self.state == MOD_NETWORK_SS_CLOSED);
    EXPECT_RAISE(VM_OS_ERROR, MP_EBADF, socket_listen(2, args));
    CHECK(conversions == 1 && sockets == 1 && closes == 1);
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    if (!strcmp(argv[1], "closed")) test_closed();
    else if (!strcmp(argv[1], "validation")) test_validation();
    else if (!strcmp(argv[1], "dispatch")) test_dispatch();
    else if (!strcmp(argv[1], "callback-failure")) test_callback_failure();
    else if (!strcmp(argv[1], "selection-failure")) test_selection_failure();
    else CHECK(false);
    puts("PASS"); return 0;
}
"""


class SocketListenHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("gcc")
        if compiler is None and FALLBACK_GCC.is_file():
            compiler = str(FALLBACK_GCC)
        if compiler is None:
            raise unittest.SkipTest("host GCC unavailable")
        source = MODSOCKET.read_text(encoding="utf-8")
        definitions = "\n\n".join(extract_function(source, name)
                                  for name in ("socket_select_nic", "socket_listen"))
        config = (ROOT / "lib/micropython/py/mpconfig.h").read_text(encoding="utf-8")
        default = re.search(r"^#define MICROPY_PY_SOCKET_LISTEN_BACKLOG_DEFAULT .+$", config, re.MULTILINE)
        if default is None:
            raise AssertionError("Missing existing default backlog definition")
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-listen-host-")
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        c_file = root / "listen.c"
        cls.executable = root / "listen.exe"
        c_file.write_text(PRELUDE + "\n" + default.group() + "\n" + definitions + "\n" + TESTS,
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

    def test_closed_precedes_family_type_and_malformed_backlog_without_nic(self):
        self.run_scenario("closed")

    def test_invalid_family_udp_proto_and_backlog_precede_nic_selection(self):
        self.run_scenario("validation")

    def test_default_clamped_and_large_backlog_selected_and_unselected_dispatch(self):
        self.run_scenario("dispatch")

    def test_callback_errno_preserves_self_state_and_selected_nic_for_retry(self):
        self.run_scenario("callback-failure")

    def test_nic_creation_and_timeout_failure_rollback_and_retry(self):
        self.run_scenario("selection-failure")


if __name__ == "__main__":
    unittest.main()
