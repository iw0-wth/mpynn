# SPDX-License-Identifier: MIT
"""Compile complete production accept/ioctl wrappers with a host VM and real NLR."""
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
    """Extract the complete definition, ignoring braces in comments and literals."""
    match = re.search(rf"^static\s+(?:mp_obj_t|mp_uint_t)\s+{re.escape(name)}\s*\(",
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
#include <setjmp.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char byte;
typedef uint32_t mp_uint_t;
typedef int32_t mp_int_t;
typedef void *mp_obj_t;
#define MP_OBJ_NULL ((mp_obj_t)NULL)
#define MP_OBJ_TO_PTR(obj) ((void *)(obj))
#define MP_OBJ_FROM_PTR(ptr) ((mp_obj_t)(ptr))
#define MICROPY_PY_SOCKET_EXTENDED_STATE 1
#define MOD_NETWORK_AF_INET 2
#define MOD_NETWORK_SOCK_STREAM 1
#define MOD_NETWORK_SOCK_DGRAM 2
#define MOD_NETWORK_IPADDR_BUF_SIZE 4
#define MOD_NETWORK_SS_NEW 0
#define MOD_NETWORK_SS_LISTENING 1
#define MOD_NETWORK_SS_CONNECTED 2
#define MOD_NETWORK_SS_CLOSED 3
#define MP_EBADF 9
#define MP_EAGAIN 11
#define MP_ENOMEM 12
#define MP_EINVAL 22
#define MP_EOPNOTSUPP 95
#define MP_EAFNOSUPPORT 97
#define MP_ENETDOWN 100
#define MP_STREAM_CLOSE 1
#define MP_STREAM_POLL 2
#define MP_STREAM_POLL_HUP 4
#define MP_STREAM_POLL_WR 8
#define MP_STREAM_POLL_NVAL 16
#define MP_STREAM_ERROR ((mp_uint_t)-1)
#define NETUTILS_BIG 1
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)

typedef struct { int tag; } mp_obj_type_t;
typedef struct { const mp_obj_type_t *type; } mp_obj_base_t;
static const mp_obj_type_t socket_type = {1};
typedef struct _mod_network_socket_obj_t mod_network_socket_obj_t;
/* Match modnetwork.h: accept returns int, close void, ioctl mp_uint_t. */
typedef struct {
    int (*accept)(mod_network_socket_obj_t *, mod_network_socket_obj_t *,
                  byte *, mp_uint_t *, int *);
    void (*close)(mod_network_socket_obj_t *);
    mp_uint_t (*ioctl)(mod_network_socket_obj_t *, mp_uint_t, mp_uint_t, int *);
} mod_network_nic_protocol_t;
struct _mod_network_socket_obj_t {
    mp_obj_base_t base;
    mp_obj_t nic;
    mod_network_nic_protocol_t *nic_protocol;
    uint32_t domain : 5;
    uint32_t type : 5;
    uint32_t proto : 5;
    uint32_t bound : 1;
    int32_t fileno : 16;
    int32_t timeout;
    mp_obj_t callback;
    int32_t state : 8;
    void *_private;
};
typedef struct { mp_obj_base_t base; size_t len; mp_obj_t items[2]; } mp_obj_tuple_t;
typedef struct { char host[16]; mp_uint_t port; } peer_obj_t;

/* Nested VM frames must run setjmp in their caller, never in a helper. */
typedef struct nlr_buf_t {
    struct nlr_buf_t *prev;
    jmp_buf target;
    void *volatile ret_val;
} nlr_buf_t;
static nlr_buf_t *nlr_top;
#define nlr_push(buf) (((buf)->prev = nlr_top), (nlr_top = (buf)), setjmp((buf)->target))
#define nlr_pop() do { CHECK(nlr_top != NULL); nlr_top = nlr_top->prev; } while (0)
static _Noreturn void nlr_jump(void *exception) {
    CHECK(nlr_top != NULL && exception != NULL);
    nlr_buf_t *frame = nlr_top;
    nlr_top = frame->prev;
    frame->ret_val = exception;
    longjmp(frame->target, 1);
}
enum { VM_OS_ERROR = 1, VM_MEMORY_ERROR = 2, VM_VALUE_ERROR = 3 };
typedef struct { int kind, code; } exception_t;
static exception_t os_exception, child_exception = {VM_MEMORY_ERROR, 101};
static exception_t tuple_exception = {VM_MEMORY_ERROR, 102};
static exception_t format_exception = {VM_MEMORY_ERROR, 103};
static exception_t other_exception = {VM_VALUE_ERROR, 104};
static _Noreturn void mp_raise_OSError(int code) {
    os_exception = (exception_t){VM_OS_ERROR, code};
    nlr_jump(&os_exception);
}
static byte nic_token, parent_native, callback_token, child_native[8];
static mod_network_nic_protocol_t protocol;
static mod_network_socket_obj_t parent, children[8], *last_child;
static mp_obj_tuple_t tuples[8];
static peer_obj_t peers[8];
static unsigned child_allocs, tuple_allocs, formats, accepts, closes, adapter_cleanups;
static unsigned native_closed[8];
static int callback_error;
static bool fail_child_alloc, fail_tuple_alloc;
static void *format_failure;
static const byte peer_ip[4] = {192, 0, 2, 123};
static const mp_uint_t peer_port = 54321;

