// SPDX-License-Identifier: MIT
// A bounded native file/CPU image subset for tensor preprocessing.
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "py/runtime.h"
#include "py/objstr.h"
#include "py/objtuple.h"
#include "py/objlist.h"
#include <limits.h>
#include "py/stream.h"
#include "extmod/vfs.h"
#include "ndarray.h"
#include "image_core.h"

typedef struct {
    mp_obj_base_t base;
    unsigned w,h,format;
    uint8_t *owned;
} if_obj;
static const mp_obj_type_t if_type;

static void if_status(int status) {
    if (status==IF_UNSUPPORTED) mp_raise_msg(&mp_type_NotImplementedError,
        MP_ERROR_TEXT("unsupported image format/operation (JPEG unavailable)"));
    if (status==IF_NOMEM) mp_raise_msg(&mp_type_MemoryError,MP_ERROR_TEXT("PNG decode memory limit"));
    if (status) mp_raise_ValueError(MP_ERROR_TEXT("invalid, truncated, or oversized image"));
}

static size_t if_checked_size(mp_int_t w,mp_int_t h,mp_int_t format) {
    size_t size=0;
    if (w<=0||h<=0||w>(mp_int_t)IF_MAX_DIM||h>(mp_int_t)IF_MAX_DIM||format<1||format>2) {
        mp_raise_ValueError(MP_ERROR_TEXT("image dimensions/format out of bounds"));
    }
    if_status(if_size((unsigned)w,(unsigned)h,(unsigned)format,&size));
    return size;
}

static if_obj *if_self(mp_obj_t value) {
    if (!mp_obj_is_type(value,&if_type)) mp_raise_TypeError(MP_ERROR_TEXT("expected image.Image"));
    return MP_OBJ_TO_PTR(value);
}

static if_image if_pixels(if_obj *self) {
    return (if_image){self->w,self->h,self->format,self->owned};
}

static if_obj *if_new(unsigned w,unsigned h,unsigned format) {
    size_t size=if_checked_size(w,h,format);
    if_obj *self=mp_obj_malloc(if_obj,&if_type);
    self->w=w;self->h=h;self->format=format;
    self->owned=m_new0(uint8_t,size);
    return self;
}

static mp_obj_t if_load(mp_obj_t path) {
    mp_obj_t args[]={path,MP_OBJ_NEW_QSTR(MP_QSTR_rb)};
    mp_obj_t file=mp_vfs_open(2,args,(mp_map_t *)&mp_const_empty_map);
    nlr_buf_t nlr;
    if_obj *result;
    if (nlr_push(&nlr)==0) {
        int error=0;
        mp_off_t size=mp_stream_seek(file,0,MP_SEEK_END,&error);
        if (size==(mp_off_t)-1) mp_raise_OSError(error);
        if (size<=0||(uint64_t)size>IF_MAX_BYTES) mp_raise_ValueError(MP_ERROR_TEXT("image file size out of bounds"));
        if (mp_stream_seek(file,0,MP_SEEK_SET,&error)==(mp_off_t)-1) mp_raise_OSError(error);
        uint8_t *data=m_new(uint8_t,(size_t)size);
        mp_uint_t received=mp_stream_read_exactly(file,data,(size_t)size,&error);
        if (error) mp_raise_OSError(error);
        if (received!=(mp_uint_t)size) mp_raise_msg(&mp_type_OSError,MP_ERROR_TEXT("short image file read"));
        if_header header;
        if_status(if_probe(data,(size_t)size,&header));
        result=if_new(header.w,header.h,header.format);
        if_image pixels=if_pixels(result);
        if_status(if_decode(data,(size_t)size,&header,&pixels));
        nlr_pop();
    } else {
        nlr_buf_t close_nlr;
        if (nlr_push(&close_nlr)==0) {mp_stream_close(file);nlr_pop();}
        nlr_jump(nlr.ret_val);
    }
    mp_stream_close(file);
    return MP_OBJ_FROM_PTR(result);
}

