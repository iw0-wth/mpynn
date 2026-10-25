# SPDX-License-Identifier: MIT
"""Strict host regression for the real file-audio C implementation.

The harness compiles audio_file.c itself against small MicroPython API stubs and
executes its real WAV parser, VFS reads, lifecycle and VM callback paths.  It
also compiles the complete source with the Raspberry Pi ARM compiler using a
fresh generated root-pointer/qstr header directory.  It does not use a Unix
MicroPython interpreter or claim hardware coverage.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "modules/audio/audio_file.c"
MP = ROOT / "lib/micropython"
ARM = Path(os.environ.get("MPYNN_ARM_GCC", "E:/arm-none-eabi/bin/arm-none-eabi-gcc.exe"))
HOST = Path(os.environ.get("MPYNN_HOST_GCC", "E:/msys64/ucrt64/bin/gcc.exe"))
GEN = ROOT / "build/RPI1B/micropython/genhdr"


def checked(command, cwd=None):
    env = os.environ.copy()
    env["PATH"] = str(HOST.parent) + os.pathsep + env.get("PATH", "")
    p = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise AssertionError(" ".join(map(str, command)) + "\nreturncode=" + str(p.returncode) + "\n" + p.stdout + p.stderr)
    return p.stdout


def arm_flags(temp):
    return [ARM, "-mcpu=arm1176jzf-s", "-marm", "-mfpu=vfp", "-mfloat-abi=hard",
            "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
            "-DMICROPY_ROM_TEXT_COMPRESSION=0", "-I" + str(temp), "-I" + str(MP),
            "-I" + str(ROOT / "ports/raspberrypi"), "-I" + str(ROOT / "boards/RPI1B"),
            "-I" + str(ROOT / "modules/audio")]


HARNESS = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#undef assert
#define assert(x) do { if (!(x)) { fprintf(stderr, "assertion failed: %s:%d: %s\\n", __FILE__, __LINE__, #x); abort(); } } while (0)
#define MICROPY_ENABLE_SCHEDULER 0
#define MICROPY_PY_BUILTINS_BYTEARRAY 1
#define MICROPY_PY_BUILTINS_MEMORYVIEW 0
#define MICROPY_PY_BUILTINS_STR_UNICODE 0
#define MP_ERROR_TEXT(x) x
#define MP_ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define MP_OBJ_NULL ((mp_obj_t)0)
#define MP_SEEK_SET 0
#define MP_SEEK_CUR 1
#define MP_SEEK_END 2
#define MP_OBJ_NEW_QSTR(x) ((mp_obj_t)(x))
#define MP_ROM_QSTR(x) ((mp_obj_t)(x))
#define MP_ROM_PTR(x) ((mp_obj_t)(x))
#define MP_ROM_INT(x) ((mp_obj_t)(x))
#define MP_ROM_NONE ((mp_obj_t)0)
#define MP_QSTR___name__ 0
#define MP_QSTR_rb 1
#define MP_QSTR_wav 2
#define MP_QSTR_pcm 3
#define MP_QSTR_audio 4
#define MP_QSTR_init 5
#define MP_QSTR_channels 6
#define MP_QSTR_frequency 7
#define MP_QSTR_samples 8
#define MP_QSTR_source 9
#define MP_QSTR_format 10
#define MP_QSTR_start_streaming 11
#define MP_QSTR_stop_streaming 12
#define MP_QSTR_deinit 13
#define MP_QSTR_poll 14
#define MP_QSTR_is_streaming 15
#define MP_QSTR_eof 16
#define MP_OBJ_FROM_PTR(x) ((mp_obj_t)(uintptr_t)(x))
#define MP_OBJ_TO_PTR(x) ((void *)(uintptr_t)(x))
#define MP_ARG_BOOL 1
#define MP_ARG_INT 2
#define MP_ARG_OBJ 3
#define MP_ARG_REQUIRED 0x100
#define MP_ARG_KW_ONLY 0x200
#define m_new(t,n) ((t *)host_alloc((n) * sizeof(t)))
#define m_del(t,p,n) host_free((p), (n) * sizeof(t))
#define MP_DEFINE_CONST_FUN_OBJ_KW(n,a,f) const int n = 0
#define MP_DEFINE_CONST_FUN_OBJ_0(n,f) const int n = 0
#define MP_DEFINE_CONST_FUN_OBJ_1(n,f) const int n = 0
#define MP_DEFINE_CONST_DICT(n,t) const int n = 0
#define MP_REGISTER_MODULE(n,m)
#define MP_REGISTER_ROOT_POINTER(x)
#define MP_NORETURN _Noreturn

typedef uintptr_t mp_obj_t;
typedef uintptr_t mp_rom_obj_t;
typedef unsigned char byte;
typedef unsigned mp_uint_t;
typedef int mp_int_t;
typedef long long mp_off_t;
typedef const char *mp_rom_error_text_t;
typedef struct { int tag; } mp_obj_type_t;
typedef struct { mp_obj_t key, value; } mp_map_elem_t;
typedef struct { int dummy; } mp_map_t;
typedef struct { int dummy; } mp_sched_node_t;
typedef struct { mp_obj_t u_obj; mp_rom_obj_t u_rom_obj; mp_int_t u_int; } mp_arg_val_t;
typedef struct { int qst, flags; mp_arg_val_t defval; } mp_arg_t;
typedef struct { mp_obj_t base; size_t len; void *items; } fake_bytes_t;
typedef struct { mp_obj_t base; const char *data; size_t len; } fake_str_t;
typedef struct { mp_obj_t base; } fake_callable_t;
typedef struct { mp_obj_t qst, value; } mp_rom_map_elem_t;
typedef struct { const mp_obj_type_t *type; } mp_obj_base_t;
typedef struct { mp_obj_base_t base; mp_obj_t globals; } mp_obj_module_t;
static const mp_obj_type_t mp_type_module = {7};
typedef struct { mp_obj_t audio_file_handle, audio_file_callback, audio_file_buffer; byte *audio_file_data; } roots_t;
static roots_t roots;
#define MP_STATE_VM(x) (roots.x)
static const mp_obj_t mp_const_none = 0x2;
static const mp_obj_type_t mp_type_ValueError = {1}, mp_type_TypeError = {2},
    mp_type_RuntimeError = {3}, mp_type_OSError = {4}, mp_type_str = {5},
    mp_type_callable = {6};
static const mp_map_t mp_const_empty_map = {0};
static fake_str_t wav_format = {0, "wav", 3};
typedef struct nlr_buf { jmp_buf jump; void *ret_val; struct nlr_buf *prev; } nlr_buf_t;
static nlr_buf_t *current_nlr;
static const char *last_error;
static int close_count, alloc_count, fail_alloc, callback_calls, callback_throw;
static int callback_stop, callback_deinit, read_error, seek_error;
static mp_obj_t audio_stop_streaming(void);
static byte file_data[65536];
static size_t file_size, file_pos;
static size_t read_limit;
void audio_file_deinit(void);
static void host_raise(const char *msg) { last_error = msg; nlr_buf_t *n = current_nlr; if (!n) { fprintf(stderr, "untrapped NLR: %s\\n", msg); exit(88); } current_nlr = n->prev; longjmp(n->jump, 1); }
static void *host_alloc(size_t n) { if (fail_alloc) { host_raise("alloc"); } ++alloc_count; return calloc(1, n); }
static void host_free(void *p, size_t n) { (void)n; free(p); }
static void mp_raise_msg(const mp_obj_type_t *type, const char *msg) { (void)type; host_raise(msg); }
static void mp_raise_OSError(int e) { (void)e; host_raise("OSError"); }
#define nlr_push(p) ((p)->prev = current_nlr, current_nlr = (p), setjmp((p)->jump))
#define nlr_pop() (current_nlr = current_nlr->prev)
#define nlr_jump(v) host_raise((const char *)(v))
static bool mp_obj_is_str(mp_obj_t o) { (void)o; return true; }
static const char *mp_obj_str_get_data(mp_obj_t o, size_t *len) { (void)o; *len = 3; return "wav"; }
static bool mp_obj_is_callable(mp_obj_t o) { return o == 0xCA11; }
static mp_obj_t mp_obj_new_bool(mp_int_t x) { return x ? 1 : 0; }
static mp_obj_t mp_obj_new_bytes(const byte *p, size_t n) { if (fail_alloc) host_raise("alloc"); fake_bytes_t *b = calloc(1, sizeof(*b)); b->base = 0xBEEF; b->len = n; b->items = malloc(n); memcpy(b->items, p, n); return (mp_obj_t)(uintptr_t)b; }
static mp_obj_t mp_obj_new_bytearray_by_ref(size_t n, void *p) { fake_bytes_t *b = calloc(1, sizeof(*b)); b->base = 0xBABE; b->len = n; b->items = p; return (mp_obj_t)(uintptr_t)b; }
static void mp_arg_parse_all(size_t np, const mp_obj_t *p, mp_map_t *kw, size_t n, const mp_arg_t *a, mp_arg_val_t *o) { (void)np;(void)p;(void)kw;(void)n;(void)a; o[0].u_int=1; o[1].u_int=16000; o[2].u_int=2; o[3].u_obj=0x5000; o[4].u_rom_obj=(mp_rom_obj_t)(uintptr_t)&wav_format; }
static mp_obj_t mp_builtin_open(size_t n, const mp_obj_t *a, mp_map_t *kw) { (void)n;(void)a;(void)kw; return 0xF11E; }
static mp_uint_t mp_stream_read_exactly(mp_obj_t f, void *dst, mp_uint_t n, int *err) { assert(f == 0xF11E); if (read_error) { *err=5; return 0; } size_t available = file_pos < file_size ? file_size - file_pos : 0; size_t got = available < n ? available : n; if (read_limit && got > read_limit) got = read_limit; memcpy(dst, file_data + file_pos, got); file_pos += got; return got; }
static mp_off_t mp_stream_seek(mp_obj_t f, mp_off_t off, int whence, int *err) { assert(f == 0xF11E); if (seek_error) { *err=5; return -1; } if (whence == 0) file_pos=(size_t)off; else if (whence == 1) file_pos += (size_t)off; else file_pos=file_size+(size_t)off; return (mp_off_t)file_pos; }
static mp_obj_t mp_stream_close(mp_obj_t f) { assert(f == 0xF11E); ++close_count; if (read_error == 9) { last_error = "close"; } return mp_const_none; }
static mp_obj_t mp_call_function_1_protected(mp_obj_t f, mp_obj_t arg) { assert(f == 0xCA11); ++callback_calls; if (callback_throw) { last_error="callback"; return MP_OBJ_NULL; } if (callback_stop) { audio_stop_streaming(); } if (callback_deinit) { audio_file_deinit(); } (void)arg; return mp_const_none; }
#include "audio_file.c"
static void expect_fail(void (*fn)(void)) { nlr_buf_t j = {0}; if (nlr_push(&j)==0) { fn(); assert(!"expected failure"); nlr_pop(); } }
static void reset_file(const byte *p, size_t n) { wav_format.base = MP_OBJ_FROM_PTR(&mp_type_str); memcpy(file_data,p,n); file_size=n; file_pos=0; read_limit=0; read_error=0; seek_error=0; last_error=NULL; close_count=0; callback_calls=0; callback_throw=0; callback_stop=0; callback_deinit=0; fail_alloc=0; roots.audio_file_handle=mp_const_none; roots.audio_file_callback=mp_const_none; roots.audio_file_buffer=mp_const_none; roots.audio_file_data=NULL; audio_state=(audio_file_state_t){0}; }
static size_t append_chunk(byte *p,size_t at,const char *id,const byte *v,size_t n) { memcpy(p+at,id,4);at+=4; p[at++]=(byte)n;p[at++]=(byte)(n>>8);p[at++]=(byte)(n>>16);p[at++]=(byte)(n>>24);memcpy(p+at,v,n);at+=n;if(n&1)p[at++]=0;return at; }
static size_t make_wav(byte *p,bool data_first,bool odd_junk) { byte fmt[16]={1,0,1,0,0x80,0x3e,0,0,0,0x7d,0,0,2,0,16,0}; byte data[]={1,0,2,0,3,0,4,0}; byte junk[]={0x7f}; size_t at=12;if(data_first)at=append_chunk(p,at,"data",data,sizeof(data));if(odd_junk)at=append_chunk(p,at,"JUNK",junk,1);at=append_chunk(p,at,"fmt ",fmt,sizeof(fmt));if(!data_first)at=append_chunk(p,at,"data",data,sizeof(data));memcpy(p,"RIFF",4);p[4]=(byte)(at-8);p[5]=(byte)((at-8)>>8);p[6]=(byte)((at-8)>>16);p[7]=(byte)((at-8)>>24);memcpy(p+8,"WAVE",4);return at; }
static void init_wav(void) { mp_arg_val_t unused[1];(void)unused; mp_obj_t pos[1]={0}; mp_map_t kw={0}; (void)audio_init(0,pos,&kw); }
static void poll_once(void) { audio_state.streaming=true; roots.audio_file_callback=0xCA11; audio_file_poll(); }
int main(void) {
 byte wav[256]; size_t n=make_wav(wav,true,true); reset_file(wav,n); init_wav(); assert(audio_state.initialized && file_pos > 0); poll_once(); assert(callback_calls==1); assert(((fake_bytes_t *)(uintptr_t)roots.audio_file_buffer)->len==4); audio_file_poll(); assert(callback_calls==2); audio_file_poll(); assert(callback_calls==2 && audio_state.eof && !audio_state.streaming); audio_file_deinit(); assert(close_count==1 && roots.audio_file_handle==mp_const_none && roots.audio_file_data==NULL);
 reset_file(wav,n); file_data[4]=0xff;file_data[5]=0xff;file_data[6]=0xff;file_data[7]=0xff; expect_fail(init_wav); assert(close_count==1 && roots.audio_file_handle==mp_const_none && roots.audio_file_data==NULL);
  reset_file(wav,n); seek_error=1; expect_fail(init_wav); assert(close_count==1 && roots.audio_file_handle==mp_const_none);
  reset_file(wav,n); init_wav(); read_error=9; audio_file_deinit(); assert(close_count==1 && roots.audio_file_handle==mp_const_none);
 reset_file(wav,n); init_wav(); roots.audio_file_callback=0xCA11; audio_state.streaming=true; callback_throw=1; audio_file_poll(); assert(callback_calls==1 && !audio_state.streaming && audio_state.eof && !audio_state.in_poll && !audio_state.in_callback); audio_file_poll(); assert(callback_calls==1); audio_file_deinit();
 reset_file(wav,n); init_wav(); roots.audio_file_callback=0xCA11; audio_state.streaming=true; callback_deinit=1; audio_file_poll(); assert(!audio_state.initialized && roots.audio_file_handle==mp_const_none && roots.audio_file_data==NULL && !audio_state.in_poll); 
 reset_file(wav,n); init_wav(); fail_alloc=1; roots.audio_file_callback=0xCA11; audio_state.streaming=true; audio_file_poll(); assert(!audio_state.streaming && audio_state.eof && !audio_state.in_poll); audio_file_deinit();
 return 0;
}
'''


def test_native_host_c_regression():
    assert HOST.is_file(), "host GCC required"
    with tempfile.TemporaryDirectory(prefix="audio-native-host-") as d:
        d = Path(d)
        # Include the real source from its module directory; stubs are supplied
        # by this translation unit, so no Unix MicroPython runtime is involved.
        source = d / "check.c"
        source.write_text(HARNESS, encoding="utf-8")
        stub = d / "py"
        stub.mkdir()
        for name in ("builtin.h", "obj.h", "objarray.h", "runtime.h", "stream.h"):
            (stub / name).write_text("/* declarations are supplied by the harness */\n", encoding="utf-8")
        exe = d / "check.exe"
        checked([HOST, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-Wno-unused-parameter", "-Wno-unused-function", "-Wno-unused-const-variable", "-I" + str(d),
                 "-I" + str(ROOT / "modules/audio"),
                 source, "-o", exe])
        checked([exe])


def test_complete_audio_arm_syntax():
    assert ARM.is_file(), "real ARM GCC required"
    assert GEN.is_dir(), "parent generated MicroPython headers required"
    with tempfile.TemporaryDirectory(prefix="audio-arm-") as d:
        d = Path(d)
        gen = d / "genhdr"
        gen.mkdir()
        for name in ("mpversion.h", "root_pointers.h", "moduledefs.h", "qstrdefs.preprocessed.h"):
            shutil.copyfile(GEN / name, gen / name)
        qstrs = sorted(set(re.findall(r"MP_QSTR_([a-zA-Z0-9_]+)", SOURCE.read_text(encoding="utf-8"))))
        extra = d / "audio-qstr.h"
        extra.write_text("\n".join("Q(" + q + ")" for q in qstrs) + "\n", encoding="utf-8")
        generated = checked([sys.executable, "-B", MP / "py/makeqstrdata.py",
                             gen / "qstrdefs.preprocessed.h", extra])
        (gen / "qstrdefs.generated.h").write_text(generated, encoding="utf-8")
        # Compile the complete source against fresh qstr/root/module headers.
        checked([*arm_flags(d), "-fsyntax-only", SOURCE])