static bool is_child(mod_network_socket_obj_t *s) {
    for (unsigned i = 0; i < child_allocs && i < 8; ++i) {
        if (s == &children[i]) return true;
    }
    return false;
}
static void check_parent(void) {
    CHECK(parent.nic == &nic_token && parent.nic_protocol == &protocol);
    CHECK(parent.domain == MOD_NETWORK_AF_INET && parent.type == MOD_NETWORK_SOCK_STREAM);
    CHECK(parent.state == MOD_NETWORK_SS_LISTENING && parent.bound);
    CHECK(parent._private == &parent_native && parent.fileno == 77);
    CHECK(parent.timeout == 1357 && parent.callback == &callback_token);
}
static void check_attached_child(void) {
    CHECK(last_child != NULL && last_child != &parent && is_child(last_child));
    CHECK(last_child->nic == parent.nic && last_child->nic_protocol == parent.nic_protocol);
    CHECK(last_child->state == MOD_NETWORK_SS_CONNECTED && last_child->_private != NULL);
    CHECK(last_child->domain == parent.domain && last_child->type == parent.type);
    CHECK(last_child->proto == parent.proto && !last_child->bound);
    CHECK(last_child->timeout == -1 && last_child->callback == MP_OBJ_NULL);
    check_parent();
}
static void *fake_malloc(size_t size, const mp_obj_type_t *type) {
    CHECK(size == sizeof(mod_network_socket_obj_t) && type == &socket_type);
    CHECK(child_allocs < 8);
    unsigned index = child_allocs++;
    if (fail_child_alloc) nlr_jump(&child_exception);
    last_child = &children[index];
    /* Poison memory so missing initialization cannot pass by accident. */
    memset(last_child, 0xA5, sizeof(*last_child));
    last_child->base.type = type;
    return last_child;
}
#define mp_obj_malloc_with_finaliser(type, obj_type) ((type *)fake_malloc(sizeof(type), (obj_type)))
static mp_obj_t mp_obj_new_tuple(size_t len, const mp_obj_t *items) {
    CHECK(len == 2 && items == NULL && tuple_allocs < 8);
    check_attached_child();
    unsigned index = tuple_allocs++;
    if (fail_tuple_alloc) nlr_jump(&tuple_exception);
    tuples[index] = (mp_obj_tuple_t){.len = len};
    return &tuples[index];
}
static mp_obj_t netutils_format_inet_addr(const uint8_t *ip, mp_uint_t port, int endian) {
    check_attached_child();
    CHECK(formats < 8 && endian == NETUTILS_BIG && port == peer_port);
    CHECK(!memcmp(ip, peer_ip, sizeof(peer_ip)));
    unsigned index = formats++;
    if (format_failure != NULL) nlr_jump(format_failure);
    snprintf(peers[index].host, sizeof(peers[index].host), "%u.%u.%u.%u",
             (unsigned)ip[0], (unsigned)ip[1], (unsigned)ip[2], (unsigned)ip[3]);
    peers[index].port = port;
    return &peers[index];
}
static int fake_accept(mod_network_socket_obj_t *s, mod_network_socket_obj_t *child,
                       byte *ip, mp_uint_t *port, int *error) {
    CHECK(s == &parent && child == last_child && is_child(child));
    CHECK(ip != NULL && port != NULL && error != NULL);
    check_parent();
    CHECK(child->base.type == &socket_type);
    CHECK(child->nic == MP_OBJ_NULL && child->nic_protocol == NULL);
    CHECK(child->domain == s->domain && child->type == s->type && child->proto == s->proto);
    CHECK(!child->bound && child->fileno == -1 && child->timeout == -1);
    CHECK(child->callback == MP_OBJ_NULL && child->state == MOD_NETWORK_SS_NEW);
    CHECK(child->_private == NULL);
    ++accepts;
    *error = callback_error;
    child->_private = &child_native[child_allocs - 1];
    if (callback_error) {
        /* The adapter owns private-state rollback on callback failure. */
        ++adapter_cleanups;
        child->_private = NULL;
        return -1;
    }
    child->state = MOD_NETWORK_SS_CONNECTED;
    memcpy(ip, peer_ip, sizeof(peer_ip));
    *port = peer_port;
    return 0;
}
static void fake_close(mod_network_socket_obj_t *child) {
    CHECK(child != &parent && is_child(child));
    CHECK(child->nic == &nic_token && child->nic_protocol == &protocol);
    CHECK(child->_private != NULL);
    unsigned index;
    for (index = 0; index < 8; ++index) {
        if (child->_private == &child_native[index]) break;
    }
    CHECK(index < 8 && native_closed[index] == 0);
    ++native_closed[index]; ++closes;
    child->_private = NULL;
}
static mp_uint_t fake_ioctl(mod_network_socket_obj_t *s, mp_uint_t request,
                            mp_uint_t arg, int *error) {
    (void)s; (void)request; (void)arg; (void)error;
    CHECK(false); return MP_STREAM_ERROR;
}
static mod_network_nic_protocol_t protocol = {fake_accept, fake_close, fake_ioctl};
static void reset(void) {
    CHECK(nlr_top == NULL);
    parent = (mod_network_socket_obj_t){.base = {&socket_type}, .nic = &nic_token,
        .nic_protocol = &protocol, .domain = MOD_NETWORK_AF_INET,
        .type = MOD_NETWORK_SOCK_STREAM, .proto = 0, .bound = true, .fileno = 77,
        .timeout = 1357, .callback = &callback_token, .state = MOD_NETWORK_SS_LISTENING,
        ._private = &parent_native};
    memset(children, 0, sizeof(children)); memset(native_closed, 0, sizeof(native_closed));
    memset(tuples, 0, sizeof(tuples)); memset(peers, 0, sizeof(peers));
    child_allocs = tuple_allocs = formats = accepts = closes = adapter_cleanups = 0;
    callback_error = 0; fail_child_alloc = fail_tuple_alloc = false;
    format_failure = NULL; last_child = NULL;
}
#define EXPECT_EXCEPTION(exception, expression) do { \
    nlr_buf_t outer; \
    if (nlr_push(&outer) == 0) { (void)(expression); nlr_pop(); CHECK(false); } \
    CHECK(outer.ret_val == (void *)(exception)); \
    CHECK(nlr_top == NULL); \
} while (0)
#define EXPECT_OS_ERROR(expected_code, expression) do { \
    EXPECT_EXCEPTION(&os_exception, expression); \
    CHECK(os_exception.kind == VM_OS_ERROR && os_exception.code == (expected_code)); \
} while (0)
"""

TESTS = r"""
static void no_allocation_or_native(void) {
    CHECK(!child_allocs && !tuple_allocs && !formats && !accepts && !closes);
    CHECK(!adapter_cleanups && last_child == NULL);
}
static void test_closed(void) {
    for (unsigned selected = 0; selected < 2; ++selected) {
        reset(); parent.nic = selected ? &nic_token : MP_OBJ_NULL;
        parent.state = MOD_NETWORK_SS_CLOSED;
        parent.domain = 31; parent.type = MOD_NETWORK_SOCK_DGRAM; parent.proto = 17;
        EXPECT_OS_ERROR(MP_EBADF, socket_accept(&parent));
        no_allocation_or_native();
        CHECK(parent.state == MOD_NETWORK_SS_CLOSED && parent._private == &parent_native);
    }
}
static void test_validation(void) {
    for (unsigned selected = 0; selected < 2; ++selected) {
        reset(); parent.nic = selected ? &nic_token : MP_OBJ_NULL;
        parent.domain = 31; parent.type = MOD_NETWORK_SOCK_DGRAM; parent.proto = 17;
        parent.state = MOD_NETWORK_SS_NEW;
        EXPECT_OS_ERROR(MP_EAFNOSUPPORT, socket_accept(&parent));
        no_allocation_or_native();
        parent.domain = MOD_NETWORK_AF_INET;
        EXPECT_OS_ERROR(MP_EOPNOTSUPP, socket_accept(&parent));
        no_allocation_or_native();
        parent.type = MOD_NETWORK_SOCK_STREAM;
        EXPECT_OS_ERROR(MP_EOPNOTSUPP, socket_accept(&parent));
        no_allocation_or_native();
        parent.proto = 6;
        EXPECT_OS_ERROR(MP_EINVAL, socket_accept(&parent));
        no_allocation_or_native();
    }
    static const int states[] = {MOD_NETWORK_SS_NEW, MOD_NETWORK_SS_CONNECTED, 7};
    for (unsigned i = 0; i < sizeof(states)/sizeof(states[0]); ++i) {
        reset(); parent.state = states[i];
        EXPECT_OS_ERROR(MP_EINVAL, socket_accept(&parent));
        no_allocation_or_native(); CHECK(parent.state == states[i]);
    }
    reset(); parent.nic = MP_OBJ_NULL;
    EXPECT_OS_ERROR(MP_EINVAL, socket_accept(&parent));
    no_allocation_or_native(); CHECK(parent.state == MOD_NETWORK_SS_LISTENING);
}
static void stale_close(mod_network_socket_obj_t *child) {
    int error = 0;
    unsigned previous = closes;
    CHECK(socket_ioctl(child, MP_STREAM_CLOSE, 0, &error) == 0);
    CHECK(socket_ioctl(child, MP_STREAM_CLOSE, 0, &error) == 0);
    CHECK(closes == previous && child->nic == MP_OBJ_NULL);
    CHECK(child->state == MOD_NETWORK_SS_CLOSED);
    check_parent();
}
static mod_network_socket_obj_t *check_success(void) {
    mp_obj_tuple_t *result = socket_accept(&parent);
    CHECK(nlr_top == NULL && result != NULL && result->len == 2);
    mod_network_socket_obj_t *child = result->items[0];
    CHECK(child == last_child); check_attached_child();
    peer_obj_t *peer = result->items[1];
    CHECK(peer != NULL && !strcmp(peer->host, "192.0.2.123") && peer->port == peer_port);
    return child;
}
static void test_callback_failure(void) {
    static const int errors[] = {MP_EAGAIN, MP_ENETDOWN, MP_ENOMEM};
    for (unsigned i = 0; i < sizeof(errors)/sizeof(errors[0]); ++i) {
        reset(); callback_error = errors[i];
        EXPECT_OS_ERROR(errors[i], socket_accept(&parent));
        CHECK(child_allocs == 1 && accepts == 1 && adapter_cleanups == 1);
        CHECK(!tuple_allocs && !formats && !closes);
        CHECK(last_child->nic == MP_OBJ_NULL && last_child->nic_protocol == NULL);
        CHECK(last_child->_private == NULL); check_parent();
        stale_close(last_child);
        callback_error = 0;
        (void)check_success();
        CHECK(child_allocs == 2 && accepts == 2 && tuple_allocs == 1 && formats == 1);
        CHECK(!closes && adapter_cleanups == 1);
    }
}
static void test_success(void) {
    for (unsigned proto = 0; proto < 2; ++proto) {
        reset(); parent.proto = proto ? 6 : 0;
        mod_network_socket_obj_t *first = check_success();
        mod_network_socket_obj_t *second = check_success();
        CHECK(first != second && first->_private != second->_private);
        CHECK(first->nic == second->nic && first->nic_protocol == second->nic_protocol);
        CHECK(child_allocs == 2 && accepts == 2 && tuple_allocs == 2 && formats == 2);
        CHECK(!closes && !adapter_cleanups);
        int error = 0;
        CHECK(socket_ioctl(first, MP_STREAM_CLOSE, 0, &error) == 0);
        CHECK(closes == 1 && !first->_private && first->state == MOD_NETWORK_SS_CLOSED);
        CHECK(second->state == MOD_NETWORK_SS_CONNECTED && second->_private != NULL);
        stale_close(first);
        CHECK(socket_ioctl(second, MP_STREAM_CLOSE, 0, &error) == 0);
        CHECK(closes == 2); stale_close(second);
    }
}
static void test_child_allocator_failure(void) {
    reset(); fail_child_alloc = true;
    EXPECT_EXCEPTION(&child_exception, socket_accept(&parent));
    CHECK(child_allocs == 1 && !accepts && !tuple_allocs && !formats && !closes);
    CHECK(last_child == NULL); check_parent();
    fail_child_alloc = false;
    (void)check_success();
    CHECK(child_allocs == 2 && accepts == 1);
}
static void test_result_failure(bool formatting, bool other) {
    reset();
    fail_tuple_alloc = !formatting;
    format_failure = formatting ? (other ? (void *)&other_exception : (void *)&format_exception) : NULL;
    void *original = formatting ? format_failure : (void *)&tuple_exception;
    EXPECT_EXCEPTION(original, socket_accept(&parent));
    CHECK(child_allocs == 1 && accepts == 1 && tuple_allocs == 1);
    CHECK(formats == (unsigned)formatting && closes == 1 && !adapter_cleanups);
    CHECK(native_closed[0] == 1 && last_child->_private == NULL);
    CHECK(last_child->nic == MP_OBJ_NULL && last_child->nic_protocol == NULL);
    CHECK(last_child->state == MOD_NETWORK_SS_CLOSED); check_parent();
    mod_network_socket_obj_t *failed = last_child;
    stale_close(failed);
    fail_tuple_alloc = false; format_failure = NULL;
    mod_network_socket_obj_t *retry = check_success();
    CHECK(retry != failed && retry->_private != NULL && failed->_private == NULL);
    CHECK(child_allocs == 2 && accepts == 2 && tuple_allocs == 2);
    CHECK(formats == 1u + (unsigned)formatting && closes == 1 && native_closed[1] == 0);
    stale_close(failed);
    CHECK(retry->state == MOD_NETWORK_SS_CONNECTED && retry->_private != NULL);
    int error = 0;
    CHECK(socket_ioctl(retry, MP_STREAM_CLOSE, 0, &error) == 0);
    CHECK(closes == 2 && native_closed[1] == 1); stale_close(retry);
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    if (!strcmp(argv[1], "closed")) test_closed();
    else if (!strcmp(argv[1], "validation")) test_validation();
    else if (!strcmp(argv[1], "callback-failure")) test_callback_failure();
    else if (!strcmp(argv[1], "success")) test_success();
    else if (!strcmp(argv[1], "child-memory-error")) test_child_allocator_failure();
    else if (!strcmp(argv[1], "tuple-memory-error")) test_result_failure(false, false);
    else if (!strcmp(argv[1], "format-memory-error")) test_result_failure(true, false);
    else if (!strcmp(argv[1], "format-other-error")) test_result_failure(true, true);
    else CHECK(false);
    CHECK(nlr_top == NULL); puts("PASS"); return 0;
}
"""


class SocketAcceptHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("gcc")
        if compiler is None and FALLBACK_GCC.is_file():
            compiler = str(FALLBACK_GCC)
        if compiler is None:
            raise unittest.SkipTest("host GCC unavailable")
        source = MODSOCKET.read_text(encoding="utf-8")
        definitions = "\n\n".join(extract_function(source, name)
                                  for name in ("socket_accept", "socket_ioctl"))
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-accept-host-")
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
        c_file = root / "accept.c"
        cls.executable = root / "accept.exe"
        c_file.write_text(PRELUDE + "\n" + definitions + "\n" + TESTS, encoding="utf-8")
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

    def test_closed_ebadf_precedes_all_other_validation_without_allocating(self):
        self.run_scenario("closed")

    def test_invalid_family_type_proto_nic_and_state_do_not_allocate_or_accept(self):
        self.run_scenario("validation")

    def test_callback_eagain_and_errors_do_not_format_or_attach_child_nic(self):
        self.run_scenario("callback-failure")

    def test_success_initializes_unbound_blocking_independent_children_and_valid_peer(self):
        self.run_scenario("success")

    def test_child_allocator_memory_error_precedes_native_callback_and_allows_retry(self):
        self.run_scenario("child-memory-error")

    def test_tuple_memory_error_closes_once_propagates_original_and_allows_retry(self):
        self.run_scenario("tuple-memory-error")

    def test_address_memory_error_closes_once_propagates_original_and_allows_retry(self):
        self.run_scenario("format-memory-error")

    def test_non_memory_format_exception_has_identical_cleanup_and_identity(self):
        self.run_scenario("format-other-error")


if __name__ == "__main__":
    unittest.main()