static mp_obj_t if_make_new(const mp_obj_type_t *type,size_t n_args,size_t n_kw,const mp_obj_t *all_args) {
    (void)type;
    enum {ARG_path_or_width,ARG_height,ARG_format,ARG_buffer,ARG_copy_to_fb};
    static const mp_arg_t allowed[]={
        {MP_QSTR_path,MP_ARG_OBJ|MP_ARG_REQUIRED,{.u_obj=MP_OBJ_NULL}},
        {MP_QSTR_height,MP_ARG_OBJ,{.u_rom_obj=MP_ROM_NONE}},
        {MP_QSTR_pixformat,MP_ARG_INT,{.u_int=IF_RGB565}},
        {MP_QSTR_buffer,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_NONE}},
        {MP_QSTR_copy_to_fb,MP_ARG_BOOL|MP_ARG_KW_ONLY,{.u_bool=false}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all_kw_array(n_args,n_kw,all_args,MP_ARRAY_SIZE(allowed),allowed,args);
    if (args[ARG_copy_to_fb].u_bool) mp_raise_msg(&mp_type_NotImplementedError,MP_ERROR_TEXT("framebuffer is unavailable"));
    if (mp_obj_is_str(args[ARG_path_or_width].u_obj)) {
        if (args[ARG_height].u_obj!=mp_const_none||args[ARG_buffer].u_obj!=mp_const_none) {
            mp_raise_TypeError(MP_ERROR_TEXT("file image cannot use height/buffer"));
        }
        return if_load(args[ARG_path_or_width].u_obj);
    }
    if (args[ARG_height].u_obj==mp_const_none) mp_raise_TypeError(MP_ERROR_TEXT("image height is required"));
    mp_int_t w=mp_obj_get_int(args[ARG_path_or_width].u_obj),h=mp_obj_get_int(args[ARG_height].u_obj);
    size_t size=if_checked_size(w,h,args[ARG_format].u_int);
    if (args[ARG_buffer].u_obj==mp_const_none) return MP_OBJ_FROM_PTR(if_new(w,h,args[ARG_format].u_int));
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(args[ARG_buffer].u_obj,&buffer,MP_BUFFER_WRITE);
    if (buffer.len<size) mp_raise_ValueError(MP_ERROR_TEXT("image buffer is too small"));
    if_obj *self=if_new(w,h,args[ARG_format].u_int);
    // Allocation can run a GC finalizer; validate the current buffer again.
    mp_get_buffer_raise(args[ARG_buffer].u_obj,&buffer,MP_BUFFER_WRITE);
    if (buffer.len<size) mp_raise_ValueError(MP_ERROR_TEXT("image buffer was resized too small"));
    // buffer= initializes an owned copy. Resizing or releasing the original
    // Python buffer can never invalidate an Image object's pixel storage.
    memcpy(self->owned,buffer.buf,size);
    return MP_OBJ_FROM_PTR(self);
}

static mp_obj_t if_width(mp_obj_t self) {return mp_obj_new_int_from_uint(if_self(self)->w);}
static mp_obj_t if_height(mp_obj_t self) {return mp_obj_new_int_from_uint(if_self(self)->h);}
static mp_obj_t if_format(mp_obj_t self) {return mp_obj_new_int_from_uint(if_self(self)->format);}
static mp_obj_t if_size_method(mp_obj_t self_in) {
    if_obj *self=if_self(self_in);return mp_obj_new_int_from_uint(if_checked_size(self->w,self->h,self->format));
}
static MP_DEFINE_CONST_FUN_OBJ_1(if_width_obj,if_width);
static MP_DEFINE_CONST_FUN_OBJ_1(if_height_obj,if_height);
static MP_DEFINE_CONST_FUN_OBJ_1(if_format_obj,if_format);
static MP_DEFINE_CONST_FUN_OBJ_1(if_size_obj,if_size_method);

static void if_coordinates(if_obj *self,mp_obj_t x_in,mp_obj_t y_in,unsigned *x,unsigned *y) {
    mp_int_t ix=mp_obj_get_int(x_in),iy=mp_obj_get_int(y_in);
    if (ix<0||iy<0||(mp_uint_t)ix>=self->w||(mp_uint_t)iy>=self->h) mp_raise_ValueError(MP_ERROR_TEXT("pixel is outside image"));
    *x=(unsigned)ix;*y=(unsigned)iy;
}

static mp_obj_t if_get_pixel(size_t n_args,const mp_obj_t *args) {
    if_obj *self=if_self(args[0]);unsigned x,y;if_coordinates(self,args[1],args[2],&x,&y);
    if_image pixels=if_pixels(self);uint8_t rgb[3];if_get_rgb(&pixels,x,y,rgb);
    bool tuple=n_args<4||mp_obj_is_true(args[3]);
    if (self->format==IF_GRAYSCALE) return mp_obj_new_int(rgb[0]);
    if (!tuple) {
        size_t p=2*((size_t)y*self->w+x);return mp_obj_new_int(pixels.data[p]|(unsigned)pixels.data[p+1]<<8);
    }
    mp_obj_t values[]={mp_obj_new_int(rgb[0]),mp_obj_new_int(rgb[1]),mp_obj_new_int(rgb[2])};
    return mp_obj_new_tuple(3,values);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(if_get_pixel_obj,3,4,if_get_pixel);

static mp_obj_t if_set_pixel(size_t n_args,const mp_obj_t *args) {
    (void)n_args;
    mp_obj_t expanded[4];
    if (n_args==3) {size_t count;mp_obj_t *xy;mp_obj_get_array(args[1],&count,&xy);if (count!=2) mp_raise_ValueError(MP_ERROR_TEXT("pixel needs x,y"));expanded[0]=args[0];expanded[1]=xy[0];expanded[2]=xy[1];expanded[3]=args[2];args=expanded;}
    if_obj *self=if_self(args[0]);unsigned x,y;if_coordinates(self,args[1],args[2],&x,&y);
    if_image pixels=if_pixels(self);uint8_t rgb[3];
    if (mp_obj_is_int(args[3])) {
        mp_int_t value=mp_obj_get_int(args[3]);
        if (value<0||value>(self->format==IF_GRAYSCALE?255:65535)) mp_raise_ValueError(MP_ERROR_TEXT("pixel value out of range"));
        if (self->format==IF_GRAYSCALE) rgb[0]=rgb[1]=rgb[2]=(uint8_t)value;
        else {size_t p=2*((size_t)y*self->w+x);pixels.data[p]=(uint8_t)value;pixels.data[p+1]=(uint8_t)(value>>8);return args[0];}
    } else {
        size_t count;mp_obj_t *values;mp_obj_get_array(args[3],&count,&values);
        if (count!=3) mp_raise_ValueError(MP_ERROR_TEXT("RGB pixel needs three channels"));
        for (unsigned c=0;c<3;++c) {mp_int_t v=mp_obj_get_int(values[c]);if (v<0||v>255) mp_raise_ValueError(MP_ERROR_TEXT("channel out of range"));rgb[c]=(uint8_t)v;}
    }
    if_set_rgb(&pixels,x,y,rgb);return args[0];
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(if_set_pixel_obj,3,4,if_set_pixel);

static if_roi if_get_roi(if_obj *self,mp_obj_t roi_in) {
    if_roi roi={0,0,self->w,self->h};
    if (roi_in!=mp_const_none) {
        size_t count;mp_obj_t *values;mp_obj_get_array(roi_in,&count,&values);
        if (count!=4) mp_raise_ValueError(MP_ERROR_TEXT("roi requires x,y,w,h"));
        mp_int_t x=mp_obj_get_int(values[0]),y=mp_obj_get_int(values[1]);
        mp_int_t w=mp_obj_get_int(values[2]),h=mp_obj_get_int(values[3]);
        if (x<0||y<0||w<=0||h<=0||(mp_uint_t)x>self->w||(mp_uint_t)y>self->h||
            (mp_uint_t)w>self->w-(mp_uint_t)x||(mp_uint_t)h>self->h-(mp_uint_t)y) mp_raise_ValueError(MP_ERROR_TEXT("roi outside image"));
        roi=(if_roi){x,y,(unsigned)w,(unsigned)h};
    }
    return roi;
}

static unsigned if_scaled(unsigned dimension,mp_obj_t scale_in) {
    float scale=mp_obj_get_float(scale_in);
    float result=dimension*scale;
    if (!(result>=1)||result>IF_MAX_DIM||!isfinite(result)) mp_raise_ValueError(MP_ERROR_TEXT("invalid image scale"));
    return (unsigned)result;
}

static mp_obj_t if_copy(size_t n_args,const mp_obj_t *pos_args,mp_map_t *kwargs) {
    static const mp_arg_t allowed[]={
        {MP_QSTR_roi,MP_ARG_OBJ,{.u_rom_obj=MP_ROM_NONE}},
        {MP_QSTR_x_scale,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_INT(1)}},
        {MP_QSTR_y_scale,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_INT(1)}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args-1,pos_args+1,kwargs,MP_ARRAY_SIZE(allowed),allowed,args);
    if_obj *self=if_self(pos_args[0]);if_roi roi=if_get_roi(self,args[0].u_obj);
    unsigned w=if_scaled(roi.w,args[1].u_obj),h=if_scaled(roi.h,args[2].u_obj);
    if_obj *copy=if_new(w,h,self->format);if_image dst=if_pixels(copy),src=if_pixels(self);
    if_status(if_draw(&dst,&src,roi,0,0,w,h,IF_BILINEAR));return MP_OBJ_FROM_PTR(copy);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_copy_obj,1,if_copy);

static mp_obj_t if_resize(size_t n_args,const mp_obj_t *pos_args,mp_map_t *kwargs) {
    static const mp_arg_t allowed[]={
        {MP_QSTR_width,MP_ARG_INT|MP_ARG_REQUIRED,{.u_int=0}},
        {MP_QSTR_height,MP_ARG_INT|MP_ARG_REQUIRED,{.u_int=0}},
        {MP_QSTR_hint,MP_ARG_INT|MP_ARG_KW_ONLY,{.u_int=IF_BILINEAR}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args-1,pos_args+1,kwargs,MP_ARRAY_SIZE(allowed),allowed,args);
    if_obj *self=if_self(pos_args[0]);if_checked_size(args[0].u_int,args[1].u_int,self->format);
    if_obj *copy=if_new(args[0].u_int,args[1].u_int,self->format);if_image dst=if_pixels(copy),src=if_pixels(self);
    if_status(if_draw(&dst,&src,(if_roi){0,0,self->w,self->h},0,0,copy->w,copy->h,args[2].u_int));
    return MP_OBJ_FROM_PTR(copy);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_resize_obj,1,if_resize);

static mp_obj_t if_grayscale(size_t n_args,const mp_obj_t *pos_args,mp_map_t *kwargs) {
    static const mp_arg_t allowed[]={{MP_QSTR_copy,MP_ARG_BOOL|MP_ARG_KW_ONLY,{.u_bool=false}}};
    mp_arg_val_t args[1];mp_arg_parse_all(n_args-1,pos_args+1,kwargs,1,allowed,args);
    if_obj *self=if_self(pos_args[0]);if_obj *gray=if_new(self->w,self->h,IF_GRAYSCALE);
    if_image dst=if_pixels(gray),src=if_pixels(self);
    if_status(if_draw(&dst,&src,(if_roi){0,0,self->w,self->h},0,0,self->w,self->h,0));
    if (args[0].u_bool) return MP_OBJ_FROM_PTR(gray);
    self->format=IF_GRAYSCALE;self->owned=gray->owned;
    return pos_args[0];
}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_grayscale_obj,1,if_grayscale);

static bool if_overlaps(const void *a,size_t a_size,const void *b,size_t b_size) {
    uintptr_t aa=(uintptr_t)a,bb=(uintptr_t)b;
    return aa<bb?bb-aa<a_size:aa-bb<b_size;
}

static mp_obj_t if_draw_image(size_t n_args,const mp_obj_t *pos_args,mp_map_t *kwargs) {
    enum {ARG_image,ARG_x,ARG_y,ARG_roi,ARG_hint,ARG_x_scale,ARG_y_scale};
    static const mp_arg_t allowed[]={
        {MP_QSTR_image,MP_ARG_OBJ|MP_ARG_REQUIRED,{.u_obj=MP_OBJ_NULL}},
        {MP_QSTR_x,MP_ARG_INT,{.u_int=0}},{MP_QSTR_y,MP_ARG_INT,{.u_int=0}},
        {MP_QSTR_roi,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_NONE}},
        {MP_QSTR_hint,MP_ARG_INT|MP_ARG_KW_ONLY,{.u_int=0}},
        {MP_QSTR_x_scale,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_INT(1)}},
        {MP_QSTR_y_scale,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_INT(1)}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args-1,pos_args+1,kwargs,MP_ARRAY_SIZE(allowed),allowed,args);
    if_obj *self=if_self(pos_args[0]),*source=if_self(args[ARG_image].u_obj);
    if_roi roi=if_get_roi(source,args[ARG_roi].u_obj);
    unsigned hint=args[ARG_hint].u_int;
    if (hint&~(IF_BILINEAR|IF_CENTER|IF_SCALE_ASPECT_IGNORE|IF_BLACK_BACKGROUND)) mp_raise_ValueError(MP_ERROR_TEXT("unsupported draw_image hint"));
    unsigned w=if_scaled(roi.w,args[ARG_x_scale].u_obj),h=if_scaled(roi.h,args[ARG_y_scale].u_obj);
    mp_int_t x=args[ARG_x].u_int,y=args[ARG_y].u_int;
    if (hint&IF_SCALE_ASPECT_IGNORE) {w=self->w;h=self->h;}
    else if (hint&IF_CENTER) {
        float scale=fminf((float)self->w/roi.w,(float)self->h/roi.h);
        w=(unsigned)(roi.w*scale);h=(unsigned)(roi.h*scale);if (!w) w=1;if (!h) h=1;
    }
    if (hint&IF_CENTER) {
        int64_t cx=(int64_t)x+((int64_t)self->w-w)/2,cy=(int64_t)y+((int64_t)self->h-h)/2;
        if (cx<INT32_MIN||cx>INT32_MAX||cy<INT32_MIN||cy>INT32_MAX) mp_raise_ValueError(MP_ERROR_TEXT("draw position overflow"));
        x=(mp_int_t)cx;y=(mp_int_t)cy;
    }
    if_image dst=if_pixels(self),src=if_pixels(source);
    size_t dst_size=if_checked_size(self->w,self->h,self->format),src_size=if_checked_size(source->w,source->h,source->format);
    if (if_overlaps(dst.data,dst_size,src.data,src_size)) {
        uint8_t *snapshot=m_new(uint8_t,src_size);memcpy(snapshot,src.data,src_size);src.data=snapshot;
    }
    if_status(if_draw(&dst,&src,roi,x,y,w,h,hint));return pos_args[0];
}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_draw_image_obj,2,if_draw_image);

