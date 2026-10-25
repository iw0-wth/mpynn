# SPDX-License-Identifier: MIT
"""Compile actual codec C: independent IEEE reference, binding stubs, ARM syntax."""
import ctypes
import math
import os
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'ports/raspberrypi'
MP = ROOT / 'lib/micropython'
ULAB = ROOT / 'modules/ulab/code'
BOARD = ROOT / 'boards/RPI1B'
HOST = Path(os.environ.get('MPYNN_HOST_GCC', 'E:/msys64/ucrt64/bin/gcc.exe'))
ARM = Path(os.environ.get('MPYNN_ARM_GCC', 'E:/arm-none-eabi/bin/arm-none-eabi-gcc.exe'))
GENHDR = ROOT / 'build/RPI1B/micropython/genhdr'


def checked(command):
    env = os.environ.copy()
    env['PATH'] = str(HOST.parent) + os.pathsep + env.get('PATH', '')
    result = subprocess.run(list(map(str, command)), capture_output=True,
                            text=True, timeout=90, env=env)
    if result.returncode:
        raise AssertionError(' '.join(map(str, command)) + '\n' + result.stdout + result.stderr)
    return result.stdout


def reference(value):
    if math.isnan(value):
        return 0x7e00
    try:
        return struct.unpack('<H', struct.pack('<e', value))[0]
    except (OverflowError, struct.error):
        return 0xfc00 if value < 0 else 0x7c00


class TensorCodecTests(unittest.TestCase):
    def test_real_core_exhaustive_half_and_int32(self):
        self.assertTrue(HOST.is_file(), 'host GCC required')
        with tempfile.TemporaryDirectory(prefix='tensor-codec-core-', ignore_cleanup_errors=True) as folder:
            dll = Path(folder) / 'codec.dll'
            checked([HOST, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared',
                     '-DUML_CODEC_CORE_ONLY', PORT / 'tensor_codec.c', '-o', dll])
            lib = ctypes.CDLL(str(dll))
            encode = lib.uml_codec_float_to_half
            encode.argtypes = [ctypes.c_float]
            encode.restype = ctypes.c_uint16
            decode = lib.uml_codec_half_to_float
            decode.argtypes = [ctypes.c_uint16]
            decode.restype = ctypes.c_float
            for bits in range(65536):
                value = struct.unpack('<e', struct.pack('<H', bits))[0]
                actual = decode(bits)
                if math.isnan(value):
                    self.assertTrue(math.isnan(actual))
                    self.assertEqual(encode(actual), 0x7e00)
                else:
                    self.assertEqual(struct.pack('<f', actual), struct.pack('<f', value))
                    self.assertEqual(encode(actual), bits)
            cases = [0, -0.0, 2**-25, 2**-24, 2**-14, 1 + 2**-11,
                     1 + 3 * 2**-11, 2 - 2**-11, 65504, 65520, 131072,
                     float('inf'), -float('inf'), float('nan')]
            randomizer = random.Random(0x1620)
            cases += [struct.unpack('<f', struct.pack('<I', randomizer.getrandbits(32)))[0]
                      for _ in range(100000)]
            for value in cases:
                self.assertEqual(encode(value), reference(value), repr(value))
            store = lib.uml_codec_store_int32
            store.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int64]
            load = lib.uml_codec_load_int32
            load.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int32)]
            buffer = (ctypes.c_ubyte * 6)(*([0xa5] * 6))
            unaligned = ctypes.byref(buffer, 1)
            for value in [-2**31, -2**24-1, -1, 0, 2**24+1, 2**31-1]:
                self.assertEqual(store(unaligned, 4, value), 0)
                self.assertEqual(bytes(buffer)[1:5], struct.pack('<i', value))
                result = ctypes.c_int32()
                self.assertEqual(load(unaligned, 4, ctypes.byref(result)), 0)
                self.assertEqual(result.value, value)
                self.assertEqual((buffer[0], buffer[5]), (0xa5, 0xa5))
            before = bytes(buffer)
            for value in [-2**31-1, 2**31, 2**63-1]:
                self.assertEqual(store(unaligned, 4, value), -1)
                self.assertEqual(bytes(buffer), before)
            self.assertEqual(store(unaligned, 3, 1), -1)
            self.assertEqual(store(None, 4, 1), -1)
            self.assertEqual(bytes(buffer), before)
            result = ctypes.c_int32(99)
            self.assertEqual(load(unaligned, 3, ctypes.byref(result)), -1)
            self.assertEqual(result.value, 99)
            layout = lib.uml_codec_layout
            layout.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t), ctypes.c_char,
                               ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
            count, size = ctypes.c_size_t(99), ctypes.c_size_t(99)
            self.assertEqual(layout(0, None, b'e', ctypes.byref(count), ctypes.byref(size)), 0)
            self.assertEqual((count.value, size.value), (1, 2))
            for dims in [(0,), (2**32,), (64, 1024, 1024), (2, 3, 4, 5, 6)]:
                shape = (ctypes.c_size_t * len(dims))(*dims)
                self.assertEqual(layout(len(dims), shape, b'i', ctypes.byref(count), ctypes.byref(size)), -1)
            # ctypes must unload before TemporaryDirectory removes the Windows DLL.
            if os.name == 'nt':
                import _ctypes
                _ctypes.FreeLibrary(lib._handle)

    def test_actual_binding_with_micropython_stubs(self):
        self.assertTrue(HOST.is_file(), 'host GCC required')
        with tempfile.TemporaryDirectory(prefix='tensor-codec-stubs-') as folder:
            path = Path(folder)
            (path / 'py').mkdir()
            (path / 'stub.h').write_text(STUBS, encoding='utf-8')
            for name in ['obj.h', 'runtime.h', 'objarray.h', 'objtuple.h', 'objlist.h', 'objint.h']:
                (path / 'py' / name).write_text('#include "stub.h"\n', encoding='utf-8')
            (path / 'ndarray.h').write_text('#include "stub.h"\n', encoding='utf-8')
            source = path / 'test.c'
            source.write_text('#include "' + (PORT / 'tensor_codec.c').as_posix() + '"\n' + MAIN,
                              encoding='utf-8')
            exe = path / 'checks.exe'
            checked([HOST, '-std=c11', '-Wall', '-Wextra', '-Werror',
                     '-Wno-unused-parameter', '-Wno-unused-function', '-I' + str(path),
                     source, '-o', exe])
            checked([exe])

    def test_complete_codec_arm_syntax(self):
        self.assertTrue(ARM.is_file(), 'real ARM GCC required')
        flags = ['-mcpu=arm1176jzf-s', '-marm', '-mfpu=vfp', '-mfloat-abi=hard',
                 '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                 '-DMODULE_ULAB_ENABLED=1', '-DULAB_CONFIG_FILE="ulab_config.h"',
                 '-DMICROPY_ROM_TEXT_COMPRESSION=0', '-I' + str(GENHDR.parent),
                 '-I' + str(PORT), '-I' + str(BOARD), '-I' + str(MP), '-I' + str(ULAB)]
        checked([ARM, *flags, '-fsyntax-only', PORT / 'tensor_codec.c'])


