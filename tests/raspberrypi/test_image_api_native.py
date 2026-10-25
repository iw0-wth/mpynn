# SPDX-License-Identifier: MIT
"""Strict actual-C coverage of the owned file-image API additions."""
import importlib.util
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
MPYNN = ROOT / 'mpynn'
MODULE = MPYNN / 'modules/image_file'
EXISTING = MPYNN / 'tests/raspberrypi'


def load(name):
    spec = importlib.util.spec_from_file_location(name, EXISTING / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = load('test_image_file_native')
binding = load('test_image_file_binding_host')


class ImageApiTests(unittest.TestCase):
    def test_complete_arm_sources(self):
        # Uses actual MP/ulab/board headers and freshly generated image qstrs.
        native.ImageFileNativeTests('test_complete_sources_actual_arm_headers').test_complete_sources_actual_arm_headers()

    def test_actual_core_and_bindings(self):
        names = ['if_status', 'if_checked_size', 'if_self', 'if_pixels', 'if_new',
                 'if_load', 'if_make_new', 'if_width', 'if_height', 'if_format',
                 'if_size_method', 'if_coordinates', 'if_get_pixel', 'if_set_pixel',
                 'if_get_roi', 'if_scaled', 'if_copy', 'if_resize', 'if_grayscale',
                 'if_overlaps', 'if_draw_image', 'if_to_ndarray', 'if_int',
                 'if_geometry', 'if_color', 'if_to_bytes', 'if_bytearray', 'if_clear',
                 'if_draw_shape', 'if_rectangle', 'if_line', 'if_circle', 'if_string',
                 'if_filter_method', 'if_mean', 'if_median', 'if_unavailable',
                 'if_next', 'if_getiter']
        prefix = binding.PREFIX
        text = (MODULE / 'modimage.c').read_text()
        existing = set(re.findall(r'MP_QSTR_(\w+)', prefix))
        extra = sorted(set(re.findall(r'MP_QSTR_(\w+)', text)) - existing)
        prefix = prefix.replace('MP_QSTR_hint,MP_QSTR_copy', 'MP_QSTR_hint,' + ','.join('MP_QSTR_' + x for x in extra) + ',MP_QSTR_copy')
        prefix += STUBS
        source = prefix + '\n'.join(binding.extract(n) for n in names)
        source += binding.MAIN.replace('    return 0;', CHECKS + '\n    return 0;')
        with tempfile.TemporaryDirectory(prefix='image-api-') as folder:
            path = Path(folder)
            c = path / 'test.c'
            c.write_text(source)
            exe = path / 'test.exe'
            env = os.environ.copy()
            env['PATH'] = str(binding.HOST.parent) + os.pathsep + env.get('PATH', '')
            for cmd in ([binding.HOST, '-std=c11', '-Wall', '-Wextra', '-Werror',
                         '-Wno-unused-parameter', '-I' + str(MODULE), c,
                         MODULE / 'image_core.c', '-lm', '-o', exe], [exe]):
                p = subprocess.run(list(map(str, cmd)), capture_output=True, text=True,
                                   timeout=90, env=env)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


STUBS = r'''
typedef mp_obj_t (*mp_fun_1_t)(mp_obj_t);
typedef struct {mp_obj_base_t base;mp_fun_1_t iternext;mp_obj_t image;unsigned row;} if_iter;
typedef struct {uintptr_t slots[4];} mp_obj_iter_buf_t;
static const mp_obj_type_t mp_type_polymorph_iter={9};
#define MP_OBJ_STOP_ITERATION ((mp_obj_t)2)
static mp_obj_t mp_obj_new_list(size_t n,const mp_obj_t *items) {return mp_obj_new_tuple(n,items);}
static mp_obj_t mp_obj_list_append(mp_obj_t row,mp_obj_t value) {tuple_obj *t=(void *)row;t->items=realloc(t->items,(t->len+1)*sizeof(value));t->items[t->len++]=value;return 0;}
static mp_obj_t mp_obj_new_bytes(const uint8_t *data,size_t n) {buffer_obj *b=new_object(sizeof(*b),&buffer_type);b->data=malloc(n);memcpy(b->data,data,n);b->len=n;return (mp_obj_t)b;}
static mp_obj_t mp_obj_new_bytearray(size_t n,void *data) {mp_obj_t b=mp_obj_new_bytes(data,n);((buffer_obj *)b)->writable=true;return b;}
'''

CHECKS = r'''
    reset_args();
    if_obj *canvas=if_new(16,16,IF_GRAYSCALE);
    mp_obj_t cv=(mp_obj_t)canvas;
    mp_obj_t rectitems[]={mp_obj_new_int(-2),mp_obj_new_int(-2),mp_obj_new_int(6),mp_obj_new_int(6)};
    mp_obj_t shape[]={cv,mp_obj_new_tuple(4,rectitems)};
    set_int(MP_QSTR_fill,1);set_obj(MP_QSTR_color,mp_obj_new_int(90));
    assert(if_rectangle(2,shape,NULL)==cv);
    assert(canvas->owned[0]==90&&canvas->owned[3*16+3]==90&&canvas->owned[4*16+4]==0);
    reset_args();if_clear(cv);
    rectitems[0]=mp_obj_new_int(INT32_MIN);rectitems[1]=mp_obj_new_int(8);
    rectitems[2]=mp_obj_new_int(INT32_MAX);rectitems[3]=mp_obj_new_int(8);
    shape[1]=mp_obj_new_tuple(4,rectitems);if_line(2,shape,NULL);
    for(unsigned x=0;x<16;++x)assert(canvas->owned[8*16+x]==255);
    if_clear(cv);
    mp_obj_t circleitems[]={mp_obj_new_int(8),mp_obj_new_int(8),mp_obj_new_int(3)};
    shape[1]=mp_obj_new_tuple(3,circleitems);if_circle(2,shape,NULL);
    assert(canvas->owned[8*16+11]==255&&canvas->owned[8*16+8]==0);
    set_int(MP_QSTR_fill,1);if_circle(2,shape,NULL);assert(canvas->owned[8*16+8]==255);
    reset_args();if_clear(cv);
    mp_obj_t xyitems[]={mp_obj_new_int(0),mp_obj_new_int(0)};
    buffer_obj label={{&str_type},1,(void *)"A",false};
    mp_obj_t textargs[]={cv,mp_obj_new_tuple(2,xyitems),(mp_obj_t)&label};
    if_string(3,textargs,NULL);
    unsigned white=0;for(unsigned i=0;i<256;++i)white+=canvas->owned[i]==255;
    assert(white>5&&white<60);
    set_int(MP_QSTR_string_rotation,90);EXPECT_ERROR((void)if_string(3,textargs,NULL));
    reset_args();label.data=(void *)"\xC3\xA9";label.len=2;
    EXPECT_ERROR((void)if_string(3,textargs,NULL));
    buffer_obj *bc=(void *)if_to_bytes(cv),*ba=(void *)if_bytearray(cv);
    assert(bc->len==256&&bc->data!=canvas->owned&&ba->data!=canvas->owned&&ba->writable);
    ((uint8_t *)ba->data)[0]=42;assert(canvas->owned[0]!=42);
    mp_obj_iter_buf_t itbuf;mp_obj_t it=if_getiter(cv,&itbuf);
    for(unsigned y=0;y<16;++y) {tuple_obj *row=(void *)if_next(it);assert(row->len==16);}
    assert(if_next(it)==MP_OBJ_STOP_ITERATION);
    if_obj *filtered=if_new(3,3,IF_GRAYSCALE);filtered->owned[4]=255;
    mp_obj_t filterargs[]={(mp_obj_t)filtered,mp_obj_new_int(1)};
    assert(if_median(2,filterargs,NULL)==(mp_obj_t)filtered&&filtered->owned[4]==0);
    filtered->owned[4]=255;if_mean(2,filterargs,NULL);
    for(unsigned i=0;i<9;++i)assert(filtered->owned[i]==28);
    set_int(MP_QSTR_threshold,1);EXPECT_ERROR((void)if_mean(2,filterargs,NULL));
    reset_args();filterargs[1]=mp_obj_new_int(8);EXPECT_ERROR((void)if_median(2,filterargs,NULL));
    EXPECT_ERROR((void)if_unavailable(1,filterargs,NULL));
    mp_obj_t pairitems[]={mp_obj_new_int(0),mp_obj_new_int(0)};
    mp_obj_t pairset[]={cv,mp_obj_new_tuple(2,pairitems),mp_obj_new_int(71)};
    if_set_pixel(3,pairset);assert(canvas->owned[0]==71);
    // Packed RGB565 writes and clipped geometry preserve guard bytes.
    uint8_t guards[20];memset(guards,0xA5,sizeof(guards));
    if_image guarded={3,3,IF_RGB565,guards+1};
    assert(if_draw_rectangle(&guarded,-1,-1,4,4,0xF800,1,1)==IF_OK);
    assert(guards[0]==0xA5&&guards[19]==0xA5&&guards[1]==0&&guards[2]==0xF8);
    assert(if_draw_circle(&guarded,INT32_MAX,INT32_MIN,2,0xFFFF,1,1)==IF_OK);
    assert(if_draw_rectangle(&guarded,0,0,-1,1,0,1,1)==IF_BOUNDS);
    assert(if_draw_circle(&guarded,0,0,8193,0,1,1)==IF_BOUNDS);
    assert(if_draw_line(&guarded,INT32_MIN,INT32_MIN,INT32_MAX,INT32_MAX,0xFFFF,2)==IF_OK);
    assert(guards[0]==0xA5&&guards[19]==0xA5);
    assert(!current);
'''

if __name__ == '__main__':
    unittest.main()
