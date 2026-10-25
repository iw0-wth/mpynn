# SPDX-License-Identifier: MIT
"""Compile and execute the actual image codecs/core; syntax-check real MP glue.

Only host tests build a DLL with bounded GC allocator stubs. Firmware uses real
MicroPython GC and VFS; no Python image library is involved in its implementation.
"""
import ctypes as C
import os
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'modules/image_file'
MP = ROOT / 'lib/micropython'
PORT = ROOT / 'ports/raspberrypi'
BOARD = ROOT / 'boards/RPI1B'
ULAB = ROOT / 'modules/ulab/code'
GENHDR = ROOT / 'build/RPI1B/micropython/genhdr'
HOST = Path('E:/msys64/ucrt64/bin/gcc.exe')
ARM = Path('E:/arm-none-eabi/bin/arm-none-eabi-gcc.exe')


def checked(command):
    env = os.environ.copy()
    env['PATH'] = str(HOST.parent) + os.pathsep + env.get('PATH', '')
    result = subprocess.run([str(x) for x in command], capture_output=True,
                            text=True, timeout=90, env=env)
    if result.returncode:
        raise AssertionError(' '.join(map(str, command)) + '\n' + result.stdout + result.stderr)
    return result.stdout


class Header(C.Structure):
    _fields_ = [('w', C.c_uint), ('h', C.c_uint), ('format', C.c_uint), ('kind', C.c_uint),
                ('offset', C.c_size_t), ('stride', C.c_size_t), ('maxval', C.c_uint),
                ('bits', C.c_uint), ('top_down', C.c_int)]


class Image(C.Structure):
    _fields_ = [('w', C.c_uint), ('h', C.c_uint), ('format', C.c_uint), ('data', C.c_void_p)]


class Roi(C.Structure):
    _fields_ = [('x', C.c_int), ('y', C.c_int), ('w', C.c_uint), ('h', C.c_uint)]


