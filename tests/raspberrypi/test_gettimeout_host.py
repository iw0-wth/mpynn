# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
GCC=Path('E:/msys64/ucrt64/bin/gcc.exe')

class GetTimeoutTests(unittest.TestCase):
    def test_none_zero_and_fractional_seconds(self):
        if not GCC.is_file():self.skipTest('host GCC unavailable')
        source=(ROOT/'ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c').read_text()
        start=source.index('static mp_obj_t socket_gettimeout(')
        end=source.index('static MP_DEFINE_CONST_FUN_OBJ_1(socket_gettimeout_obj',start)
        program=r'''
#include <assert.h>
#include <stdint.h>
typedef void *mp_obj_t;
typedef float mp_float_t;
typedef struct {int32_t timeout;} mod_network_socket_obj_t;
#define MP_OBJ_TO_PTR(x) (x)
#define mp_const_none ((void*)0)
#define MICROPY_PY_BUILTINS_FLOAT 1
#define MICROPY_FLOAT_CONST(x) x##f
static float seconds;
static mp_obj_t mp_obj_new_float(float value){seconds=value;return &seconds;}
''' + source[start:end] + r'''
int main(void){
 mod_network_socket_obj_t s={-1};assert(socket_gettimeout(&s)==mp_const_none);
 s.timeout=0;assert(socket_gettimeout(&s)==&seconds && seconds==0.0f);
 s.timeout=1250;assert(socket_gettimeout(&s)==&seconds && seconds==1.25f);
 s.timeout=5000;assert(socket_gettimeout(&s)==&seconds && seconds==5.0f);
 assert(s.timeout==5000);
}
'''
        env=os.environ.copy();env['PATH']=str(GCC.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'test.c';exe=root/'test.exe';src.write_text(program)
            for cmd in ([str(GCC),'-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],[str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main()
