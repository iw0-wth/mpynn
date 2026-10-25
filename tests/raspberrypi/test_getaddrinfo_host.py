# SPDX-License-Identifier: MIT
"""Execute the actual port getaddrinfo callback with a tiny host VM and real NLR."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest

SOURCE = (Path(__file__).resolve().parents[2]
          / "ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c")
SOCKET_HEADER = Path(__file__).resolve().parents[2] / "ports/raspberrypi/socket_port.h"
FLAG_NAMES = ("AI_PASSIVE", "AI_NUMERICHOST", "AI_NUMERICSERV")
WINDOWS_GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")
COMPILER = str(WINDOWS_GCC) if WINDOWS_GCC.is_file() else shutil.which("gcc")

PRELUDE = r"""
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)
typedef uintptr_t mp_obj_t;
typedef intptr_t mp_int_t;
typedef uintptr_t mp_uint_t;
typedef struct { size_t len; mp_obj_t items[5]; } mp_obj_tuple_t;
typedef struct { size_t len; mp_obj_t items[5]; } mp_obj_list_t;
typedef struct { const char *data; size_t len; } fake_str_t;
#define MP_OBJ_TO_PTR(o) ((void *)(uintptr_t)(o))
#define MP_OBJ_NEW_SMALL_INT(i) ((((uintptr_t)(intptr_t)(i)) << 1) | 1)
#define MP_OBJ_NEW_QSTR(q) ((mp_obj_t)(uintptr_t)&empty_string)
#define MP_QSTR_ 0
#define MP_ERROR_TEXT(s) (s)
#define MOD_NETWORK_AF_INET 2
#define MOD_NETWORK_SOCK_STREAM 1
#define MOD_NETWORK_SOCK_DGRAM 2
#define MOD_NETWORK_IPADDR_BUF_SIZE 4
#define NETUTILS_BIG 1
#define MP_EAFNOSUPPORT 97
#define MP_EOPNOTSUPP 95
#define MP_ENETDOWN 100
#define MP_EINVAL 22
static const uintptr_t none_object = 0;
#define mp_const_none ((mp_obj_t)(uintptr_t)&none_object)
static fake_str_t empty_string = {"", 0};
static const int mp_type_OSError = 1;
typedef struct nlr_buf_t {
    jmp_buf jb;
    void *ret_val;
    struct nlr_buf_t *prev;
} nlr_buf_t;
static nlr_buf_t *nlr_top;
#define nlr_push(n) (((n)->prev = nlr_top), (nlr_top = (n)), setjmp((n)->jb))
static void nlr_pop(void) { CHECK(nlr_top); nlr_top = nlr_top->prev; }
static _Noreturn void nlr_jump(void *value) {
    nlr_buf_t *n = nlr_top;
    CHECK(n);
    nlr_top = n->prev;
    n->ret_val = value;
    longjmp(n->jb, 1);
}
enum { VALUE_ERROR = 1, OS_ERROR, OS_MESSAGE };
static struct { int kind, code; const char *message; } exception;
static _Noreturn void mp_raise_ValueError(const char *message) {
    exception.kind = VALUE_ERROR; exception.code = 0; exception.message = message;
    nlr_jump(&exception);
}
static _Noreturn void mp_raise_OSError(int code) {
    exception.kind = OS_ERROR; exception.code = code; exception.message = NULL;
    nlr_jump(&exception);
}
static _Noreturn void mp_raise_msg(const int *type, const char *message) {
    CHECK(type == &mp_type_OSError);
    exception.kind = OS_MESSAGE; exception.code = 0; exception.message = message;
    nlr_jump(&exception);
}
static mp_int_t mp_obj_get_int(mp_obj_t obj) {
    CHECK(obj & 1); return ((intptr_t)obj) >> 1;
}
static bool mp_obj_is_str(mp_obj_t obj) { return obj != mp_const_none && !(obj & 1); }
static const char *mp_obj_str_get_data(mp_obj_t obj, size_t *len) {
    CHECK(mp_obj_is_str(obj)); fake_str_t *s = MP_OBJ_TO_PTR(obj);
    *len = s->len; return s->data;
}
static mp_obj_tuple_t tuples[4];
static size_t tuple_count;
static mp_obj_list_t result_list;
static mp_obj_t mp_obj_new_tuple(size_t len, const mp_obj_t *items) {
    CHECK(tuple_count < 4 && len <= 5);
    mp_obj_tuple_t *tuple = &tuples[tuple_count++];
    memset(tuple, 0, sizeof(*tuple)); tuple->len = len;
    if (items) memcpy(tuple->items, items, len * sizeof(*items));
    return (mp_obj_t)(uintptr_t)tuple;
}
static mp_obj_t mp_obj_new_list(size_t len, const mp_obj_t *items) {
    CHECK(len <= 5); result_list.len = len;
    memcpy(result_list.items, items, len * sizeof(*items));
    return (mp_obj_t)(uintptr_t)&result_list;
}
typedef struct {
    int (*gethostbyname)(mp_obj_t, const char *, mp_uint_t, uint8_t *);
} mod_network_nic_protocol_t;
typedef struct { mod_network_nic_protocol_t *protocol; } fake_nic_t;
static mp_obj_list_t mod_network_nic_list;
#define MP_STATE_PORT(field) (field)
#define mp_obj_get_type(nic) ((fake_nic_t *)MP_OBJ_TO_PTR(nic))
#define MP_OBJ_TYPE_GET_SLOT(type, slot) ((type)->slot)
static unsigned parse_calls, dns_calls, format_calls;
static int dns_error, dns_interrupt;
static fake_str_t *requested_host;
static const uint8_t dns_ip[4] = {203, 0, 113, 42};
static fake_str_t formatted_host;
static char formatted_text[32];
static mp_obj_t netutils_format_inet_addr(const uint8_t *ip, mp_int_t port, int endian) {
    CHECK(endian == NETUTILS_BIG && port >= 0 && port <= 65535); ++format_calls;
    snprintf(formatted_text, sizeof(formatted_text), "%u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
    formatted_host.data = formatted_text; formatted_host.len = strlen(formatted_text);
    mp_obj_t items[2] = {(mp_obj_t)(uintptr_t)&formatted_host, MP_OBJ_NEW_SMALL_INT(port)};
    return mp_obj_new_tuple(2, items);
}
static int fake_gethostbyname(mp_obj_t nic, const char *host, mp_uint_t len, uint8_t *out) {
    CHECK(nic != 0 && host == requested_host->data && len == requested_host->len);
    ++dns_calls;
    if (dns_interrupt) mp_raise_ValueError("DNS callback interrupted");
    if (dns_error) return dns_error;
    memcpy(out, dns_ip, 4); return 0;
}
static mod_network_nic_protocol_t resolver_protocol = {fake_gethostbyname};
static mod_network_nic_protocol_t no_resolver_protocol = {NULL};
static fake_nic_t resolver_nic = {&resolver_protocol};
static fake_nic_t no_resolver_nic = {&no_resolver_protocol};
"""

HARNESS = r"""
static mp_obj_t args[6];
static fake_str_t host_object, service_object;
static int expected_port;
static const char *expected_ip;
static const int supported_flags[] = {
    0, MPYNN_SOCKET_AI_PASSIVE, MPYNN_SOCKET_AI_NUMERICHOST,
    MPYNN_SOCKET_AI_PASSIVE | MPYNN_SOCKET_AI_NUMERICHOST,
    MPYNN_SOCKET_AI_NUMERICSERV,
    MPYNN_SOCKET_AI_PASSIVE | MPYNN_SOCKET_AI_NUMERICSERV,
    MPYNN_SOCKET_AI_NUMERICHOST | MPYNN_SOCKET_AI_NUMERICSERV,
    MPYNN_SOCKET_AI_PASSIVE | MPYNN_SOCKET_AI_NUMERICHOST | MPYNN_SOCKET_AI_NUMERICSERV,
};
static void set_none_host(int flags) {
    args[0] = mp_const_none;
    expected_ip = flags & MPYNN_SOCKET_AI_PASSIVE ? "0.0.0.0" : "127.0.0.1";
}
static void set_none_port(void) { args[1] = mp_const_none; expected_port = 0; }
static void set_service(const char *service, size_t len, int port) {
    service_object.data = service; service_object.len = len;
    args[1] = (mp_obj_t)(uintptr_t)&service_object; expected_port = port;
}
static void prepare(const char *host, size_t len, int port, int family, int type, int proto, int flags, int nics) {
    CHECK(nlr_top == NULL);
    tuple_count = parse_calls = dns_calls = format_calls = 0;
    dns_error = dns_interrupt = 0;
    memset(&exception, 0, sizeof(exception));
    host_object.data = host; host_object.len = len; requested_host = &host_object;
    args[0] = (mp_obj_t)(uintptr_t)&host_object;
    expected_port = port; expected_ip = NULL;
    args[1] = MP_OBJ_NEW_SMALL_INT(port); args[2] = MP_OBJ_NEW_SMALL_INT(family);
    args[3] = MP_OBJ_NEW_SMALL_INT(type); args[4] = MP_OBJ_NEW_SMALL_INT(proto);
    args[5] = MP_OBJ_NEW_SMALL_INT(flags);
    mod_network_nic_list.len = (size_t)nics;
    mod_network_nic_list.items[0] = (mp_obj_t)(uintptr_t)(nics == 2 ? &no_resolver_nic : &resolver_nic);
    mod_network_nic_list.items[1] = (mp_obj_t)(uintptr_t)&resolver_nic;
}
static void check_success(size_t n_args, int expected_type, int expected_proto, int expected_dns) {
    nlr_buf_t outer;
    if (nlr_push(&outer) == 0) {
        mp_obj_list_t *list = MP_OBJ_TO_PTR(mod_socket_getaddrinfo(n_args, args));
        nlr_pop();
        CHECK(list == &result_list && list->len == 1);
        mp_obj_tuple_t *tuple = MP_OBJ_TO_PTR(list->items[0]);
        CHECK(tuple->len == 5);
        CHECK(mp_obj_get_int(tuple->items[0]) == MOD_NETWORK_AF_INET);
        CHECK(mp_obj_get_int(tuple->items[1]) == expected_type);
        CHECK(mp_obj_get_int(tuple->items[2]) == expected_proto);
        size_t len; const char *canon = mp_obj_str_get_data(tuple->items[3], &len);
        CHECK(len == 0 && canon[0] == '\0');
        mp_obj_tuple_t *address = MP_OBJ_TO_PTR(tuple->items[4]);
        CHECK(address->len == 2);
        const char *ip = mp_obj_str_get_data(address->items[0], &len);
        const char *wanted_ip = expected_ip ? expected_ip : (expected_dns ? "203.0.113.42" : "192.0.2.7");
        CHECK(len == strlen(wanted_ip) && !memcmp(ip, wanted_ip, len));
        CHECK(mp_obj_get_int(address->items[1]) == expected_port);
    } else {
        fprintf(stderr, "unexpected exception: kind=%d code=%d message=%s\n", exception.kind,
                exception.code, exception.message ? exception.message : "");
        CHECK(!"success path raised");
    }
    CHECK(nlr_top == NULL && dns_calls == (unsigned)expected_dns && format_calls == 1);
    CHECK(parse_calls == 0);
}
static void check_error(size_t n_args, int kind, int code, unsigned parses, unsigned dns) {
    nlr_buf_t outer;
    if (nlr_push(&outer) == 0) {
        (void)mod_socket_getaddrinfo(n_args, args);
        CHECK(!"invalid call did not raise");
    } else {
        CHECK(outer.ret_val == &exception && exception.kind == kind && exception.code == code);
    }
    CHECK(nlr_top == NULL && parse_calls == parses && dns_calls == dns && format_calls == 0);
    CHECK(tuple_count == 0);
}
int main(int argc, char **argv) {
    CHECK(argc == 2); const char *mode = argv[1];
    if (!strcmp(mode, "defaults")) {
        for (size_t count = 2; count <= 6; ++count) {
            prepare("192.0.2.7", 9, 80, 0, 0, 0, 0, 0);
            check_success(count, MOD_NETWORK_SOCK_STREAM, 6, 0);
        }
    } else if (!strcmp(mode, "valid-matrix")) {
        // All supported family/type/protocol combinations, including both inference directions.
        for (int family = 0; family <= 2; family += 2) {
            for (int type = 0; type <= 2; ++type) {
                const int protocols[] = {0, 6, 17};
                for (size_t p = 0; p < 3; ++p) {
                    int proto = protocols[p];
                    if ((type == 1 && proto == 17) || (type == 2 && proto == 6)) continue;
                    int result_type = type ? type : (proto == 17 ? 2 : 1);
                    prepare("192.0.2.7", 9, 53, family, type, proto, 0, 0);
                    check_success(6, result_type, result_type == 2 ? 17 : 6, 0);
                }
            }
        }
    } else if (!strcmp(mode, "port-boundaries")) {
        const int ports[] = {0, 65535};
        for (size_t p = 0; p < 2; ++p) {
            prepare("192.0.2.7", 9, ports[p], 2, 2, 17, 0, 0);
            check_success(6, 2, 17, 0);
        }
    } else if (!strcmp(mode, "services")) {
        const struct { const char *name; int port, type, proto; } services[] = {
            {"http", 80, 1, 6}, {"https", 443, 1, 6}, {"ntp", 123, 2, 17},
            {"domain", 53, 2, 17}, {"ssh", 22, 1, 6}, {"telnet", 23, 1, 6}, {"ftp", 21, 1, 6}
        };
        for (size_t i = 0; i < sizeof(services) / sizeof(services[0]); ++i) {
            for (size_t count = 2; count <= 6; ++count) {
                for (int hints = 0; hints < 4; ++hints) {
                    prepare("192.0.2.7", 9, 0, 2, hints & 1 ? services[i].type : 0,
                            hints & 2 ? services[i].proto : 0, 0, 0);
                    set_service(services[i].name, strlen(services[i].name), services[i].port);
                    check_success(count, services[i].type, services[i].proto, 0);
                }
            }
        }
        prepare("example.org", 11, 0, 0, 0, 0, 0, 1);
        set_service("https", 5, 443); check_success(2, 1, 6, 1);
    } else if (!strcmp(mode, "service-conflicts")) {
        const char *names[] = {"http", "https", "ntp", "domain", "ssh", "telnet", "ftp"};
        for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
            int opposite_type = i == 2 || i == 3 ? 1 : 2;
            int opposite_proto = opposite_type == 1 ? 6 : 17;
            for (int hints = 1; hints < 4; ++hints) {
                prepare("example.org", 11, 0, 0, hints & 1 ? opposite_type : 0,
                        hints & 2 ? opposite_proto : 0, 0, 1);
                set_service(names[i], strlen(names[i]), 0);
                check_error(6, OS_ERROR, MP_EOPNOTSUPP, 0, 0);
            }
        }
    } else if (!strcmp(mode, "unknown-services")) {
        const char *names[] = {"", "smtp", "HTTP", "http ", " http", "http/udp", "-1", "+80", "80 ", "0x50", "80.0"};
        for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
            prepare("example.org", 11, 0, 0, 0, 0, 0, 1);
            set_service(names[i], strlen(names[i]), 0);
            check_error(6, OS_ERROR, MP_EOPNOTSUPP, 0, 0);
        }
    } else if (!strcmp(mode, "decimal-services")) {
        const struct { const char *name; int port; } ports[] = {
            {"0", 0}, {"65535", 65535}, {"80", 80}, {"00053", 53}, {"0000000000000000000000000000000000000000", 0}
        };
        for (size_t i = 0; i < sizeof(ports) / sizeof(ports[0]); ++i) {
            for (int type = 1; type <= 2; ++type) {
                prepare("192.0.2.7", 9, 0, 2, type, 0, 0, 0);
                set_service(ports[i].name, strlen(ports[i].name), ports[i].port);
                check_success(6, type, type == 1 ? 6 : 17, 0);
            }
            prepare("192.0.2.7", 9, 0, 0, 0, 0, 0, 0);
            set_service(ports[i].name, strlen(ports[i].name), ports[i].port);
            check_success(2, 1, 6, 0);
        }
    } else if (!strcmp(mode, "invalid-decimal-services")) {
        const char *ports[] = {"65536", "999999999999999999999999999999999999999999999999999"};
        for (size_t i = 0; i < sizeof(ports) / sizeof(ports[0]); ++i) {
            prepare("example.org", 11, 0, 0, 0, 0, 0, 1);
            set_service(ports[i], strlen(ports[i]), 0);
            check_error(6, VALUE_ERROR, 0, 0, 0);
        }
    } else if (!strcmp(mode, "service-nul")) {
        const char *names[] = {"http\0suffix", "80\0suffix", "http\0", "80\0"};
        const size_t lengths[] = {11, 9, 5, 3};
        for (size_t i = 0; i < 4; ++i) {
            prepare("example.org", 11, 0, 0, 0, 0, 0, 1);
            set_service(names[i], lengths[i], 0);
            check_error(6, VALUE_ERROR, 0, 0, 0);
        }
    } else if (!strcmp(mode, "supported-flags")) {
        for (size_t i = 0; i < 8; ++i) {
            int flags = supported_flags[i];
            for (int nics = 0; nics <= 2; ++nics) {
                for (int type = 1; type <= 2; ++type) {
                    prepare("192.0.2.7", 9, 0, 2, type, 0, flags, nics);
                    check_success(6, type, type == 1 ? 6 : 17, 0);
                    prepare("192.0.2.7", 9, 0, 2, type, 0, flags, nics);
                    set_service("00053", 5, 53);
                    check_success(6, type, type == 1 ? 6 : 17, 0);
                    prepare("192.0.2.7", 9, 80, 2, type, 0, flags, nics);
                    set_none_port(); check_success(6, type, type == 1 ? 6 : 17, 0);
                }
            }
        }
    } else if (!strcmp(mode, "none-host")) {
        for (size_t i = 0; i < 8; ++i) {
            int flags = supported_flags[i];
            for (int nics = 0; nics <= 2; ++nics) {
                for (int type = 1; type <= 2; ++type) {
                    prepare("", 0, 0, 2, type, 0, flags, nics);
                    set_none_host(flags); check_success(6, type, type == 1 ? 6 : 17, 0);
                    prepare("", 0, 0, 2, type, 0, flags, nics);
                    set_none_host(flags); set_service("00053", 5, 53);
                    check_success(6, type, type == 1 ? 6 : 17, 0);
                }
            }
            // Named services remain supported unless NUMERICSERV was requested.
            if (!(flags & MPYNN_SOCKET_AI_NUMERICSERV)) {
                prepare("", 0, 0, 0, 0, 0, flags, 0);
                set_none_host(flags); set_service("ntp", 3, 123);
                check_success(6, 2, 17, 0);
            }
        }
        prepare("", 0, 80, 0, 0, 0, 0, 0);
        set_none_host(0); check_success(2, 1, 6, 0);
    } else if (!strcmp(mode, "both-none")) {
        for (size_t i = 0; i < 8; ++i) {
            for (size_t count = 2; count <= 6; ++count) {
                prepare("", 0, 0, 0, 0, 0, supported_flags[i], 1);
                set_none_host(supported_flags[i]); set_none_port();
                check_error(count, VALUE_ERROR, 0, 0, 0);
            }
        }
    } else if (!strcmp(mode, "ipv4-helper")) {
        const char *invalid[] = {
            "", ".", "...", "1", "1.2.3", "1.2.3.4.5", "1..2.3", ".1.2.3", "1.2.3.",
            "256.0.0.1", "0.256.0.1", "0.0.256.1", "0.0.0.256", "0000.1.2.3",
            "1.0000.2.3", "1.2.0000.3", "1.2.3.0000", "192.0.2.7suffix", "1.2.3.4 ",
            " 1.2.3.4", "-1.2.3.4", "+1.2.3.4", "1.2.3.-4", "0x1.2.3.4", "example.org",
            "99999999999999999999999999999999.0.0.1",
        };
        const uint8_t untouched[4] = {17, 34, 51, 68};
        for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
            uint8_t out[4]; memcpy(out, untouched, sizeof(out));
            CHECK(!socket_parse_ipv4_literal(invalid[i], strlen(invalid[i]), out));
            CHECK(!memcmp(out, untouched, sizeof(out)));
        }
        // Length is authoritative: do not read suffixes or require a terminating NUL.
        const char bounded[] = {'1', '.', '2', '.', '3', '.', '4'};
        const uint8_t bounded_ip[4] = {1, 2, 3, 4};
        uint8_t out[4];
        CHECK(socket_parse_ipv4_literal(bounded, sizeof(bounded), out));
        CHECK(!memcmp(out, bounded_ip, sizeof(out)));
        CHECK(socket_parse_ipv4_literal("1.2.3.4suffix", 7, out));
        CHECK(!memcmp(out, bounded_ip, sizeof(out)));
        memcpy(out, untouched, sizeof(out));
        CHECK(!socket_parse_ipv4_literal("1.2.3.4\0suffix", 14, out));
        CHECK(!memcmp(out, untouched, sizeof(out)));
        for (unsigned value = 0; value <= 255; ++value) {
            char text[16];
            snprintf(text, sizeof(text), "%03u.%u.%03u.%u", value, value, value, value);
            CHECK(socket_parse_ipv4_literal(text, strlen(text), out));
            for (size_t octet = 0; octet < 4; ++octet) CHECK(out[octet] == value);
        }
        CHECK(nlr_top == NULL && parse_calls == 0 && dns_calls == 0);
    } else if (!strcmp(mode, "strict-numeric-hosts")) {
        const struct { const char *host, *ip; } valid[] = {
            {"0.0.0.0", "0.0.0.0"}, {"255.255.255.255", "255.255.255.255"},
            {"000.000.000.000", "0.0.0.0"}, {"001.002.003.004", "1.2.3.4"},
            {"010.020.030.040", "10.20.30.40"}, {"099.009.090.000", "99.9.90.0"},
            {"00.01.02.03", "0.1.2.3"}, {"255.000.025.005", "255.0.25.5"},
            {"198.51.100.1", "198.51.100.1"},
        };
        const char *invalid[] = {
            ".", "...", "0", "1234", "1.2", "1.2.3", "1.2.3.4.5", "1..2.3", ".1.2.3", "1.2.3.",
            "256.0.0.1", "0.256.0.1", "0.0.256.1", "0.0.0.256", "999.0.0.1", "0000.1.2.3",
            "1.0000.2.3", "1.2.0000.3", "1.2.3.0000", "1.2.3.4.",
            "99999999999999999999999999999999.0.0.1",
        };
        for (size_t f = 0; f < 8; ++f) {
            for (int nics = 0; nics <= 2; ++nics) {
                for (size_t h = 0; h < sizeof(valid) / sizeof(valid[0]); ++h) {
                    prepare(valid[h].host, strlen(valid[h].host), 80, 0, 0, 0, supported_flags[f], nics);
                    expected_ip = valid[h].ip; check_success(6, 1, 6, 0);
                }
                for (size_t h = 0; h < sizeof(invalid) / sizeof(invalid[0]); ++h) {
                    prepare(invalid[h], strlen(invalid[h]), 80, 0, 0, 0, supported_flags[f], nics);
                    check_error(6, OS_ERROR, MP_EINVAL, 0, 0);
                }
            }
        }
    } else if (!strcmp(mode, "full-hostname")) {
        const char *hosts[] = {
            "192.0.2.7suffix", "192.0.2.7.example.org", "256.0.0.1suffix", "1.2.3.4.5suffix",
            "example.org", "123example", "-1.2.3.4", "+1.2.3.4", "1.2.3.4 ", " 1.2.3.4",
            "0x1.2.3.4", "::1",
        };
        for (size_t f = 0; f < 8; ++f) {
            for (size_t h = 0; h < sizeof(hosts) / sizeof(hosts[0]); ++h) {
                for (int nics = 0; nics <= 2; ++nics) {
                    prepare(hosts[h], strlen(hosts[h]), 80, 0, 0, 0, supported_flags[f], nics);
                    if (supported_flags[f] & MPYNN_SOCKET_AI_NUMERICHOST) {
                        check_error(6, OS_ERROR, MP_EINVAL, 0, 0);
                    } else if (nics == 0) {
                        check_error(6, OS_MESSAGE, 0, 0, 0);
                        CHECK(exception.message && strstr(exception.message, "NIC"));
                    } else {
                        // The NIC checks the original pointer AND full supplied length.
                        check_success(6, 1, 6, 1);
                    }
                }
            }
        }
    } else if (!strcmp(mode, "numeric-host-required")) {
        const char *hosts[] = {
            "example.org", "not-an-ip", "", "::1", "256.0.0.1", "192.0.2.7junk",
            "1..2.3", "1.2.3", "1.2.3.4.5", "-1.2.3.4", "+1.2.3.4", "1.2.3.-4",
            "1.2.3.4 ", " 1.2.3.4", ".1.2.3", "1.2.3.", "0000.1.2.3",
            "99999999999999999999999999999999.0.0.1",
        };
        for (size_t i = 0; i < 8; ++i) {
            if (!(supported_flags[i] & MPYNN_SOCKET_AI_NUMERICHOST)) continue;
            for (size_t h = 0; h < sizeof(hosts) / sizeof(hosts[0]); ++h) {
                for (int nics = 0; nics <= 2; ++nics) {
                    prepare(hosts[h], strlen(hosts[h]), 0, 0, 0, 0, supported_flags[i], nics);
                    set_none_port();
                    check_error(6, OS_ERROR, MP_EINVAL, 0, 0);
                    // Validation errors must leave the NLR stack reusable.
                    prepare("192.0.2.7", 9, 0, 0, 0, 0, supported_flags[i], nics);
                    check_success(6, 1, 6, 0);
                }
            }
            for (int nics = 0; nics <= 2; ++nics) {
                prepare("198.51.100.1", 12, 0, 0, 0, 0, supported_flags[i], nics);
                expected_ip = "198.51.100.1";
                set_none_port(); check_success(6, 1, 6, 0);
            }
        }
    } else if (!strcmp(mode, "numeric-service-required")) {
        const char *services[] = {"http", "https", "ntp", "domain", "ssh", "telnet", "ftp"};
        for (size_t i = 0; i < 8; ++i) {
            if (!(supported_flags[i] & MPYNN_SOCKET_AI_NUMERICSERV)) continue;
            for (size_t s = 0; s < 7; ++s) {
                for (int host_kind = 0; host_kind < 3; ++host_kind) {
                    const char *host = host_kind == 0 ? "example.org" : "192.0.2.7";
                    prepare(host, strlen(host), 0, 0, 0, 0, supported_flags[i], 1);
                    if (host_kind == 2) set_none_host(supported_flags[i]);
                    set_service(services[s], strlen(services[s]), 0);
                    check_error(6, OS_ERROR, MP_EOPNOTSUPP, 0, 0);
                }
            }
        }
    } else if (!strcmp(mode, "passive-hostname")) {
        for (int numeric_service = 0; numeric_service <= 1; ++numeric_service) {
            int flags = MPYNN_SOCKET_AI_PASSIVE | (numeric_service ? MPYNN_SOCKET_AI_NUMERICSERV : 0);
            prepare("example.org", 11, 0, 0, 0, 0, flags, 1);
            set_none_port(); check_success(6, 1, 6, 1);
            prepare("example.org", 11, 0, 0, 0, 0, flags, 1);
            set_service("0", 1, 0); check_success(6, 1, 6, 1);
        }
    } else if (!strcmp(mode, "none-empty-semantics")) {
        prepare("", 0, 0, 0, 0, 0, 0, 1);
        set_none_port(); check_success(6, 1, 6, 1);
        prepare("", 0, 0, 0, 0, 0, MPYNN_SOCKET_AI_PASSIVE, 1);
        set_none_port(); check_success(6, 1, 6, 1);
        prepare("", 0, 0, 0, 0, 0, 0, 1);
        set_none_port(); dns_error = MP_EINVAL;
        check_error(6, OS_ERROR, MP_EINVAL, 0, 1);
        prepare("", 0, 0, 0, 0, 0, 0, 0);
        set_none_port(); check_error(6, OS_MESSAGE, 0, 0, 0);
        CHECK(exception.message && strstr(exception.message, "NIC"));
        prepare("", 0, 0, 0, 0, 0, 0, 1);
        set_none_host(0); set_service("", 0, 0);
        check_error(6, OS_ERROR, MP_EOPNOTSUPP, 0, 0);
    } else if (!strcmp(mode, "invalid-none-hints")) {
        const int hints[][3] = {
            {10, 0, MP_EAFNOSUPPORT}, {-1, 0, MP_EAFNOSUPPORT},
            {0, 2, MP_EOPNOTSUPP}, {0, -1, MP_EOPNOTSUPP},
            {0, MPYNN_SOCKET_AI_PASSIVE | 2, MP_EOPNOTSUPP},
        };
        for (size_t i = 0; i < sizeof(hints) / sizeof(hints[0]); ++i) {
            prepare("", 0, 0, hints[i][0], 0, 0, hints[i][1], 1);
            set_none_host(hints[i][1]); check_error(6, OS_ERROR, hints[i][2], 0, 0);
            prepare("example.org", 11, 0, hints[i][0], 0, 0, hints[i][1], 1);
            set_none_port(); check_error(6, OS_ERROR, hints[i][2], 0, 0);
        }
    } else if (!strcmp(mode, "exports")) {
        CHECK(MPYNN_SOCKET_AI_PASSIVE == 1);
        CHECK(MPYNN_SOCKET_AI_NUMERICHOST == 4);
        CHECK(MPYNN_SOCKET_AI_NUMERICSERV == 0x400);
        CHECK(flag_exports[0].key == MP_QSTR_AI_PASSIVE && flag_exports[0].value == MPYNN_SOCKET_AI_PASSIVE);
        CHECK(flag_exports[1].key == MP_QSTR_AI_NUMERICHOST && flag_exports[1].value == MPYNN_SOCKET_AI_NUMERICHOST);
        CHECK(flag_exports[2].key == MP_QSTR_AI_NUMERICSERV && flag_exports[2].value == MPYNN_SOCKET_AI_NUMERICSERV);
    } else if (!strcmp(mode, "invalid-hints")) {
        const int invalid[][5] = {
            {10, 0, 0, 0, MP_EAFNOSUPPORT}, {-1, 0, 0, 0, MP_EAFNOSUPPORT},
            {0, 3, 0, 0, MP_EOPNOTSUPP}, {0, -1, 0, 0, MP_EOPNOTSUPP},
            {0, 0, 1, 0, MP_EOPNOTSUPP}, {0, 0, -1, 0, MP_EOPNOTSUPP},
            {0, 1, 17, 0, MP_EOPNOTSUPP}, {0, 2, 6, 0, MP_EOPNOTSUPP},
            {0, 0, 0, 2, MP_EOPNOTSUPP}, {0, 0, 0, -1, MP_EOPNOTSUPP},
            {0, 0, 0, 8, MP_EOPNOTSUPP},
            {0, 0, 0, MPYNN_SOCKET_AI_PASSIVE | 2, MP_EOPNOTSUPP},
            {0, 0, 0, MPYNN_SOCKET_AI_NUMERICHOST | MPYNN_SOCKET_AI_NUMERICSERV | 2, MP_EOPNOTSUPP}
        };
        for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
            for (int numeric = 0; numeric <= 1; ++numeric) {
                const char *host = numeric ? "192.0.2.7" : "example.org";
                prepare(host, strlen(host), 80, invalid[i][0], invalid[i][1], invalid[i][2], invalid[i][3], 1);
                check_error(6, OS_ERROR, invalid[i][4], 0, 0);
                prepare(host, strlen(host), 0, invalid[i][0], invalid[i][1], invalid[i][2], invalid[i][3], 1);
                set_service("http", 4, 80);
                check_error(6, OS_ERROR, invalid[i][4], 0, 0);
            }
        }
    } else if (!strcmp(mode, "invalid-ports")) {
        const int ports[] = {-1, 65536};
        for (size_t p = 0; p < 2; ++p) {
            prepare("example.org", 11, ports[p], 0, 0, 0, 0, 1);
            check_error(6, VALUE_ERROR, 0, 0, 0);
        }
    } else if (!strcmp(mode, "embedded-nul")) {
        static const struct { const char *host; size_t len; } names[] = {
            {"example\0org", 11}, {"example.org\0", 12}, {"192.0.2.7\0suffix", 16},
            {"192.0.2.7\0", 10}, {"1.2\0.3.4", 8},
        };
        for (size_t f = 0; f < 8; ++f) {
            for (size_t h = 0; h < sizeof(names) / sizeof(names[0]); ++h) {
                for (int nics = 0; nics <= 2; ++nics) {
                    prepare(names[h].host, names[h].len, 80, 0, 0, 0, supported_flags[f], nics);
                    check_error(6, VALUE_ERROR, 0, 0, 0);
                }
            }
        }
    } else if (!strcmp(mode, "hostname")) {
        prepare("example.org", 11, 443, 2, 1, 6, 0, 1);
        check_success(6, 1, 6, 1);
    } else if (!strcmp(mode, "skip-nonresolver")) {
        prepare("example.org", 11, 53, 0, 0, 17, 0, 2);
        check_success(6, 2, 17, 1);
    } else if (!strcmp(mode, "empty-hostname")) {
        prepare("", 0, 0, 0, 0, 0, 0, 1);
        check_success(2, 1, 6, 1);
    } else if (!strcmp(mode, "hostname-error")) {
        prepare("example.org", 11, 80, 0, 0, 0, 0, 1); dns_error = MP_ENETDOWN;
        check_error(2, OS_ERROR, MP_ENETDOWN, 0, 1);
    } else if (!strcmp(mode, "hostname-exception")) {
        prepare("example.org", 11, 80, 0, 0, 0, 0, 1); dns_interrupt = 1;
        check_error(2, VALUE_ERROR, 0, 0, 1);
        CHECK(!strcmp(exception.message, "DNS callback interrupted"));
        // An actual DNS exception unwinds to our outer frame, not an inner parser frame.
        prepare("example.org", 11, 80, 0, 0, 0, 0, 1);
        check_success(2, 1, 6, 1);
    } else if (!strcmp(mode, "no-nic")) {
        prepare("example.org", 11, 80, 0, 0, 0, 0, 0);
        check_error(2, OS_MESSAGE, 0, 0, 0);
        CHECK(exception.message && strstr(exception.message, "NIC"));
    } else CHECK(!"unknown scenario");
    puts("PASS"); return 0;
}
"""


@unittest.skipUnless(COMPILER, "host GCC is not installed")
class GetAddrInfoHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text(encoding="utf-8")
        start = source.index("static mp_obj_t mod_socket_getaddrinfo(")
        end = source.index("static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_socket_getaddrinfo_obj", start)
        callback = source[start:end]
        helper_start = source.index("static bool socket_parse_ipv4_literal(")
        helper_end = source.index("\n}", helper_start) + len("\n}")
        helper = source[helper_start:helper_end] + "\n"
        if "netutils_parse_ipv4_addr" in callback or "nlr_" in callback:
            raise AssertionError("getaddrinfo must use the literal helper without an upstream parser or inner NLR")
        # Compile the real port definitions, not a duplicate set of fake flag values.
        header = SOCKET_HEADER.read_text(encoding="utf-8")
        definitions = []
        exports = []
        globals_table = source[source.index("static const mp_rom_map_elem_t mp_module_socket_globals_table[]"):]
        for name in FLAG_NAMES:
            define = re.search(r"^#define MPYNN_SOCKET_" + name + r"\s+[^\n]+$", header, re.MULTILINE)
            if define is None:
                raise AssertionError("missing port flag definition: " + name)
            definitions.append(define.group(0))
            entry = re.search(
                r"\{\s*MP_ROM_QSTR\(MP_QSTR_" + name
                + r"\),\s*MP_ROM_INT\(MPYNN_SOCKET_" + name + r"\)\s*\},",
                globals_table)
            if entry is None:
                raise AssertionError("missing module flag export: " + name)
            exports.append(entry.group(0))
        flag_definitions = "\n".join(definitions) + "\n"
        # The entries below are copied verbatim from the actual module globals.
        export_snippet = r"""