def png(w, h, rows, color=2, depth=8, extra=()):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, depth, color, 0, 0, 0)) +
            b''.join(chunk(name, data) for name, data in extra) +
            chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def bmp(w, h, rows, bits=24, top_down=False):
    stride = ((w * bits + 31) // 32) * 4
    raster = b''.join(row + bytes(stride - len(row)) for row in rows)
    height = -h if top_down else h
    return (b'BM' + struct.pack('<IHHI', 54 + len(raster), 0, 0, 54) +
            struct.pack('<IiiHHIIiiII', 40, w, height, 1, bits, 0, len(raster), 0, 0, 0, 0) + raster)


class ImageFileNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HOST.is_file():
            raise AssertionError('host GCC is required')
        cls.temp = tempfile.TemporaryDirectory(prefix='image-file-codecs-')
        path = Path(cls.temp.name)
        (path / 'py').mkdir()
        (path / 'py/gc.h').write_text('''#include <stddef.h>
#include <stdbool.h>
void *gc_alloc(size_t,unsigned);void gc_free(void *);size_t gc_nbytes(const void *);
void *gc_realloc(void *,size_t,bool);
''', encoding='utf-8')
        (path / 'gc.c').write_text(GC_STUB, encoding='utf-8')
        cls.dll_path = path / 'image_checks.dll'
        checked([HOST, '-shared', '-std=c11', '-Wall', '-Wextra', '-Werror',
                 '-I' + str(path), '-I' + str(MODULE), MODULE / 'image_core.c',
                 MODULE / 'png_codec.c', MODULE / 'lodepng.c', path / 'gc.c', '-lm', '-o', cls.dll_path])
        cls.dll = C.CDLL(str(cls.dll_path))
        cls.dll.if_probe.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Header)]
        cls.dll.if_decode.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Header), C.POINTER(Image)]
        cls.dll.if_get_rgb.argtypes = [C.POINTER(Image), C.c_uint, C.c_uint, C.c_void_p]
        cls.dll.if_draw.argtypes = [C.POINTER(Image), C.POINTER(Image), Roi,
                                   C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_uint]
        cls.dll.if_to_tensor.argtypes = [C.POINTER(Image), C.c_char, C.c_void_p, C.c_size_t]
        cls.dll.test_gc_live.restype = C.c_size_t

    @classmethod
    def tearDownClass(cls):
        # Windows keeps a loaded DLL open; release before removing temp outputs.
        import _ctypes
        _ctypes.FreeLibrary(cls.dll._handle)
        cls.dll = None
        cls.temp.cleanup()

    def decode(self, data):
        raw = C.create_string_buffer(bytes(data))
        header = Header()
        status = self.dll.if_probe(raw, len(data), C.byref(header))
        if status:
            return status, None, None
        pixels = C.create_string_buffer(header.w * header.h * header.format)
        image = Image(header.w, header.h, header.format, C.addressof(pixels))
        status = self.dll.if_decode(raw, len(data), C.byref(header), C.byref(image))
        self.assertEqual(self.dll.test_gc_live(), 0, 'codec temporary allocations must be freed')
        return status, image, pixels

    def rgb(self, image, x, y):
        rgb = (C.c_uint8 * 3)()
        self.dll.if_get_rgb(C.byref(image), x, y, rgb)
        return tuple(rgb)

    def test_png_real_decoder_colors_alpha_palette_and_16bit(self):
        fixtures = [
            (png(2, 1, b'\x00\xff\x00\x00\x00\xff\x00'), [(255, 0, 0), (0, 255, 0)]),
            (png(1, 1, b'\x00\xff\x00\x00\x80', 6), [(132, 0, 0)]),
            (png(2, 1, b'\x00\x00\x01', 3, extra=((b'PLTE', b'\xff\x00\x00\x00\xff\x00'),)),
             [(255, 0, 0), (0, 255, 0)]),
            (png(2, 1, b'\x00\x00\xff', 0), [(0, 0, 0), (255, 255, 255)]),
            (png(1, 1, b'\x00\xff\xff\x00\x00\x00\x00', 2, 16), [(255, 0, 0)]),
        ]
        for data, expected in fixtures:
            with self.subTest(color=expected):
                status, image, pixels = self.decode(data)
                self.assertEqual(status, 0)
                self.assertEqual([self.rgb(image, x, 0) for x in range(image.w)], expected)

    def test_png_crc_truncation_and_excessive_inflate_rejected(self):
        valid = png(1, 1, b'\x00\xff\x00\x00')
        bad = bytearray(valid)
        bad[-1] ^= 1
        self.assertNotEqual(self.decode(bad)[0], 0)
        for length in (1, 7, 20, 32, len(valid) - 8, len(valid) - 1):
            self.assertNotEqual(self.decode(valid[:length])[0], 0)
        self.assertNotEqual(self.decode(png(8193, 1, b''))[0], 0)
        self.assertNotEqual(self.decode(png(1, 1, b'\0' * 100000))[0], 0)

    def test_png_allocation_failures_release_partial_state(self):
        data = png(2, 2, b'\x00\xff\x00\x00\x00\xff\x00' * 2)
        for fail_after in range(24):
            with self.subTest(allocation=fail_after):
                self.dll.test_gc_fail_after(fail_after)
                status, image, pixels = self.decode(data)
                self.assertIn(status, (0, -4))
                self.assertEqual(self.dll.test_gc_live(), 0)
        self.dll.test_gc_fail_after(-1)
        self.assertEqual(self.decode(data)[0], 0)

    def test_bmp_bottom_up_top_down_padding_32bit(self):
        fixtures = [bmp(1, 2, [b'\x00\x00\xff', b'\xff\x00\x00']),
                    bmp(1, 2, [b'\xff\x00\x00', b'\x00\x00\xff'], top_down=True),
                    bmp(1, 2, [b'\xff\x00\x00\0', b'\x00\x00\xff\0'], bits=32, top_down=True)]
        for data in fixtures:
            status, image, pixels = self.decode(data)
            self.assertEqual(status, 0)
            self.assertEqual(self.rgb(image, 0, 0), (0, 0, 255))
            self.assertEqual(self.rgb(image, 0, 1), (255, 0, 0))
            self.assertNotEqual(self.decode(data[:-1])[0], 0)
        bad = bytearray(fixtures[0]);bad[30] = 1
        self.assertEqual(self.decode(bad)[0], -2)

    def test_netpbm_p1_to_p6_binary_separators_comments_16bit(self):
        fixtures = [
            (b'P1\n# pixels\n2 1\n0 1\n', [255, 0]),
            (b'P2\n2 1\n15\n0 15', [0, 255]),
            (b'P4\n2 1\n\x40', [255, 0]),
            (b'P5\n2 1\n255\n #', [32, 35]),
            (b'P5\r\n2 1\r\n65535\r\n\0\0\xff\xff', [0, 255]),
        ]
        for data, expected in fixtures:
            status, image, pixels = self.decode(data)
            self.assertEqual(status, 0)
            self.assertEqual(list(pixels.raw), expected)
        for data in (b'P3\n2 1\n255\n255 0 0 0 255 0', b'P6\n2 1\n255\n\xff\0\0\0\xff\0'):
            status, image, pixels = self.decode(data)
            self.assertEqual(status, 0)
            self.assertEqual(self.rgb(image, 0, 0), (255, 0, 0))
            self.assertEqual(self.rgb(image, 1, 0), (0, 255, 0))
        for data in (b'P2\n1 1\n255\n256', b'P6\n1 1\n255\n\0', b'P2\n99999999999999999 1\n255\n0',
                     b'P2\n8193 1\n255\n0', b'P2\n0 1\n255\n0'):
            self.assertNotEqual(self.decode(data)[0], 0)
        self.assertEqual(self.decode(b'\xff\xd8\xff\xd9')[0], -2)

    def test_actual_cpu_resize_roi_grayscale_and_tensor_output(self):
        status, src, pixels = self.decode(b'P5\n2 2\n255\n\0\x64\xc8\xff')
        self.assertEqual(status, 0)
        dst_bytes = C.create_string_buffer(1)
        dst = Image(1, 1, 1, C.addressof(dst_bytes))
        self.assertEqual(self.dll.if_draw(C.byref(dst), C.byref(src), Roi(0, 0, 2, 2), 0, 0, 1, 1, 1), 0)
        self.assertEqual(dst_bytes.raw, bytes([139]))
        self.assertEqual(self.dll.if_draw(C.byref(dst), C.byref(src), Roi(1, 1, 1, 1), 0, 0, 1, 1, 0), 0)
        self.assertEqual(dst_bytes.raw, b'\xff')
        self.assertNotEqual(self.dll.if_draw(C.byref(dst), C.byref(src), Roi(-1, 0, 2, 2), 0, 0, 1, 1, 0), 0)
        output = (C.c_float * 4)()
        self.assertEqual(self.dll.if_to_tensor(C.byref(src), b'f', output, C.sizeof(output)), 0)
        self.assertEqual(list(output), [0, 100, 200, 255])
        quant = (C.c_int8 * 4)()
        self.assertEqual(self.dll.if_to_tensor(C.byref(src), b'b', quant, C.sizeof(quant)), 0)
        self.assertEqual(list(quant), [-128, -28, 72, 127])
        self.assertNotEqual(self.dll.if_to_tensor(C.byref(src), b'f', output, 3), 0)
        self.assertNotEqual(self.dll.if_to_tensor(C.byref(src), b'x', output, 16), 0)
        status, color, color_pixels = self.decode(b'P6\n1 1\n255\n\xff\0\0')
        self.assertEqual(self.dll.if_draw(C.byref(dst), C.byref(color), Roi(0, 0, 1, 1), 0, 0, 1, 1, 0), 0)
        self.assertEqual(dst_bytes.raw, bytes([77]))

    def test_small_malformed_headers_are_bounded(self):
        randomizer = random.Random(2026)
        for prefix in (b'BM', b'P1', b'P2', b'P4', b'P6', b'\x89PNG\r\n\x1a\n'):
            for _ in range(100):
                data = prefix + randomizer.randbytes(randomizer.randrange(128))
                self.assertNotEqual(self.decode(data)[0], 0)

    def test_original_lodepng_bytes_are_preserved(self):
        for name in ('lodepng.c', 'lodepng.h'):
            self.assertEqual((MODULE / name).read_bytes(), (ROOT / 'lib/imlib' / name).read_bytes())

    def test_complete_sources_actual_arm_headers(self):
        self.assertTrue(ARM.is_file())
        with tempfile.TemporaryDirectory(prefix='image-file-arm-') as folder:
            temporary = Path(folder)
            gen = temporary / 'genhdr';gen.mkdir()
            for name in ('mpversion.h', 'root_pointers.h', 'moduledefs.h'):
                shutil.copyfile(GENHDR / name, gen / name)
            flags = ['-mcpu=arm1176jzf-s', '-marm', '-mfpu=vfp', '-mfloat-abi=hard',
                     '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                     '-DMODULE_ULAB_ENABLED=1', '-DULAB_CONFIG_FILE="ulab_config.h"',
                     '-DMICROPY_ROM_TEXT_COMPRESSION=0', '-I' + str(temporary), '-I' + str(MODULE),
                     '-I' + str(PORT), '-I' + str(BOARD), '-I' + str(MP), '-I' + str(ULAB)]
            preprocessed = checked([ARM, *flags, '-E', '-DNO_QSTR', MODULE / 'modimage.c'])
            tokens = sorted(set(re.findall(r'MP_QSTR_([a-zA-Z0-9_]+)', preprocessed)))
            extra = temporary / 'image-qstr.h'
            extra.write_text('\n'.join('Q(' + token + ')' for token in tokens) + '\n', encoding='utf-8')
            qstr = checked([sys.executable, '-B', MP / 'py/makeqstrdata.py',
                            GENHDR / 'qstrdefs.preprocessed.h', extra])
            (gen / 'qstrdefs.generated.h').write_text(qstr, encoding='utf-8')
            for name in ('modimage.c', 'image_core.c', 'png_codec.c', 'lodepng.c'):
                checked([ARM, *flags, '-fsyntax-only', MODULE / name])


