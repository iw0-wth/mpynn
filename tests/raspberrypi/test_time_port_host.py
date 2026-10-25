# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT=Path(__file__).resolve().parents[2]/'ports/raspberrypi'
GCC=Path('E:/msys64/ucrt64/bin/gcc.exe')

class TimePortTests(unittest.TestCase):
    def test_calendar_reads_share_rtc_and_fail_explicitly(self):
        if not GCC.is_file(): self.skipTest('host GCC unavailable')
        headers={
            'py/mperrno.h':'#define MP_EIO 5\n',
            'shared/timeutils/timeutils.h': '''
#include <stdint.h>
typedef struct {uint32_t observed;} timeutils_struct_time_t;
void timeutils_seconds_since_1970_to_struct_time(uint32_t, timeutils_struct_time_t*);
'''}
        source=r'''
#include <stdint.h>
#include <assert.h>
#include <setjmp.h>
typedef uint32_t mp_obj_t;
static uint32_t epoch=946684800; static int failed; static jmp_buf trap;
static _Noreturn void mp_raise_OSError(int error) {assert(error==5);longjmp(trap,1);}
static mp_obj_t mp_obj_new_int_from_uint(uint32_t v) {return v;}
#include "modtime_port.c"
int mpynn_rtc_get_utc(uint32_t *s,unsigned *v,unsigned *source) {*s=epoch;*v=0;*source=0;return failed;}
void timeutils_seconds_since_1970_to_struct_time(uint32_t s,timeutils_struct_time_t *tm) {tm->observed=s;}
int main(void) {
 timeutils_struct_time_t tm;
 assert(mp_time_time_get()==946684800);
 mp_time_localtime_get(&tm);assert(tm.observed==epoch);
 assert(mp_hal_time_ns()==UINT64_C(946684800000000000));
 epoch=1700000000;
 assert(mp_time_time_get()==epoch);
 mp_time_localtime_get(&tm);assert(tm.observed==epoch);
 failed=-1;
 if(!setjmp(trap)) {mp_time_time_get();assert(0);}
}
'''
        env=os.environ.copy();env['PATH']=str(GCC.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,text in headers.items():
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(text)
            src=root/'test.c';src.write_text(source);exe=root/'test.exe'
            for cmd in ([str(GCC),'-std=c11','-Wall','-Wextra','-Werror','-I'+str(root),'-iquote',str(PORT),str(src),'-o',str(exe)],[str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main()
