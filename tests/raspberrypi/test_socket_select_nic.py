# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
GCC=Path('E:/msys64/ucrt64/bin/gcc.exe')

class SelectNICTests(unittest.TestCase):
    def test_creation_retry_and_timeout_cleanup(self):
        if not GCC.is_file(): self.skipTest('host GCC unavailable')
        source=(ROOT/'ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c').read_text()
        start=source.index('static void socket_select_nic(')
        brace=source.index('{',start)
        depth=1;end=brace+1
        while depth:
            depth+=(source[end]=='{')-(source[end]=='}')
            end+=1
        program=r'''
#include <assert.h>
#include <setjmp.h>
#include <stddef.h>
typedef unsigned char byte;
#define MP_OBJ_NULL NULL
#define MICROPY_PY_SOCKET_EXTENDED_STATE 1
#define MOD_NETWORK_SS_CLOSED 3
struct Socket;
typedef struct {int (*socket)(struct Socket*,int*); int (*settimeout)(struct Socket*,int,int*); void (*close)(struct Socket*);} mod_network_nic_protocol_t;
typedef struct Socket {void *nic;mod_network_nic_protocol_t *nic_protocol;int timeout,state;} mod_network_socket_obj_t;
static int creates, closes, timeout_calls, error, creation_error, timeout_error;
static jmp_buf trap;
static int create(struct Socket*s,int*e) {(void)s;++creates;*e=creation_error;return creation_error?-1:0;}
static int timeout(struct Socket*s,int ms,int*e) {(void)s;(void)ms;++timeout_calls;*e=timeout_error;return timeout_error?-1:0;}
static void close_socket(struct Socket*s) {++closes;s->state=3;}
static mod_network_nic_protocol_t proto={create,timeout,close_socket};
#define MP_OBJ_TYPE_GET_SLOT(type,slot) (&proto)
static void *mod_network_find_nic(const byte *ip) {(void)ip;return &proto;}
static _Noreturn void mp_raise_OSError(int e) {error=e;longjmp(trap,1);}
''' + source[start:end] + r'''
int main(void) {
 mod_network_socket_obj_t s={NULL,NULL,0,0};byte ip[4]={0};
 creation_error=95;
 if(!setjmp(trap)){socket_select_nic(&s,ip);assert(0);}
 assert(error==95 && s.nic==NULL && s.nic_protocol==NULL && creates==1 && closes==0);
 creation_error=0;socket_select_nic(&s,ip);
 assert(s.nic && creates==2 && timeout_calls==1);
 socket_select_nic(&s,ip);assert(creates==2);
 s.nic=NULL;s.nic_protocol=NULL;timeout_error=22;
 if(!setjmp(trap)){socket_select_nic(&s,ip);assert(0);}
 assert(error==22 && closes==1 && s.nic==NULL && s.nic_protocol==NULL && s.state==3);
}
'''
        env=os.environ.copy();env['PATH']=str(GCC.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'test.c';exe=root/'test.exe';src.write_text(program)
            for cmd in ([str(GCC),'-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],[str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main()
