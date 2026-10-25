# SPDX-License-Identifier: MIT
"""Strict native tests of real WDT C binding and C++ bridge, no Pi MMIO.

Double treats every constructor/API/destructor call as hardware activity, checks
TASK_LEVEL and ownership order, and aborts on Circle's immediate-reboot Restart.
C binding runs against a tiny 32-bit-integer VM double, not real MP GC/parser.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / 'ports/raspberrypi'
WATCHDOG = r'''
#pragma once
#include <cassert>
extern unsigned CurrentExecutionLevel();
extern unsigned calls, constructions, destructions, starts, stops, last_timeout;
extern bool running;
extern unsigned time_left;
class CBcmWatchdog {
public:
    static const unsigned MaxTimeoutSeconds = 15;
    CBcmWatchdog() { touch(); ++constructions; }
    ~CBcmWatchdog() { touch(); assert(!running); ++destructions; }
    void Start(unsigned seconds) {
        touch(); assert(seconds >= 1 && seconds <= 15);
        ++starts; last_timeout = seconds; running = true; time_left = seconds;
    }
    void Stop() { touch(); ++stops; running = false; }
    void Restart(unsigned = 0) { assert(!"Circle Restart is an immediate reboot, NOT feed"); }
    bool IsRunning() const { touch(); return running; }
    unsigned GetTimeLeft() const { touch(); return time_left; }
private:
    static void touch() { assert(CurrentExecutionLevel() == 0); ++calls; }
};
'''
HARNESS = r'''
#include <cassert>
#include <climits>
#include <cstdio>
#include "machine_wdt.h"
#include <circle/bcmwatchdog.h>
unsigned mask, calls, constructions, destructions, starts, stops, last_timeout, time_left;
bool running;
unsigned CurrentExecutionLevel() { return mask & 0x40 ? 2 : mask & 0x80 ? 1 : 0; }
extern "C" void test_binding();
int main() {
    const unsigned char a = 0, b = 0;
    unsigned live = 99, left = 99;
    assert(mpynn_wdt_deinit_all() == 0 && calls == 0);
    assert(mpynn_wdt_feed(&a) == MPYNN_WDT_UNINITIALIZED);
    assert(mpynn_wdt_snapshot(&a, &live, &left) == MPYNN_WDT_UNINITIALIZED);
    assert(live == 99 && left == 99);
    assert(mpynn_wdt_init(nullptr, 0, 1, 1) == MPYNN_WDT_INVALID);
    for (int id : {-1, 1, INT_MIN, INT_MAX})
        assert(mpynn_wdt_init(&a, id, 1, 1) == MPYNN_WDT_INVALID);
    for (int timeout : {-1, 0, 16, 5000, INT_MIN, INT_MAX})
        assert(mpynn_wdt_init(&a, 0, timeout, 1) == MPYNN_WDT_INVALID);
    assert(mpynn_wdt_init(&a, 0, 1, 0) == MPYNN_WDT_INVALID);
    assert(mpynn_wdt_init(&a, 0, 1, 2) == MPYNN_WDT_INVALID);
    assert(calls == 0);
    for (unsigned m : {0x80u, 0x40u, 0xc0u}) {
        mask = m;
        assert(mpynn_wdt_init(&a, 0, 1, 1) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_init(&a, 0, 0, 0) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_feed(&a) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_snapshot(&a, &live, &left) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_deinit(&a) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_deinit_all() == MPYNN_WDT_BUSY);
        assert(calls == 0);
    }
    mask = 0;
    assert(mpynn_wdt_init(&a, 0, 0, 0) == 0 && calls == 0);
    assert(mpynn_wdt_feed(&a) == MPYNN_WDT_UNINITIALIZED && calls == 0);
    assert(mpynn_wdt_init(&b, 0, 1, 1) == MPYNN_WDT_BUSY && calls == 0);
    assert(mpynn_wdt_deinit(&b) == MPYNN_WDT_BUSY && calls == 0);
    assert(mpynn_wdt_snapshot(&a, &live, nullptr) == MPYNN_WDT_INVALID && calls == 0);
    assert(mpynn_wdt_snapshot(&a, &live, &left) == 0 && live == 0 && left == 0 && calls == 0);
    assert(mpynn_wdt_init(&a, 0, 1, 1) == 0 && constructions == 1 && starts == 1);
    assert(mpynn_wdt_init(&a, 0, 15, 1) == 0 && constructions == 1 && starts == 2);
    unsigned saved = calls;
    assert(mpynn_wdt_init(&a, 0, 0, 0) == 0 && calls == saved);
    assert(mpynn_wdt_init(&a, 0, 16, 1) == MPYNN_WDT_INVALID && calls == saved);
    assert(mpynn_wdt_feed(&b) == MPYNN_WDT_BUSY && calls == saved);
    assert(mpynn_wdt_snapshot(&b, &live, &left) == MPYNN_WDT_BUSY && calls == saved);
    assert(mpynn_wdt_feed(&a) == 0 && last_timeout == 15 && starts == 3);
    time_left = 7;
    assert(mpynn_wdt_snapshot(&a, &live, &left) == 0 && live == 1 && left == 7);
    // A hardware stop does not make feed an immediate reboot: Start restores
    // precisely the last explicitly configured timeout.
    running = false;
    saved = calls;
    assert(mpynn_wdt_snapshot(&a, &live, &left) == 0 && live == 0 && left == 0 && calls == saved + 1);
    assert(mpynn_wdt_feed(&a) == 0 && running && time_left == 15);
    for (unsigned m : {0x80u, 0x40u, 0xc0u}) {
        mask = m; saved = calls;
        assert(mpynn_wdt_init(&a, 0, 10, 1) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_feed(&a) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_snapshot(&a, &live, &left) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_deinit(&a) == MPYNN_WDT_BUSY);
        assert(mpynn_wdt_deinit_all() == MPYNN_WDT_BUSY);
        assert(calls == saved && running);
    }
    mask = 0;
    assert(mpynn_wdt_deinit(&a) == 0 && stops == 1 && destructions == 1 && !running);
    saved = calls;
    assert(mpynn_wdt_deinit(&a) == 0 && calls == saved);
    assert(mpynn_wdt_feed(&a) == MPYNN_WDT_UNINITIALIZED && calls == saved);
    assert(mpynn_wdt_init(&b, 0, 2, 1) == 0 && constructions == 2);
    assert(mpynn_wdt_deinit_all() == 0 && stops == 2 && destructions == 2);
    assert(mpynn_wdt_feed(&b) == MPYNN_WDT_UNINITIALIZED);
    test_binding();
    std::puts("PASS");
}
'''
RUNTIME = r'''
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
typedef uintptr_t mp_obj_t;
typedef int32_t mp_int_t;
typedef struct mp_obj_type mp_obj_type_t;
typedef struct { const mp_obj_type_t *type; } mp_obj_base_t;
typedef union { mp_obj_t u_obj; mp_int_t u_int; } mp_arg_val_t;
typedef struct { unsigned qstr, flags; mp_arg_val_t defval; } mp_arg_t;
typedef struct { uintptr_t qstr, value; } mp_rom_map_elem_t;
typedef struct { size_t count; const mp_rom_map_elem_t *table; } mp_obj_dict_t;
struct mp_obj_type {
    mp_obj_t (*make_new)(const mp_obj_type_t *, size_t, size_t, const mp_obj_t *);
    const mp_obj_dict_t *locals;
};
enum { MP_QSTR_id=10, MP_QSTR_timeout, MP_QSTR_feed, MP_QSTR_restart,
    MP_QSTR_deinit, MP_QSTR_is_running, MP_QSTR_time_left, MP_QSTR_WDT };
#define MP_ARG_INT 1
#define MP_ARG_OBJ 2
#define MP_TYPE_FLAG_NONE 0
#define MP_OBJ_NULL ((mp_obj_t)0)
#define mp_const_none ((mp_obj_t)2)
#define MP_OBJ_FROM_PTR(p) ((mp_obj_t)(uintptr_t)(p))
#define MP_OBJ_TO_PTR(p) ((void *)(uintptr_t)(p))
#define MP_ROM_QSTR(q) q
#define MP_ROM_PTR(p) ((uintptr_t)(p))
#define MP_ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define MP_ERROR_TEXT(t) t
#define MP_DEFINE_CONST_FUN_OBJ_1(name, fn) const struct {mp_obj_t (*fun)(mp_obj_t);} name = {fn}
#define MP_DEFINE_CONST_DICT(name, entries) const mp_obj_dict_t name = {MP_ARRAY_SIZE(entries), entries}
#define MP_DEFINE_CONST_OBJ_TYPE(name, q, flags, mk, fn, ld, dict) const mp_obj_type_t name = {fn, dict}
mp_int_t mp_obj_get_int(mp_obj_t obj);
void mp_arg_parse_all_kw_array(size_t n_args, size_t n_kw, const mp_obj_t *all,
    size_t n_allowed, const mp_arg_t *allowed, mp_arg_val_t *out);
mp_obj_t mp_obj_new_bool(bool value);
mp_obj_t mp_obj_new_int_from_uint(unsigned value);
_Noreturn void mp_raise_ValueError(const char *message);
_Noreturn void mp_raise_OSError(int error);
'''
BINDING = r'''
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include "machine_wdt.c"
extern unsigned calls, starts, stops, mask, last_timeout;
static jmp_buf exception;
static int expecting, raised;
static mp_obj_t integer(int32_t v) { return (mp_obj_t)((int64_t)v * 2 + 1); }
mp_int_t mp_obj_get_int(mp_obj_t o) {
    if (!(o & 1)) mp_raise_ValueError("not an integer");
    return (mp_int_t)(((intptr_t)o - 1)/2);
}
mp_obj_t mp_obj_new_bool(bool b) { return integer(b); }
mp_obj_t mp_obj_new_int_from_uint(unsigned v) { return integer((int32_t)v); }
_Noreturn void mp_raise_ValueError(const char *s) {
    assert(s && expecting); raised = -100; longjmp(exception, 1);
}
_Noreturn void mp_raise_OSError(int e) {
    assert(expecting); raised = e; longjmp(exception, 1);
}
void mp_arg_parse_all_kw_array(size_t n_args, size_t n_kw, const mp_obj_t *all,
    size_t count, const mp_arg_t *allowed, mp_arg_val_t *out) {
    if (n_args > count) mp_raise_ValueError("too many arguments");
    bool used[2] = {false, false};
    assert(count == 2);
    for (size_t i=0; i<count; ++i) out[i] = allowed[i].defval;
    for (size_t i=0; i<n_args+n_kw; ++i) {
        size_t target=i;
        mp_obj_t value;
        if (i < n_args) value=all[i];
        else {
            unsigned key=(unsigned)all[n_args+2*(i-n_args)];
            for (target=0; target<count && allowed[target].qstr != key; ++target) {}
            if (target==count) mp_raise_ValueError("unknown keyword");
            value=all[n_args+2*(i-n_args)+1];
        }
        if (used[target]) mp_raise_ValueError("duplicate argument");
        used[target]=true;
        if (allowed[target].flags == MP_ARG_INT) out[target].u_int=mp_obj_get_int(value);
        else out[target].u_obj=value;
    }
}
#define ERROR(code, expr) do { expecting=1; raised=0; if (!setjmp(exception)) { \
    (void)(expr); assert(!"expected exception"); } assert(raised==(code)); expecting=0; } while(0)
void test_binding(void) {
    unsigned saved=calls;
    mp_obj_t self=machine_wdt_type.make_new(&machine_wdt_type, 0, 0, NULL);
    assert(self == MP_OBJ_FROM_PTR(&wdt0) && calls==saved);
    assert(wdt_is_running_obj.fun(self)==integer(0) && calls==saved);
    ERROR(MP_ENODEV, wdt_feed_obj.fun(self));
    assert(calls==saved);
    mp_obj_t args[4];
    for (int32_t id=-1; id<=1; id+=2) {
        args[0]=integer(id);
        ERROR(-100, wdt_make_new(NULL, 1, 0, args)); assert(calls==saved);
    }
    int32_t invalid[]={INT_MIN,-1,0,16,5000,INT_MAX};
    for (size_t i=0; i<MP_ARRAY_SIZE(invalid); ++i) {
        args[0]=MP_QSTR_timeout; args[1]=integer(invalid[i]);
        ERROR(-100, wdt_make_new(NULL, 0, 1, args)); assert(calls==saved);
    }
    args[0]=MP_QSTR_timeout; args[1]=mp_const_none;
    ERROR(-100, wdt_make_new(NULL, 0, 1, args)); assert(calls==saved);
    args[0]=integer(0); args[1]=integer(10);
    mask=0x80;
    ERROR(MP_EBUSY, wdt_make_new(NULL, 2, 0, args)); assert(calls==saved);
    mask=0;
    assert(wdt_make_new(NULL, 2, 0, args)==self && last_timeout==10);
    saved=calls;
    assert(wdt_make_new(NULL, 0, 0, NULL)==self && calls==saved);
    assert(wdt_feed_obj.fun(self)==mp_const_none && calls==saved+1);
    assert(wdt_time_left_obj.fun(self)==integer(10));
    // All registered functions are real, and restart aliases safe feed.
    assert(machine_wdt_type.locals->count == 5);
    assert(wdt_locals_table[0].value==wdt_locals_table[1].value);
    mask=0x40; saved=calls;
    ERROR(MP_EBUSY, wdt_feed_obj.fun(self));
    ERROR(MP_EBUSY, wdt_deinit_obj.fun(self));
    ERROR(MP_EBUSY, wdt_is_running_obj.fun(self));
    ERROR(MP_EBUSY, wdt_time_left_obj.fun(self));
    assert(calls==saved);
    mask=0;
    assert(wdt_deinit_obj.fun(self)==mp_const_none);
    saved=calls;
    assert(wdt_deinit_obj.fun(self)==mp_const_none && calls==saved);
    ERROR(MP_ENODEV, wdt_feed_obj.fun(self));
    assert(wdt_make_new(NULL, 0, 0, NULL)==self && calls==saved);
    ERROR(MP_ENODEV, wdt_feed_obj.fun(self));
    args[0]=MP_QSTR_id; args[1]=integer(0);
    args[2]=MP_QSTR_timeout; args[3]=integer(15);
    assert(wdt_make_new(NULL, 0, 2, args)==self && last_timeout==15);
    assert(mpynn_wdt_deinit_all()==0);
    ERROR(MP_ENODEV, wdt_feed_obj.fun(self));
    assert(wdt_make_new(NULL, 0, 0, NULL)==self);
    ERROR(MP_ENODEV, wdt_feed_obj.fun(self));
    assert(mpynn_wdt_deinit_all()==0);
}
'''


class MachineWDTHostTests(unittest.TestCase):
    def test_native_binding_and_bridge_context_validation_ownership_lifecycle(self):
        cxx = (os.environ.get('CXX') or
               ('E:/msys64/ucrt64/bin/g++.exe' if Path('E:/msys64/ucrt64/bin/g++.exe').is_file() else None) or
               shutil.which('g++') or shutil.which('clang++'))
        cc = (os.environ.get('CC') or
              ('E:/msys64/ucrt64/bin/gcc.exe' if Path('E:/msys64/ucrt64/bin/gcc.exe').is_file() else None) or
              shutil.which('gcc') or shutil.which('clang'))
        self.assertTrue(cxx and cc, 'native C and C++ compilers required')
        env = os.environ.copy()
        env['PATH'] = str(Path(cxx).parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory(prefix='machine-wdt-host-') as tmp:
            root = Path(tmp)
            for directory in ('circle', 'py', 'extmod'):
                (root / directory).mkdir()
            for filename, content in {
                'circle/bcmwatchdog.h': WATCHDOG,
                'circle/synchronize.h': '#define TASK_LEVEL 0\nunsigned CurrentExecutionLevel();\n',
                'circle/new.h': '#include <new>\n',
                'py/runtime.h': RUNTIME,
                'py/mperrno.h': '#define MP_EBUSY 16\n#define MP_ENODEV 19\n#define MP_EIO 5\n',
                'extmod/modmachine.h': '#include "py/runtime.h"\nextern const mp_obj_type_t machine_wdt_type;\n',
                'wdt_test.cpp': '#include <initializer_list>\n' + HARNESS,
                'binding_test.c': BINDING,
            }.items():
                (root / filename).write_text(content, encoding='utf-8')
            obj = root / 'binding.o'
            binary = root / ('wdt.exe' if os.name == 'nt' else 'wdt')
            common = ['-Wall', '-Wextra', '-Werror', '-pedantic', '-I', str(root), '-iquote', str(PORT)]
            result = subprocess.run([cc, '-std=c11', *common,
                '-c', str(root / 'binding_test.c'), '-o', str(obj)], env=env,
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([cxx, '-std=c++17', *common,
                str(root / 'wdt_test.cpp'), str(PORT / 'machine_wdt.cpp'), str(obj),
                '-o', str(binary)], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), 'PASS')

    def test_soft_reset_and_surface_contract(self):
        main = (PORT / 'mpmain.c').read_text(encoding='utf-8')
        cleanup = main.index('(void)mpynn_wdt_deinit_all();')
        self.assertLess(main.index('mpynn_irq_restore(0);'), cleanup)
        self.assertLess(cleanup, main.index('gc_sweep_all();'))
        self.assertLess(cleanup, main.index('mp_deinit();'))
        final_cleanup = main.rindex('mpynn_wdt_deinit_all();')
        self.assertLess(main.index('gc_sweep_all();'), final_cleanup)
        self.assertLess(final_cleanup, main.index('mp_deinit();'))
        cpp = (PORT / 'machine_wdt.cpp').read_text(encoding='utf-8')
        self.assertNotIn('#include "gpio_bridge.h"', cpp)
        self.assertNotIn('->Restart(', cpp)
        config = (PORT / 'mpconfigport.h').read_text(encoding='utf-8')
        self.assertIn('#define MICROPY_PY_MACHINE_WDT (1)', config)
        make = (PORT / 'Makefile').read_text(encoding='utf-8')
        self.assertIn('machine_wdt.c', make)
        self.assertIn('machine_wdt.cpp', make)
        self.assertNotIn('MP_QSTR_WDT', (PORT / 'modmachine_port.c').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