static mp_obj_t if_to_ndarray(size_t n_args,const mp_obj_t *pos_args,mp_map_t *kwargs) {
    static const mp_arg_t allowed[]={
        {MP_QSTR_dtype,MP_ARG_OBJ|MP_ARG_REQUIRED,{.u_obj=MP_OBJ_NULL}},
        {MP_QSTR_buffer,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_NONE}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args-1,pos_args+1,kwargs,MP_ARRAY_SIZE(allowed),allowed,args);
    mp_int_t dtype;
    if (mp_obj_is_str(args[0].u_obj)) {
        size_t length;const char *text=mp_obj_str_get_data(args[0].u_obj,&length);
        if (length!=1) mp_raise_ValueError(MP_ERROR_TEXT("dtype needs one character"));
        dtype=text[0];
    } else dtype=mp_obj_get_int(args[0].u_obj);
    if (dtype!='f'&&dtype!='b'&&dtype!='B') mp_raise_ValueError(MP_ERROR_TEXT("dtype must be f,b,B"));
    if_obj *self=if_self(pos_args[0]);
    unsigned channels=self->format==IF_GRAYSCALE?1:3;
    size_t elements=(size_t)self->w*self->h*channels;
    if (elements>IF_MAX_BYTES/(dtype=='f'?sizeof(float):1)) mp_raise_ValueError(MP_ERROR_TEXT("tensor is too large"));
    size_t bytes=elements*(dtype=='f'?sizeof(float):1);
    size_t shape[ULAB_MAX_DIMS]={0};
    unsigned rank=channels==1?2:3;
    shape[ULAB_MAX_DIMS-rank]=self->h;shape[ULAB_MAX_DIMS-rank+1]=self->w;
    if (channels==3) shape[ULAB_MAX_DIMS-1]=3;
    // All arrays own their data. buffer= receives an initial conversion copy,
    // never an aliased ndarray: later in-place array operations require an
    // explicit copy back to a caller's buffer (used by ml.Normalization).
    if (args[1].u_obj!=mp_const_none) {
        mp_buffer_info_t buffer;mp_get_buffer_raise(args[1].u_obj,&buffer,MP_BUFFER_WRITE);
        if (buffer.len<bytes) mp_raise_ValueError(MP_ERROR_TEXT("tensor buffer is too small"));
    }
    ndarray_obj_t *array=ndarray_new_dense_ndarray(rank,shape,(uint8_t)dtype);
    if_image src=if_pixels(self);
    if_status(if_to_tensor(&src,(char)dtype,array->array,bytes));
    if (args[1].u_obj!=mp_const_none) {
        // Re-fetch after allocation in case a GC finalizer changed the buffer.
        mp_buffer_info_t buffer;mp_get_buffer_raise(args[1].u_obj,&buffer,MP_BUFFER_WRITE);
        if (buffer.len<bytes) mp_raise_ValueError(MP_ERROR_TEXT("tensor buffer was resized too small"));
        memcpy(buffer.buf,array->array,bytes);
    }
    return MP_OBJ_FROM_PTR(array);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_to_ndarray_obj,1,if_to_ndarray);