STUBS = r'''
#ifndef CODEC_TEST_STUBS
#define CODEC_TEST_STUBS
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#define MP_ERROR_TEXT(x) x
#define MP_OBJ_TO_PTR(x) ((void *)(x))
#define MP_OBJ_FROM_PTR(x) ((mp_obj_t)(x))
#define MP_BUFFER_READ 1
#define MP_BUFFER_WRITE 2
#define MP_OBJ_STOP_ITERATION 4
#define NDARRAY_FLOAT 'f'
#define NDARRAY_INT8 'b'
#define NDARRAY_UINT8 'B'
#define NDARRAY_INT16 'h'
#define NDARRAY_UINT16 'H'
#define ULAB_MAX_DIMS 4
#define MP_OBJ_NULL 0
typedef uintptr_t mp_obj_t;
typedef intptr_t mp_int_t;
typedef float mp_float_t;
typedef struct {int tag;} mp_obj_type_t;
typedef struct {const mp_obj_type_t *type;} mp_obj_base_t;
static const mp_obj_type_t mp_type_bytearray={1},mp_type_bytes={2},mp_type_memoryview={3},
    mp_type_list={4},mp_type_tuple={5},mp_type_array={6},mp_type_float={7},
    ulab_ndarray_type={8},int_type={9},callback_type={10},bool_type={11};
typedef struct {mp_obj_base_t base; size_t len; mp_obj_t items[];} mp_obj_tuple_t;
typedef struct {mp_obj_base_t base; size_t len; void *buf;} raw_obj;
typedef struct {mp_obj_base_t base; int64_t number; float real;} number_obj;
typedef struct {void *buf;size_t len;} mp_buffer_info_t;
typedef struct {mp_obj_t object;size_t index;} mp_obj_iter_buf_t;
typedef struct {mp_obj_base_t base;uint8_t dtype,ndim;size_t len;
    size_t shape[4];int32_t strides[4];void *array;} ndarray_obj_t;
static jmp_buf error_trap;
static int error_kind,callback_mode;
static mp_obj_t escaped;
static _Noreturn void mp_raise_ValueError(const char *msg){error_kind=1;longjmp(error_trap,1);}
static _Noreturn void mp_raise_TypeError(const char *msg){error_kind=2;longjmp(error_trap,1);}
static bool mp_obj_is_type(mp_obj_t value,const mp_obj_type_t *type){return value && !(value&1) && ((mp_obj_base_t *)value)->type==type;}
static bool mp_obj_is_int(mp_obj_t value){return (value&1)||mp_obj_is_type(value,&int_type);}
static bool mp_obj_is_float(mp_obj_t value){return mp_obj_is_type(value,&mp_type_float);}
static bool mp_obj_is_callable(mp_obj_t value){return mp_obj_is_type(value,&callback_type);}
static int64_t integer(mp_obj_t value){return value&1 ? (intptr_t)value>>1 : ((number_obj *)value)->number;}
static mp_obj_t mp_obj_new_int_from_uint(size_t value){return (value<<1)|1;}
static mp_obj_t mp_obj_new_int(int value){return ((uintptr_t)(intptr_t)value<<1)|1;}
static mp_obj_t large(int64_t value){number_obj *p=calloc(1,sizeof(*p));p->base.type=&int_type;p->number=value;return (mp_obj_t)p;}
static mp_obj_t real(float value){number_obj *p=calloc(1,sizeof(*p));p->base.type=&mp_type_float;p->real=value;return (mp_obj_t)p;}
static float mp_obj_get_float_to_f(mp_obj_t value){return mp_obj_is_int(value)?(float)integer(value):((number_obj *)value)->real;}
static void mp_obj_int_to_bytes(mp_obj_t value,size_t size,uint8_t *p,bool big,bool sign,bool check){
    assert(size==4&&!big&&sign&&check);int64_t n=integer(value);
    if(n<INT32_MIN||n>INT32_MAX){error_kind=3;longjmp(error_trap,1);}
    uint32_t bits=(uint32_t)n;for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(bits>>(8*i));
}
static mp_obj_t mp_obj_new_tuple(size_t count,const mp_obj_t *items){
    mp_obj_tuple_t *p=calloc(1,sizeof(*p)+count*sizeof(mp_obj_t));p->base.type=&mp_type_tuple;p->len=count;
    if(items){memcpy(p->items,items,count*sizeof(mp_obj_t));}return (mp_obj_t)p;
}
static void mp_obj_get_array(mp_obj_t value,size_t *count,mp_obj_t **items){mp_obj_tuple_t *p=(void *)value;*count=p->len;*items=p->items;}
static void mp_get_buffer_raise(mp_obj_t value,mp_buffer_info_t *buffer,int flags){raw_obj *p=(void *)value;buffer->buf=p->buf;buffer->len=p->len;}
static mp_obj_t mp_call_function_1(mp_obj_t fun,mp_obj_t arg){
    assert(fun==(mp_obj_t)&mp_type_bytearray);raw_obj *p=calloc(1,sizeof(*p));p->base.type=&mp_type_bytearray;
    p->len=integer(arg);p->buf=calloc(1,p->len);return (mp_obj_t)p;
}
static mp_obj_t mp_call_function_n_kw(mp_obj_t fun,size_t count,size_t kw,const mp_obj_t *args){
    assert(count==3&&kw==0);escaped=args[0];raw_obj *p=(void *)escaped;
    for(size_t i=0;i<p->len;++i)assert(!((uint8_t *)p->buf)[i]);
    memset(p->buf,42,p->len);assert(integer(args[2])=='i');
    if(callback_mode==1)--p->len;
    if(callback_mode==2)mp_raise_ValueError("callback failed");
    return real(123); /* ignored return */
}
static mp_obj_t mp_getiter(mp_obj_t value,mp_obj_iter_buf_t *buf){buf->object=value;buf->index=0;return (mp_obj_t)buf;}
static mp_obj_t mp_iternext(mp_obj_t iterator){mp_obj_iter_buf_t *it=(void *)iterator;mp_obj_tuple_t *p=(void *)it->object;
    return it->index<p->len?p->items[it->index++]:MP_OBJ_STOP_ITERATION;
}
static mp_float_t ndarray_get_float_value(void *p,uint8_t dtype){
    switch(dtype){case 'b':{int8_t n;memcpy(&n,p,1);return n;}case 'B':{uint8_t n;memcpy(&n,p,1);return n;}
    case 'h':{int16_t n;memcpy(&n,p,2);return n;}case 'H':{uint16_t n;memcpy(&n,p,2);return n;}
    default:{float f;memcpy(&f,p,4);return f;}}
}
static ndarray_obj_t *ndarray_new_dense_ndarray(unsigned rank,size_t *shape,uint8_t dtype){
    ndarray_obj_t *p=calloc(1,sizeof(*p));p->base.type=&ulab_ndarray_type;p->ndim=rank;p->dtype=dtype;p->len=1;
    memcpy(p->shape,shape,sizeof(p->shape));for(unsigned i=4-rank;i<4;++i)p->len*=shape[i];
    p->array=calloc(p->len,sizeof(float));return p;
}
#define EXPECT_ERROR(kind,expr) do{error_kind=0;if(!setjmp(error_trap)){expr;assert(!"expected error");}assert(error_kind==kind);}while(0)
#endif
'''

