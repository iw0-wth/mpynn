# SPDX-License-Identifier: MIT
"""Host binding contracts for real machine_i2c.c with narrow MP doubles.

No VM/GC/ARM/electrical bus. Strict tagged ints, keyword and required argument
parsing, buffer flags, raised errno and bridge call expectations exercise wrapper
validation/cleanup and routing; real allocator/finaliser behavior needs ARM/board.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'ports/raspberrypi'
RUNTIME = r'''
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
typedef uintptr_t mp_obj_t;
typedef intptr_t mp_int_t;
typedef uintptr_t mp_uint_t;
typedef struct { int unused; } mp_obj_type_t;
typedef struct { const mp_obj_type_t *type; } mp_obj_base_t;
typedef struct { void *buf; size_t len; } mp_buffer_info_t;
typedef struct { size_t used; const mp_obj_t *table; } mp_map_t;
typedef union { mp_int_t u_int; mp_obj_t u_obj; bool u_bool; } mp_arg_val_t;
typedef struct { unsigned qstr, flags; mp_arg_val_t defval; } mp_arg_t;
typedef struct { uintptr_t key,value; } mp_rom_map_elem_t;
typedef struct { char *buf; size_t len; } vstr_t;
#define mp_const_none ((mp_obj_t)0)
#define MP_OBJ_NULL ((mp_obj_t)0)
#define MP_OBJ_FROM_PTR(p) ((mp_obj_t)(uintptr_t)(p))
#define MP_OBJ_TO_PTR(p) ((void *)(uintptr_t)(p))
#define MP_OBJ_NEW_SMALL_INT(n) ((mp_obj_t)((mp_uint_t)(mp_int_t)(n)*2u+1u))
#define MP_ROM_QSTR(q) ((uintptr_t)(q))
#define MP_ROM_PTR(p) ((uintptr_t)(p))
#define MP_ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define MP_ERROR_TEXT(t) (t)
#define MP_ARG_INT 1
#define MP_ARG_OBJ 2
#define MP_ARG_KW_ONLY 4
#define MP_ARG_REQUIRED 8
#define MP_BUFFER_READ 1
#define MP_BUFFER_WRITE 2
#define MP_TYPE_FLAG_NONE 0
QSTR_ENUM
#define MP_DEFINE_CONST_FUN_OBJ_KW(name, fn, f) const void *name=(void *)&f
#define MP_DEFINE_CONST_FUN_OBJ_1(name, f) const void *name=(void *)&f
#define MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(name, min, max, f) const void *name=(void *)&f
#define MP_DEFINE_CONST_DICT(name, table) const void *const name=&table
#define MP_DEFINE_CONST_OBJ_TYPE(name, qstr, flags, ...) const mp_obj_type_t name={0}
#define mp_obj_malloc_with_finaliser(t, typ) ((t *)host_finaliser_alloc(sizeof(t),typ))
void *host_finaliser_alloc(size_t n, const mp_obj_type_t *type);
_Noreturn void mp_raise_ValueError(const char *text);
_Noreturn void mp_raise_TypeError(const char *text);
_Noreturn void mp_raise_NotImplementedError(const char *text);
_Noreturn void mp_raise_OSError(int err);
mp_int_t mp_obj_get_int(mp_obj_t obj);
bool mp_obj_is_true(mp_obj_t obj);
void mp_arg_check_num(size_t n, size_t kw, size_t min, size_t max, bool allow_kw);
void mp_arg_parse_all(size_t n,const mp_obj_t *pos,mp_map_t *kw,size_t count,const mp_arg_t *allowed,mp_arg_val_t *out);
void mp_map_init_fixed_table(mp_map_t *map,size_t n,const mp_obj_t *table);
void mp_get_buffer_raise(mp_obj_t obj,mp_buffer_info_t *buffer,int flags);
void vstr_init_len(vstr_t *v,size_t len);
void vstr_clear(vstr_t *v);
mp_obj_t mp_obj_new_bytes_from_vstr(vstr_t *v);
mp_obj_t mp_obj_new_list(size_t n,const mp_obj_t *items);
void mp_obj_list_append(mp_obj_t list,mp_obj_t item);
'''
HARNESS = r'''
#include "machine_i2c.c"
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"%d: %s\n",__LINE__,#c); exit(1); } } while(0)
static jmp_buf failure;
static int error_kind,error_errno,irq=1,bridge_result;
static unsigned calls,allocations,vallocs,vfrees,deferred;
static int expected_op;
static const void *expected_owner;
static unsigned expected_addr=0x50,expected_freq=400000,expected_len=4,expected_prefix_len;
static unsigned char expected_prefix[2];
static int expected_buffer_flags;
static unsigned char data[8]={1,2,3,4,5,6,7,8},copied[16];
static size_t copied_len,list_count;
static unsigned listed[112];
static mp_buffer_info_t buffer={data,4};
#define INT(n) MP_OBJ_NEW_SMALL_INT(n)
#define EXPECT_ERROR(k,e,expr) do { unsigned before=calls; error_kind=0; error_errno=0; if(setjmp(failure)==0) { (void)(expr); CHECK(false); } CHECK(error_kind==(k) && error_errno==(e)); CHECK(calls==before); } while(0)
_Noreturn void mp_raise_ValueError(const char *t) { CHECK(t); error_kind=1; longjmp(failure,1); }
_Noreturn void mp_raise_TypeError(const char *t) { CHECK(t); error_kind=2; longjmp(failure,1); }
_Noreturn void mp_raise_NotImplementedError(const char *t) { CHECK(t); error_kind=3; longjmp(failure,1); }
_Noreturn void mp_raise_OSError(int e) { error_kind=4; error_errno=e; longjmp(failure,1); }
mp_int_t mp_obj_get_int(mp_obj_t o) { if(!(o&1)) mp_raise_TypeError("integer"); return (mp_int_t)o >> 1; }
bool mp_obj_is_true(mp_obj_t o) { return mp_obj_get_int(o)!=0; }
int mpynn_irq_is_enabled(void) { return irq; }
void *host_finaliser_alloc(size_t n,const mp_obj_type_t *t) {
    ++allocations; mp_obj_base_t *o=calloc(1,n); CHECK(o); o->type=t; return o;
}
void mp_arg_check_num(size_t n,size_t kw,size_t min,size_t max,bool allow_kw) {
    if(n<min || n>max || (kw && !allow_kw)) mp_raise_TypeError("arg count");
}
void mp_map_init_fixed_table(mp_map_t *m,size_t n,const mp_obj_t *t) { m->used=n; m->table=t; }
void mp_arg_parse_all(size_t n,const mp_obj_t *pos,mp_map_t *kw,size_t count,const mp_arg_t *allowed,mp_arg_val_t *out) {
    bool seen[16]={0}; CHECK(count<=16);
    for(size_t i=0;i<count;++i) out[i]=allowed[i].defval;
    for(size_t i=0;i<n;++i) {
        if(i>=count || (allowed[i].flags&MP_ARG_KW_ONLY)) mp_raise_TypeError("position");
        out[i].u_obj=pos[i]; seen[i]=true;
    }
    for(size_t k=0;k<kw->used;++k) {
        unsigned name=(unsigned)kw->table[k*2]; size_t i;
        for(i=0;i<count && name!=allowed[i].qstr;++i) {}
        if(i==count || seen[i]) mp_raise_TypeError("keyword");
        out[i].u_obj=kw->table[k*2+1]; seen[i]=true;
    }
    for(size_t i=0;i<count;++i) {
        if(!seen[i] && (allowed[i].flags&MP_ARG_REQUIRED)) mp_raise_TypeError("required");
        if(seen[i] && (allowed[i].flags&MP_ARG_INT)) out[i].u_int=mp_obj_get_int(out[i].u_obj);
    }
}
void mp_get_buffer_raise(mp_obj_t o,mp_buffer_info_t *b,int flags) {
    CHECK(o==MP_OBJ_FROM_PTR(&buffer) && flags==expected_buffer_flags); *b=buffer;
}
void vstr_init_len(vstr_t *v,size_t n) { ++vallocs; v->len=n; v->buf=calloc(1,n?n:1); CHECK(v->buf); }
void vstr_clear(vstr_t *v) { CHECK(v->buf); ++vfrees; free(v->buf); v->buf=NULL; }
mp_obj_t mp_obj_new_bytes_from_vstr(vstr_t *v) {
    copied_len=v->len; CHECK(copied_len<=sizeof(copied)); memcpy(copied,v->buf,v->len); vstr_clear(v); return 0x100;
}
mp_obj_t mp_obj_new_list(size_t n,const mp_obj_t *items) { CHECK(n==0 && !items); list_count=0; return 0x200; }
void mp_obj_list_append(mp_obj_t list,mp_obj_t item) { CHECK(list==0x200 && list_count<112); listed[list_count++]=mp_obj_get_int(item); }
int mpynn_i2c_init(const void *owner,unsigned freq,unsigned timeout) {
    CHECK(expected_op==0 && owner && freq==expected_freq && timeout==100000);
    expected_owner=owner; ++calls; return bridge_result;
}
int mpynn_i2c_deinit(const void *owner,int defer) {
    CHECK(owner==expected_owner); ++calls; deferred=defer; return bridge_result;
}
int mpynn_i2c_deinit_all(void) { CHECK(false); return 0; }
static int transfer(int op,const void *owner,unsigned addr,void *buf,size_t len) {
    CHECK(op==expected_op && owner==expected_owner && addr==expected_addr && len==expected_len); ++calls;
    if(op==1 || op==3) { if(len) memset(buf,0xab,len); }
    if(op==2 && expected_prefix_len) {
        CHECK(!memcmp(buf,expected_prefix,expected_prefix_len));
        CHECK(!memcmp((char *)buf+expected_prefix_len,data,len-expected_prefix_len));
    }
    return bridge_result;
}
int mpynn_i2c_read(const void *owner,unsigned addr,void *buf,size_t len) { return transfer(1,owner,addr,buf,len); }
int mpynn_i2c_write(const void *owner,unsigned addr,const void *buf,size_t len) {
    if(expected_op==4) { CHECK(owner==expected_owner && addr>=8 && addr<120 && !buf && !len); ++calls;
        if(addr==8 || addr==119) return 0;
        return addr==10 && bridge_result ? bridge_result : MPYNN_I2C_NACK;
    }
    return transfer(2,owner,addr,(void *)buf,len);
}
int mpynn_i2c_write_read(const void *owner,unsigned addr,const void *prefix,size_t plen,void *buf,size_t len) {
    CHECK(plen==expected_prefix_len && !memcmp(prefix,expected_prefix,plen));
    return transfer(3,owner,addr,buf,len);
}
int main(void) {
    mp_obj_t ctor[]={INT(1)}, extra[]={INT(1),INT(100000)}, bad[]={INT(0)};
    mp_map_t empty={0,NULL};
    EXPECT_ERROR(1,0,i2c_make_new(&machine_i2c_type,1,0,bad));
    irq=0; EXPECT_ERROR(4,MP_EBUSY,i2c_make_new(&machine_i2c_type,1,0,ctor)); irq=1;
    mp_obj_t self=i2c_make_new(&machine_i2c_type,1,0,ctor);
    CHECK(allocations==1 && ((machine_i2c_obj_t *)MP_OBJ_TO_PTR(self))->freq==400000);
    expected_op=0; expected_freq=100000;
    // Constructor optional positional frequency is explicitly supported.
    mp_obj_t other=i2c_make_new(&machine_i2c_type,2,0,extra); free(MP_OBJ_TO_PTR(other));
    expected_owner=MP_OBJ_TO_PTR(self);
    mp_obj_t args[]={self,INT(0x50),INT(4),INT(0)};
    expected_op=1; expected_len=4; bridge_result=4;
    CHECK(i2c_readfrom(3,args)==0x100 && copied_len==4 && copied[0]==0xab);
    EXPECT_ERROR(3,0,i2c_readfrom(4,args));
    args[1]=INT(0x10050); EXPECT_ERROR(1,0,i2c_readfrom(3,args));
    args[1]=INT(-1); EXPECT_ERROR(1,0,i2c_readfrom(3,args));
    args[1]=INT(0x50); args[2]=INT(-1); EXPECT_ERROR(1,0,i2c_readfrom(3,args));
    args[2]=INT(65536); EXPECT_ERROR(1,0,i2c_readfrom(3,args));
    args[2]=INT(4); irq=0; EXPECT_ERROR(4,MP_EBUSY,i2c_readfrom(3,args)); irq=1;
    unsigned before=calls,freed=vfrees; bridge_result=MPYNN_I2C_TIMEOUT;
    error_kind=0; if(setjmp(failure)==0) { i2c_readfrom(3,args); CHECK(false); }
    CHECK(error_kind==4 && error_errno==MP_ETIMEDOUT && calls==before+1 && vfrees==freed+1);
    before=calls; bridge_result=MPYNN_I2C_NACK;
    if(setjmp(failure)==0) { i2c_readfrom(3,args); CHECK(false); }
    CHECK(error_errno==MP_ENODEV && calls==before+1);
    args[2]=MP_OBJ_FROM_PTR(&buffer); expected_buffer_flags=MP_BUFFER_READ;
    expected_op=2; bridge_result=4;
    CHECK(mp_obj_get_int(i2c_writeto(3,args))==4);
    buffer.len=65536; EXPECT_ERROR(1,0,i2c_writeto(3,args)); buffer.len=4;
    expected_buffer_flags=MP_BUFFER_WRITE; expected_op=1;
    CHECK(i2c_readfrom_into(3,args)==mp_const_none && data[0]==0xab);
    expected_op=4; bridge_result=0;
    CHECK(i2c_scan(self)==0x200 && list_count==2 && listed[0]==8 && listed[1]==119);
    bridge_result=MPYNN_I2C_TIMEOUT; before=calls;
    if(setjmp(failure)==0) { i2c_scan(self); CHECK(false); }
    CHECK(error_errno==MP_ETIMEDOUT && calls==before+3);
    mp_obj_t mem[]={self,INT(0x50),INT(0x1234),INT(4)};
    mp_obj_t kw[]={MP_QSTR_addrsize,INT(16)}; mp_map_t kwargs={1,kw};
    expected_prefix[0]=0x12; expected_prefix[1]=0x34; expected_prefix_len=2;
    expected_op=3; bridge_result=4; expected_len=4;
    CHECK(i2c_readfrom_mem(4,mem,&kwargs)==0x100 && copied_len==4 && copied[3]==0xab);
    kw[1]=INT(24); EXPECT_ERROR(3,0,i2c_readfrom_mem(4,mem,&kwargs));
    kw[1]=INT(16); mem[2]=INT(65536); EXPECT_ERROR(1,0,i2c_readfrom_mem(4,mem,&kwargs));
    mem[2]=INT(-1); EXPECT_ERROR(1,0,i2c_readfrom_mem(4,mem,&kwargs));
    mem[2]=INT(0x1234); mem[3]=MP_OBJ_FROM_PTR(&buffer);
    expected_op=2; expected_buffer_flags=MP_BUFFER_READ; expected_len=6; bridge_result=6;
    CHECK(i2c_writeto_mem(4,mem,&kwargs)==mp_const_none);
    buffer.len=65534; EXPECT_ERROR(1,0,i2c_writeto_mem(4,mem,&kwargs)); buffer.len=4;
    expected_op=3; expected_len=4; expected_buffer_flags=MP_BUFFER_WRITE; bridge_result=4;
    CHECK(i2c_readfrom_mem_into(4,mem,&kwargs)==mp_const_none);
    EXPECT_ERROR(2,0,i2c_readfrom_mem(1,mem,&empty));
    mp_obj_t initargs[]={self,INT(123)};
    EXPECT_ERROR(1,0,i2c_init(2,initargs,&empty));
    mp_obj_t timeoutkw[]={MP_QSTR_timeout,INT(5000)}; mp_map_t timeoutmap={1,timeoutkw};
    EXPECT_ERROR(3,0,i2c_init(1,&self,&timeoutmap));
    mp_obj_t unknownkw[]={MP_QSTR_addrsize,INT(8)}; mp_map_t unknownmap={1,unknownkw};
    EXPECT_ERROR(2,0,i2c_init(1,&self,&unknownmap));
    EXPECT_ERROR(3,0,i2c_unsupported(1,&self));
    bridge_result=0; irq=0;
    EXPECT_ERROR(4,MP_EBUSY,i2c_deinit(self));
    CHECK(i2c_finalise(self)==mp_const_none && deferred==1);
    irq=1; CHECK(i2c_deinit(self)==mp_const_none && deferred==0);
    CHECK(vallocs==vfrees);
    free(MP_OBJ_TO_PTR(self));
    puts("I2C binding validation/errors/finaliser contracts passed");
}
'''

class I2CBindingHost(unittest.TestCase):
    def test_binding_contracts(self):
        compiler=shutil.which('gcc') or 'E:/msys64/ucrt64/bin/gcc.exe'
        if not Path(compiler).exists():
            self.skipTest('host gcc unavailable')
        source=(PORT/'machine_i2c.c').read_text(encoding='utf-8')
        qstrs=sorted(set(re.findall(r'MP_QSTR_[a-zA-Z0-9_]+',source)))
        runtime=RUNTIME.replace('QSTR_ENUM','enum { '+','.join(qstrs)+' };')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'py').mkdir()
            (root/'py/runtime.h').write_text(runtime,encoding='utf-8')
            (root/'py/obj.h').write_text('#include "runtime.h"\n',encoding='utf-8')
            (root/'py/mphal.h').write_text('int mpynn_irq_is_enabled(void);\n',encoding='utf-8')
            (root/'py/mperrno.h').write_text('#define MP_EINVAL 22\n#define MP_EBUSY 16\n#define MP_ENODEV 19\n#define MP_ETIMEDOUT 110\n#define MP_EIO 5\n',encoding='utf-8')
            harness=root/'test.c'; harness.write_text(HARNESS,encoding='utf-8')
            binary=root/('test.exe' if os.name=='nt' else 'test')
            env=os.environ.copy(); env['PATH']=str(Path(compiler).parent)+os.pathsep+env.get('PATH','')
            result=subprocess.run([compiler,'-std=c11','-Wall','-Wextra','-Werror',
                '-Wno-unused-parameter','-Wno-unused-function','-Wno-unused-const-variable',
                '-I'+str(root),'-iquote',str(PORT),str(harness),'-o',str(binary)],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('contracts passed',result.stdout)

if __name__=='__main__':
    unittest.main()