GC_STUB = r'''
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <assert.h>
static size_t live;
static int fail_after=-1;
void test_gc_fail_after(int n) {fail_after=n;}
static int fail_alloc(void) {if(fail_after==0)return 1;if(fail_after>0)--fail_after;return 0;}
size_t test_gc_live(void) {return live;}
void *gc_alloc(size_t n,unsigned flags) {(void)flags;if(fail_alloc())return NULL;size_t *p=malloc(sizeof(max_align_t)+n);if(!p)return NULL;p[0]=n;live+=n;return (uint8_t *)p+sizeof(max_align_t);}
size_t gc_nbytes(const void *p) {return p?((const size_t *)((const uint8_t *)p-sizeof(max_align_t)))[0]:0;}
void gc_free(void *p) {if(p){size_t *start=(void *)((uint8_t *)p-sizeof(max_align_t));assert(live>=start[0]);live-=start[0];free(start);}}
void *gc_realloc(void *p,size_t n,bool move) {(void)move;if(!p)return gc_alloc(n,0);if(fail_alloc())return NULL;size_t *start=(void *)((uint8_t *)p-sizeof(max_align_t));size_t old=start[0];size_t *q=realloc(start,sizeof(max_align_t)+n);if(!q)return NULL;q[0]=n;live=live-old+n;return (uint8_t *)q+sizeof(max_align_t);}
'''

if __name__ == '__main__':
    unittest.main()
