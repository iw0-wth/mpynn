# SPDX-License-Identifier: MIT
"""Host-check the port's real receive-into helper and both wrapper bodies.

Only the three C function bodies are extracted: registration macros are neither
compiled nor replaced by no-ops. The tiny VM/NIC doubles expose writable buffer
requests, bounded writes, one-operation receives, peer construction and errors.
All generated C/executables live in a temporary directory, not the port build.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[2]
          / "ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c")
COMPILER = Path("E:/msys64/ucrt64/bin/gcc.exe")


def extract_bodies(source):
    bodies = []
    for name in ("socket_receive_into", "socket_recv_into", "socket_recvfrom_into"):
        matches = re.findall(
            r"^static mp_obj_t " + name + r"\([^\n]*\) \{\n.*?^\}",
            source, re.MULTILINE | re.DOTALL,
        )
        if len(matches) != 1:
            raise AssertionError("expected one actual function body for " + name)
        bodies.append(matches[0])
    return "\n\n".join(bodies)


PRELUDE = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)
typedef uintptr_t mp_uint_t;
typedef intptr_t mp_int_t;
typedef intptr_t mp_obj_t;
typedef unsigned char byte;
#define MP_OBJ_TO_PTR(x) ((void *)(x))
#define MP_OBJ_FROM_PTR(x) ((mp_obj_t)(x))
#define MP_OBJ_NULL ((mp_obj_t)0)
#define MP_BUFFER_WRITE 2
#define MP_ERROR_TEXT(x) x
#define MP_EBADF 9
#define MP_EIO 5
#define MP_EAGAIN 11
#define MP_ENOTCONN 107
#define MP_ENETDOWN 100
#define MP_EOPNOTSUPP 95
#define MOD_NETWORK_SS_NEW 0
#define MOD_NETWORK_SS_CONNECTED 2
#define MOD_NETWORK_SS_CLOSED 3
#define NETUTILS_BIG 1

typedef struct { void *buf; size_t len; int typecode; } mp_buffer_info_t;
typedef struct { mp_buffer_info_t info; bool writable; } buffer_object_t;
struct Socket;
typedef struct {
    mp_uint_t (*recv)(struct Socket *, byte *, mp_uint_t, int *);
    mp_uint_t (*recvfrom)(struct Socket *, byte *, mp_uint_t, byte *, mp_uint_t *, int *);
} protocol_t;
typedef struct Socket {
    mp_obj_t nic;
    const protocol_t *nic_protocol;
    int state;
} mod_network_socket_obj_t;
typedef enum { NO_EXCEPTION, OS_EXCEPTION, VALUE_EXCEPTION, TYPE_EXCEPTION } exception_t;
static jmp_buf trap;
static exception_t raised;
static int raised_errno;
static byte guarded[18];
static buffer_object_t buffer;
static mod_network_socket_obj_t socket_object;
static unsigned buffer_calls, recv_calls, recvfrom_calls, consumed;
static unsigned integer_calls, format_calls, tuple_calls;
static size_t last_capacity, packet_length, written;
static byte *last_buffer;
static int driver_error;
static bool bad_count;
static mp_uint_t count_override, returned_integer;
static mp_obj_t tuple_values[2];
static byte formatted_ip[4];
static mp_uint_t formatted_port;
static const byte peer_ip[4] = {203, 0, 113, 29};
static const mp_uint_t peer_port = 54321;
static const byte payload[] = "first packet data";
static byte peer_object, tuple_object;

static _Noreturn void mp_raise_OSError(int error) {
    raised = OS_EXCEPTION; raised_errno = error; longjmp(trap, 1);
}
static _Noreturn void mp_raise_ValueError(const char *message) {
    CHECK(message != NULL && message[0]); raised = VALUE_EXCEPTION; longjmp(trap, 1);
}
static void mp_get_buffer_raise(mp_obj_t obj, mp_buffer_info_t *info, unsigned flags) {
    CHECK(obj == MP_OBJ_FROM_PTR(&buffer) && flags == MP_BUFFER_WRITE);
    ++buffer_calls;
    if (!buffer.writable) {
#if READONLY_IS_VALUEERROR
        mp_raise_ValueError("read-only buffer");
#else
        raised = TYPE_EXCEPTION; longjmp(trap, 1);
#endif
    }
    *info = buffer.info;
}
static mp_int_t mp_obj_get_int(mp_obj_t obj) { return obj; }
static mp_obj_t mp_obj_new_int_from_uint(mp_uint_t value) {
    ++integer_calls; returned_integer = value;
    return MP_OBJ_FROM_PTR(&returned_integer);
}
static mp_obj_t netutils_format_inet_addr(byte *ip, mp_uint_t port, int order) {
    CHECK(order == NETUTILS_BIG && recvfrom_calls == 1 && recv_calls == 0);
    CHECK(!driver_error && !bad_count && integer_calls == 1);
    CHECK(returned_integer <= last_capacity);
    ++format_calls; memcpy(formatted_ip, ip, sizeof(formatted_ip)); formatted_port = port;
    return MP_OBJ_FROM_PTR(&peer_object);
}
static mp_obj_t mp_obj_new_tuple(size_t n, mp_obj_t *values) {
    CHECK(n == 2 && format_calls == 1 && integer_calls == 1);
    ++tuple_calls; memcpy(tuple_values, values, sizeof(tuple_values));
    return MP_OBJ_FROM_PTR(&tuple_object);
}
static mp_uint_t receive_data(struct Socket *self, byte *data, mp_uint_t capacity, int *error) {
    CHECK(self == &socket_object && data == buffer.info.buf);
    CHECK(capacity <= buffer.info.len && recv_calls + recvfrom_calls == 1);
    last_buffer = data; last_capacity = capacity;
    *error = driver_error;
    if (driver_error) return (mp_uint_t)-1;
    if (bad_count) return count_override;
    /* A second packet/chunk remains pending: a stream-readall loop is a bug. */
    CHECK(consumed == 0); ++consumed;
    written = packet_length < capacity ? packet_length : capacity;
    CHECK(written <= sizeof(payload) - 1);
    if (written) memcpy(data, payload, written);
    return written;
}
static mp_uint_t nic_recv(struct Socket *self, byte *data, mp_uint_t capacity, int *error) {
    ++recv_calls; return receive_data(self, data, capacity, error);
}
static mp_uint_t nic_recvfrom(struct Socket *self, byte *data, mp_uint_t capacity,
                             byte *ip, mp_uint_t *port, int *error) {
    ++recvfrom_calls;
    mp_uint_t count = receive_data(self, data, capacity, error);
    /* Deliberately leave peer output uninitialised on driver failure. */
    if (!driver_error && !bad_count) { memcpy(ip, peer_ip, 4); *port = peer_port; }
    return count;
}
static const protocol_t protocol = {nic_recv, nic_recvfrom};
'''

SCENARIOS = r'''
typedef mp_obj_t (*wrapper_t)(size_t, const mp_obj_t *);
static wrapper_t wrapper;
static bool with_peer;
static mp_obj_t args[4];

static void reset(bool peer) {
    with_peer = peer; wrapper = peer ? socket_recvfrom_into : socket_recv_into;
    memset(guarded, 0xA5, sizeof(guarded));
    buffer = (buffer_object_t){{guarded + 1, 16, 'B'}, true};
    socket_object = (mod_network_socket_obj_t){1, &protocol, MOD_NETWORK_SS_CONNECTED};
    args[0] = MP_OBJ_FROM_PTR(&socket_object); args[1] = MP_OBJ_FROM_PTR(&buffer);
    args[2] = 0; args[3] = 0;
    buffer_calls = recv_calls = recvfrom_calls = consumed = 0;
    integer_calls = format_calls = tuple_calls = 0;
    last_capacity = written = 0; last_buffer = NULL;
    packet_length = 3; driver_error = 0; bad_count = false; count_override = 0;
    returned_integer = 999; formatted_port = 0;
    memset(formatted_ip, 0, sizeof(formatted_ip)); memset(tuple_values, 0, sizeof(tuple_values));
    raised = NO_EXCEPTION; raised_errno = 0;
}
static void check_sentinels(void) {
    CHECK(guarded[0] == 0xA5);
    for (size_t i = written; i < sizeof(guarded) - 1; ++i) CHECK(guarded[i + 1] == 0xA5);
    if (written) CHECK(memcmp(guarded + 1, payload, written) == 0);
}
static void success(size_t n_args, size_t capacity, size_t count) {
    mp_obj_t result = 0;
    if (setjmp(trap) == 0) result = wrapper(n_args, args);
    else CHECK(false);
    CHECK(raised == NO_EXCEPTION && buffer_calls == 1);
    CHECK(recv_calls == (with_peer ? 0u : 1u));
    CHECK(recvfrom_calls == (with_peer ? 1u : 0u));
    CHECK(consumed == 1 && last_capacity == capacity && last_buffer == guarded + 1);
    CHECK(integer_calls == 1 && returned_integer == count && written == count);
    if (with_peer) {
        CHECK(result == MP_OBJ_FROM_PTR(&tuple_object) && tuple_calls == 1 && format_calls == 1);
        CHECK(tuple_values[0] == MP_OBJ_FROM_PTR(&returned_integer));
        CHECK(tuple_values[1] == MP_OBJ_FROM_PTR(&peer_object));
        CHECK(memcmp(formatted_ip, peer_ip, 4) == 0 && formatted_port == peer_port);
    } else {
        CHECK(result == MP_OBJ_FROM_PTR(&returned_integer) && !tuple_calls && !format_calls);
    }
    check_sentinels();
}
static void failure(size_t n_args, exception_t kind, int error, unsigned io_calls) {
    if (setjmp(trap) == 0) { (void)wrapper(n_args, args); CHECK(false); }
    CHECK(raised == kind && raised_errno == error && buffer_calls == 1);
    CHECK(recv_calls == (with_peer ? 0u : io_calls));
    CHECK(recvfrom_calls == (with_peer ? io_calls : 0u));
    CHECK(!consumed && !written && !integer_calls && !format_calls && !tuple_calls);
    check_sentinels();
}
static void common(const char *scenario, bool peer) {
    reset(peer);
    if (!strcmp(scenario, "default-capacity")) {
        packet_length = 16; success(2, 16, 16);
    } else if (!strcmp(scenario, "zero-means-full")) {
        packet_length = 16; success(3, 16, 16);
        reset(peer); packet_length = 16; success(4, 16, 16);
    } else if (!strcmp(scenario, "positive-max")) {
        const mp_int_t limits[] = {1, 5, 16};
        for (size_t i = 0; i < sizeof(limits) / sizeof(limits[0]); ++i) {
            reset(peer); args[2] = limits[i]; packet_length = 16;
            success(3, (size_t)limits[i], (size_t)limits[i]);
            reset(peer); args[2] = limits[i]; packet_length = 16;
            success(4, (size_t)limits[i], (size_t)limits[i]);
        }
    } else if (!strcmp(scenario, "invalid-sizes")) {
        const mp_int_t sizes[] = {-1, INTPTR_MIN, 17, INTPTR_MAX};
        for (size_t i = 0; i < sizeof(sizes) / sizeof(sizes[0]); ++i) {
            reset(peer); args[2] = sizes[i]; failure(3, VALUE_EXCEPTION, 0, 0);
        }
        reset(peer); buffer.info.len = 0; args[2] = 1; failure(3, VALUE_EXCEPTION, 0, 0);
    } else if (!strcmp(scenario, "unsupported-flags")) {
        const mp_int_t flags[] = {1, -1, INTPTR_MAX};
        for (size_t i = 0; i < sizeof(flags) / sizeof(flags[0]); ++i) {
            reset(peer); args[3] = flags[i]; failure(4, OS_EXCEPTION, MP_EOPNOTSUPP, 0);
        }
    } else if (!strcmp(scenario, "read-only")) {
        buffer.writable = false;
        failure(2, READONLY_IS_VALUEERROR ? VALUE_EXCEPTION : TYPE_EXCEPTION, 0, 0);
    } else if (!strcmp(scenario, "closed-and-new")) {
        socket_object.state = MOD_NETWORK_SS_CLOSED;
        failure(2, OS_EXCEPTION, MP_EBADF, 0);
        reset(peer); socket_object.state = MOD_NETWORK_SS_CLOSED; socket_object.nic = MP_OBJ_NULL;
        failure(2, OS_EXCEPTION, MP_EBADF, 0);
        reset(peer); socket_object.state = MOD_NETWORK_SS_NEW; socket_object.nic = MP_OBJ_NULL;
        failure(2, OS_EXCEPTION, MP_ENOTCONN, 0);
    } else if (!strcmp(scenario, "driver-errors")) {
        const int errors[] = {MP_EAGAIN, MP_ENETDOWN, MP_EBADF};
        for (size_t i = 0; i < sizeof(errors) / sizeof(errors[0]); ++i) {
            reset(peer); driver_error = errors[i]; failure(2, OS_EXCEPTION, errors[i], 1);
        }
    } else if (!strcmp(scenario, "invalid-driver-count")) {
        const mp_uint_t counts[] = {6, 17, (mp_uint_t)-2};
        for (size_t i = 0; i < sizeof(counts) / sizeof(counts[0]); ++i) {
            reset(peer); args[2] = 5; bad_count = true; count_override = counts[i];
            failure(3, OS_EXCEPTION, MP_EIO, 1); CHECK(last_capacity == 5);
        }
    } else if (!strcmp(scenario, "empty-buffer")) {
        buffer.info.len = 0; success(2, 0, 0);
        reset(peer); buffer.info.len = 0; success(3, 0, 0);
    } else CHECK(false);
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    const char *scenario = argv[1];
    if (!strcmp(scenario, "stream-partial")) {
        reset(false); success(2, 16, 3);
        reset(false); args[2] = 8; success(3, 8, 3);
        reset(false); packet_length = 0; success(2, 16, 0);
    } else if (!strcmp(scenario, "udp-single-truncated-empty")) {
        reset(true); success(2, 16, 3);
        reset(true); args[2] = 2; packet_length = 16; success(3, 2, 2);
        reset(true); packet_length = 0; success(2, 16, 0);
    } else {
        common(scenario, false); common(scenario, true);
    }
    printf("%s: passed (readonly=%s)\n", scenario,
           READONLY_IS_VALUEERROR ? "ValueError" : "TypeError");
    return 0;
}
'''


class ReceiveIntoHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not COMPILER.is_file():
            raise unittest.SkipTest("host GCC unavailable")
        cls.folder = tempfile.TemporaryDirectory(prefix="socket_receive_into_")
        cls.addClassCleanup(cls.folder.cleanup)
        root = Path(cls.folder.name)
        program = PRELUDE + extract_bodies(SOURCE.read_text(encoding="utf-8")) + SCENARIOS
        src = root / "receive_into.c"
        src.write_text(program, encoding="utf-8")
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(COMPILER.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.executables = []
        for readonly_kind in (0, 1):
            exe = root / ("receive_into_%d.exe" % readonly_kind)
            command = [str(COMPILER), "-std=c11", "-Wall", "-Wextra", "-Werror",
                       "-DREADONLY_IS_VALUEERROR=" + str(readonly_kind), str(src), "-o", str(exe)]
            result = subprocess.run(command, env=cls.env, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError("GCC failed:\n" + result.stdout + result.stderr)
            cls.executables.append(exe)

    def run_scenario(self, scenario):
        for readonly_kind, exe in enumerate(self.executables):
            with self.subTest(readonly="ValueError" if readonly_kind else "TypeError"):
                result = subprocess.run([str(exe), scenario], env=self.env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(scenario + ": passed", result.stdout)

    def test_default_capacity(self):
        self.run_scenario("default-capacity")

    def test_nbytes_zero_uses_full_capacity(self):
        self.run_scenario("zero-means-full")

    def test_positive_nbytes_limits_writes(self):
        self.run_scenario("positive-max")

    def test_negative_and_oversize_rejected_before_io(self):
        self.run_scenario("invalid-sizes")

    def test_nonzero_flags_rejected_before_io(self):
        self.run_scenario("unsupported-flags")

    def test_readonly_vm_exception_variants(self):
        self.run_scenario("read-only")

    def test_closed_ebadf_and_new_enotconn_before_io(self):
        self.run_scenario("closed-and-new")

    def test_partial_stream_data_returns_after_one_recv(self):
        self.run_scenario("stream-partial")

    def test_udp_single_truncated_and_empty_peer_output(self):
        self.run_scenario("udp-single-truncated-empty")

    def test_driver_count_above_capacity_is_eio(self):
        self.run_scenario("invalid-driver-count")

    def test_driver_errors_do_not_construct_results_or_format_peer(self):
        self.run_scenario("driver-errors")

    def test_empty_buffer_and_peer_output(self):
        self.run_scenario("empty-buffer")


if __name__ == "__main__":
    unittest.main()
