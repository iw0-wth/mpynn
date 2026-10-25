# SPDX-License-Identifier: MIT
"""Test real console TX retry helper, not UART hardware or IRQ delivery."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / "ports/raspberrypi"
COMPILER = Path("E:/msys64/ucrt64/bin/g++.exe")
SOURCE = r'''
#include <cassert>
#include <cstring>
#include <string>
#include <vector>
#include "console_tx.h"
int main() {
    const std::string input(300, 'x');
    std::string output;
    uint64_t ticks = 0;
    unsigned calls = 0, polls = 0;
    auto clock = [&]() { return ++ticks; };
    auto poll = [&]() { ++polls; };
    size_t count = mpynn_console_write_all(input.data(), input.size(),
        [&](const char *p, size_t len) {
            ++calls;
            if (calls % 3 == 1) return 0; // temporary full ring, must retry
            assert(p == input.data() + output.size());
            int n = len > 7 ? 7 : (int)len;
            output.append(p, n);
            return n;
        }, clock, poll, 20);
    assert(count == input.size() && output == input && polls > 0);
    ticks = 0; polls = 0;
    count = mpynn_console_write_all("abc", 3,
        [](const char*, size_t) { return 0; }, clock, poll, 10);
    assert(count == 0 && ticks >= 10 && polls > 0 && polls < 20);
    calls = 0;
    count = mpynn_console_write_all("abc", 3,
        [&](const char*, size_t) { return ++calls == 1 ? 1 : -1; }, clock, poll);
    assert(count == 1 && calls == 2);
    count = mpynn_console_write_all("a", 1,
        [](const char*, size_t) { return 2; }, clock, poll);
    assert(count == 0); // corrupt writer count cannot advance past buffer
    calls = 0;
    count = mpynn_console_write_all("", 0,
        [&](const char*, size_t) { ++calls; return 0; }, clock, poll);
    assert(count == 0 && calls == 0);
    // No unsigned timer rollover bug in a stalled request.
    ticks = UINT64_MAX - 3;
    count = mpynn_console_write_all("abc", 3,
        [](const char*, size_t) { return 0; }, clock, poll, 10);
    assert(count == 0 && ticks < 20);
}
'''


class ConsoleTxTests(unittest.TestCase):
    def test_backpressure_partial_errors_timeout_and_wrap(self):
        if not COMPILER.is_file():
            self.skipTest("host g++ unavailable")
        env = os.environ.copy()
        env['PATH'] = str(COMPILER.parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src, exe = root/'test.cpp', root/'test.exe'
            src.write_text(SOURCE)
            for command in ([str(COMPILER), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                             '-I'+str(PORT), str(src), '-o', str(exe)], [str(exe)]):
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, str(command)+'\n'+result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
