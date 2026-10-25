# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
GCC=Path('E:/msys64/ucrt64/bin/gcc.exe')

class TimeoutTests(unittest.TestCase):
    def test_real_settimeout_validates_before_mutation(self):
        if not GCC.is_file(): self.skipTest('host GCC unavailable')
        source=(ROOT/'ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c').read_text()
        start=source.index('static mp_obj_t socket_settimeout(')
        end=source.index('static MP_DEFINE_CONST_FUN_OBJ_2(socket_settimeout_obj',start)
        program=r'''
#include <stdint.h>
#include <stddef.h>
#include <setjmp.h>
#include <assert.h>
#include <math.h>
typedef uint32_t mp_uint_t;
typedef int32_t mp_int_t;
typedef float mp_float_t;
typedef void *mp_obj_t;
#define MP_OBJ_TO_PTR(x) (x)
#define mp_const_none NULL
#define MP_OBJ_NULL NULL
#define MICROPY_FLOAT_CONST(x) x##f
#define MICROPY_PY_SOCKET_EXTENDED_STATE 1
#define MP_ERROR_TEXT(x) x
struct Socket;
struct Proto {int (*settimeout)(struct Socket*,mp_uint_t,int*);};
typedef struct Socket {void*nic;struct Proto*nic_protocol;int32_t timeout;} mod_network_socket_obj_t;
static int calls;
static int apply_error;
static int raised_errno;
static mp_uint_t applied_ms;
static jmp_buf trap;
#if MICROPY_PY_BUILTINS_FLOAT
 typedef float test_input_t;
 static test_input_t value;
 static float mp_obj_get_float(mp_obj_t x) {(void)x;return value;}
#else
 typedef int32_t test_input_t;
 static test_input_t value;
 static int32_t mp_obj_get_int(mp_obj_t x) {(void)x;return value;}
#endif
static _Noreturn void mp_raise_ValueError(const char*x) {(void)x;longjmp(trap,1);}
static _Noreturn void mp_raise_OSError(int e) {raised_errno=e;longjmp(trap,2);}
static int apply(struct Socket*s,mp_uint_t ms,int*e) {
 ++calls;applied_ms=ms;
 if(apply_error){*e=apply_error;return -1;}
 s->timeout=(int32_t)ms;return 0;
}
''' + source[start:end] + r'''
static void expect_valid(struct Socket*s,mp_obj_t input,int32_t expected) {
 int before=calls;s->timeout=777;
 assert(socket_settimeout(s,input)==NULL);
 assert(s->timeout==expected);
 assert(calls==before+(s->nic!=NULL));
 if(s->nic!=NULL)assert(applied_ms==(mp_uint_t)expected);
}
static void expect_seconds(struct Socket*s,test_input_t seconds,int32_t expected) {
 value=seconds;expect_valid(s,s,expected);
}
static void expect_invalid(struct Socket*s,test_input_t seconds) {
 value=seconds;s->timeout=777;int before=calls;
 int exception=setjmp(trap);
 if(!exception){socket_settimeout(s,s);assert(0);}
 assert(exception==1);
 assert(s->timeout==777 && calls==before);
}
static void expect_apply_error(struct Socket*s,mp_obj_t input,mp_uint_t expected) {
 int before=calls;s->timeout=777;apply_error=123;raised_errno=0;
 int exception=setjmp(trap);
 if(!exception){socket_settimeout(s,input);assert(0);}
 assert(exception==2 && raised_errno==123);
 assert(s->timeout==777 && calls==before+1 && applied_ms==expected);
 apply_error=0;
}
int main(void) {
 struct Proto p={apply};mod_network_socket_obj_t s={NULL,&p,777};
 for(int bound=0;bound<2;++bound){
  s.nic=bound?&s:NULL;
  expect_valid(&s,NULL,-1);
  expect_seconds(&s,0,0);
  expect_seconds(&s,2,2000);
  expect_invalid(&s,-1);
  expect_invalid(&s,2147484);
  #if MICROPY_PY_BUILTINS_FLOAT
  expect_seconds(&s,0.0001f,1);
  expect_seconds(&s,0.00125f,2);
  expect_seconds(&s,0.0101f,11);
  expect_seconds(&s,1.2501f,1251);
  expect_seconds(&s,0.001f,1);
  expect_seconds(&s,1.25f,1250);
  // Exact binary32 nextafterf(0, +INFINITY), without a libm dependency.
  expect_seconds(&s,0x1p-149f,1);
  expect_seconds(&s,0x1p-126f,1);
  expect_seconds(&s,-0.0f,0);
  expect_invalid(&s,-0x1p-149f);
  expect_invalid(&s,-0.0001f);
  expect_invalid(&s,NAN);
  expect_invalid(&s,INFINITY);
  expect_invalid(&s,-INFINITY);
  // Largest float seconds below the guard; the next float rounds to 2^31 ms.
  expect_seconds(&s,2147483.5f,2147483520);
  expect_invalid(&s,2147483.75f);
  #else
  expect_seconds(&s,2147483,2147483000);
  #endif
 }
 s.nic=&s;
 value=2;expect_apply_error(&s,&s,2000);
 value=0;expect_apply_error(&s,&s,0);
 expect_apply_error(&s,NULL,UINT32_MAX);
 #if MICROPY_PY_BUILTINS_FLOAT
 value=0.00125f;expect_apply_error(&s,&s,2);
 #endif
 // A failed callback must not poison subsequent successful calls.
 expect_seconds(&s,2,2000);
}
'''
        env=os.environ.copy();env['PATH']=str(GCC.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'test.c';src.write_text(program)
            for mode in (0,1):
                exe=root/('test%d.exe'%mode)
                for cmd in ([str(GCC),'-std=c11','-Wall','-Wextra','-Werror',
                             '-DMICROPY_PY_BUILTINS_FLOAT='+str(mode),str(src),'-o',str(exe)],[str(exe)]):
                    r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                    self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main()
