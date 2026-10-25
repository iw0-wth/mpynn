# SPDX-License-Identifier: MIT
"""Real-C binding checks: bounded host harness and actual ARM syntax compilation.

Host stubs exercise the extracted binding functions, not a Python replacement
for inference. ARM compilation uses the complete C file and real MicroPython,
ulab, board, backend and generated headers. No firmware build is started.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'ports/raspberrypi'
SOURCE = PORT / 'uml_binding.c'
MP = ROOT / 'lib/micropython'
ULAB = ROOT / 'modules/ulab/code'
BOARD = ROOT / 'boards/RPI1B'
ARM = Path(os.environ.get('MPYNN_ARM_GCC', 'E:/arm-none-eabi/bin/arm-none-eabi-gcc.exe'))
HOST = Path('E:/msys64/ucrt64/bin/gcc.exe')
GENHDR = ROOT / 'build/RPI1B/micropython/genhdr'


def checked(command):
    env = os.environ.copy()
    env['PATH'] = str(HOST.parent) + os.pathsep + env.get('PATH', '')
    result = subprocess.run([str(x) for x in command], capture_output=True,
                            text=True, timeout=90, env=env)
    if result.returncode:
        raise AssertionError(' '.join(map(str, command)) + '\n' + result.stdout + result.stderr)
    return result.stdout


def function(name):
    text = SOURCE.read_text(encoding='utf-8')
    match = re.search(r'^static [^\n]+\b' + name + r'\(', text, re.M)
    if not match:
        raise AssertionError('Missing real C function ' + name)
    opening = text.index('{', match.start())
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end] + '\n'


class UmlBindingTests(unittest.TestCase):
    def test_complete_binding_arm_syntax(self):
        self.assertTrue(ARM.is_file(), 'real ARM GCC required')
        with tempfile.TemporaryDirectory(prefix='uml-binding-arm-') as folder:
            temporary = Path(folder)
            gen = temporary / 'genhdr'
            gen.mkdir()
            for name in ('mpversion.h', 'root_pointers.h', 'moduledefs.h'):
                shutil.copyfile(GENHDR / name, gen / name)
            flags = ['-mcpu=arm1176jzf-s', '-marm', '-mfpu=vfp', '-mfloat-abi=hard',
                     '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                     '-DMODULE_ULAB_ENABLED=1', '-DULAB_CONFIG_FILE="ulab_config.h"',
                     '-DMICROPY_ROM_TEXT_COMPRESSION=0', '-I' + str(temporary),
                     '-I' + str(PORT), '-I' + str(BOARD), '-I' + str(MP), '-I' + str(ULAB)]
            preprocessed = checked([ARM, *flags, '-E', '-DNO_QSTR', SOURCE])
            qstrs = sorted(set(re.findall(r'MP_QSTR_([a-zA-Z0-9_]+)', preprocessed)))
            extra = temporary / 'binding-qstr.h'
            extra.write_text('\n'.join('Q(' + q + ')' for q in qstrs) + '\n', encoding='utf-8')
            generated = checked([sys.executable, '-B', MP / 'py/makeqstrdata.py',
                                 GENHDR / 'qstrdefs.preprocessed.h', extra])
            (gen / 'qstrdefs.generated.h').write_text(generated, encoding='utf-8')
            checked([ARM, *flags, '-fsyntax-only', SOURCE])

    def test_real_c_conversion_lifetime_and_exception_contracts(self):
        self.assertTrue(HOST.is_file(), 'host C compiler required')
        names = ['uml_status', 'uml_aligned_alloc', 'uml_release', 'uml_require_live', 'uml_dtype_size',
                 'uml_validate_tensor', 'uml_tensor', 'uml_load_model', 'uml_model_make_new', 'uml_quantize', 'uml_store',
                 'uml_array_input', 'uml_input', 'uml_output_value',
                 'uml_model_predict', 'uml_model_deinit']
        source = (HARNESS_PREFIX + '\n'.join(function(name) for name in names) +
                  function('uml_outputs').replace('uml_outputs(', 'uml_outputs_actual(', 1) + HARNESS_MAIN)
        with tempfile.TemporaryDirectory(prefix='uml-binding-host-') as folder:
            path = Path(folder)
            c = path / 'checks.c'
            c.write_text(source, encoding='utf-8')
            exe = path / 'checks.exe'
            checked([HOST, '-std=c11', '-Wall', '-Wextra', '-Werror',
                     '-Wno-unused-parameter', c, '-lm', '-o', exe])
            checked([exe])


HARNESS_PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <limits.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <setjmp.h>
#define ULAB_MAX_DIMS 4
#define NDARRAY_COMPLEX 'c'
#define NDARRAY_FLOAT 'f'
#define UML_BACKEND_OK 0
#define MP_ERROR_TEXT(x) x
#define MP_ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define MP_OBJ_TO_PTR(x) ((void *)(x))
#define MP_OBJ_FROM_PTR(x) ((mp_obj_t)(x))
#define MP_ARG_OBJ 1
#define MP_QSTR_callback 1
#define MP_QSTR_raw_output 6
#define MP_ARG_BOOL 16
#define UML_CODEC_MAX_DIMS 4
#define MP_ROM_NONE 0
#define MP_BUFFER_READ 1
#define UML_MODEL_MAX (32u*1024u*1024u)
#define UML_ARENA_DEFAULT (2u*1024u*1024u)
#define UML_ARENA_MAX (64u*1024u*1024u)
#define UML_TENSOR_COUNT_MAX 128u
#define MP_ARG_REQUIRED 2
#define MP_ARG_KW_ONLY 4
#define MP_ARG_INT 8
#define MP_QSTR_path 2
#define MP_QSTR_postprocess 3
#define MP_QSTR_arena_size 4
#define MP_QSTR_rb 5
#define MP_OBJ_NEW_QSTR(x) (x)
#define MP_SEEK_END 2
#define MP_SEEK_SET 0
#define m_new0(t,n) ((t *)calloc((n),sizeof(t)))
#define mp_obj_malloc_with_finaliser(t,ty) ((t *)calloc(1,sizeof(t)))
#define MP_OBJ_NULL 0
#define mp_const_none 0

typedef uintptr_t mp_obj_t;
typedef intptr_t mp_int_t;
typedef float mp_float_t;
typedef uintptr_t mp_uint_t;
typedef long mp_off_t;
typedef struct {int kind;} mp_obj_type_t;
typedef struct {const mp_obj_type_t *type;} mp_obj_base_t;
static const mp_obj_type_t mp_type_RuntimeError={1}, mp_type_list={2}, mp_type_tuple={3};
static const mp_obj_type_t ulab_ndarray_type={4}, mp_type_bytearray={5}, callback_type={6}, str_type={7};
static const mp_obj_type_t uml_model_type={8}, mp_type_OSError={9};
typedef struct {mp_obj_base_t base;size_t len;mp_obj_t *items;} mp_obj_tuple_t;
typedef mp_obj_tuple_t mp_obj_list_t;
typedef struct {mp_obj_base_t base;uint8_t dtype,itemsize,boolean,ndim;size_t len;
    size_t shape[4];int32_t strides[4];void *array,*origin;} ndarray_obj_t;
typedef struct {void *data;size_t bytes;unsigned ndim;int32_t shape[4];char dtype;
    float scale;int32_t zero_point;} uml_tensor_info;
typedef struct {mp_obj_base_t base;void *model_raw,*state_raw,*arena_raw;
    void *model_data,*state,*arena;size_t model_size,arena_size,inputs,outputs;
    mp_obj_t input_shape,input_scale,input_zero_point,input_dtype;
    mp_obj_t output_shape,output_scale,output_zero_point,output_dtype,postprocess;
    bool live,busy;} uml_model_obj_t;
typedef struct nlr_buf {jmp_buf jump;void *ret_val;struct nlr_buf *prev;} nlr_buf_t;
static nlr_buf_t *current_nlr;
#define nlr_push(p) (((p)->prev=current_nlr),current_nlr=(p),setjmp((p)->jump))
#define nlr_pop() (current_nlr=current_nlr->prev)
static _Noreturn void nlr_jump(void *value) {nlr_buf_t *n=current_nlr;assert(n);current_nlr=n->prev;n->ret_val=value;longjmp(n->jump,1);}
static _Noreturn void mp_raise_ValueError(const char *s) {nlr_jump((void *)s);}
static _Noreturn void mp_raise_TypeError(const char *s) {nlr_jump((void *)s);}
static _Noreturn void mp_raise_msg(const mp_obj_type_t *t,const char *s) {nlr_jump((void *)s);}
static _Noreturn void mp_raise_msg_varg(const mp_obj_type_t *t,const char *s,int status) {nlr_jump((void *)s);}
static _Noreturn void mp_raise_OSError(int error) {nlr_jump((void *)"OSError");}
typedef struct {int used;} mp_map_t;
static const mp_map_t mp_const_empty_map={0};
typedef union {mp_obj_t u_obj;mp_obj_t u_rom_obj;intptr_t u_int;bool u_bool;} mp_arg_val_t;
typedef struct {int qstr,flags;mp_arg_val_t defval;} mp_arg_t;
typedef struct {void *buf;size_t len;} mp_buffer_info_t;
static unsigned uml_prediction_depth;
static uml_tensor_info backend_info;
static int destroy_count,invoke_count,invoke_fail,callback_action;
static int file_mode,close_count,create_fail,metadata_fail;
static mp_obj_t constructor_source,constructor_postprocess;
static mp_int_t constructor_arena=UML_ARENA_DEFAULT;
static char file_bytes[]={1,2,3,4};
static size_t uml_backend_state_size(void) {return 64;}
static size_t uml_backend_state_align(void) {return 16;}
static int uml_backend_create(void *s,size_t n,const void *m,size_t z,void *a,size_t az) {assert(!((uintptr_t)s%16));assert(!((uintptr_t)m%16));assert(!((uintptr_t)a%16));assert(n==64&&z==4&&az>=1024);return create_fail;}
static size_t uml_backend_input_count(void *p) {return 1;}
static size_t uml_backend_output_count(void *p) {return 1;}
static void uml_metadata(uml_model_obj_t *self,int output) {if(metadata_fail)mp_raise_ValueError("metadata failed");}
static mp_obj_t mp_vfs_open(size_t n,const mp_obj_t *args,mp_map_t *kw) {assert(n==2&&args[1]==MP_QSTR_rb);return 77;}
static mp_off_t mp_stream_seek(mp_obj_t f,mp_off_t off,int whence,int *error) {assert(f==77);if(file_mode==1){*error=5;return -1;}return whence==MP_SEEK_END?4:0;}
static mp_uint_t mp_stream_read_exactly(mp_obj_t f,void *buf,size_t n,int *error) {assert(f==77&&n==4);if(file_mode==2){*error=5;return 0;}memcpy(buf,file_bytes,4);return file_mode==3?3:4;}
static mp_obj_t mp_stream_close(mp_obj_t f) {assert(f==77);++close_count;if(file_mode==4)mp_raise_ValueError("close failed");return 0;}
static void mp_arg_parse_all_kw_array(size_t n,size_t kw,const mp_obj_t *all,size_t count,const mp_arg_t *allowed,mp_arg_val_t *out) {assert(count==3);out[0].u_obj=constructor_source;out[1].u_obj=constructor_postprocess;out[2].u_int=constructor_arena;}
static bool mp_obj_is_str(mp_obj_t o) {return o&&((mp_obj_base_t *)o)->type==&str_type;}

static mp_obj_t callback_option,retained_scratch;
static uml_model_obj_t *active_model;
static mp_obj_t active_inputs;
static mp_obj_t uml_model_predict(size_t,const mp_obj_t *,mp_map_t *);
static mp_obj_t uml_model_deinit(mp_obj_t);
static int uml_backend_destroy(void *p) {++destroy_count;return 0;}
static int uml_backend_tensor_info(void *p,int out,size_t i,uml_tensor_info *info) {*info=backend_info;return 0;}
static int uml_backend_invoke(void *p) {++invoke_count;return invoke_fail;}
static bool mp_obj_is_type(mp_obj_t o,const mp_obj_type_t *t) {return o && ((mp_obj_base_t *)o)->type==t;}
static bool mp_obj_is_callable(mp_obj_t o) {return mp_obj_is_type(o,&callback_type);}
static void mp_arg_parse_all(size_t n,const mp_obj_t *a,mp_map_t *kw,size_t nallowed,const mp_arg_t *allowed,mp_arg_val_t *out) {assert(nallowed==2);out[0].u_obj=callback_option;out[1].u_bool=false;}
static void mp_obj_get_array(mp_obj_t o,size_t *len,mp_obj_t **items) {mp_obj_tuple_t *t=(void *)o;*len=t->len;*items=t->items;}
static mp_obj_t mp_obj_new_tuple(size_t n,const mp_obj_t *items) {mp_obj_tuple_t *t=calloc(1,sizeof(*t));t->base.type=&mp_type_tuple;t->len=n;t->items=calloc(n,sizeof(*items));if(n)memcpy(t->items,items,n*sizeof(*items));return (mp_obj_t)t;}
static mp_obj_t mp_obj_new_list(size_t n,const mp_obj_t *items) {mp_obj_tuple_t *t=(void *)mp_obj_new_tuple(0,NULL);t->base.type=&mp_type_list;t->len=n;t->items=calloc(n,sizeof(mp_obj_t));if(items)memcpy(t->items,items,n*sizeof(mp_obj_t));return (mp_obj_t)t;}
static ndarray_obj_t *ndarray_new_dense_ndarray(uint8_t ndim,size_t *shape,uint8_t dtype) {ndarray_obj_t *a=calloc(1,sizeof(*a));a->base.type=&ulab_ndarray_type;a->ndim=ndim;a->dtype=dtype;a->len=1;memcpy(a->shape,shape,sizeof(a->shape));for(unsigned d=4-ndim;d<4;++d)a->len*=shape[d];a->array=calloc(a->len,sizeof(float));return a;}
static mp_obj_t mp_obj_new_int_from_uint(size_t n) {return n;}
static mp_obj_t mp_obj_new_int(int n) {return (mp_obj_t)n;}
static mp_obj_t uml_shape(const uml_tensor_info *info) {return 44;}
static mp_obj_t uml_outputs(uml_model_obj_t *self,bool raw_output) {return 99;}
static int uml_codec_load_int32(const void *source,size_t bytes,int32_t *value) {assert(bytes==4);memcpy(value,source,4);return 0;}
static mp_obj_t uml_codec_pack(mp_obj_t value,unsigned ndim,const size_t *shape,char dtype) {assert(dtype=='i');return value;}
static mp_obj_t mp_obj_new_bytearray(size_t bytes,const void *source) {mp_obj_tuple_t *b=calloc(1,sizeof(*b));b->base.type=&mp_type_bytearray;b->len=bytes;b->items=malloc(bytes);memcpy(b->items,source,bytes);return (mp_obj_t)b;}
static float ndarray_get_float_value(void *p,uint8_t dtype) {assert(dtype=='f');float v;memcpy(&v,p,sizeof(v));return v;}
static void mp_get_buffer_raise(mp_obj_t o,mp_buffer_info_t *b,int mode) {mp_obj_tuple_t *t=(void *)o;b->buf=t->items;b->len=t->len;}
static mp_obj_t mp_call_function_n_kw(mp_obj_t fun,size_t n,size_t kw,const mp_obj_t *args) {
    if(fun==(mp_obj_t)&mp_type_bytearray) {mp_obj_tuple_t *b=calloc(1,sizeof(*b));b->base.type=&mp_type_bytearray;b->len=args[0];b->items=calloc(1,b->len);return (mp_obj_t)b;}
    assert(mp_obj_is_callable(fun));
    if(mp_obj_is_type(args[0],&mp_type_bytearray)) {
        retained_scratch=args[0];mp_obj_tuple_t *b=(void *)args[0];memset(b->items,0x2a,b->len);
        assert(args[1]==44 && args[2]=='b');
        assert((void *)b->items!=backend_info.data);
        if(callback_action==1) --b->len;
        if(callback_action==2) uml_model_deinit((mp_obj_t)active_model);
        if(callback_action==3) mp_raise_ValueError("callback failure");
        if(callback_action==4) {mp_obj_t a[]={(mp_obj_t)active_model,active_inputs};uml_model_predict(2,a,NULL);}
        if(callback_action==5) {mp_obj_tuple_t *t=(void *)active_inputs;t->len=0;t->items=NULL;}
    } else {
        assert(n==3 && args[0]==(mp_obj_t)active_model && args[1]==active_inputs && args[2]==99);
        if(callback_action==6) mp_raise_ValueError("postprocess failure");
        return 123;
    }
    return 0;
}
#define EXPECT_ERROR(statement) do {nlr_buf_t trap;if(nlr_push(&trap)==0){statement;assert(!"expected NLR exception");nlr_pop();}}while(0)
'''

HARNESS_MAIN = r'''
int main(void) {
    assert(uml_quantize(0,.5f,-3,-128,127)==-3);
    assert(uml_quantize(.25f,.5f,0,-128,127)==1);
    assert(uml_quantize(-.25f,.5f,0,-128,127)==-1);
    assert(uml_quantize(.25f,.5f,-3,-128,127)==-2);
    assert(uml_quantize(-.25f,.5f,-3,-128,127)==-4);
    assert(uml_quantize(INFINITY,1,0,-128,127)==127);
    assert(uml_quantize(-INFINITY,1,0,-128,127)==-128);
    EXPECT_ERROR((void)uml_quantize(NAN,1,0,-128,127));
    int8_t bytes[8]={0};
    uml_tensor_info info={bytes,4,2,{2,2},'b',.5f,-3};
    float values[]={1,2,3,4};
    ndarray_obj_t array={{&ulab_ndarray_type},'f',4,0,2,4,{0,0,2,2},{0,0,8,4},values,values};
    uml_array_input(&info,&array);
    assert(bytes[0]==-1 && bytes[1]==1 && bytes[2]==3 && bytes[3]==5);
    // A transpose and a reversed slice must follow byte strides, not linear data.
    array.strides[2]=4;array.strides[3]=8;
    uml_array_input(&info,&array);
    assert(bytes[0]==-1 && bytes[1]==3 && bytes[2]==1 && bytes[3]==5);
    array.array=values+3;array.strides[2]=-8;array.strides[3]=-4;
    uml_array_input(&info,&array);
    assert(bytes[0]==5 && bytes[1]==3 && bytes[2]==1 && bytes[3]==-1);
    array.shape[3]=3;EXPECT_ERROR(uml_array_input(&info,&array));array.shape[3]=2;
    array.dtype='c';EXPECT_ERROR(uml_array_input(&info,&array));array.dtype='f';
    info.bytes=3;EXPECT_ERROR((void)uml_validate_tensor(&info));info.bytes=4;
    info.scale=0;EXPECT_ERROR((void)uml_validate_tensor(&info));info.scale=.5f;
    assert(uml_output_value(&info,0)==4);
    uint16_t u16[1];info.dtype='H';info.data=u16;uml_store(u16,0,&info,INFINITY);assert(u16[0]==65535);
    int16_t i16[1];info.dtype='h';info.data=i16;uml_store(i16,0,&info,-INFINITY);assert(i16[0]==-32768);
    uint8_t u8[1];info.dtype='B';info.data=u8;uml_store(u8,0,&info,-INFINITY);assert(u8[0]==0);
    float f[1];info.dtype='f';info.data=f;uml_store(f,0,&info,1.25f);assert(f[0]==1.25f);

    backend_info=(uml_tensor_info){bytes,4,2,{2,2},'b',.5f,-3};
    uml_model_obj_t model={0};model.live=true;model.state=&model;model.inputs=1;
    active_model=&model;
    model.outputs=1;bytes[0]=-1;bytes[1]=1;bytes[2]=3;bytes[3]=5;
    mp_obj_list_t *actual_outputs=(void *)uml_outputs_actual(&model,false);
    ndarray_obj_t *actual_array=(void *)actual_outputs->items[0];
    assert(actual_array->array!=bytes&&actual_array->shape[2]==2&&actual_array->shape[3]==2);
    assert(((float *)actual_array->array)[0]==1 && ((float *)actual_array->array)[3]==4);
    memset(bytes,0,sizeof(bytes));assert(((float *)actual_array->array)[3]==4);
    // Int32 is raw numeric storage, never scale/zero_point quantized.
    int32_t exact[]={INT32_MIN,16777217,INT32_MAX,0};
    backend_info=(uml_tensor_info){exact,sizeof(exact),1,{4},'i',0,0};
    assert(uml_validate_tensor(&backend_info)==4&&uml_dtype_size('i')==4);
    assert(uml_output_value(&backend_info,0)==(float)INT32_MIN);
    mp_obj_list_t *raw_outputs=(void *)uml_outputs_actual(&model,true);
    mp_obj_tuple_t *raw_bytes=(void *)raw_outputs->items[0];
    assert(raw_bytes->len==sizeof(exact)&&raw_bytes->items!=(void *)exact);
    assert(!memcmp(raw_bytes->items,exact,sizeof(exact)));
    mp_obj_tuple_t input_bytes={{&mp_type_bytearray},sizeof(exact),(void *)exact};
    int32_t target[4]={0};backend_info.data=target;
    uml_input(&model,0,(mp_obj_t)&input_bytes);assert(!memcmp(target,exact,sizeof(exact)));
    backend_info=(uml_tensor_info){bytes,4,2,{2,2},'b',.5f,-3};
    mp_obj_base_t callback={&callback_type};
    mp_obj_t item=(mp_obj_t)&callback;
    mp_obj_list_t list={{&mp_type_list},1,&item};active_inputs=(mp_obj_t)&list;
    mp_obj_t args[]={(mp_obj_t)&model,(mp_obj_t)&list};
    assert(uml_model_predict(2,args,NULL)==99);
    assert(!model.busy && !uml_prediction_depth && invoke_count==1);
    assert(bytes[0]==42 && bytes[3]==42);
    mp_obj_t saved_scratch=retained_scratch;
    callback_action=1;EXPECT_ERROR((void)uml_model_predict(2,args,NULL));
    assert(!model.busy && !uml_prediction_depth);
    callback_action=2;EXPECT_ERROR((void)uml_model_predict(2,args,NULL));assert(model.live);
    callback_action=3;EXPECT_ERROR((void)uml_model_predict(2,args,NULL));
    callback_action=4;EXPECT_ERROR((void)uml_model_predict(2,args,NULL));
    callback_action=5;assert(uml_model_predict(2,args,NULL)==99);list.len=1;list.items=&item;
    callback_action=0;invoke_fail=-10;EXPECT_ERROR((void)uml_model_predict(2,args,NULL));invoke_fail=0;
    callback_option=(mp_obj_t)&callback;
    assert(uml_model_predict(2,args,NULL)==123);
    callback_action=6;EXPECT_ERROR((void)uml_model_predict(2,args,NULL));
    assert(!model.busy && !uml_prediction_depth);
    callback_action=0;callback_option=0;model.postprocess=(mp_obj_t)&callback;
    assert(uml_model_predict(2,args,NULL)==123);
    list.len=0;EXPECT_ERROR((void)uml_model_predict(2,args,NULL));list.len=1;
    uml_model_deinit((mp_obj_t)&model);uml_model_deinit((mp_obj_t)&model);
    assert(!model.live && !model.state && destroy_count==1);
    // The escaped callback bytearray remains valid independently of the model.
    mp_obj_tuple_t *retained=(void *)saved_scratch;assert(((uint8_t *)retained->items)[0]==42);
    EXPECT_ERROR((void)uml_model_predict(2,args,NULL));
    assert(!current_nlr);
    // Constructor owns copied/aligned bytes and closes real stream paths.
    mp_obj_base_t path={&str_type};constructor_source=(mp_obj_t)&path;
    int before=destroy_count;
    uml_model_obj_t *created=(void *)uml_model_make_new(&uml_model_type,1,0,NULL);
    assert(created->live&&created->model_size==4&&close_count==1);
    assert(!memcmp(created->model_data,file_bytes,4));
    uml_model_deinit((mp_obj_t)created);assert(destroy_count==before+1);
    for(file_mode=1;file_mode<=4;++file_mode) {
        before=close_count;EXPECT_ERROR((void)uml_model_make_new(&uml_model_type,1,0,NULL));
        assert(close_count==before+1);
    }
    file_mode=0;create_fail=-7;before=destroy_count;
    EXPECT_ERROR((void)uml_model_make_new(&uml_model_type,1,0,NULL));
    assert(destroy_count==before+1);create_fail=0;metadata_fail=1;before=destroy_count;
    EXPECT_ERROR((void)uml_model_make_new(&uml_model_type,1,0,NULL));
    assert(destroy_count==before+1);metadata_fail=0;
    mp_obj_tuple_t raw={{&mp_type_bytearray},4,(void *)file_bytes};constructor_source=(mp_obj_t)&raw;
    created=(void *)uml_model_make_new(&uml_model_type,1,0,NULL);
    assert(created->model_data!=file_bytes&&!memcmp(created->model_data,file_bytes,4));
    uml_model_deinit((mp_obj_t)created);
    constructor_arena=1;EXPECT_ERROR((void)uml_model_make_new(&uml_model_type,1,0,NULL));
    constructor_arena=UML_ARENA_DEFAULT;uml_prediction_depth=1;
    EXPECT_ERROR((void)uml_model_make_new(&uml_model_type,1,0,NULL));uml_prediction_depth=0;
    assert(!current_nlr);
    return 0;
}
'''

if __name__ == '__main__':
    unittest.main()
