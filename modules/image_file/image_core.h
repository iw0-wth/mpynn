// SPDX-License-Identifier: MIT
#ifndef MPYNN_IMAGE_FILE_CORE_H
#define MPYNN_IMAGE_FILE_CORE_H
#include <stddef.h>
#include <stdint.h>
#define IF_MAX_BYTES (64u * 1024u * 1024u)
#define IF_MAX_DIM 8192u
#define IF_GRAYSCALE 1
#define IF_RGB565 2
#define IF_BILINEAR 1u
#define IF_CENTER 2u
#define IF_SCALE_ASPECT_IGNORE 4u
#define IF_BLACK_BACKGROUND 8u

typedef struct {unsigned w,h,format;uint8_t *data;} if_image;
typedef struct {int x,y;unsigned w,h;} if_roi;
typedef struct {unsigned w,h,format,kind;size_t offset,stride;unsigned maxval,bits;int top_down;} if_header;
enum {IF_OK=0,IF_INVALID=-1,IF_UNSUPPORTED=-2,IF_BOUNDS=-3,IF_NOMEM=-4};
int if_size(unsigned w,unsigned h,unsigned format,size_t *bytes);
int if_probe(const uint8_t *data,size_t size,if_header *header);
int if_decode(const uint8_t *data,size_t size,const if_header *header,if_image *image);
void if_get_rgb(const if_image *image,unsigned x,unsigned y,uint8_t rgb[3]);
void if_set_rgb(if_image *image,unsigned x,unsigned y,const uint8_t rgb[3]);
int if_draw(if_image *dst,const if_image *src,if_roi roi,int x,int y,unsigned w,unsigned h,unsigned hint);
int if_to_tensor(const if_image *src,char dtype,void *output,size_t bytes);
// Drawing clips to the destination and accepts signed 32-bit coordinates.
int if_draw_rectangle(if_image *dst,int x,int y,int w,int h,unsigned color,unsigned thickness,int fill);
int if_draw_line(if_image *dst,int x0,int y0,int x1,int y1,unsigned color,unsigned thickness);
int if_draw_circle(if_image *dst,int x,int y,int radius,unsigned color,unsigned thickness,int fill);
int if_draw_string(if_image *dst,int x,int y,const char *text,size_t length,unsigned color,float scale,int x_spacing,int y_spacing);
// Separate source/destination required; radius <= 7 bounds CPU work and stack use.
int if_filter(if_image *dst,const if_image *src,unsigned radius,int median,float percentile);
int if_png_decode(const uint8_t *data,size_t size,if_image *output);
#endif
