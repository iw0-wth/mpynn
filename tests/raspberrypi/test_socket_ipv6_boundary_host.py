# SPDX-License-Identifier: MIT
"""AF_INET6 is a compatibility export, not an IPv6 transport implementation.

Execute complete production resolver, listen, bind/connect and NIC-selection
functions, plus the production udp_socket allocator boundary. Unlike generic
unsupported-family tests, use the exported AF_INET6 value from the vendored
header and follow lazy socket creation through adapter rejection and rollback.
No VM, Circle, hardware, DNS or native sockets are needed.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODSOCKET = ROOT / "ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c"
ADAPTER = ROOT / "ports/raspberrypi/socket_udp_port.c"
NETWORK_HEADER = ROOT / "lib/micropython/extmod/modnetwork.h"
ERRNO_HEADER = ROOT / "lib/micropython/py/mperrno.h"
SOCKET_HEADER = ROOT / "ports/raspberrypi/socket_port.h"
CONFIG_HEADER = ROOT / "lib/micropython/py/mpconfig.h"
WINDOWS_GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")


def extract_function(source, name):
    """Extract a complete static definition without changing its production body."""
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


def numeric_define(source, name):
    # Select the literal portable errno definition, not the host-errno alias.
    match = re.search(rf"^#define\s+{re.escape(name)}\s+\(?\s*(0x[0-9a-fA-F]+|[0-9]+)\s*\)?(?:\s|$)",
                      source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"Missing numeric source definition: {name}")
    return f"#define {name} ({match.group(1)})\n"


def production_constants():
    network = NETWORK_HEADER.read_text(encoding="utf-8")
    errno = ERRNO_HEADER.read_text(encoding="utf-8")
    socket = SOCKET_HEADER.read_text(encoding="utf-8")
    config = CONFIG_HEADER.read_text(encoding="utf-8")
    result = "".join(numeric_define(network, name) for name in (
        "MOD_NETWORK_AF_INET", "MOD_NETWORK_AF_INET6", "MOD_NETWORK_SOCK_STREAM",
        "MOD_NETWORK_SOCK_DGRAM", "MOD_NETWORK_IPADDR_BUF_SIZE", "MOD_NETWORK_SS_NEW",
        "MOD_NETWORK_SS_LISTENING", "MOD_NETWORK_SS_CONNECTED", "MOD_NETWORK_SS_CLOSED"))
    result += "".join(numeric_define(errno, name) for name in (
        "MP_EAFNOSUPPORT", "MP_EBADF", "MP_EOPNOTSUPP", "MP_EINVAL"))
    result += "".join(numeric_define(socket, "MPYNN_SOCKET_" + name) for name in (
        "AI_PASSIVE", "AI_NUMERICHOST", "AI_NUMERICSERV"))
    result += numeric_define(config, "MICROPY_PY_SOCKET_LISTEN_BACKLOG_DEFAULT")
    return result


PRELUDE = r"""
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)
typedef unsigned char byte;
typedef uintptr_t mp_obj_t;
typedef int32_t mp_int_t;
typedef uint32_t mp_uint_t;
#define MP_OBJ_NULL ((mp_obj_t)0)
#define MP_OBJ_TO_PTR(o) ((void *)(uintptr_t)(o))
#define MP_OBJ_FROM_PTR(p) ((mp_obj_t)(uintptr_t)(p))
#define MP_OBJ_NEW_SMALL_INT(i) ((((uintptr_t)(intptr_t)(i)) << 1) | 1)
#define MP_OBJ_NEW_QSTR(q) ((mp_obj_t)(uintptr_t)&empty_string)
#define MP_ERROR_TEXT(s) (s)
#define MICROPY_PY_SOCKET_EXTENDED_STATE 1
#define NETUTILS_BIG 1
#define MP_QSTR_ 0
typedef struct { size_t len; mp_obj_t items[5]; } mp_obj_tuple_t;
typedef struct { const char *data; size_t len; } fake_str_t;
static const uintptr_t none_object;
#define mp_const_none ((mp_obj_t)(uintptr_t)&none_object)
static fake_str_t empty_string = {"", 0};
static const int mp_type_OSError = 1;
static jmp_buf raise_target;
static int raised_kind, raised_code;
enum { OS_ERROR = 1, VALUE_ERROR, OS_MESSAGE };
static _Noreturn void mp_raise_OSError(int code) {
    raised_kind = OS_ERROR; raised_code = code; longjmp(raise_target, 1);
}
static _Noreturn void mp_raise_ValueError(const char *message) {
    CHECK(message); raised_kind = VALUE_ERROR; raised_code = 0; longjmp(raise_target, 1);
}
static _Noreturn void mp_raise_msg(const int *type, const char *message) {
    CHECK(type == &mp_type_OSError && message);
    raised_kind = OS_MESSAGE; raised_code = 0; longjmp(raise_target, 1);
}
static unsigned conversions, arrays, strings, allocations, tuples, lists, formats;
static unsigned nic_lists, finds, nic_types, dns, adapter_calls, native_calls;
static mp_int_t mp_obj_get_int(mp_obj_t obj) {
    ++conversions; CHECK(obj & 1); return (mp_int_t)(((intptr_t)obj) >> 1);
}
static bool mp_obj_is_str(mp_obj_t obj) { return obj != mp_const_none && !(obj & 1); }
static const char *mp_obj_str_get_data(mp_obj_t obj, size_t *len) {
    ++strings; CHECK(mp_obj_is_str(obj)); fake_str_t *s = MP_OBJ_TO_PTR(obj);
    *len = s->len; return s->data;
}
static void mp_obj_get_array_fixed_n(mp_obj_t obj, size_t count, mp_obj_t **items) {
    ++arrays; mp_obj_tuple_t *tuple = MP_OBJ_TO_PTR(obj);
    CHECK(tuple && tuple->len == count); *items = tuple->items;
}
static mp_obj_tuple_t result_tuple;
static mp_obj_t mp_obj_new_tuple(size_t count, const mp_obj_t *items) {
    ++allocations; ++tuples; CHECK(count <= 5);
    result_tuple.len = count;
    if (items) memcpy(result_tuple.items, items, count * sizeof(*items));
    return MP_OBJ_FROM_PTR(&result_tuple);
}
static mp_obj_t mp_obj_new_list(size_t count, const mp_obj_t *items) {
    ++allocations; ++lists; CHECK(count == 1 && items); return MP_OBJ_FROM_PTR(&result_tuple);
}
static mp_obj_t netutils_format_inet_addr(const byte *ip, mp_uint_t port, int endian) {
    ++allocations; ++formats; CHECK(ip && port <= 65535 && endian == NETUTILS_BIG);
    return MP_OBJ_FROM_PTR(&empty_string);
}
typedef struct mod_network_socket_obj_t mod_network_socket_obj_t;
typedef struct {
    int (*gethostbyname)(mp_obj_t, const char *, mp_uint_t, uint8_t *);
    int (*socket)(mod_network_socket_obj_t *, int *);
    int (*bind)(mod_network_socket_obj_t *, byte *, mp_uint_t, int *);
    int (*connect)(mod_network_socket_obj_t *, byte *, mp_uint_t, int *);
    int (*listen)(mod_network_socket_obj_t *, mp_int_t, int *);
    int (*settimeout)(mod_network_socket_obj_t *, mp_uint_t, int *);
    void (*close)(mod_network_socket_obj_t *);
} mod_network_nic_protocol_t;
struct mod_network_socket_obj_t {
    mp_obj_t nic;
    mod_network_nic_protocol_t *nic_protocol;
    int domain, type, proto, state, fileno;
    bool bound;
    int32_t timeout;
    mp_obj_t callback;
    void *_private;
};
typedef struct { const mod_network_nic_protocol_t *protocol; } mp_obj_type_t;
#define MP_OBJ_TYPE_GET_SLOT(type, slot) ((type)->slot)
static mp_obj_type_t nic_type;
static byte nic_token;
static mp_obj_tuple_t mod_network_nic_list;
static mp_obj_tuple_t *host_nic_list(void) { ++nic_lists; return &mod_network_nic_list; }
#define MP_STATE_PORT(field) (*host_nic_list())
static const mp_obj_type_t *mp_obj_get_type(mp_obj_t obj) {
    ++nic_types; CHECK(obj == MP_OBJ_FROM_PTR(&nic_token)); return &nic_type;
}
static mp_obj_t mod_network_find_nic(const byte *ip) {
    ++finds; CHECK(ip); return MP_OBJ_FROM_PTR(&nic_token);
}
static void *host_m_new0(size_t size) {
    ++allocations; void *p = calloc(1, size); CHECK(p); return p;
}
#define m_new0(type, count) ((type *)host_m_new0(sizeof(type) * (count)))
"""

DOUBLES = r"""
static int host_adapter_socket(mod_network_socket_obj_t *s, int *error) {
    ++adapter_calls; return udp_socket(s, error);
}
static int host_dns(mp_obj_t nic, const char *name, mp_uint_t len, byte *out) {
    ++dns; CHECK(nic && name && len && out); memcpy(out, (byte[4]){192,0,2,1}, 4); return 0;
}
static int host_endpoint(mod_network_socket_obj_t *s, byte *ip, mp_uint_t port, int *error) {
    ++native_calls; CHECK(s && ip && port == 80 && error); return 0;
}
static int host_listen(mod_network_socket_obj_t *s, mp_int_t backlog, int *error) {
    ++native_calls; CHECK(s && backlog >= 0 && error); return 0;
}
static int host_timeout(mod_network_socket_obj_t *s, mp_uint_t timeout, int *error) {
    ++native_calls; CHECK(s && timeout == 0 && error); return 0;
}
static void host_close(mod_network_socket_obj_t *s) {
    ++native_calls; CHECK(s); free(s->_private); s->_private = NULL;
}
static mod_network_nic_protocol_t protocol = {
    host_dns, host_adapter_socket, host_endpoint, host_endpoint,
    host_listen, host_timeout, host_close
};
static void reset_counts(void) {
    conversions = arrays = strings = allocations = tuples = lists = formats = 0;
    nic_lists = finds = nic_types = dns = adapter_calls = native_calls = 0;
    raised_kind = raised_code = 0;
    nic_type.protocol = &protocol;
    mod_network_nic_list.len = 1;
    mod_network_nic_list.items[0] = MP_OBJ_FROM_PTR(&nic_token);
}
#define EXPECT_AF(expression) do { \
    raised_kind = raised_code = 0; \
    if (setjmp(raise_target) == 0) { (void)(expression); CHECK(false); } \
    CHECK(raised_kind == OS_ERROR && raised_code == MP_EAFNOSUPPORT); \
} while (0)
"""

TESTS = r"""
static mod_network_socket_obj_t fresh(int family, int type, int proto) {
    // Match socket_make_new's lazy, NIC-free initialized object.
    return (mod_network_socket_obj_t){.domain=family, .type=type, .proto=proto,
        .state=MOD_NETWORK_SS_NEW, .timeout=-1, .fileno=-1};
}
static void test_resolver(void) {
    static const char *const hosts[] = {"example.invalid", "192.0.2.1", "::1", NULL};
    for (size_t h = 0; h < sizeof(hosts)/sizeof(hosts[0]); ++h) {
        for (unsigned available = 0; available < 2; ++available) {
            for (size_t argc = 3; argc <= 6; ++argc) {
                reset_counts(); mod_network_nic_list.len = available;
                fake_str_t host = {hosts[h], hosts[h] ? strlen(hosts[h]) : 0};
                mp_obj_t args[] = {hosts[h] ? MP_OBJ_FROM_PTR(&host) : mp_const_none,
                    MP_OBJ_NEW_SMALL_INT(80), MP_OBJ_NEW_SMALL_INT(MOD_NETWORK_AF_INET6),
                    MP_OBJ_NEW_SMALL_INT(MOD_NETWORK_SOCK_STREAM),
                    MP_OBJ_NEW_SMALL_INT(6), MP_OBJ_NEW_SMALL_INT(0)};
                EXPECT_AF(mod_socket_getaddrinfo(argc, args));
                CHECK(!nic_lists && !nic_types && !finds && !dns && !adapter_calls);
                CHECK(!allocations && !tuples && !lists && !formats && !native_calls);
            }
        }
    }
}
static void test_adapter(void) {
    const int types[] = {MOD_NETWORK_SOCK_STREAM, MOD_NETWORK_SOCK_DGRAM, 99};
    const int protocols[] = {0, 6, 17, 41};
    for (size_t t = 0; t < sizeof(types)/sizeof(types[0]); ++t) {
        for (size_t p = 0; p < sizeof(protocols)/sizeof(protocols[0]); ++p) {
            reset_counts();
            mod_network_socket_obj_t s = fresh(MOD_NETWORK_AF_INET6, types[t], protocols[p]);
            int error = 0;
            CHECK(udp_socket(&s, &error) == -1 && error == MP_EAFNOSUPPORT);
            CHECK(!s._private && !s.nic && !s.nic_protocol && !s.bound);
            CHECK(s.domain == MOD_NETWORK_AF_INET6 && s.state == MOD_NETWORK_SS_NEW);
            CHECK(!allocations && !native_calls && !finds && !dns);
            // Family rejection must not overwrite an existing private sentinel.
            byte sentinel = 0xA5; s._private = &sentinel;
            CHECK(udp_socket(&s, &error) == -1 && error == MP_EAFNOSUPPORT);
            CHECK(s._private == &sentinel && sentinel == 0xA5 && !allocations);
        }
    }
    reset_counts();
    mod_network_socket_obj_t closed = fresh(MOD_NETWORK_AF_INET6, MOD_NETWORK_SOCK_STREAM, 0);
    closed.state = MOD_NETWORK_SS_CLOSED;
    int error = 0;
    CHECK(udp_socket(&closed, &error) == -1 && error == MP_EBADF);
    CHECK(!allocations && !closed._private && !native_calls);
}
static void test_wrappers(void) {
    fake_str_t host = {"192.0.2.1", 9};
    mp_obj_tuple_t address = {.len=2, .items={MP_OBJ_FROM_PTR(&host), MP_OBJ_NEW_SMALL_INT(80)}};
    for (unsigned operation = 0; operation < 2; ++operation) {
        reset_counts();
        mod_network_socket_obj_t s = fresh(MOD_NETWORK_AF_INET6, MOD_NETWORK_SOCK_STREAM, 0);
        for (unsigned retry = 1; retry <= 2; ++retry) {
            if (operation == 0) EXPECT_AF(socket_bind(MP_OBJ_FROM_PTR(&s), MP_OBJ_FROM_PTR(&address)));
            else EXPECT_AF(socket_connect(MP_OBJ_FROM_PTR(&s), MP_OBJ_FROM_PTR(&address)));
            CHECK(arrays == retry && finds == retry && nic_types == retry && adapter_calls == retry);
            CHECK(!s.nic && !s.nic_protocol && !s._private && !s.bound);
            CHECK(s.domain == MOD_NETWORK_AF_INET6 && s.state == MOD_NETWORK_SS_NEW);
            CHECK(!allocations && !native_calls && !dns && !nic_lists);
        }
    }
    reset_counts();
    mod_network_socket_obj_t s = fresh(MOD_NETWORK_AF_INET6, MOD_NETWORK_SOCK_STREAM, 0);
    mp_obj_t listen_args[] = {MP_OBJ_FROM_PTR(&s), mp_const_none};
    EXPECT_AF(socket_listen(2, listen_args)); // Family beats even a malformed backlog.
    CHECK(!conversions && !finds && !nic_types && !adapter_calls && !native_calls);
    CHECK(!allocations && !s.nic && !s.nic_protocol && !s._private);
    // Already-selected NICs cannot bypass the listen family guard either.
    s.nic = MP_OBJ_FROM_PTR(&nic_token); s.nic_protocol = &protocol;
    EXPECT_AF(socket_listen(1, listen_args));
    CHECK(!allocations && !native_calls && !adapter_calls);
    CHECK(s.nic == MP_OBJ_FROM_PTR(&nic_token) && s.nic_protocol == &protocol);
}
static void test_ipv4_control(void) {
    reset_counts();
    fake_str_t host = {"192.0.2.1", 9};
    mp_obj_tuple_t address = {.len=2, .items={MP_OBJ_FROM_PTR(&host), MP_OBJ_NEW_SMALL_INT(80)}};
    mod_network_socket_obj_t s = fresh(MOD_NETWORK_AF_INET, MOD_NETWORK_SOCK_STREAM, 6);
    CHECK(socket_connect(MP_OBJ_FROM_PTR(&s), MP_OBJ_FROM_PTR(&address)) == mp_const_none);
    CHECK(allocations == 1 && adapter_calls == 1 && native_calls == 1);
    CHECK(finds == 1 && s._private && s.state == MOD_NETWORK_SS_CONNECTED);
    CHECK(state(&s)->kind == MOD_NETWORK_SOCK_STREAM && state(&s)->nodelay);
    free(s._private);
    reset_counts();
    fake_str_t name = {"example.invalid", 15};
    mp_obj_t args[] = {MP_OBJ_FROM_PTR(&name), MP_OBJ_NEW_SMALL_INT(80),
        MP_OBJ_NEW_SMALL_INT(MOD_NETWORK_AF_INET)};
    (void)mod_socket_getaddrinfo(3, args);
    CHECK(nic_lists && nic_types == 1 && dns == 1);
    CHECK(allocations == 3 && tuples == 1 && lists == 1 && formats == 1);
}
int main(int argc, char **argv) {
    CHECK(argc == 2 && MOD_NETWORK_AF_INET6 == 10 && MOD_NETWORK_AF_INET == 2);
    if (!strcmp(argv[1], "resolver")) test_resolver();
    else if (!strcmp(argv[1], "adapter")) test_adapter();
    else if (!strcmp(argv[1], "wrappers")) test_wrappers();
    else if (!strcmp(argv[1], "ipv4-control")) test_ipv4_control();
    else CHECK(false);
    puts("PASS"); return 0;
}
"""


class SocketIPv6SourceContractTests(unittest.TestCase):
    def test_af_inet6_is_an_actual_globals_export_with_header_value(self):
        source = MODSOCKET.read_text(encoding="utf-8")
        # Commented-out protocol constants are not actual globals entries.
        active = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
        table = re.search(r"mp_module_socket_globals_table\[\]\s*=\s*\{(.*?)\n\};",
                          active, re.DOTALL)
        self.assertIsNotNone(table, "Missing real module globals table")
        entries = re.findall(r"\{\s*MP_ROM_QSTR\(MP_QSTR_AF_INET6\),\s*"
                             r"MP_ROM_INT\(([^)]+)\)\s*\}", table.group(1))
        self.assertEqual(entries, ["MOD_NETWORK_AF_INET6"])
        self.assertEqual(numeric_define(NETWORK_HEADER.read_text(encoding="utf-8"),
                                        "MOD_NETWORK_AF_INET6"),
                         "#define MOD_NETWORK_AF_INET6 (10)\n")

    def test_constructor_stores_requested_domain_without_eager_nic_creation(self):
        constructor = extract_function(MODSOCKET.read_text(encoding="utf-8"), "socket_make_new")
        self.assertRegex(constructor, r"s->domain\s*=\s*mp_obj_get_int\(args\[0\]\)")
        self.assertIn("s->nic = MP_OBJ_NULL;", constructor)
        self.assertIn("s->nic_protocol = NULL;", constructor)
        self.assertIn("s->_private = NULL;", constructor)
        self.assertNotRegex(constructor, r"socket_select_nic\s*\(|mod_network_find_nic\s*\(")


class SocketIPv6BoundaryHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("gcc")
        if compiler is None and WINDOWS_GCC.is_file():
            compiler = str(WINDOWS_GCC)
        if compiler is None:
            raise unittest.SkipTest("host GCC unavailable")
        source = MODSOCKET.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        # Use the actual transport-state layout, not a hand-copied allocator type.
        layout = re.search(r"typedef struct \{\n.*?\n\} udp_state_t;", adapter, re.DOTALL)
        if layout is None:
            raise AssertionError("Missing production UDP transport state")
        adapter_functions = "\n\n".join(extract_function(adapter, name)
                                         for name in ("fail", "state", "udp_socket"))
        wrappers = "\n\n".join(extract_function(source, name) for name in (
            "socket_select_nic", "socket_parse_address", "socket_bind", "socket_connect",
            "socket_listen", "socket_parse_ipv4_literal", "mod_socket_getaddrinfo"))
        program = (production_constants() + PRELUDE + "\n" + layout.group() + "\n"
                   + adapter_functions + "\n" + DOUBLES + "\n" + wrappers + "\n" + TESTS)
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-ipv6-boundary-")
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        c_file = root / "ipv6_boundary.c"
        cls.executable = root / "ipv6_boundary.exe"
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

    def test_explicit_ipv6_resolver_family_precedes_dns_nic_and_result_allocations(self):
        self.run_scenario("resolver")

    def test_real_adapter_rejects_ipv6_before_m_new_or_native_calls(self):
        self.run_scenario("adapter")

    def test_ipv6_listen_guard_and_bind_connect_adapter_rejection_rollback(self):
        self.run_scenario("wrappers")

    def test_ipv4_controls_prove_allocator_dns_and_dispatch_doubles_are_live(self):
        self.run_scenario("ipv4-control")


if __name__ == "__main__":
    unittest.main()
