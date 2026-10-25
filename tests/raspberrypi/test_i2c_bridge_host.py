# SPDX-License-Identifier: MIT
"""Strict host doubles for production machine_i2c.cpp; no MMIO/ARM/VM.

Constructor signatures/constants mirror the staged CI2CMaster override. These
checks test ownership/order, exact transfer results, limits, context rejection,
and deferred GC teardown, not electrical I2C or real GC execution.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'ports/raspberrypi'
HEADERS = {
    'circle/i2cmaster.h': r'''#pragma once
#include <stdint.h>
typedef uint8_t u8;
typedef bool boolean;
#define I2C_MASTER_TRANSFER_TIMEOUT_US 100000
#define I2C_MASTER_INALID_PARM 1
#define I2C_MASTER_ERROR_NACK 2
#define I2C_MASTER_ERROR_CLKT 3
#define I2C_MASTER_DATA_LEFT 4
#define I2C_MASTER_TIMEOUT 5
#define I2C_MASTER_BUS_BUSY 6
class CI2CMaster {
public:
    CI2CMaster(unsigned device, boolean fast = false, unsigned config = 0);
    ~CI2CMaster();
    boolean Initialize();
    void SetClock(unsigned hz);
    int Read(u8 addr, void *buf, unsigned count);
    int Write(u8 addr, const void *buf, unsigned count);
    int WriteReadRepeatedStart(u8 addr, const void *prefix, unsigned prefix_len,
        void *buf, unsigned count);
};
''',
    'circle/new.h': '#pragma once\n#include <new>\n',
    'circle/synchronize.h': '#pragma once\n#define TASK_LEVEL 0\nunsigned CurrentExecutionLevel();\n',
}
HARNESS = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <circle/i2cmaster.h>
#include "gpio_bridge.h"
#include "machine_i2c.h"
#define CHECK(c) do { if (!(c)) { std::fprintf(stderr,"%d: %s\n", __LINE__,#c); std::exit(1); } } while(0)
static unsigned level, constructors, destructors, inits, clocks, calls, claims, releases;
static bool init_ok = true, expected_fast;
static const void *pins[4];
static int fail_pin = -1, gpio_failure = MPYNN_GPIO_BUSY;
static int reply = 4;
static int expected_op;
static unsigned expected_len, expected_addr = 0x50, expected_prefix_len;
static const void *expected_buffer, *expected_prefix;
static const void *reentrant_owner;
unsigned CurrentExecutionLevel() { return level; }
extern "C" int mpynn_gpio_claim(int pin, const void *owner) {
    CHECK(level == 0 && owner && (pin == 2 || pin == 3)); ++claims;
    if (pin == fail_pin) return gpio_failure;
    if (pins[pin] && pins[pin] != owner) return MPYNN_GPIO_BUSY;
    pins[pin] = owner;
    return 0;
}
extern "C" int mpynn_gpio_release(int pin, const void *owner) {
    CHECK(level == 0 && owner && pins[pin] == owner); ++releases;
    if (destructors != constructors) CHECK(inits == 0); // partial claim rollback only
    pins[pin] = nullptr;
    return 0;
}
CI2CMaster::CI2CMaster(unsigned device, boolean fast, unsigned config) {
    CHECK(level == 0 && device == 1 && config == 0 && fast == expected_fast);
    CHECK(pins[2] && pins[2] == pins[3]); ++constructors;
}
CI2CMaster::~CI2CMaster() {
    CHECK(level == 0 && pins[2] && pins[2] == pins[3]); ++destructors;
}
boolean CI2CMaster::Initialize() { ++inits; return init_ok; }
void CI2CMaster::SetClock(unsigned hz) {
    CHECK(level == 0 && (hz == 100000 || hz == 400000)); ++clocks;
}
static int transfer(int op, u8 addr, const void *buf, unsigned len) {
    CHECK(level == 0 && pins[2] && pins[2] == pins[3]);
    CHECK(op == expected_op && addr == expected_addr && len == expected_len);
    CHECK(buf == expected_buffer); ++calls;
    if (reentrant_owner) {
        unsigned before = calls;
        CHECK(mpynn_i2c_write(reentrant_owner, 0x50, nullptr, 0) == MPYNN_I2C_BUSY);
        CHECK(mpynn_i2c_init(reentrant_owner, 100000, 100000) == MPYNN_I2C_BUSY);
        CHECK(mpynn_i2c_deinit(reentrant_owner, 0) == MPYNN_I2C_BUSY);
        CHECK(mpynn_i2c_deinit_all() == MPYNN_I2C_BUSY);
        CHECK(calls == before);
    }
    return reply;
}
int CI2CMaster::Read(u8 addr, void *buf, unsigned count) { return transfer(1,addr,buf,count); }
int CI2CMaster::Write(u8 addr, const void *buf, unsigned count) { return transfer(2,addr,buf,count); }
int CI2CMaster::WriteReadRepeatedStart(u8 addr, const void *prefix, unsigned plen, void *buf, unsigned count) {
    CHECK(prefix == expected_prefix && plen == expected_prefix_len);
    return transfer(3,addr,buf,count);
}
int main() {
    char a, b, buffer[8] = {}, prefix[2] = {0x12,0x34};
    CHECK(mpynn_i2c_init(nullptr,100000,100000) == MPYNN_I2C_INVALID);
    CHECK(mpynn_i2c_init(&a,1,100000) == MPYNN_I2C_INVALID);
    CHECK(mpynn_i2c_init(&a,100000,1) == MPYNN_I2C_INVALID);
    CHECK(claims == 0 && constructors == 0);
    level = 1;
    CHECK(mpynn_i2c_init(&a,100000,100000) == MPYNN_I2C_CONTEXT);
    CHECK(mpynn_i2c_read(&a,0x50,buffer,4) == MPYNN_I2C_CONTEXT);
    CHECK(mpynn_i2c_deinit_all() == MPYNN_I2C_CONTEXT);
    CHECK(claims == 0 && calls == 0);
    level = 0;
    CHECK(mpynn_i2c_read(&a,0x50,buffer,4) == MPYNN_I2C_NOT_READY);
    fail_pin = 2;
    CHECK(mpynn_i2c_init(&a,100000,100000) == MPYNN_I2C_BUSY);
    CHECK(claims == 1 && releases == 0 && constructors == 0);
    fail_pin = 3;
    CHECK(mpynn_i2c_init(&a,100000,100000) == MPYNN_I2C_BUSY);
    CHECK(claims == 3 && releases == 1 && !pins[2] && constructors == 0);
    fail_pin = 2; gpio_failure = MPYNN_GPIO_INVALID;
    CHECK(mpynn_i2c_init(&a,100000,100000) == MPYNN_I2C_BOARD);
    fail_pin = -1; init_ok = false;
    CHECK(mpynn_i2c_init(&a,100000,100000) == MPYNN_I2C_IO);
    CHECK(constructors == 1 && destructors == 1 && !pins[2] && !pins[3]);
    init_ok = true; expected_fast = true;
    CHECK(mpynn_i2c_init(&a,400000,100000) == 0);
    unsigned before = claims;
    CHECK(mpynn_i2c_init(&a,100000,100000) == 0);
    CHECK(claims == before && constructors == 2 && clocks == 1);
    CHECK(mpynn_i2c_init(&b,100000,100000) == MPYNN_I2C_BUSY);
    CHECK(mpynn_i2c_read(&b,0x50,buffer,4) == MPYNN_I2C_NOT_READY);
    CHECK(mpynn_i2c_deinit(&b,0) == 0 && destructors == 1);
    CHECK(mpynn_i2c_read(&a,128,buffer,4) == MPYNN_I2C_INVALID);
    CHECK(mpynn_i2c_write(&a,0x50,buffer,65536) == MPYNN_I2C_INVALID);
    CHECK(mpynn_i2c_read(&a,0x50,nullptr,4) == MPYNN_I2C_INVALID);
    CHECK(mpynn_i2c_write_read(&a,0x50,prefix,0,buffer,4) == MPYNN_I2C_INVALID);
    CHECK(mpynn_i2c_write_read(&a,0x50,prefix,17,buffer,4) == MPYNN_I2C_INVALID);
    CHECK(calls == 0);
    CHECK(mpynn_i2c_read(&a,0x50,nullptr,0) == 0 && calls == 0);
    expected_op = 1; expected_len = 4; expected_buffer = buffer;
    CHECK(mpynn_i2c_read(&a,0x50,buffer,4) == 4);
    reply = 3; CHECK(mpynn_i2c_read(&a,0x50,buffer,4) == MPYNN_I2C_IO);
    reply = 5; CHECK(mpynn_i2c_read(&a,0x50,buffer,4) == MPYNN_I2C_IO);
    const int native[] = {-1,-2,-3,-4,-5,-6,-99};
    const int mapped[] = {MPYNN_I2C_INVALID,MPYNN_I2C_NACK,MPYNN_I2C_TIMEOUT,
        MPYNN_I2C_IO,MPYNN_I2C_TIMEOUT,MPYNN_I2C_BUSY,MPYNN_I2C_IO};
    for(unsigned i=0; i<7; ++i) { reply=native[i]; CHECK(mpynn_i2c_read(&a,0x50,buffer,4)==mapped[i]); }
    reply = 0; expected_len = 0; expected_op = 2; expected_buffer = nullptr;
    CHECK(mpynn_i2c_write(&a,0x50,nullptr,0) == 0);
    expected_op=2; expected_len=4; expected_buffer=buffer; reply=4;
    reentrant_owner=&a;
    CHECK(mpynn_i2c_write(&a,0x50,buffer,4) == 4);
    reentrant_owner=nullptr;
    expected_op=3; expected_prefix=prefix; expected_prefix_len=2;
    CHECK(mpynn_i2c_write_read(&a,0x50,prefix,2,buffer,4) == 4);
    level=1; before=destructors;
    CHECK(mpynn_i2c_deinit(&a,0) == MPYNN_I2C_CONTEXT);
    CHECK(mpynn_i2c_deinit(&a,1) == 0);
    CHECK(destructors==before && pins[2]==&a);
    level=0; expected_fast=false;
    // Reusing SAME GC address must still flush deferred state and reconstruct.
    CHECK(mpynn_i2c_init(&a,100000,100000) == 0);
    CHECK(destructors==before+1 && constructors==3);
    CHECK(mpynn_i2c_deinit(&a,0) == 0);
    CHECK(mpynn_i2c_deinit(&a,0) == 0);
    CHECK(destructors==constructors && !pins[2] && !pins[3]);
    CHECK(mpynn_i2c_init(&b,100000,100000) == 0);
    CHECK(mpynn_i2c_deinit_all() == 0);
    CHECK(destructors==constructors && !pins[2] && !pins[3]);
    std::puts("I2C bridge strict ownership/limits/context/error contracts passed");
}
'''

class I2CBridgeHost(unittest.TestCase):
    def test_strict_contracts(self):
        compiler = shutil.which('g++') or 'E:/msys64/ucrt64/bin/g++.exe'
        if not Path(compiler).exists():
            self.skipTest('host g++ unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, contents in HEADERS.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding='utf-8')
            harness = root / 'test.cpp'
            harness.write_text(HARNESS, encoding='utf-8')
            binary = root / ('test.exe' if os.name == 'nt' else 'test')
            env = os.environ.copy()
            env['PATH'] = str(Path(compiler).parent) + os.pathsep + env.get('PATH', '')
            result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-I'+str(root), '-I'+str(PORT), str(harness), str(PORT/'machine_i2c.cpp'),
                '-o', str(binary)], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('contracts passed', result.stdout)

if __name__ == '__main__':
    unittest.main()
