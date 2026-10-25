# SPDX-License-Identifier: MIT
"""Compile the real ulab C sources for ARMv6; never substitute a Python array.

Run with D:/anaconda3/python.exe -B -m unittest discover -s
mpynn/tests/raspberrypi -p test_ulab_native.py -v from the workspace root.
The compiler and existing generated-header directory can be overridden with
MPYNN_ARM_GCC and MPYNN_ULAB_GENHDR. No firmware or shared build output is made.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / 'modules/ulab/code'
PORT = ROOT / 'ports/raspberrypi'
BOARD = ROOT / 'boards/RPI1B'
MP = ROOT / 'lib/micropython'
GCC = Path(os.environ.get('MPYNN_ARM_GCC', 'E:/arm-none-eabi/bin/arm-none-eabi-gcc.exe'))
GENHDR = Path(os.environ.get('MPYNN_ULAB_GENHDR', str(ROOT / 'build/RPI1B/micropython/genhdr')))


def source_paths():
    text = (PORT / 'ulab.mk').read_text(encoding='utf-8')
    names = re.findall(r'^    ([a-z_/]+\.c)[ )\\]*$', text, re.M)
    return [CODE / name for name in names]


def checked(command, **kwargs):
    result = subprocess.run([str(arg) for arg in command], capture_output=True,
                            text=True, timeout=90, **kwargs)
    if result.returncode:
        raise AssertionError('Command failed: ' + ' '.join(map(str, command)) +
                             '\n' + result.stdout + result.stderr)
    return result.stdout


class UlabNativeTests(unittest.TestCase):
    def test_exact_vendored_source_snapshot(self):
        import json
        vendor = CODE.parent
        manifest = json.loads((vendor / 'VENDOR.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], '6.12.0')
        self.assertEqual(manifest['snapshot'], 'd161443')
        for name, digest in manifest['sha256'].items():
            with self.subTest(path=name):
                self.assertEqual(hashlib.sha256((vendor / name).read_bytes()).hexdigest(), digest)
        sources = source_paths()
        self.assertEqual(len(sources), 33)
        self.assertEqual(set(sources), set(CODE.rglob('*.c')))

    def test_actual_sources_armv6_strict_syntax(self):
        self.assertTrue(GCC.is_file(), 'ARM GCC is required; no mock compiler allowed')
        self.assertTrue((GENHDR / 'qstrdefs.preprocessed.h').is_file(),
                        'Existing MicroPython genhdr is required; set MPYNN_ULAB_GENHDR')
        sources = source_paths()
        self.assertEqual(len(sources), 33, 'compile the complete upstream source list')
        with tempfile.TemporaryDirectory(prefix='mpynn-ulab-') as directory:
            temporary = Path(directory)
            generated = temporary / 'genhdr'
            generated.mkdir()
            for name in ('mpversion.h', 'root_pointers.h', 'moduledefs.h'):
                shutil.copyfile(GENHDR / name, generated / name)
            flags = ['-mcpu=arm1176jzf-s', '-marm', '-mfpu=vfp', '-mfloat-abi=hard',
                     '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                     '-DMODULE_ULAB_ENABLED=1', '-DULAB_CONFIG_FILE="ulab_config.h"',
                     '-DMICROPY_ROM_TEXT_COMPRESSION=0', '-DNDEBUG',
                     '-I' + str(temporary), '-I' + str(PORT), '-I' + str(BOARD),
                     '-I' + str(MP), '-I' + str(CODE)]
            # Preprocess actual sources with the real port configuration. Reuse the
            # existing core qstr definitions, adding only tokens the compiler sees.
            # Generate their data with MicroPython's own generator, not fake defines.
            tokens = set()
            for source in sources:
                preprocessed = checked([GCC, *flags, '-E', '-DNO_QSTR', source])
                tokens.update(re.findall(r'MP_QSTR_([_a-zA-Z0-9]+)', preprocessed))
            collected = temporary / 'ulab-qstr.h'
            collected.write_text('\n'.join('Q(' + name + ')' for name in sorted(tokens)) + '\n',
                                 encoding='utf-8')
            qstr = checked([sys.executable, '-B', MP / 'py/makeqstrdata.py',
                            GENHDR / 'qstrdefs.preprocessed.h', collected])
            (generated / 'qstrdefs.generated.h').write_text(qstr, encoding='utf-8')
            checks = temporary / 'ulab-config-check.c'
            checks.write_text('''#include "py/runtime.h"
#include "ulab.h"
_Static_assert(MODULE_ULAB_ENABLED == 1, "native ulab enabled");
_Static_assert(ULAB_MAX_DIMS == 4, "four dimensional ndarray ABI");
_Static_assert(ULAB_SUPPORTS_COMPLEX && ULAB_HAS_SCIPY, "full upstream defaults");
_Static_assert(NDARRAY_HAS_BINARY_OPS && NDARRAY_HAS_INPLACE_OPS, "array arithmetic");
_Static_assert(ULAB_NUMPY_HAS_FROMBUFFER && ULAB_NUMPY_HAS_ZEROS, "tensor input");
_Static_assert(ULAB_NUMPY_HAS_ROLL && NDARRAY_HAS_RESHAPE, "tensor shape operations");
_Static_assert(ULAB_NUMPY_HAS_MINMAX && ULAB_NUMPY_HAS_ARGMINMAX, "tensor reductions");
''', encoding='utf-8')
            checked([GCC, *flags, '-fsyntax-only', checks])
            for source in sources:
                with self.subTest(source=source.relative_to(ROOT).as_posix()):
                    checked([GCC, *flags, '-fsyntax-only', source])


if __name__ == '__main__':
    unittest.main()