static int if_int(mp_obj_t value) {
    mp_int_t n=mp_obj_get_int(value);
    if (n<INT_MIN||n>INT_MAX) mp_raise_ValueError(MP_ERROR_TEXT("coordinate overflow"));
    return (int)n;
}
static void if_geometry(mp_obj_t value,size_t count,int *out) {
    size_t n;mp_obj_t *items;mp_obj_get_array(value,&n,&items);
    if (n!=count) mp_raise_ValueError(MP_ERROR_TEXT("invalid geometry tuple"));
    for (size_t i=0;i<n;++i) out[i]=if_int(items[i]);
}
static unsigned if_color(if_obj *self,mp_obj_t value) {
    if (value==mp_const_none) return self->format==IF_GRAYSCALE?255:65535;
    if (mp_obj_is_int(value)) {
        mp_int_t n=mp_obj_get_int(value);
        if (n<0||n>(self->format==IF_GRAYSCALE?255:65535)) mp_raise_ValueError(MP_ERROR_TEXT("color out of range"));
        return (unsigned)n;
    }
    int channels[3];if_geometry(value,3,channels);
    for (unsigned i=0;i<3;++i) if (channels[i]<0||channels[i]>255) mp_raise_ValueError(MP_ERROR_TEXT("channel out of range"));
    if (self->format==IF_GRAYSCALE) return (77u*channels[0]+150u*channels[1]+29u*channels[2]+128u)>>8;
    return ((channels[0]>>3)<<11)|((channels[1]>>2)<<5)|(channels[2]>>3);
}
static mp_obj_t if_to_bytes(mp_obj_t self_in) {
    if_obj *self=if_self(self_in);
    return mp_obj_new_bytes(self->owned,if_checked_size(self->w,self->h,self->format));
}
static MP_DEFINE_CONST_FUN_OBJ_1(if_to_bytes_obj,if_to_bytes);
static mp_obj_t if_bytearray(mp_obj_t self_in) {
    if_obj *self=if_self(self_in);
    return mp_obj_new_bytearray(if_checked_size(self->w,self->h,self->format),self->owned);
}
static MP_DEFINE_CONST_FUN_OBJ_1(if_bytearray_obj,if_bytearray);
static mp_obj_t if_clear(mp_obj_t self_in) {
    if_obj *self=if_self(self_in);memset(self->owned,0,if_checked_size(self->w,self->h,self->format));return self_in;
}
static MP_DEFINE_CONST_FUN_OBJ_1(if_clear_obj,if_clear);
static mp_obj_t if_draw_shape(size_t n_args,const mp_obj_t *pos,mp_map_t *kw,unsigned shape) {
    static const mp_arg_t allowed[]={
        {MP_QSTR_color,MP_ARG_OBJ,{.u_rom_obj=MP_ROM_NONE}},
        {MP_QSTR_thickness,MP_ARG_INT,{.u_int=1}},
        {MP_QSTR_fill,MP_ARG_BOOL,{.u_bool=false}},
    };
    if_obj *self=if_self(pos[0]);int g[4]={0};if_geometry(pos[1],shape==2?3:4,g);
    mp_arg_val_t a[3];mp_arg_parse_all(n_args-2,pos+2,kw,shape==0?2:3,allowed,a);
    if (a[1].u_int<0||a[1].u_int>(mp_int_t)IF_MAX_DIM) mp_raise_ValueError(MP_ERROR_TEXT("thickness out of bounds"));
    unsigned color=if_color(self,a[0].u_obj);if_image dst=if_pixels(self);int status;
    if (!shape) status=if_draw_line(&dst,g[0],g[1],g[2],g[3],color,a[1].u_int);
    else if (shape==1) status=if_draw_rectangle(&dst,g[0],g[1],g[2],g[3],color,a[1].u_int,a[2].u_bool);
    else status=if_draw_circle(&dst,g[0],g[1],g[2],color,a[1].u_int,a[2].u_bool);
    if_status(status);return pos[0];
}
static mp_obj_t if_rectangle(size_t n,const mp_obj_t *p,mp_map_t *k) {return if_draw_shape(n,p,k,1);}
static mp_obj_t if_line(size_t n,const mp_obj_t *p,mp_map_t *k) {return if_draw_shape(n,p,k,0);}
static mp_obj_t if_circle(size_t n,const mp_obj_t *p,mp_map_t *k) {return if_draw_shape(n,p,k,2);}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_rectangle_obj,2,if_rectangle);
static MP_DEFINE_CONST_FUN_OBJ_KW(if_line_obj,2,if_line);
static MP_DEFINE_CONST_FUN_OBJ_KW(if_circle_obj,2,if_circle);
static mp_obj_t if_string(size_t n,const mp_obj_t *p,mp_map_t *kw) {
    static const mp_arg_t allowed[]={
        {MP_QSTR_color,MP_ARG_OBJ,{.u_rom_obj=MP_ROM_NONE}},
        {MP_QSTR_scale,MP_ARG_OBJ,{.u_rom_obj=MP_ROM_INT(1)}},
        {MP_QSTR_x_spacing,MP_ARG_INT,{.u_int=0}},
        {MP_QSTR_y_spacing,MP_ARG_INT,{.u_int=0}},
        {MP_QSTR_mono_space,MP_ARG_BOOL,{.u_bool=true}},
        {MP_QSTR_char_rotation,MP_ARG_INT,{.u_int=0}},
        {MP_QSTR_char_hmirror,MP_ARG_BOOL,{.u_bool=false}},
        {MP_QSTR_char_vflip,MP_ARG_BOOL,{.u_bool=false}},
        {MP_QSTR_string_rotation,MP_ARG_INT,{.u_int=0}},
        {MP_QSTR_string_hmirror,MP_ARG_BOOL,{.u_bool=false}},
        {MP_QSTR_string_vflip,MP_ARG_BOOL,{.u_bool=false}},
    };
    if_obj *self=if_self(p[0]);int xy[2];if_geometry(p[1],2,xy);
    size_t len;const char *text=mp_obj_str_get_data(p[2],&len);
    mp_arg_val_t a[11];mp_arg_parse_all(n-3,p+3,kw,11,allowed,a);
    if (!a[4].u_bool||a[5].u_int||a[6].u_bool||a[7].u_bool||a[8].u_int||a[9].u_bool||a[10].u_bool)
        mp_raise_msg(&mp_type_NotImplementedError,MP_ERROR_TEXT("text transforms/proportional font unavailable"));
    if (a[2].u_int<0||a[2].u_int>(mp_int_t)IF_MAX_DIM||a[3].u_int<0||a[3].u_int>(mp_int_t)IF_MAX_DIM)
        mp_raise_ValueError(MP_ERROR_TEXT("text spacing out of bounds"));
    if_image dst=if_pixels(self);if_status(if_draw_string(&dst,xy[0],xy[1],text,len,if_color(self,a[0].u_obj),
        mp_obj_get_float(a[1].u_obj),a[2].u_int,a[3].u_int));return p[0];
}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_string_obj,3,if_string);
static mp_obj_t if_filter_method(size_t n,const mp_obj_t *p,mp_map_t *kw,bool median) {
    static const mp_arg_t allowed[]={
        {MP_QSTR_percentile,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_NONE}},
        {MP_QSTR_threshold,MP_ARG_BOOL|MP_ARG_KW_ONLY,{.u_bool=false}},
        {MP_QSTR_offset,MP_ARG_INT|MP_ARG_KW_ONLY,{.u_int=0}},
        {MP_QSTR_invert,MP_ARG_BOOL|MP_ARG_KW_ONLY,{.u_bool=false}},
        {MP_QSTR_mask,MP_ARG_OBJ|MP_ARG_KW_ONLY,{.u_rom_obj=MP_ROM_NONE}},
    };
    mp_arg_val_t a[5];mp_arg_parse_all(n-2,p+2,kw,5,allowed,a);
    if ((!median&&a[0].u_obj!=mp_const_none)||a[1].u_bool||a[2].u_int||a[3].u_bool||a[4].u_obj!=mp_const_none)
        mp_raise_msg(&mp_type_NotImplementedError,MP_ERROR_TEXT("filter threshold/mask options unavailable"));
    mp_int_t radius=mp_obj_get_int(p[1]);
    if (radius<0||radius>7) mp_raise_ValueError(MP_ERROR_TEXT("filter radius must be 0..7"));
    float percentile=a[0].u_obj==mp_const_none?.5f:mp_obj_get_float(a[0].u_obj);
    if (!isfinite(percentile)||percentile<0||percentile>1) mp_raise_ValueError(MP_ERROR_TEXT("invalid percentile"));
    if_obj *self=if_self(p[0]),*copy=if_new(self->w,self->h,self->format);
    if_image src=if_pixels(self),dst=if_pixels(copy);if_status(if_filter(&dst,&src,radius,median,percentile));
    self->owned=copy->owned;return p[0];
}
static mp_obj_t if_mean(size_t n,const mp_obj_t *p,mp_map_t *k) {return if_filter_method(n,p,k,false);}
static mp_obj_t if_median(size_t n,const mp_obj_t *p,mp_map_t *k) {return if_filter_method(n,p,k,true);}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_mean_obj,2,if_mean);
static MP_DEFINE_CONST_FUN_OBJ_KW(if_median_obj,2,if_median);
static mp_obj_t if_unavailable(size_t n,const mp_obj_t *p,mp_map_t *k) {
    (void)n;(void)p;(void)k;
    mp_raise_msg(&mp_type_NotImplementedError,MP_ERROR_TEXT("histogram/statistics/rotation unavailable in file images"));
}
static MP_DEFINE_CONST_FUN_OBJ_KW(if_unavailable_obj,1,if_unavailable);
typedef struct {mp_obj_base_t base;mp_fun_1_t iternext;mp_obj_t image;unsigned row;} if_iter;
static mp_obj_t if_next(mp_obj_t iter_in) {
    if_iter *it=MP_OBJ_TO_PTR(iter_in);if_obj *self=if_self(it->image);
    if (it->row>=self->h) return MP_OBJ_STOP_ITERATION;
    unsigned y=it->row++;mp_obj_t row=mp_obj_new_list(0,NULL);
    for (unsigned x=0;x<self->w;++x) {
        size_t p=(size_t)y*self->w+x;unsigned v=self->owned[p];
        if (self->format==IF_RGB565) v=self->owned[2*p]|(unsigned)self->owned[2*p+1]<<8;
        mp_obj_list_append(row,mp_obj_new_int_from_uint(v));
    }
    return row;
}
static mp_obj_t if_getiter(mp_obj_t self,mp_obj_iter_buf_t *buf) {
    _Static_assert(sizeof(if_iter)<=sizeof(mp_obj_iter_buf_t),"iterator buffer");
    if_iter *it=(if_iter *)buf;it->base.type=&mp_type_polymorph_iter;it->iternext=if_next;it->image=self;it->row=0;
    return MP_OBJ_FROM_PTR(it);
}

