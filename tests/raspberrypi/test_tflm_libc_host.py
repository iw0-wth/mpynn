# SPDX-License-Identifier: MIT
"""Execute the real port numeric helpers without pulling Circle/newlib stdio."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'ports/raspberrypi/tflm_libc.c'
GCC = Path('E:/msys64/ucrt64/bin/gcc.exe')


def extract(name):
    text = SOURCE.read_text(encoding='utf-8')
    match = re.search(r'^(?:static )?[^\n]+\b' + name + r'\([^\n]*\) \{', text, re.M)
    if not match:
        raise AssertionError('Missing function ' + name)
    opening = text.index('{', match.start())
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end]


class TflmLibcTests(unittest.TestCase):
    def test_actual_numeric_helpers(self):
        source = '#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n#include <limits.h>\n#include <errno.h>\n#include <assert.h>\n'
        source += '\n'.join(extract(name) for name in ('tflm_digit', 'strtoll', 'bsearch'))
        source += r'''
static int cmp(const void *a, const void *b) {
    int x=*(const int *)a, y=*(const int *)b; return (x>y)-(x<y);
}
int main(void) {
    char *end; const char *s;
    s="-9223372036854775808"; errno=0;
    assert(strtoll(s,&end,10)==LLONG_MIN && !*end && errno==0);
    s="9223372036854775807"; assert(strtoll(s,&end,10)==LLONG_MAX && !*end);
    s="9223372036854775808junk"; errno=0;
    assert(strtoll(s,&end,10)==LLONG_MAX && *end=='j' && errno==ERANGE);
    s="-999999999999999999999999999999"; errno=0;
    assert(strtoll(s,&end,10)==LLONG_MIN && !*end && errno==ERANGE);
    s="  +0xFFrest"; assert(strtoll(s,&end,0)==255 && *end=='r');
    s="077!"; assert(strtoll(s,&end,0)==63 && *end=='!');
    s="zZ"; assert(strtoll(s,&end,36)==1295 && !*end);
    s="-x"; assert(strtoll(s,&end,10)==0 && end==s);
    s="0x"; assert(strtoll(s,&end,0)==0 && *end=='x');
    s="12"; errno=0; assert(strtoll(s,&end,1)==0 && end==s && errno==EINVAL);
    int items[]={1,2,5,7,9}, key=5;
    assert(bsearch(&key,items,5,sizeof(int),cmp)==items+2);
    key=4; assert(bsearch(&key,items,5,sizeof(int),cmp)==NULL);
    assert(bsearch(&key,items,0,sizeof(int),cmp)==NULL);
    assert(bsearch(&key,items,SIZE_MAX,2,cmp)==NULL);
    assert(bsearch(&key,items,5,0,cmp)==NULL);
    return 0;
}
'''
        env = os.environ.copy()
        env['PATH'] = str(GCC.parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory(prefix='tflm-libc-') as folder:
            path = Path(folder)
            c, exe = path / 'checks.c', path / 'checks.exe'
            c.write_text(source, encoding='utf-8')
            for command in ([str(GCC), '-std=c11', '-Wall', '-Wextra', '-Werror', '-fno-builtin', str(c), '-o', str(exe)], [str(exe)]):
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
