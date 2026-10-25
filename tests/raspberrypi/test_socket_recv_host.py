# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
GCC=Path('E:/msys64/ucrt64/bin/gcc.exe')

class ReceiveTests(unittest.TestCase):
    def test_negative_length_and_buffer_cleanup(self):
        if not GCC.is_file():self.skipTest('host GCC unavailable')
        source=(ROOT/'ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c').read_text()
        methods=''
        for name in ('socket_recv','socket_recvfrom'):
            start=source.index('static mp_obj_t '+name+'(')
            end=source.index('static MP_DEFINE_CONST_FUN_OBJ_2('+name+'_obj',start)
            methods+=source[start:end]
        program=r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <setjmp.h>
typedef uintptr_t mp_uint_t;
typedef intptr_t mp_int_t;
typedef intptr_t mp_obj_t;
typedef unsigned char byte;
#define MP_OBJ_TO_PTR(x) ((void*)(x))
#define MP_OBJ_NULL 0
#define MP_ENOTCONN 107
#define MP_EIO 5
#define MP_ERROR_TEXT(x) x
#define NETUTILS_BIG 0
#define mp_const_empty_bytes 2
struct Socket;
struct Proto {mp_uint_t(*recv)(struct Socket*,byte*,mp_uint_t,int*);mp_int_t(*recvfrom)(struct Socket*,byte*,mp_uint_t,byte*,mp_uint_t*,int*);};
typedef struct Socket {mp_obj_t nic;struct Proto*nic_protocol;} mod_network_socket_obj_t;
typedef struct {char*buf;size_t len;} vstr_t;
static jmp_buf trap;
static int allocations,live,calls,raised,result;
static _Noreturn void mp_raise_ValueError(const char*x){(void)x;raised=22;longjmp(trap,1);}
static _Noreturn void mp_raise_OSError(int e){raised=e;longjmp(trap,1);}
static mp_int_t mp_obj_get_int(mp_obj_t x){return x;}
static void vstr_init_len(vstr_t*v,size_t n){++allocations;++live;v->buf=malloc(n?n:1);v->len=n;}
static void vstr_clear(vstr_t*v){free(v->buf);--live;}
static mp_obj_t mp_obj_new_bytes_from_vstr(vstr_t*v){vstr_clear(v);return 3;}
static mp_obj_t mp_obj_new_tuple(size_t n,mp_obj_t*t){(void)t;assert(n==2);return 4;}
static mp_obj_t netutils_format_inet_addr(byte*ip,mp_uint_t p,int order){(void)ip;(void)p;(void)order;return 5;}
static mp_uint_t receive(struct Socket*s,byte*b,mp_uint_t n,int*e){(void)s;(void)b;(void)n;++calls;*e=11;return result;}
static mp_int_t receivefrom(struct Socket*s,byte*b,mp_uint_t n,byte*ip,mp_uint_t*p,int*e){ip[0]=0;*p=1;return receive(s,b,n,e);}
''' + methods + r'''
int main(void){
 struct Proto p={receive,receivefrom};mod_network_socket_obj_t s={1,&p};
 mp_obj_t(*fns[])(mp_obj_t,mp_obj_t)={socket_recv,socket_recvfrom};
 for(int i=0;i<2;++i){
  int before=allocations, prior=calls;
  if(!setjmp(trap)){fns[i]((mp_obj_t)&s,-1);assert(0);}
  assert(raised==22 && allocations==before && calls==prior);
  result=-1;if(!setjmp(trap)){fns[i]((mp_obj_t)&s,64);assert(0);}
  assert(raised==11 && live==0);
  result=0;fns[i]((mp_obj_t)&s,64);assert(live==0);
  result=2;fns[i]((mp_obj_t)&s,64);assert(live==0);
  result=65;if(!setjmp(trap)){fns[i]((mp_obj_t)&s,64);assert(0);}
  assert(raised==5 && live==0);
  result=-2;if(!setjmp(trap)){fns[i]((mp_obj_t)&s,64);assert(0);}
  assert(raised==5 && live==0);
 }
}
'''
        env=os.environ.copy();env['PATH']=str(GCC.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'test.c';exe=root/'test.exe';src.write_text(program)
            for cmd in ([str(GCC),'-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],[str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main()