static const mp_rom_map_elem_t if_locals_table[]={
    {MP_ROM_QSTR(MP_QSTR_clone),MP_ROM_PTR(&if_copy_obj)},
    {MP_ROM_QSTR(MP_QSTR_to_bytes),MP_ROM_PTR(&if_to_bytes_obj)},
    {MP_ROM_QSTR(MP_QSTR_bytearray),MP_ROM_PTR(&if_bytearray_obj)},
    {MP_ROM_QSTR(MP_QSTR_clear),MP_ROM_PTR(&if_clear_obj)},
    {MP_ROM_QSTR(MP_QSTR_draw_rectangle),MP_ROM_PTR(&if_rectangle_obj)},
    {MP_ROM_QSTR(MP_QSTR_draw_line),MP_ROM_PTR(&if_line_obj)},
    {MP_ROM_QSTR(MP_QSTR_draw_circle),MP_ROM_PTR(&if_circle_obj)},
    {MP_ROM_QSTR(MP_QSTR_draw_string),MP_ROM_PTR(&if_string_obj)},
    {MP_ROM_QSTR(MP_QSTR_mean),MP_ROM_PTR(&if_mean_obj)},
    {MP_ROM_QSTR(MP_QSTR_median),MP_ROM_PTR(&if_median_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_hist),MP_ROM_PTR(&if_unavailable_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_histogram),MP_ROM_PTR(&if_unavailable_obj)},
    {MP_ROM_QSTR(MP_QSTR_histogram),MP_ROM_PTR(&if_unavailable_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_stats),MP_ROM_PTR(&if_unavailable_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_statistics),MP_ROM_PTR(&if_unavailable_obj)},
    {MP_ROM_QSTR(MP_QSTR_statistics),MP_ROM_PTR(&if_unavailable_obj)},
    {MP_ROM_QSTR(MP_QSTR_rotation_corr),MP_ROM_PTR(&if_unavailable_obj)},

    {MP_ROM_QSTR(MP_QSTR_width),MP_ROM_PTR(&if_width_obj)},
    {MP_ROM_QSTR(MP_QSTR_height),MP_ROM_PTR(&if_height_obj)},
    {MP_ROM_QSTR(MP_QSTR_format),MP_ROM_PTR(&if_format_obj)},
    {MP_ROM_QSTR(MP_QSTR_size),MP_ROM_PTR(&if_size_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_pixel),MP_ROM_PTR(&if_get_pixel_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_pixel),MP_ROM_PTR(&if_set_pixel_obj)},
    {MP_ROM_QSTR(MP_QSTR_copy),MP_ROM_PTR(&if_copy_obj)},
    {MP_ROM_QSTR(MP_QSTR_resize),MP_ROM_PTR(&if_resize_obj)},
    {MP_ROM_QSTR(MP_QSTR_to_grayscale),MP_ROM_PTR(&if_grayscale_obj)},
    {MP_ROM_QSTR(MP_QSTR_grayscale),MP_ROM_PTR(&if_grayscale_obj)},
    {MP_ROM_QSTR(MP_QSTR_draw_image),MP_ROM_PTR(&if_draw_image_obj)},
    {MP_ROM_QSTR(MP_QSTR_to_ndarray),MP_ROM_PTR(&if_to_ndarray_obj)},
};
static MP_DEFINE_CONST_DICT(if_locals,if_locals_table);
static MP_DEFINE_CONST_OBJ_TYPE(if_type,MP_QSTR_Image,MP_TYPE_FLAG_NONE,
    make_new,if_make_new,iter,if_getiter,locals_dict,&if_locals);
