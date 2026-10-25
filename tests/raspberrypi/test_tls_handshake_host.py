# SPDX-License-Identifier: MIT
"""Real mbedTLS 3.6.6 TLS over bounded, nonblocking, in-memory BIO rings.

Compile the Raspberry Pi's actual mbedtls/mbedtls_config_port.h, tls_clock.c,
MicroPython timeutils, and hardware-poll glue. Only the UTC provider, monotonic
clock, MP allocation hooks, and random-byte HAL are host fakes. The deterministic
RNG is TEST ONLY, not suitable for production or evidence of entropy quality.
No sockets, internet, firmware build, global configuration changes, or board.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'ports/raspberrypi'
MP = ROOT / 'lib/micropython'
TLS = MP / 'lib/mbedtls'

OBJ = r'''
#pragma once
#include <stdint.h>
#include <stdbool.h>
typedef uint32_t mp_uint_t;
typedef int32_t mp_int_t;
typedef uint32_t mp_timestamp_t;
typedef void *mp_obj_t;
#define MICROPY_TIMESTAMP_IMPL 0
#define MICROPY_TIMESTAMP_IMPL_UINT 0
#define MICROPY_EPOCH_IS_1970 0
static inline mp_uint_t mp_obj_get_uint(mp_obj_t o) { (void)o; return 0; }
static inline mp_obj_t mp_obj_new_int_from_uint(mp_uint_t n) { (void)n; return 0; }
'''

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include "tls_random_bridge.h"
#include "mbedtls/build_info.h"
#include "mbedtls/ssl.h"
#include "mbedtls/entropy.h"
#include "mbedtls/ctr_drbg.h"
#include "mbedtls/error.h"
#include "fixtures.h"

#if MBEDTLS_VERSION_NUMBER != 0x03060600
#error "This regression test targets the vendored mbedTLS 3.6.6"
#endif
#if !defined(MBEDTLS_PLATFORM_MEMORY) || !defined(MBEDTLS_ENTROPY_HARDWARE_ALT)
#error "Must use the actual bare-metal Raspberry Pi configuration"
#endif
#define STEP_CAP 20000
#define RING_SIZE 257

/* TEST ONLY: deterministic fake RTC and entropy, never production hooks. */
static int utc_available;
static time_t fake_utc;
static uint64_t ticks;
static uint64_t random_state = UINT64_C(0x243f6a8885a308d3);
static size_t random_calls;
int mpynn_tls_get_utc(time_t *out) {
    *out = fake_utc;
    return utc_available;
}
uint64_t mpynn_ticks_us64(void) { return ticks; }
void mp_hal_get_random(size_t length, void *buffer) {
    unsigned char *bytes = buffer;
    ++random_calls;
    for (size_t i = 0; i < length; ++i) {
        random_state ^= random_state << 13;
        random_state ^= random_state >> 7;
        random_state ^= random_state << 17;
        bytes[i] = (unsigned char)(random_state >> 24);
    }
}

/* Fake MicroPython tracked allocation, including alignment and leak checks. */
typedef union allocation allocation;
union allocation {
    struct { allocation *next; } link;
    max_align_t alignment;
};
static allocation *allocations;
static size_t live_allocations, peak_allocations;
void *m_tracked_calloc(size_t count, size_t size) {
    if (size && count > (SIZE_MAX - sizeof(allocation)) / size) return NULL;
    allocation *a = calloc(1, sizeof(*a) + count * size);
    if (!a) return NULL;
    a->link.next = allocations;
    allocations = a;
    ++live_allocations;
    if (live_allocations > peak_allocations) peak_allocations = live_allocations;
    return a + 1;
}
void m_tracked_free(void *ptr) {
    if (!ptr) return;
    allocation *a = (allocation *)ptr - 1;
    allocation **link = &allocations;
    while (*link && *link != a) link = &(*link)->link.next;
    assert(*link == a); /* Detect foreign pointers and double frees. */
    *link = a->link.next;
    assert(live_allocations);
    --live_allocations;
    free(a);
}

/* Real TLS records are deliberately fragmented and backpressured. */
typedef struct {
    unsigned char data[RING_SIZE];
    size_t head, length, sent, received, want_read, want_write, wraps;
} ring;
typedef struct { ring *incoming, *outgoing; } bio;
static int bio_send(void *context, const unsigned char *data, size_t length) {
    ring *r = ((bio *)context)->outgoing;
    if (!length) return 0;
    if (r->length == RING_SIZE) {
        ++r->want_write;
        return MBEDTLS_ERR_SSL_WANT_WRITE;
    }
    size_t n = length;
    if (n > 73) n = 73;
    if (n > RING_SIZE - r->length) n = RING_SIZE - r->length;
    size_t tail = (r->head + r->length) % RING_SIZE;
    for (size_t i = 0; i < n; ++i) {
        r->data[tail] = data[i];
        if (++tail == RING_SIZE) { tail = 0; ++r->wraps; }
    }
    r->length += n;
    r->sent += n;
    return (int)n;
}
static int bio_recv(void *context, unsigned char *data, size_t length) {
    ring *r = ((bio *)context)->incoming;
    if (!length) return 0;
    if (!r->length) {
        ++r->want_read;
        return MBEDTLS_ERR_SSL_WANT_READ;
    }
    size_t n = length;
    if (n > 59) n = 59;
    if (n > r->length) n = r->length;
    for (size_t i = 0; i < n; ++i) {
        data[i] = r->data[r->head];
        r->head = (r->head + 1) % RING_SIZE;
    }
    r->length -= n;
    r->received += n;
    return (int)n;
}
static int retryable(int result) {
    return result == MBEDTLS_ERR_SSL_WANT_READ ||
           result == MBEDTLS_ERR_SSL_WANT_WRITE;
}
static void check(int result) {
    if (result) {
        char description[256];
        mbedtls_strerror(result, description, sizeof description);
        fprintf(stderr, "Unexpected mbedTLS result -0x%04x: %s\n",
                (unsigned)-result, description);
        abort();
    }
}

typedef struct {
    mbedtls_ssl_context ssl;
    mbedtls_ssl_config config;
    mbedtls_entropy_context entropy;
    mbedtls_ctr_drbg_context drbg;
} peer;
static void peer_init(peer *p, int endpoint) {
    mbedtls_ssl_init(&p->ssl);
    mbedtls_ssl_config_init(&p->config);
    mbedtls_entropy_init(&p->entropy);
    mbedtls_ctr_drbg_init(&p->drbg);
    const unsigned char personal[] = "TEST ONLY host TLS handshake";
    check(mbedtls_ctr_drbg_seed(&p->drbg, mbedtls_entropy_func, &p->entropy,
                               personal, sizeof personal));
    check(mbedtls_ssl_config_defaults(&p->config, endpoint,
                                     MBEDTLS_SSL_TRANSPORT_STREAM,
                                     MBEDTLS_SSL_PRESET_DEFAULT));
    mbedtls_ssl_conf_rng(&p->config, mbedtls_ctr_drbg_random, &p->drbg);
    mbedtls_ssl_conf_min_tls_version(&p->config, MBEDTLS_SSL_VERSION_TLS1_2);
    mbedtls_ssl_conf_max_tls_version(&p->config, MBEDTLS_SSL_VERSION_TLS1_2);
}
static void peer_free(peer *p) {
    mbedtls_ssl_free(&p->ssl);
    mbedtls_ssl_config_free(&p->config);
    mbedtls_ctr_drbg_free(&p->drbg);
    mbedtls_entropy_free(&p->entropy);
}

/* Each invocation advances at most one handshake state on each side. */
static int handshake(peer *client, peer *server, int *failed_client,
                     unsigned *steps) {
    for (*steps = 0; *steps < STEP_CAP; ++*steps) {
        ticks += 1000;
        if (!mbedtls_ssl_is_handshake_over(&client->ssl)) {
            int result = mbedtls_ssl_handshake_step(&client->ssl);
            if (result && !retryable(result)) {
                *failed_client = 1;
                return result;
            }
        }
        if (!mbedtls_ssl_is_handshake_over(&server->ssl)) {
            int result = mbedtls_ssl_handshake_step(&server->ssl);
            if (result && !retryable(result)) {
                *failed_client = 0;
                return result;
            }
        }
        if (mbedtls_ssl_is_handshake_over(&client->ssl) &&
            mbedtls_ssl_is_handshake_over(&server->ssl)) return 0;
    }
    fprintf(stderr, "Handshake exceeded finite %u step cap\n", STEP_CAP);
    abort();
}

static void transfer(mbedtls_ssl_context *sender, mbedtls_ssl_context *receiver,
                     unsigned char salt) {
    unsigned char sent[8705], received[sizeof sent];
    for (size_t i = 0; i < sizeof sent; ++i) sent[i] = (unsigned char)(i + salt);
    size_t written = 0, read = 0;
    for (unsigned step = 0; step < STEP_CAP; ++step) {
        ticks += 1000;
        if (written < sizeof sent) {
            size_t n = sizeof sent - written;
            if (n > 2048) n = 2048;
            int result = mbedtls_ssl_write(sender, sent + written, n);
            if (result > 0) written += (size_t)result;
            else if (!retryable(result)) { check(result); abort(); }
        }
        if (read < sizeof received) {
            size_t n = sizeof received - read;
            if (n > 311) n = 311;
            int result = mbedtls_ssl_read(receiver, received + read, n);
            if (result > 0) read += (size_t)result;
            else if (!retryable(result)) { check(result); abort(); }
        }
        if (written == sizeof sent && read == sizeof received) {
            assert(memcmp(sent, received, sizeof sent) == 0);
            return;
        }
    }
    fprintf(stderr, "Binary record transfer exceeded finite step cap\n");
    abort();
}

int main(int argc, char **argv) {
    assert(argc == 2);
    const char *scenario = argv[1];
    int none = strcmp(scenario, "cert_none_unset") == 0;
    int success = none || strcmp(scenario, "cert_required_valid") == 0;
    int wrong_ca = strcmp(scenario, "wrong_ca") == 0;
    int wrong_hostname = strcmp(scenario, "wrong_hostname") == 0;
    int unset = none || strcmp(scenario, "unset_utc") == 0;
    int expired = strcmp(scenario, "expired_utc") == 0;
    int future = strcmp(scenario, "future_utc") == 0;
    assert(success || wrong_ca || wrong_hostname || unset || expired || future);
    utc_available = !unset;
    fake_utc = unset ? (time_t)-1 : (time_t)1735689600; /* 2025-01-01 UTC */
    if (expired) fake_utc = (time_t)1893456000; /* 2030-01-01 UTC */
    if (future) fake_utc = (time_t)1514764800; /* 2018-01-01 UTC */
    assert(mpynn_tls_time_is_valid() == !unset);
    if (unset) {
        time_t out = 123;
        assert(mpynn_tls_time(&out) == (time_t)-1 && out == (time_t)-1);
    }

    mbedtls_x509_crt cert, ca;
    mbedtls_pk_context key;
    mbedtls_x509_crt_init(&cert);
    mbedtls_x509_crt_init(&ca);
    mbedtls_pk_init(&key);
    check(mbedtls_x509_crt_parse(&cert, server_cert, sizeof server_cert));
    check(mbedtls_x509_crt_parse(&ca, wrong_ca ? wrong_ca_cert : ca_cert,
                               wrong_ca ? sizeof wrong_ca_cert : sizeof ca_cert));
    /* These are the inspected vendored fixture's actual dates, not wall time. */
    assert(cert.valid_from.year == 2019 && cert.valid_from.mon == 2 &&
           cert.valid_from.day == 10 && cert.valid_from.hour == 14 &&
           cert.valid_from.min == 44 && cert.valid_from.sec == 6);
    assert(cert.valid_to.year == 2029 && cert.valid_to.mon == 2 &&
           cert.valid_to.day == 10 && cert.valid_to.hour == 14 &&
           cert.valid_to.min == 44 && cert.valid_to.sec == 6);

    peer client, server;
    peer_init(&client, MBEDTLS_SSL_IS_CLIENT);
    peer_init(&server, MBEDTLS_SSL_IS_SERVER);
    check(mbedtls_pk_parse_key(&key, server_key, sizeof server_key, NULL, 0,
                              mbedtls_ctr_drbg_random, &server.drbg));
    check(mbedtls_pk_check_pair(&cert.pk, &key, mbedtls_ctr_drbg_random,
                               &server.drbg));
    mbedtls_ssl_conf_authmode(&server.config, MBEDTLS_SSL_VERIFY_NONE);
    check(mbedtls_ssl_conf_own_cert(&server.config, &cert, &key));
    mbedtls_ssl_conf_authmode(&client.config,
                             none ? MBEDTLS_SSL_VERIFY_NONE : MBEDTLS_SSL_VERIFY_REQUIRED);
    /* CERT_NONE deliberately has no trust anchors. */
    if (!none) mbedtls_ssl_conf_ca_chain(&client.config, &ca, NULL);
    check(mbedtls_ssl_setup(&client.ssl, &client.config));
    check(mbedtls_ssl_setup(&server.ssl, &server.config));
    check(mbedtls_ssl_set_hostname(&client.ssl,
                                  wrong_hostname ? "wrong.invalid" : "localhost"));
    ring c2s = {0}, s2c = {0};
    bio client_bio = {&s2c, &c2s}, server_bio = {&c2s, &s2c};
    mbedtls_ssl_set_bio(&client.ssl, &client_bio, bio_send, bio_recv, NULL);
    mbedtls_ssl_set_bio(&server.ssl, &server_bio, bio_send, bio_recv, NULL);

    int failed_client = 0;
    unsigned steps;
    int result = handshake(&client, &server, &failed_client, &steps);
    uint32_t flags = mbedtls_ssl_get_verify_result(&client.ssl);
    printf("%s: result=-0x%04x verify=0x%08lx steps=%u\n",
           scenario, (unsigned)-result, (unsigned long)flags, steps);
    fflush(stdout);
    if (success) {
        /* Do not silently weaken expectations if upstream CERT_NONE fails. */
        check(result);
        assert(flags == 0);
        assert(strcmp(mbedtls_ssl_get_version(&client.ssl), "TLSv1.2") == 0);
        transfer(&client.ssl, &server.ssl, 0);
        transfer(&server.ssl, &client.ssl, 37);
        assert(!c2s.length && !s2c.length);
        assert(c2s.sent == c2s.received && s2c.sent == s2c.received);
        assert(c2s.sent > 8705 && s2c.sent > 8705);
        assert(c2s.want_read + s2c.want_read > 0);
        assert(c2s.want_write + s2c.want_write > 0);
        assert(c2s.wraps > 0 && s2c.wraps > 0);
    } else {
        assert(result != 0 && failed_client);
        assert(!mbedtls_ssl_is_handshake_over(&client.ssl));
        if (wrong_ca || wrong_hostname || expired || future) {
            assert(result == MBEDTLS_ERR_X509_CERT_VERIFY_FAILED);
        }
        if (wrong_ca) assert(flags & MBEDTLS_X509_BADCERT_NOT_TRUSTED);
        if (wrong_hostname) assert(flags & MBEDTLS_X509_BADCERT_CN_MISMATCH);
        if (expired) assert(flags & MBEDTLS_X509_BADCERT_EXPIRED);
        if (future) assert(flags & MBEDTLS_X509_BADCERT_FUTURE);
        if (unset) assert(result == MBEDTLS_ERR_X509_FATAL_ERROR);
    }
    peer_free(&client);
    peer_free(&server);
    mbedtls_pk_free(&key);
    mbedtls_x509_crt_free(&ca);
    mbedtls_x509_crt_free(&cert);
    assert(random_calls > 0 && peak_allocations > 0);
    assert(live_allocations == 0 && allocations == NULL);
    puts("PASS (tracked allocations released)");
    return 0;
}
'''


class TLSHandshakeHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = os.environ.get('CC') or shutil.which('gcc') or 'E:/msys64/ucrt64/bin/gcc.exe'
        if not Path(cc).is_file():
            raise unittest.SkipTest('native gcc unavailable (set CC)')
        cls.env = os.environ.copy()
        cls.env['PATH'] = str(Path(cc).parent) + os.pathsep + cls.env.get('PATH', '')
        folder = tempfile.TemporaryDirectory(prefix='mpynn-tls-handshake-')
        cls.addClassCleanup(folder.cleanup)
        tmp = Path(folder.name)

        def write(name, content):
            path = tmp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            return str(path)

        write('py/obj.h', OBJ)
        write('py/mpconfig.h', '#define MICROPY_PY_SSL_DTLS 0\n'
              '#define MICROPY_PY_SSL 1\n#define MICROPY_SSL_MBEDTLS 1\n')
        write('py/mphal.h', '#include "tls_random_bridge.h"\n')
        # mbedTLS 3.6.6 moved tests/data_files into the framework submodule.
        data = TLS / 'framework/data_files'
        if not data.is_dir():
            data = TLS / 'tests/data_files'
        fixtures = {
            'server_cert': 'server2-sha256.crt',
            'server_key': 'server2.key',
            'ca_cert': 'test-ca-sha256.crt',
            'wrong_ca_cert': 'test-ca2.crt',
        }
        write('fixtures.h', '\n'.join(
            'static const unsigned char ' + name + '[] = ' +
            json.dumps((data / filename).read_text(encoding='ascii')) + ';'
            for name, filename in fixtures.items()))
        main = write('handshake_test.c', HARNESS)
        cls.exe = str(tmp / 'handshake.exe')
        # Same flags and real port configuration as test_tls_hooks_host.py.
        common = ['-std=c11', '-O2', '-flto', '-Wall', '-Wextra', '-Werror',
                  '-ffunction-sections', '-fdata-sections', '-I' + str(tmp),
                  '-I' + str(PORT), '-I' + str(MP), '-I' + str(TLS / 'include'),
                  '-DMBEDTLS_CONFIG_FILE="mbedtls/mbedtls_config_port.h"']
        # Disabled library modules compile away under the unmodified port config.
        sources = [str(path) for path in sorted((TLS / 'library').glob('*.c'))]
        sources += [str(PORT / 'tls_clock.c'),
                    str(MP / 'shared/timeutils/timeutils.c'), main]

        def compile_command(args):
            result = subprocess.run(args, env=cls.env, capture_output=True,
                                    text=True, timeout=180)
            if result.returncode:
                raise AssertionError('Host TLS compile failed:\n' +
                                     ' '.join(args) + '\n' + result.stdout + result.stderr)

        # Upstream hardware-poll glue ignores its context parameter. Suppress
        # only that warning for that source, retaining -Werror for our harness.
        alt = str(tmp / 'mbedtls_alt.o')
        compile_command([cc, *common, '-Wno-unused-parameter', '-c',
                         str(MP / 'extmod/mbedtls/mbedtls_alt.c'), '-o', alt])
        # X.509 hostname parsing calls Windows inet_pton for IP literals; this
        # links its string-conversion implementation, not a socket transport.
        host_libs = ['-lws2_32'] if os.name == 'nt' else []
        compile_command([cc, *common, *sources, alt,
                         '-Wl,--gc-sections', *host_libs, '-o', cls.exe])

    def run_scenario(self, name):
        # Both subprocess timeout and C handshake/record step caps prevent hangs.
        result = subprocess.run([self.exe, name], env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0,
                         name + '\n' + result.stdout + result.stderr)
        self.assertIn('PASS (tracked allocations released)', result.stdout)
        self.assertIn(name + ': result=', result.stdout)

    def test_cert_none_unavailable_utc_and_binary_records(self):
        self.run_scenario('cert_none_unset')

    def test_cert_required_valid_ca_hostname_utc_and_binary_records(self):
        self.run_scenario('cert_required_valid')

    def test_cert_required_wrong_ca(self):
        self.run_scenario('wrong_ca')

    def test_cert_required_wrong_hostname(self):
        self.run_scenario('wrong_hostname')

    def test_cert_required_unavailable_utc(self):
        self.run_scenario('unset_utc')

    def test_cert_required_expired_utc(self):
        self.run_scenario('expired_utc')

    def test_cert_required_before_validity_utc(self):
        self.run_scenario('future_utc')


if __name__ == '__main__':
    unittest.main()
