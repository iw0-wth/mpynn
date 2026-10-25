"""Execute the actual C packer and the packed shader's address contract."""
from pathlib import Path
import os
import tempfile

from test_vc4_runtime_host import _compiler_from_env, _run
import pytest

PORT = Path(__file__).resolve().parents[2] / 'ports' / 'raspberrypi'
HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "vc4_weights_pack.h"

static void check(uint32_t m, uint32_t k, uint32_t workers) {
    size_t count = (size_t)m*k;
    float *src = malloc(count*sizeof(float));
    float *saved = malloc(count*sizeof(float));
    float *storage = malloc((count+2)*sizeof(float));
    assert(src && saved && storage);
    float *packed=storage+1;
    storage[0]=12345.0f; storage[count+1]=-12345.0f;
    for(size_t i=0;i<count;++i) src[i]=(float)((int)(i%251)-125)*0.0625f;
    memcpy(saved,src,count*sizeof(float));
    assert(vc4_pack_weights_fp32(packed,src,m,k)==VC4_STATUS_OK);
    assert(memcmp(src,saved,count*sizeof(float))==0);
    assert(storage[0]==12345.0f && storage[count+1]==-12345.0f);
    unsigned char *visited=calloc(count,1);
    assert(visited);
    for(uint32_t q=0;q<workers;++q) {
        uint32_t first=q*16;
        if(first>=m) break;
        uint32_t groups=workers*16;
        uint32_t tiles=(m-first+groups-1)/groups;
        for(uint32_t tile=0;tile<tiles;++tile) {
            uint32_t row=first+tile*groups;
            for(uint32_t lane=0;lane<16;++lane) {
                float reference=0, actual=0;
                for(uint32_t col=0;col<k;++col) {
                    size_t index=(size_t)first*k + (size_t)tile*groups*k + (size_t)col*16 + lane;
                    assert(index<count);
                    assert(memcmp(packed+index,src+(size_t)(row+lane)*k+col,sizeof(float))==0);
                    ++visited[index];
                    float x=(float)((int)(col%17)-8)*0.125f;
                    reference+=src[(size_t)(row+lane)*k+col]*x;
                    actual+=packed[index]*x;
                }
                assert(reference==actual);
            }
        }
    }
    for(size_t i=0;i<count;++i) assert(visited[i]==1);
    free(visited);free(src);free(saved);free(storage);
}
int main(void) {
    float src[32], dst[32];
    for(uint32_t i=0;i<32;++i) {
        uint32_t bits=0x7fc00000u+i;
        if(i==0) bits=0x80000000u;
        memcpy(src+i,&bits,4);
    }
    assert(vc4_pack_weights_fp32(dst,src,16,2)==0);
    for(uint32_t r=0;r<16;++r) for(uint32_t k=0;k<2;++k)
        assert(memcmp(dst+k*16+r,src+r*2+k,4)==0);
    assert(vc4_pack_weights_fp32(src,src,16,2)==VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_pack_weights_fp32(src+1,src,16,1)==VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_pack_weights_fp32(dst,src,15,2)==VC4_STATUS_INVALID_SHAPE);
    assert(vc4_pack_weights_fp32(dst,src,16,0)==VC4_STATUS_INVALID_SHAPE);
    assert(vc4_pack_weights_fp32(dst,src,16,UINT32_MAX)==VC4_STATUS_INVALID_SHAPE);
    assert(vc4_pack_weights_fp32(0,src,16,2)==VC4_STATUS_INVALID_ARGUMENT);
    for(uint32_t w=1;w<=12;++w) {
        check(16,1,w);check(32,7,w);check(208,3,w);check(1024,17,w);
    }
    check(1024,2048,12);
    return 0;
}
'''


def test_real_c_packing_and_shader_address_contract():
    compiler = _compiler_from_env('MPYNN_HOST_GCC', ('gcc', 'E:/msys64/ucrt64/bin/gcc.exe'))
    if compiler is None:
        pytest.skip('host C compiler missing')
    with tempfile.TemporaryDirectory(prefix='vc4-packed-') as folder:
        folder = Path(folder)
        source = folder / 'test.c'
        source.write_text(HARNESS, encoding='utf-8')
        exe = folder / ('test.exe' if os.name == 'nt' else 'test')
        _run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wconversion',
              '-I'+str(PORT), str(source), str(PORT/'vc4_weights_pack.c'), '-o', exe])
        _run([exe])
