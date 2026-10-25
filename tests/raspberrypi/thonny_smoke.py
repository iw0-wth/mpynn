# SPDX-License-Identifier: MIT
# Run via Ctrl-E paste mode or Thonny raw REPL on current development firmware.
# The phase-1 frozen RPI1B-SD image deliberately lacks os and fails this test.
import builtins
import os
import sys
import gc

assert hasattr(builtins, 'id')
assert hasattr(builtins, 'repr')
assert hasattr(os, 'listdir')
assert hasattr(os, 'getcwd')
assert hasattr(os, 'chdir')
assert hasattr(os, 'rmdir')
assert isinstance(sys.path, list)
assert isinstance(sys.modules, dict)
assert isinstance(os.getcwd(), str)
assert isinstance(__import__('vfs').mount(), list)
print('MPYNN_THONNY_HELPER_PREREQS_PASS')
# machine.RTC is importable, but its clock methods raise NotImplementedError.
# Thonny may separately warn about unsupported time synchronization. In its
# ESP backend time sync catches that exception and reports a warning rather
# than treating the IDE helper setup as failed.
