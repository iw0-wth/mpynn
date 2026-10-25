# SPDX-License-Identifier: MIT
"""Native tests of real port hooks, MP timeutils, and mbedTLS X.509 time checks.

No build tree or ARM execution. Circle hardware and UTC/monotonic inputs are
stubbed; this does not test physical entropy quality or a TLS handshake.
"""
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


def compiler(name, variable):
    return os.environ.get(variable) or shutil.which(name) or str(
        Path('E:/msys64/ucrt64/bin') / (name + '.exe'))


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
CLOCK = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "tls_random_bridge.h"
#include "mbedtls/platform_time.h"
#include "mbedtls/platform_util.h"
#include "mbedtls/x509.h"
static uint64_t ticks;
uint64_t mpynn_ticks_us64(void) { return ticks; }
#ifdef OVERRIDE_UTC
static int valid;
static time_t utc;
int mpynn_tls_get_utc(time_t *out) { *out = utc; return valid; }
#endif
int main(void) {
    time_t out = 123;
    assert(!mpynn_tls_time_is_valid());
    assert(mpynn_tls_time(&out) == (time_t)-1 && out == (time_t)-1);
    mbedtls_x509_time cert = {2025, 1, 1, 0, 0, 0};
    assert(mbedtls_x509_time_is_past(&cert) == 1);
    assert(mbedtls_x509_time_is_future(&cert) == 1);
    struct tm t, before;
    memset(&t, 0x55, sizeof t); before = t;
    assert(mbedtls_platform_gmtime_r(&out, &t) == NULL);
    assert(memcmp(&t, &before, sizeof t) == 0);
    assert(mbedtls_platform_gmtime_r(NULL, &t) == NULL);
    out = 0;
    assert(mbedtls_platform_gmtime_r(&out, NULL) == NULL);
    assert(mbedtls_platform_gmtime_r(&out, &t) == &t);
    assert(t.tm_year == 70 && t.tm_mon == 0 && t.tm_mday == 1);
    assert(t.tm_wday == 4 && t.tm_yday == 0 && t.tm_isdst == 0);
    out = 951827696; // 2000-02-29 12:34:56 UTC
    assert(mbedtls_platform_gmtime_r(&out, &t) == &t);
    assert(t.tm_year == 100 && t.tm_mon == 1 && t.tm_mday == 29);
    assert(t.tm_hour == 12 && t.tm_min == 34 && t.tm_sec == 56);
    assert(t.tm_wday == 2 && t.tm_yday == 59 && t.tm_isdst == 0);
    out = INT32_MAX;
    assert(mbedtls_platform_gmtime_r(&out, &t) == &t);
    assert(t.tm_year == 138 && t.tm_mon == 0 && t.tm_mday == 19);
    if (sizeof(time_t) > 4) {
        out = (time_t)INT32_MAX + (time_t)1;
        assert(mbedtls_platform_gmtime_r(&out, &t) == NULL);
    }
    ticks = 999; assert(mbedtls_ms_time() == 0);
    ticks = 1000; assert(mbedtls_ms_time() == 1);
    ticks = UINT64_C(0x100000000) + 1234567;
    assert(mbedtls_ms_time() == (int64_t)(ticks / 1000));
    ticks = UINT64_MAX;
    assert(mbedtls_ms_time() == (int64_t)(ticks / 1000));
#ifdef OVERRIDE_UTC
    valid = 1; utc = 1735689600;
    assert(mpynn_tls_time_is_valid());
    assert(mpynn_tls_time(&out) == utc && out == utc);
    assert(!mbedtls_x509_time_is_past(&cert));
    assert(!mbedtls_x509_time_is_future(&cert));
    cert.year = 2024; assert(mbedtls_x509_time_is_past(&cert));
    cert.year = 2026; assert(mbedtls_x509_time_is_future(&cert));
    utc = (time_t)-1; assert(!mpynn_tls_time_is_valid());
    valid = 0; assert(mbedtls_x509_time_is_past(&cert));
#endif
}
'''
RNG = r'''
#include <cassert>
#include <cstring>
#include "tls_random_bridge.h"
unsigned level, constructions, calls;
struct Halt {};
extern "C" unsigned CurrentExecutionLevel(void) { return level; }
extern "C" void mpynn_platform_halt(void) { throw Halt(); }
int main() {
    unsigned char data[20];
    for (size_t n = 0; n <= 13; ++n) {
        memset(data, 0xaa, sizeof data); calls = constructions = 0;
        mp_hal_get_random(n, data + 1);
        assert(calls == (n + 3) / 4);
        assert(constructions == (n != 0));
        assert(data[0] == 0xaa && data[n + 1] == 0xaa);
        for (size_t i = 0; i < n; ++i) assert(data[i + 1] == (unsigned char)(0x11 * (i % 4 + 1)));
    }
    for (unsigned context = 0; context <= 2; ++context) {
        level = context; calls = constructions = 0;
        mp_hal_get_random(0, nullptr);
        assert(calls == 0 && constructions == 0);
        try {
            mp_hal_get_random(1, context ? data : nullptr);
            assert(false);
        } catch (const Halt &) {}
        assert(calls == 0 && constructions == 0);
    }
}
'''


class TLSHooksTests(unittest.TestCase):
    def test_real_sources(self):
        cc, cxx = compiler('gcc', 'CC'), compiler('g++', 'CXX')
        if not Path(cc).is_file() or not Path(cxx).is_file():
            self.skipTest('native gcc/g++ unavailable (set CC/CXX)')
        env = os.environ.copy()
        env['PATH'] = str(Path(cxx).parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            def write(name, content):
                path = tmp / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
                return str(path)
            def run(args):
                result = subprocess.run(args, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0,
                                 ' '.join(args) + '\n' + result.stdout + result.stderr)
            write('py/obj.h', OBJ)
            write('py/mpconfig.h', '#define MICROPY_PY_SSL_DTLS 0\n')
            common = ['-O2', '-flto', '-Wall', '-Wextra', '-Werror', '-ffunction-sections',
                      '-fdata-sections', '-I' + str(tmp), '-I' + str(PORT),
                      '-I' + str(MP), '-I' + str(TLS / 'include'),
                      '-DMBEDTLS_CONFIG_FILE="mbedtls/mbedtls_config_port.h"']
            objects = []
            for name, source in [('clock', PORT / 'tls_clock.c'),
                                 ('timeutils', MP / 'shared/timeutils/timeutils.c'),
                                 ('x509', TLS / 'library/x509.c')]:
                obj = str(tmp / (name + '.o'))
                run([cc, '-std=c11', *common, '-c', str(source), '-o', obj])
                objects.append(obj)
            main = write('clock_test.c', CLOCK)
            for override in (False, True):
                exe = str(tmp / ('clock_override.exe' if override else 'clock_default.exe'))
                run([cc, '-std=c11', *common, *(['-DOVERRIDE_UTC'] if override else []),
                     main, *objects, '-Wl,--gc-sections', '-o', exe])
                run([exe])
            write('circle/synchronize.h', '#define TASK_LEVEL 0\nextern "C" unsigned CurrentExecutionLevel(void);\n')
            write('circle/bcmrandom.h', '''#include <cstdint>
extern unsigned constructions, calls;
class CBcmRandomNumberGenerator {
public:
 CBcmRandomNumberGenerator() { ++constructions; }
 uint32_t GetNumber() { ++calls; return 0x44332211u; }
};
''')
            main = write('rng_test.cpp', RNG)
            exe = str(tmp / 'rng.exe')
            run([cxx, '-std=c++11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-fstrict-aliasing', '-I' + str(tmp), '-I' + str(PORT),
                 str(PORT / 'tls_random_bridge.cpp'), main, '-o', exe])
            run([exe])


if __name__ == '__main__':
    unittest.main()