MAIN = r'''
int main(void){
    size_t shape[]={2};mp_obj_t values[]={large(INT32_MIN),large(INT32_MAX)};
    mp_obj_t list=mp_obj_new_tuple(2,values);((mp_obj_base_t *)list)->type=&mp_type_list;
    mp_obj_t packed=uml_codec_pack(list,1,shape,'i');raw_obj *bytes=(void *)packed;
    assert(bytes->len==8);int32_t n;assert(!uml_codec_load_int32(bytes->buf,4,&n)&&n==INT32_MIN);
    assert(!uml_codec_load_int32((uint8_t *)bytes->buf+4,4,&n)&&n==INT32_MAX);
    mp_obj_t copied=uml_codec_unpack(packed,1,shape,'i',1);
    assert(((raw_obj *)copied)->buf!=bytes->buf&&!memcmp(((raw_obj *)copied)->buf,bytes->buf,8));
    ((mp_obj_tuple_t *)list)->items[0]=large(INT64_C(2147483648));
    EXPECT_ERROR(3,(void)uml_codec_pack(list,1,shape,'i'));
    ((mp_obj_tuple_t *)list)->items[0]=real(1);
    EXPECT_ERROR(2,(void)uml_codec_pack(list,1,shape,'i'));
    mp_obj_base_t boolean={&bool_type};((mp_obj_tuple_t *)list)->items[0]=(mp_obj_t)&boolean;
    EXPECT_ERROR(2,(void)uml_codec_pack(list,1,shape,'i'));
    ((mp_obj_tuple_t *)list)->items[0]=real(1.00048828125f);
    ((mp_obj_tuple_t *)list)->items[1]=real(-0.0f);
    packed=uml_codec_pack(list,1,shape,'e');bytes=(void *)packed;
    assert(((uint8_t *)bytes->buf)[0]==0&&((uint8_t *)bytes->buf)[1]==0x3c);
    assert(((uint8_t *)bytes->buf)[2]==0&&((uint8_t *)bytes->buf)[3]==0x80);
    ndarray_obj_t *decoded=(void *)uml_codec_unpack(packed,1,shape,'e',0);
    assert(decoded->array!=bytes->buf&&((float *)decoded->array)[0]==1);
    ((mp_obj_base_t *)list)->type=&mp_type_array;
    (void)uml_codec_pack(list,1,shape,'e'); /* numeric array path */
    size_t wrong[]={3};EXPECT_ERROR(1,(void)uml_codec_pack(list,1,wrong,'e'));
    EXPECT_ERROR(1,(void)uml_codec_unpack(packed,1,wrong,'e',0));
    mp_obj_base_t callback={&callback_type};
    packed=uml_codec_pack((mp_obj_t)&callback,1,shape,'i');assert(packed==escaped);
    assert(((uint8_t *)((raw_obj *)escaped)->buf)[0]==42);
    callback_mode=1;EXPECT_ERROR(1,(void)uml_codec_pack((mp_obj_t)&callback,1,shape,'i'));
    callback_mode=2;EXPECT_ERROR(1,(void)uml_codec_pack((mp_obj_t)&callback,1,shape,'i'));
    int16_t numbers[]={1,2,3,4};size_t grid[]={2,2};
    ndarray_obj_t view={{&ulab_ndarray_type},'h',2,4,{0,0,2,2},{0,0,-4,-2},numbers+3};
    packed=uml_codec_pack((mp_obj_t)&view,2,grid,'i');bytes=(void *)packed;
    for(unsigned i=0;i<4;++i){uml_codec_load_int32((uint8_t *)bytes->buf+4*i,4,&n);assert(n==4-(int)i);}
    view.dtype='f';EXPECT_ERROR(2,(void)uml_codec_pack((mp_obj_t)&view,2,grid,'i'));
    view.dtype='c';EXPECT_ERROR(2,(void)uml_codec_pack((mp_obj_t)&view,2,grid,'e'));
    size_t scalar_shape[]={1};mp_obj_t scalar_value[]={large(5)};
    mp_obj_t scalar=mp_obj_new_tuple(1,scalar_value);
    packed=uml_codec_pack(scalar,0,NULL,'i');decoded=(void *)uml_codec_unpack(packed,0,NULL,'i',0);
    assert(decoded->ndim==1&&decoded->shape[3]==1&&((float *)decoded->array)[0]==5);
    EXPECT_ERROR(1,(void)uml_codec_pack(scalar,1,scalar_shape,'z'));
    return 0;
}
'''

if __name__ == '__main__':
    unittest.main()