static const mp_rom_map_elem_t if_globals_table[]={
    {MP_ROM_QSTR(MP_QSTR___name__),MP_ROM_QSTR(MP_QSTR_image)},
    {MP_ROM_QSTR(MP_QSTR_Image),MP_ROM_PTR(&if_type)},
    {MP_ROM_QSTR(MP_QSTR_GRAYSCALE),MP_ROM_INT(IF_GRAYSCALE)},
    {MP_ROM_QSTR(MP_QSTR_RGB565),MP_ROM_INT(IF_RGB565)},
    {MP_ROM_QSTR(MP_QSTR_BILINEAR),MP_ROM_INT(IF_BILINEAR)},
    {MP_ROM_QSTR(MP_QSTR_CENTER),MP_ROM_INT(IF_CENTER)},
    {MP_ROM_QSTR(MP_QSTR_SCALE_ASPECT_IGNORE),MP_ROM_INT(IF_SCALE_ASPECT_IGNORE)},
    {MP_ROM_QSTR(MP_QSTR_BLACK_BACKGROUND),MP_ROM_INT(IF_BLACK_BACKGROUND)},
};
static MP_DEFINE_CONST_DICT(if_globals,if_globals_table);
const mp_obj_module_t image_file_module={{&mp_type_module},(mp_obj_dict_t *)&if_globals};
MP_REGISTER_MODULE(MP_QSTR_image,image_file_module);
