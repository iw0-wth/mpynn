# SPDX-License-Identifier: MIT
"""Execute real native binding functions with small MP/VFS stubs.

Tests ownership, constructor validation, stream cleanup, tensor buffer copies,
and resizing/cropping. The actual full binding is separately ARM syntax-checked.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'modules/image_file'
HOST = Path('E:/msys64/ucrt64/bin/gcc.exe')


def extract(name):
    text = (MODULE / 'modimage.c').read_text(encoding='utf-8')
    match = re.search(r'^static [^\n]+\b' + name + r'\(', text, re.M)
    if not match:
        raise AssertionError('Missing native function ' + name)
    start = text.index('{', match.start())
    depth, end = 1, start + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end] + '\n'


class ImageFileBindingTests(unittest.TestCase):
    def test_real_binding_vfs_owned_buffers_and_preprocessing(self):
        self.assertTrue(HOST.is_file(), 'host GCC required')
        functions = ['if_status', 'if_checked_size', 'if_self', 'if_pixels', 'if_new',
                     'if_load', 'if_make_new', 'if_width', 'if_height', 'if_format',
                     'if_size_method', 'if_coordinates', 'if_get_pixel', 'if_set_pixel',
                     'if_get_roi', 'if_scaled', 'if_copy', 'if_resize', 'if_grayscale',
                     'if_overlaps', 'if_draw_image', 'if_to_ndarray']
        source = PREFIX + '\n'.join(extract(name) for name in functions) + MAIN
        with tempfile.TemporaryDirectory(prefix='image-file-binding-') as folder:
            path = Path(folder)
            c = path / 'test.c';c.write_text(source, encoding='utf-8')
            exe = path / 'test.exe'
            commands = [[HOST, '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                         '-I' + str(MODULE), c, MODULE / 'image_core.c', '-lm', '-o', exe], [exe]]
            env = os.environ.copy();env['PATH'] = str(HOST.parent) + os.pathsep + env.get('PATH', '')
            for command in commands:
                result = subprocess.run([str(x) for x in command], capture_output=True,
                                        text=True, timeout=60, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <setjmp.h>
#include "image_core.h"
#define MP_ERROR_TEXT(x) x
#define MP_ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define MP_OBJ_TO_PTR(o) ((void *)(o))
#define MP_OBJ_FROM_PTR(o) ((mp_obj_t)(o))
#define MP_OBJ_NULL 0
#define mp_const_none 0
#define MP_ROM_NONE 0
#define MP_ROM_INT(n) ((n)*2+1)
#define MP_OBJ_NEW_QSTR(q) (q)
#define MP_ARG_OBJ 1
#define MP_ARG_INT 2
#define MP_ARG_REQUIRED 4
#define MP_ARG_BOOL 8
#define MP_ARG_KW_ONLY 16
#define MP_BUFFER_WRITE 2
#define MP_SEEK_END 2
#define MP_SEEK_SET 0
#define ULAB_MAX_DIMS 4
#define m_new0(t,n) ((t *)calloc(n,sizeof(t)))
#define m_new(t,n) ((t *)malloc((n)*sizeof(t)))
#define mp_obj_malloc(t,ty) ((t *)new_object(sizeof(t),ty))
enum {MP_QSTR_rb=1,MP_QSTR_path,MP_QSTR_height,MP_QSTR_pixformat,MP_QSTR_buffer,
MP_QSTR_copy_to_fb,MP_QSTR_roi,MP_QSTR_x_scale,MP_QSTR_y_scale,MP_QSTR_width,
MP_QSTR_hint,MP_QSTR_copy,MP_QSTR_image,MP_QSTR_x,MP_QSTR_y,MP_QSTR_dtype};
typedef uintptr_t mp_obj_t;
typedef uintptr_t mp_uint_t;
typedef intptr_t mp_int_t;
typedef long mp_off_t;
typedef struct {int kind;} mp_obj_type_t;
typedef struct {const mp_obj_type_t *type;} mp_obj_base_t;
static const mp_obj_type_t if_type={1},str_type={2},buffer_type={3},tuple_type={4},array_type={5};
static const mp_obj_type_t mp_type_NotImplementedError={6},mp_type_MemoryError={7},mp_type_OSError={8};
typedef struct {mp_obj_base_t base;unsigned w,h,format;uint8_t *owned;} if_obj;
typedef struct {mp_obj_base_t base;size_t len;void *data;bool writable;} buffer_obj;
typedef struct {mp_obj_base_t base;size_t len;mp_obj_t *items;} tuple_obj;
typedef struct {mp_obj_base_t base;unsigned ndim,dtype;size_t shape[4];void *array;} ndarray_obj_t;
typedef struct {void *buf;size_t len;} mp_buffer_info_t;
typedef struct {int used;} mp_map_t;
static const mp_map_t mp_const_empty_map={0};
typedef union {mp_obj_t u_obj,u_rom_obj;mp_int_t u_int;bool u_bool;} mp_arg_val_t;
typedef struct {unsigned qstr,flags;mp_arg_val_t default_value;} mp_arg_t;
typedef struct nlr {jmp_buf jump;void *ret_val;struct nlr *prev;} nlr_buf_t;
static nlr_buf_t *current;
#define nlr_push(p) (((p)->prev=current),current=(p),setjmp((p)->jump))
#define nlr_pop() (current=current->prev)
static _Noreturn void nlr_jump(void *v) {nlr_buf_t *n=current;assert(n);current=n->prev;n->ret_val=v;longjmp(n->jump,1);}
static _Noreturn void mp_raise_ValueError(const char *s) {nlr_jump((void *)s);}
static _Noreturn void mp_raise_TypeError(const char *s) {nlr_jump((void *)s);}
static _Noreturn void mp_raise_msg(const mp_obj_type_t *t,const char *s) {nlr_jump((void *)s);}
static _Noreturn void mp_raise_OSError(int e) {nlr_jump((void *)"OSError");}
static void *new_object(size_t bytes,const mp_obj_type_t *type) {mp_obj_base_t *b=calloc(1,bytes);b->type=type;return b;}
static mp_obj_t mp_obj_new_int(int n) {return (mp_obj_t)((intptr_t)n*2+1);}
static mp_obj_t mp_obj_new_int_from_uint(unsigned n) {return (mp_obj_t)n*2+1;}
static bool mp_obj_is_int(mp_obj_t o) {return (o&1)!=0;}
static bool mp_obj_is_str(mp_obj_t o) {return o&&!mp_obj_is_int(o)&&((mp_obj_base_t *)o)->type==&str_type;}
static bool mp_obj_is_type(mp_obj_t o,const mp_obj_type_t *t) {return o&&!mp_obj_is_int(o)&&((mp_obj_base_t *)o)->type==t;}
static mp_int_t mp_obj_get_int(mp_obj_t o) {assert(mp_obj_is_int(o));return ((intptr_t)o-1)/2;}
static float mp_obj_get_float(mp_obj_t o) {return (float)mp_obj_get_int(o);}
static bool mp_obj_is_true(mp_obj_t o) {return o&&mp_obj_get_int(o)!=0;}
static void mp_obj_get_array(mp_obj_t o,size_t *n,mp_obj_t **items) {tuple_obj *t=(void *)o;assert(t->base.type==&tuple_type);*n=t->len;*items=t->items;}
static mp_obj_t mp_obj_new_tuple(size_t n,const mp_obj_t *items) {tuple_obj *t=new_object(sizeof(*t),&tuple_type);t->len=n;t->items=malloc(n*sizeof(*items));memcpy(t->items,items,n*sizeof(*items));return (mp_obj_t)t;}
static const char *mp_obj_str_get_data(mp_obj_t o,size_t *n) {buffer_obj *b=(void *)o;*n=b->len;return b->data;}
static void mp_get_buffer_raise(mp_obj_t o,mp_buffer_info_t *info,int mode) {buffer_obj *b=(void *)o;if(b->base.type!=&buffer_type||!b->writable)mp_raise_TypeError("not writable");info->buf=b->data;info->len=b->len;}
static ndarray_obj_t *ndarray_new_dense_ndarray(unsigned rank,size_t *shape,unsigned dtype) {ndarray_obj_t *a=new_object(sizeof(*a),&array_type);a->ndim=rank;a->dtype=dtype;memcpy(a->shape,shape,4*sizeof(size_t));size_t n=1;for(unsigned i=4-rank;i<4;++i)n*=shape[i];a->array=calloc(n,dtype=='f'?4:1);return a;}
static mp_arg_val_t overrides[MP_QSTR_dtype+1];
static bool has_override[MP_QSTR_dtype+1];
static void reset_args(void) {memset(has_override,0,sizeof(has_override));}
static void set_obj(unsigned key,mp_obj_t value) {overrides[key].u_obj=value;has_override[key]=true;}
static void set_int(unsigned key,mp_int_t value) {overrides[key].u_int=value;has_override[key]=true;}
static void parse(size_t n,const mp_obj_t *pos,size_t allowed_n,const mp_arg_t *allowed,mp_arg_val_t *out) {
    size_t consumed=0;
    for(size_t i=0;i<allowed_n;++i) {
        out[i]=allowed[i].default_value;
        if(has_override[allowed[i].qstr])out[i]=overrides[allowed[i].qstr];
        else if(!(allowed[i].flags&MP_ARG_KW_ONLY)&&consumed<n) {
            if(allowed[i].flags&MP_ARG_INT)out[i].u_int=mp_obj_get_int(pos[consumed++]);
            else out[i].u_obj=pos[consumed++];
        }
    }
}
static void mp_arg_parse_all(size_t n,const mp_obj_t *pos,mp_map_t *kw,size_t an,const mp_arg_t *allowed,mp_arg_val_t *out) {parse(n,pos,an,allowed,out);}
static void mp_arg_parse_all_kw_array(size_t n,size_t kw,const mp_obj_t *pos,size_t an,const mp_arg_t *allowed,mp_arg_val_t *out) {parse(n,pos,an,allowed,out);}
static int file_failure,close_count;
static const uint8_t file_data[]="P5\n2 1\n255\n\0\xff";
static mp_obj_t mp_vfs_open(size_t n,mp_obj_t *a,mp_map_t *kw) {assert(n==2&&a[1]==MP_QSTR_rb);return 88;}
static mp_off_t mp_stream_seek(mp_obj_t f,mp_off_t off,int whence,int *err) {assert(f==88);if(file_failure==1){*err=5;return -1;}return whence==MP_SEEK_END?(mp_off_t)sizeof(file_data)-1:0;}
static mp_uint_t mp_stream_read_exactly(mp_obj_t f,void *out,size_t n,int *err) {assert(f==88&&n==sizeof(file_data)-1);if(file_failure==2){*err=5;return 0;}memcpy(out,file_data,n);return file_failure==3?n-1:n;}
static mp_obj_t mp_stream_close(mp_obj_t f) {assert(f==88);++close_count;if(file_failure==4)mp_raise_ValueError("close failed");return 0;}
int if_png_decode(const uint8_t *d,size_t n,if_image *i) {return IF_UNSUPPORTED;}
#define EXPECT_ERROR(statement) do {nlr_buf_t trap;if(nlr_push(&trap)==0){statement;assert(!"expected exception");nlr_pop();}}while(0)
'''

MAIN = r'''
int main(void) {
    mp_obj_t dims[]={mp_obj_new_int(2),mp_obj_new_int(1),mp_obj_new_int(IF_GRAYSCALE)};
    uint8_t initial[]={32,64};buffer_obj buffer={{&buffer_type},2,initial,true};
    set_obj(MP_QSTR_buffer,(mp_obj_t)&buffer);
    if_obj *image=(void *)if_make_new(&if_type,3,0,dims);
    assert(image->owned!=initial&&image->owned[0]==32);initial[0]=9;
    assert(image->owned[0]==32);buffer.len=0;
    assert(mp_obj_get_int(if_width((mp_obj_t)image))==2);
    assert(mp_obj_get_int(if_height((mp_obj_t)image))==1);
    assert(mp_obj_get_int(if_format((mp_obj_t)image))==IF_GRAYSCALE);
    assert(mp_obj_get_int(if_size_method((mp_obj_t)image))==2);
    mp_obj_t get[]={(mp_obj_t)image,mp_obj_new_int(0),mp_obj_new_int(0)};
    assert(mp_obj_get_int(if_get_pixel(3,get))==32);
    mp_obj_t set[]={(mp_obj_t)image,mp_obj_new_int(0),mp_obj_new_int(0),mp_obj_new_int(255)};
    if_set_pixel(4,set);assert(image->owned[0]==255);
    set[3]=mp_obj_new_int(256);EXPECT_ERROR((void)if_set_pixel(4,set));
    get[1]=mp_obj_new_int(-1);EXPECT_ERROR((void)if_get_pixel(3,get));
    reset_args();uint8_t target[8]={0};buffer=(buffer_obj){{&buffer_type},8,target,true};
    set_obj(MP_QSTR_buffer,(mp_obj_t)&buffer);
    mp_obj_t tensor_args[]={(mp_obj_t)image,mp_obj_new_int('f')};
    ndarray_obj_t *array=(void *)if_to_ndarray(2,tensor_args,NULL);
    assert(array->ndim==2&&array->shape[2]==1&&array->shape[3]==2);
    assert(array->array!=target&&((float *)array->array)[0]==255);
    float target_first;memcpy(&target_first,target,4);assert(target_first==255);
    memset(target,0,8);assert(((float *)array->array)[0]==255);
    ((float *)array->array)[0]=1;assert(!target[0]);
    buffer.len=1;EXPECT_ERROR((void)if_to_ndarray(2,tensor_args,NULL));
    buffer.len=8;buffer.writable=false;EXPECT_ERROR((void)if_to_ndarray(2,tensor_args,NULL));
    reset_args();tensor_args[1]=mp_obj_new_int('x');EXPECT_ERROR((void)if_to_ndarray(2,tensor_args,NULL));
    reset_args();mp_obj_t self[]={(mp_obj_t)image};
    if_obj *copy=(void *)if_copy(1,self,NULL);assert(copy->owned!=image->owned&&copy->owned[0]==255);
    mp_obj_t resize[]={(mp_obj_t)image,mp_obj_new_int(1),mp_obj_new_int(1)};
    if_obj *small=(void *)if_resize(3,resize,NULL);assert(small->w==1&&small->owned[0]==160);
    reset_args();mp_obj_t color_dims[]={mp_obj_new_int(1),mp_obj_new_int(1),mp_obj_new_int(IF_RGB565)};
    if_obj *color=(void *)if_make_new(&if_type,3,0,color_dims);
    mp_obj_t rgb[]={mp_obj_new_int(255),mp_obj_new_int(0),mp_obj_new_int(0)};
    set[0]=(mp_obj_t)color;set[1]=set[2]=mp_obj_new_int(0);set[3]=mp_obj_new_tuple(3,rgb);
    if_set_pixel(4,set);get[0]=(mp_obj_t)color;get[1]=mp_obj_new_int(0);
    tuple_obj *rgb_result=(void *)if_get_pixel(3,get);assert(mp_obj_get_int(rgb_result->items[0])==255);
    self[0]=(mp_obj_t)color;if_grayscale(1,self,NULL);assert(color->format==IF_GRAYSCALE&&color->owned[0]==77);
    // Exact Normalization flags fill target dimensions using a validated ROI.
    reset_args();set_int(MP_QSTR_hint,IF_BILINEAR|IF_CENTER|IF_SCALE_ASPECT_IGNORE|IF_BLACK_BACKGROUND);
    mp_obj_t draw[]={(mp_obj_t)image,(mp_obj_t)color,mp_obj_new_int(0),mp_obj_new_int(0)};
    if_draw_image(4,draw,NULL);assert(image->owned[0]==77&&image->owned[1]==77);
    // Overlapping self draws snapshot before black-background clearing.
    draw[1]=(mp_obj_t)image;if_draw_image(4,draw,NULL);assert(image->owned[0]==77);
    reset_args();buffer_obj path={{&str_type},4,(void *)"a.pgm",false};
    mp_obj_t file_args[]={(mp_obj_t)&path};
    if_obj *loaded=(void *)if_make_new(&if_type,1,0,file_args);
    assert(loaded->w==2&&loaded->owned[0]==0&&loaded->owned[1]==255&&close_count==1);
    for(file_failure=1;file_failure<=4;++file_failure) {
        int previous=close_count;EXPECT_ERROR((void)if_load((mp_obj_t)&path));assert(close_count==previous+1);
    }
    file_failure=0;reset_args();set_int(MP_QSTR_copy_to_fb,1);
    EXPECT_ERROR((void)if_make_new(&if_type,1,0,file_args));
    EXPECT_ERROR((void)if_checked_size(8193,1,1));
    assert(!current);
    return 0;
}
'''

if __name__ == '__main__':
    unittest.main()
