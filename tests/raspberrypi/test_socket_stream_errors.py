# SPDX-License-Identifier: MIT
"""Execute real generic modsocket stream callbacks with fake NIC dispatch."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
GCC=Path('E:/msys64/ucrt64/bin/gcc.exe')

class SocketStreamErrors(unittest.TestCase):
    def test_unconnected_closed_and_driver_errors(self):
        if not GCC.is_file(): self.skipTest('host GCC unavailable')
        source=(ROOT/'ports/raspberrypi/upstream_overrides/micropython/extmod/modsocket.c').read_text()
        callbacks=source[source.index('static mp_uint_t socket_read('):source.index('static mp_uint_t socket_ioctl(')]
        program=r'''
#include <stdint.h>
#include <assert.h>
#include <stddef.h>
typedef uintptr_t mp_uint_t;
typedef intptr_t mp_int_t;
typedef void *mp_obj_t;
typedef unsigned char byte;
#define MP_OBJ_TO_PTR(x) (x)
#define MP_OBJ_NULL NULL
#define MP_STREAM_ERROR ((mp_uint_t)-1)
#define MOD_NETWORK_SS_CLOSED 3
#define MP_EBADF 9
#define MP_ENOTCONN 107
struct Socket;
struct Protocol {
 mp_uint_t (*recv)(struct Socket*,byte*,mp_uint_t,int*);
 mp_uint_t (*send)(struct Socket*,const byte*,mp_uint_t,int*);
};
typedef struct Socket { void *nic; int state; struct Protocol *nic_protocol; } mod_network_socket_obj_t;
static int calls, result;
static mp_uint_t receive(struct Socket *s,byte *b,mp_uint_t n,int *e) {
 (void)s;(void)b;(void)n;++calls;if(result<0)*e=104;return result;
}
static mp_uint_t transmit(struct Socket *s,const byte *b,mp_uint_t n,int *e) {
 return receive(s,(byte*)b,n,e);
}
''' + callbacks + r'''
int main(void) {
 struct Protocol p={receive,transmit};
 mod_network_socket_obj_t s={NULL,0,&p}; char b[4]; int error=999;
 assert(socket_read(&s,b,4,&error)==MP_STREAM_ERROR && error==MP_ENOTCONN);
 error=999;assert(socket_write(&s,b,4,&error)==MP_STREAM_ERROR && error==MP_ENOTCONN);
 s.state=3;error=999;assert(socket_read(&s,b,4,&error)==MP_STREAM_ERROR && error==MP_EBADF);
 error=999;assert(socket_write(&s,b,4,&error)==MP_STREAM_ERROR && error==MP_EBADF);
 assert(calls==0);
 s.state=2;s.nic=&s;result=-1;
 assert(socket_read(&s,b,4,&error)==MP_STREAM_ERROR && error==104);
 assert(socket_write(&s,b,4,&error)==MP_STREAM_ERROR && error==104);
 result=0;assert(socket_read(&s,b,4,&error)==0); // EOF
 result=2;assert(socket_write(&s,b,4,&error)==2); // partial write
 assert(calls==4);
}
'''
        env=os.environ.copy();env['PATH']=str(GCC.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'test.c';exe=root/'test.exe';src.write_text(program)
            for cmd in ([str(GCC),'-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],[str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main()
