# SPDX-License-Identifier: MIT
"""Execute the actual RTC datetime callback with a fake VM and clock."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2]/'ports/raspberrypi'
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')

class RTCDatetimeTests(unittest.TestCase):
    def test_boot_read_and_calendar_validation(self):
        if not CXX.is_file(): self.skipTest('host g++ unavailable')
        source=(PORT/'modmachine_port.c').read_text()
        start=source.index('static mp_obj_t mpynn_rtc_datetime(')
        end=source.index('static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mpynn_rtc_datetime_obj',start)
        init_start=source.index('static mp_obj_t mpynn_rtc_init(')
        init_end=source.index('static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mpynn_rtc_init_obj',init_start)
        harness=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
using mp_obj_t=intptr_t;
using mp_int_t=intptr_t;
using timeutils_timestamp_t=uint64_t;
#define MP_EIO 5
#define MP_ERROR_TEXT(s) s
#define MP_OBJ_NEW_SMALL_INT(x) (x)
static int last_hour, last_minute, last_second;
const mp_obj_t mp_const_none=0;
struct timeutils_struct_time_t {int tm_year,tm_mon,tm_mday,tm_wday,tm_hour,tm_min,tm_sec;};
static mp_obj_t input[8], output[8];
static size_t count=8;
static int sets=0;
static uint32_t now=946684800;
static bool calibrated=false;
void mp_arg_check_num(size_t n,size_t kw,size_t min,size_t max,bool) {assert(!kw && n>=min && n<=max);}
[[noreturn]] void mp_raise_OSError(int) {throw 1;}
[[noreturn]] void mp_raise_ValueError(const char*) {throw 2;}
[[noreturn]] void mp_raise_NotImplementedError(const char*) {throw 3;}
mp_obj_t mp_obj_new_int(int x) {return x;}
mp_obj_t mp_obj_new_tuple(size_t n,mp_obj_t *a) {assert(n==8);memcpy(output,a,sizeof output);return 123;}
mp_int_t mp_obj_get_int(mp_obj_t x) {return x;}
void mp_obj_get_array(mp_obj_t obj,size_t *n,mp_obj_t **p) {*n=obj==123?8:count;*p=obj==123?output:input;}
int mpynn_rtc_get_utc(uint32_t *s,unsigned *valid,unsigned *src) {*s=now;*valid=calibrated;*src=calibrated;return 0;}
int mpynn_rtc_set_utc(uint32_t s) {now=s;calibrated=true;++sets;return 0;}
unsigned timeutils_days_in_month(int y,int m) {
 const unsigned days[]={31,28,31,30,31,30,31,31,30,31,30,31};
 assert(m>=1 && m<=12);
 return days[m-1]+(m==2 && y%4==0 && (y%100!=0 || y%400==0));
}
void timeutils_seconds_since_1970_to_struct_time(uint32_t s,timeutils_struct_time_t *t) {
 assert(s==946684800);*t={2000,1,1,5,0,0,0};
}
timeutils_timestamp_t timeutils_seconds_since_1970(int y,int,int,int h,int m,int s) {
 last_hour=h;last_minute=m;last_second=s;
 return y==2038 ? uint64_t(INT32_MAX)+1 : 946684800;
}
''' + source[start:end] + source[init_start:init_end] + r'''
int main() {
 mp_obj_t args[]={0,0};
 // Boot clock is readable even though it is not externally calibrated.
 assert(mpynn_rtc_datetime(1,args)==123 && output[0]==2000 && output[3]==5);
 assert(!calibrated && sets==0);
 mp_obj_t good[]={2000,2,29,1,12,30,45,0};memcpy(input,good,sizeof input);
 assert(mpynn_rtc_datetime(2,args)==0 && sets==1 && calibrated);
 for(auto year: {2001,2100,1969,2038}) {
  input[0]=year;
  try {mpynn_rtc_datetime(2,args);assert(false);} catch(int e) {assert(e==2);}
 }
 input[0]=2000;input[1]=4;input[2]=31;
 try {mpynn_rtc_datetime(2,args);assert(false);} catch(int e) {assert(e==2);}
 input[1]=13;
 try {mpynn_rtc_datetime(2,args);assert(false);} catch(int e) {assert(e==2);}
 assert(sets==1);
 mp_obj_t init[]={2026,3,12,13,14,15,999,0};memcpy(input,init,sizeof input);
 assert(mpynn_rtc_init(2,args)==0 && sets==2);
 assert(last_hour==13 && last_minute==14 && last_second==15);
 count=7;
 try {mpynn_rtc_init(2,args);assert(false);} catch(int e) {assert(e==2);}
 assert(sets==2);
}
'''
        harness='#include <initializer_list>\n'+harness
        env=os.environ.copy();env['PATH']=str(CXX.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'rtc.cpp';exe=root/'rtc.exe';src.write_text(harness)
            for cmd in ([str(CXX),'-std=c++17','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],[str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__': unittest.main()
