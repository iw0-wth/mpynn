# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
GCC=Path('E:/msys64/ucrt64/bin/gcc.exe')

class SendallTests(unittest.TestCase):
    def test_partial_zero_and_invalid_send_results(self):
        if not GCC.is_file(): self.skipTest('host GCC unavailable')
        source=(ROOT/'ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c').read_text()
        start=source.index('static mp_obj_t socket_sendall(')
        end=source.index('static MP_DEFINE_CONST_FUN_OBJ_2(socket_sendall_obj',start)
        program=r'''
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
#include <setjmp.h>
typedef uintptr_t mp_uint_t;
typedef void *mp_obj_t;
typedef struct {void *buf;size_t len;} mp_buffer_info_t;
#define MP_OBJ_TO_PTR(x) (x)
#define MP_OBJ_NULL NULL
#define MP_BUFFER_READ 1
#define MP_EPIPE 32
#define MP_EAGAIN 11
#define MP_EIO 5
#define mp_const_none ((void*)1)
struct Socket;
struct Proto {mp_uint_t (*send)(struct Socket*,const void*,size_t,int*);};
typedef struct Socket {void *nic;struct Proto *nic_protocol;int timeout;} mod_network_socket_obj_t;
static jmp_buf trap;
static int raised, mode, calls;
static size_t length=5, consumed;
static char data[5];
static _Noreturn void mp_raise_OSError(int e) {raised=e;longjmp(trap,1);}
static void mp_get_buffer_raise(mp_obj_t obj,mp_buffer_info_t *b,int flag) {(void)obj;(void)flag;b->buf=data;b->len=length;}
static mp_uint_t send_data(struct Socket*s,const void*b,size_t n,int*e) {
 (void)s;assert(b==data+consumed);++calls;
 if(mode==1)return 0;
 if(mode==2)return n+1;
 if(mode==3){*e=104;return (mp_uint_t)-1;}
 size_t count=n>2?2:n;consumed+=count;return count;
}
''' + source[start:end] + r'''
int main(void) {
 struct Proto p={send_data}; mod_network_socket_obj_t s={&p,&p,-1};
 assert(socket_sendall(&s,0)==mp_const_none && consumed==5 && calls==3);
 for(mode=1;mode<=3;++mode) {
  consumed=0;calls=0;raised=0;
  if(!setjmp(trap)){socket_sendall(&s,0);assert(0);}
  assert(raised==(mode==1?32:mode==2?5:104) && calls==1);
 }
 mode=0;length=0;calls=0;
 assert(socket_sendall(&s,0)==mp_const_none && calls==0);
 length=5;s.timeout=0;consumed=0;calls=0;
 if(!setjmp(trap)){socket_sendall(&s,0);assert(0);}
 assert(raised==11 && consumed==2 && calls==1);
 length=2;consumed=0;
 assert(socket_sendall(&s,0)==mp_const_none && consumed==2);
}
'''
        env=os.environ.copy();env['PATH']=str(GCC.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'test.c';exe=root/'test.exe';src.write_text(program)
            for cmd in ([str(GCC),'-std=c11','-Wall','-Wextra','-Werror','-Wno-sign-compare',str(src),'-o',str(exe)],[str(exe)]):
                result=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
