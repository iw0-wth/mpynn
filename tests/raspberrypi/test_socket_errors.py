# SPDX-License-Identifier: MIT
"""Error map tests using real Circle and MP errno headers, no network traffic."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')
SOURCE = r'''
#include <cassert>
#include <climits>
#include "socket_errors.h"
#include "socket_deadline.h"
int main() {
    MpynnSocketDeadline forever(-1, 0), immediate(0, 0), finite(7, 100);
    assert(!forever.expired(UINT64_MAX) && forever.remaining_us(0) == UINT64_MAX);
    assert(immediate.expired(0));
    assert(!finite.expired(7099) && finite.expired(7100));
    assert(finite.remaining_us(200) == 6900 && finite.remaining_us(9000) == 0);
    MpynnSocketDeadline wrap(1, UINT64_MAX-499);
    assert(!wrap.expired(499) && wrap.expired(500));
    MpynnSocketDeadline large(INT32_MAX, 0);
    assert(large.remaining_us(0) == (uint64_t)INT32_MAX*1000);

    const int codes[] = { NET_ERROR_UNKNOWN, NET_ERROR_IO, NET_ERROR_WOULD_BLOCK,
        NET_ERROR_PERMISSION_DENIED, NET_ERROR_INVALID_VALUE, NET_ERROR_PROTOCOL_ERROR,
        NET_ERROR_PROTOCOL_NOT_SUPPORTED, NET_ERROR_OPERATION_NOT_SUPPORTED,
        NET_ERROR_CONNECTION_RESET, NET_ERROR_IS_CONNECTED, NET_ERROR_NOT_CONNECTED,
        NET_ERROR_CONNECTION_TIMED_OUT, NET_ERROR_CONNECTION_REFUSED,
        NET_ERROR_DESTINATION_UNREACHABLE };
    const int expected[] = { MP_EIO, MP_EIO, MP_EAGAIN, MP_EACCES, MP_EINVAL,
        MP_EIO, MP_EOPNOTSUPP, MP_EOPNOTSUPP, MP_ECONNRESET, MP_EISCONN,
        MP_ENOTCONN, MP_ETIMEDOUT, MP_ECONNREFUSED, MP_EHOSTUNREACH };
    for (unsigned i=0; i<sizeof codes/sizeof codes[0]; ++i)
        assert(mpynn_socket_errno(-codes[i]) == expected[i]);
    assert(mpynn_socket_errno(0) == 0);
    assert(mpynn_socket_errno(1536) == 0);
    assert(mpynn_socket_errno(INT_MAX) == 0);
    assert(mpynn_socket_errno(INT_MIN) == MP_EIO);
    assert(mpynn_socket_errno(-999) == MP_EIO);
    assert(mpynn_socket_errno(-NET_ERROR_IO) != MP_EAGAIN);
    assert(mpynn_socket_errno(-NET_ERROR_WOULD_BLOCK) != MP_ENOMEM);
}
'''


class SocketErrorTests(unittest.TestCase):
    def test_circle_to_micropython_errno(self):
        if not CXX.is_file():
            self.skipTest('host g++ unavailable')
        env = os.environ.copy()
        env['PATH'] = str(CXX.parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src, exe = root/'main.cpp', root/'test.exe'
            src.write_text(SOURCE)
            # Only port configuration is faked; error definitions remain real.
            (root/'mpconfigport.h').write_text('#include <stdint.h>\n#define MICROPY_USE_INTERNAL_ERRNO 1\ntypedef intptr_t mp_int_t;\ntypedef uintptr_t mp_uint_t;\ntypedef long mp_off_t;\n')
            command = [str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                       '-I'+str(root),
                       '-I'+str(ROOT/'ports/raspberrypi'),
                       '-idirafter', str(ROOT/'lib/circle/include'),
                       '-I'+str(ROOT/'lib/micropython'), str(src), '-o', str(exe)]
            for cmd in (command, [str(exe)]):
                result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
