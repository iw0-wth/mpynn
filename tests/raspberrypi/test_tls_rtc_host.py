# SPDX-License-Identifier: MIT
"""Real TLS UTC provider; fake RTC isolates clock trust from boot time."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2]/'ports/raspberrypi'
GCC = Path('E:/msys64/ucrt64/bin/gcc.exe')
SOURCE = r'''
#include <assert.h>
#include "rtc_bridge.h"
#include "tls_random_bridge.h"
static uint32_t epoch=946684800;
static unsigned valid, source;
static int error;
int mpynn_rtc_get_utc(uint32_t *seconds, unsigned *v, unsigned *s) {
 *seconds=epoch; *v=valid; *s=source; return error;
}
int main(void) {
 time_t out=123;
 assert(!mpynn_tls_get_utc(&out) && out==123); // year-2000 boot not calibrated
 valid=1;
 assert(!mpynn_tls_get_utc(&out) && out==123); // unknown provenance
 source=1; epoch=1700000000;
 assert(mpynn_tls_get_utc(&out)==1 && out==1700000000);
 out=123; error=-1;
 assert(!mpynn_tls_get_utc(&out) && out==123);
 error=0; epoch=UINT32_MAX;
 assert(!mpynn_tls_get_utc(&out) && out==123);
 epoch=INT32_MAX;
 assert(mpynn_tls_get_utc(&out)==1 && out==INT32_MAX);
 epoch=0; assert(mpynn_tls_get_utc(&out)==1 && out==0);
 assert(!mpynn_tls_get_utc(0));
}
'''

class TLSRTCTests(unittest.TestCase):
    def test_only_calibrated_supported_utc_is_exported(self):
        if not GCC.is_file(): self.skipTest('host GCC unavailable')
        env=os.environ.copy();env['PATH']=str(GCC.parent)+os.pathsep+env.get('PATH','')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'test.c';exe=root/'test.exe';src.write_text(SOURCE)
            for cmd in ([str(GCC),'-std=c11','-Wall','-Wextra','-Werror','-iquote',str(PORT),
                         str(PORT/'tls_rtc.c'),str(src),'-o',str(exe)], [str(exe)]):
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__': unittest.main()