#define MP_ROM_QSTR(q) (q)
#define MP_ROM_INT(i) (i)
enum { MP_QSTR_AI_PASSIVE, MP_QSTR_AI_NUMERICHOST, MP_QSTR_AI_NUMERICSERV };
static const struct { int key, value; } flag_exports[] = {
""" + "\n".join(exports) + "\n};\n"
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-getaddrinfo-host-")

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
        harness = cls.root / "getaddrinfo.c"
        harness.write_text(flag_definitions + PRELUDE + helper + callback + export_snippet + HARNESS, encoding="utf-8")
        cls.executable = cls.root / "getaddrinfo-host.exe"
        cls.env = dict(os.environ)
        cls.env["PATH"] = str(Path(COMPILER).parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [COMPILER, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             str(harness), "-o", str(cls.executable)], cwd=cls.root, env=cls.env,
            capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host GCC compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, mode):
        result = subprocess.run([str(self.executable), mode], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_numeric_ipv4_defaults_without_a_nic(self):
        self.run_scenario("defaults")

    def test_explicit_and_inferred_tcp_udp_tuple_fields(self):
        self.run_scenario("valid-matrix")

    def test_output_address_and_port_boundaries(self):
        self.run_scenario("port-boundaries")

    def test_named_services_infer_or_accept_only_their_fixed_transport(self):
        self.run_scenario("services")

    def test_named_service_transport_conflicts_never_parse_or_resolve(self):
        self.run_scenario("service-conflicts")

    def test_unknown_or_non_strict_services_use_eopnotsupp(self):
        self.run_scenario("unknown-services")

    def test_decimal_strings_preserve_integer_transport_defaults(self):
        self.run_scenario("decimal-services")

    def test_out_of_range_decimal_strings_never_parse_or_resolve(self):
        self.run_scenario("invalid-decimal-services")

    def test_service_embedded_nul_never_parses_or_resolves(self):
        self.run_scenario("service-nul")

    def test_all_supported_flags_preserve_numeric_hosts_integer_decimal_and_none_ports(self):
        self.run_scenario("supported-flags")

    def test_none_host_selects_passive_or_loopback_ipv4_without_parser_or_nic(self):
        self.run_scenario("none-host")

    def test_both_none_raise_valueerror_for_every_supported_flag_combination(self):
        self.run_scenario("both-none")

    def test_ipv4_helper_is_length_bounded_and_preserves_output_on_failure(self):
        self.run_scenario("ipv4-helper")

    def test_strict_ipv4_literals_and_malformed_numeric_hosts_for_all_flag_masks(self):
        self.run_scenario("strict-numeric-hosts")

    def test_nonliteral_hosts_reach_dns_untruncated_unless_numeric_host_is_required(self):
        self.run_scenario("full-hostname")

    def test_numeric_host_flag_rejects_invalid_literals_without_dns_and_cleans_nlr(self):
        self.run_scenario("numeric-host-required")

    def test_numeric_service_flag_rejects_all_named_services_before_parser_or_dns(self):
        self.run_scenario("numeric-service-required")

    def test_passive_flag_does_not_change_hostname_lookup_or_zero_port(self):
        self.run_scenario("passive-hostname")

    def test_none_and_empty_strings_have_distinct_host_and_service_semantics(self):
        self.run_scenario("none-empty-semantics")

    def test_unsupported_flags_and_families_with_none_never_parse_or_resolve(self):
        self.run_scenario("invalid-none-hints")

    def test_actual_header_flag_values_and_module_exports_compile(self):
        self.run_scenario("exports")

    def test_invalid_hints_and_conflicts_never_parse_or_resolve(self):
        self.run_scenario("invalid-hints")

    def test_invalid_ports_never_parse_or_resolve(self):
        self.run_scenario("invalid-ports")

    def test_embedded_nul_never_parses_or_resolves(self):
        self.run_scenario("embedded-nul")

    def test_hostname_and_empty_host_delegate_to_nic_callback(self):
        for mode in ("hostname", "skip-nonresolver", "empty-hostname"):
            with self.subTest(mode=mode):
                self.run_scenario(mode)

    def test_hostname_errors_and_exceptions_propagate(self):
        for mode in ("hostname-error", "hostname-exception", "no-nic"):
            with self.subTest(mode=mode):
                self.run_scenario(mode)


if __name__ == "__main__":
    unittest.main()
