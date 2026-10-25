# SPDX-License-Identifier: MIT
"""Exercise the real TCP tail-retention helper, not a socket/network stack."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / 'ports/raspberrypi'
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')
SOURCE = r'''
#include <cassert>
#include <string>
#include <type_traits>
#include "socket_rx_cache.h"
struct Buffer {
    static int live;
    std::string bytes;
    Buffer(const std::string &s) : bytes(s) { ++live; }
    ~Buffer() { --live; }
    const void *GetPtr() const { return bytes.data(); }
    size_t GetLength() const { return bytes.size(); }
};
int Buffer::live;
int main() {
    static_assert(!std::is_copy_constructible<MpynnSocketRxCache<Buffer>>::value, "unique owner");
    for (size_t chunk = 1; chunk <= 2048; chunk *= 2) {
        MpynnSocketRxCache<Buffer> cache;
        std::string expected;
        for (unsigned i=0; i<1536; ++i) expected += (char)(i & 255);
        assert(cache.adopt(new Buffer(expected)));
        auto *other = new Buffer("other");
        assert(!cache.adopt(other));
        delete other;
        assert(!cache.read(nullptr, 10) && !cache.read(&expected[0], 0));
        assert(cache.available() == expected.size());
        std::string actual;
        unsigned char output[2050];
        while (cache.available()) {
            output[0] = 0xA5; output[chunk+1] = 0x5A;
            size_t count = cache.read(output+1, chunk);
            assert(count && count <= chunk);
            assert(output[0] == 0xA5 && output[chunk+1] == 0x5A);
            actual.append((char*)output+1, count);
        }
        assert(actual == expected && Buffer::live == 0);
        assert(cache.read(output, sizeof output) == 0);
        cache.clear(); cache.clear();
    }
    { MpynnSocketRxCache<Buffer> cache;
      assert(!cache.adopt(nullptr));
      auto *empty = new Buffer(""); assert(!cache.adopt(empty)); delete empty;
      assert(cache.adopt(new Buffer("remaining tail on close")));
      char first; assert(cache.read(&first, 1) == 1);
    }
    assert(Buffer::live == 0);
}
'''


class SocketRxCacheTests(unittest.TestCase):
    def test_fragmentation_ownership_and_close(self):
        if not CXX.is_file():
            self.skipTest('host g++ unavailable')
        env = os.environ.copy()
        env['PATH'] = str(CXX.parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src, exe = root/'main.cpp', root/'test.exe'
            src.write_text(SOURCE)
            for command in ([str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                             '-I'+str(PORT), str(src), '-o', str(exe)], [str(exe)]):
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
