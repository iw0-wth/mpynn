// SPDX-License-Identifier: MIT
// Bounded CPU pixel operations and uncompressed BMP/Netpbm readers.
#include "image_core.h"
#include <limits.h>
#include <math.h>
#include <string.h>

static unsigned if_u16(const uint8_t *p) {return p[0] | (unsigned)p[1]<<8;}
static uint32_t if_u32(const uint8_t *p) {return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;}
static uint32_t if_be32(const uint8_t *p) {return (uint32_t)p[0]<<24 | (uint32_t)p[1]<<16 | (uint32_t)p[2]<<8 | p[3];}
static int if_space(uint8_t c) {return c==' '||c=='\n'||c=='\r'||c=='\t'||c=='\v'||c=='\f';}

int if_size(unsigned w,unsigned h,unsigned format,size_t *bytes) {
    if (!w||!h||w>IF_MAX_DIM||h>IF_MAX_DIM || (format!=IF_GRAYSCALE&&format!=IF_RGB565)) return IF_BOUNDS;
    if ((size_t)w*h>IF_MAX_BYTES/format) return IF_BOUNDS;
    *bytes=(size_t)w*h*format;
    return IF_OK;
}

static int if_number(const uint8_t *data,size_t size,size_t *offset,unsigned *value) {
    size_t p=*offset;
    for (;;) {
        while (p<size&&if_space(data[p])) ++p;
        if (p>=size) return IF_INVALID;
        if (data[p]!='#') break;
        while (p<size&&data[p]!='\n'&&data[p]!='\r') ++p;
    }
    unsigned number=0;
    size_t start=p;
    while (p<size&&data[p]>='0'&&data[p]<='9') {
        unsigned digit=data[p++]-'0';
        if (number>(UINT_MAX-digit)/10) return IF_BOUNDS;
        number=number*10+digit;
    }
    if (p==start || (p<size&&!if_space(data[p])&&data[p]!='#')) return IF_INVALID;
    *offset=p;*value=number;return IF_OK;
}

int if_probe(const uint8_t *data,size_t size,if_header *header) {
    if (!data||!header||size<2||size>IF_MAX_BYTES) return IF_INVALID;
    memset(header,0,sizeof(*header));
    if (size>=8&&!memcmp(data,"\x89PNG\r\n\x1a\n",8)) {
        if (size<33||if_be32(data+8)!=13||memcmp(data+12,"IHDR",4)) return IF_INVALID;
        header->w=if_be32(data+16);header->h=if_be32(data+20);
        header->format=IF_RGB565;header->kind=7;
    } else if (data[0]=='B'&&data[1]=='M') {
        if (size<54) return IF_INVALID;
        uint32_t dib=if_u32(data+14),offset=if_u32(data+10),file_size=if_u32(data+2);
        int32_t w=(int32_t)if_u32(data+18),h=(int32_t)if_u32(data+22);
        unsigned bits=if_u16(data+28);
        if (dib<40||dib>size-14||offset<14u+dib||offset>size||file_size>size||
            (file_size&&file_size<offset)||w<=0||h==INT32_MIN||h==0||if_u16(data+26)!=1) return IF_INVALID;
        if (if_u32(data+30)!=0||(bits!=24&&bits!=32)) return IF_UNSUPPORTED;
        header->w=(unsigned)w;header->h=(unsigned)(h<0?-h:h);header->top_down=h<0;
        if (header->w>IF_MAX_DIM||header->h>IF_MAX_DIM) return IF_BOUNDS;
        header->offset=offset;header->bits=bits;header->kind=8;header->format=IF_RGB565;
        header->stride=(((size_t)header->w*bits+31)/32)*4;
        if (header->stride>SIZE_MAX/header->h||header->stride*header->h>size-offset ||
            (file_size&&header->stride*header->h>file_size-offset)) return IF_INVALID;
    } else if (data[0]=='P'&&data[1]>='1'&&data[1]<='6') {
        header->kind=data[1]-'0';header->offset=2;
        if (if_number(data,size,&header->offset,&header->w)||if_number(data,size,&header->offset,&header->h)) return IF_INVALID;
        header->format=(header->kind==3||header->kind==6)?IF_RGB565:IF_GRAYSCALE;
        header->maxval=1;
        if (header->kind!=1&&header->kind!=4) {
            if (if_number(data,size,&header->offset,&header->maxval)||!header->maxval||header->maxval>65535) return IF_INVALID;
        }
        if (header->kind>=4) {
            // Binary PNM has exactly one header separator (CRLF is one logical
            // separator). Do not discard raster bytes that happen to be space/#.
            if (header->offset>=size||!if_space(data[header->offset])) return IF_INVALID;
            if (data[header->offset++]=='\r'&&header->offset<size&&data[header->offset]=='\n') ++header->offset;
        }
    } else if (data[0]==0xff&&data[1]==0xd8) {
        // The current OpenMV JPEG decoder cannot safely validate arbitrary files
        // independently of imlib/EXIF/DSP assumptions. Reject explicitly.
        return IF_UNSUPPORTED;
    } else return IF_UNSUPPORTED;
    size_t bytes;
    return if_size(header->w,header->h,header->format,&bytes);
}

void if_get_rgb(const if_image *image,unsigned x,unsigned y,uint8_t rgb[3]) {
    size_t index=(size_t)y*image->w+x;
    if (image->format==IF_GRAYSCALE) rgb[0]=rgb[1]=rgb[2]=image->data[index];
    else {
        uint16_t pixel=(uint16_t)(image->data[2*index]|(unsigned)image->data[2*index+1]<<8);
        unsigned r=(pixel>>11)&31,g=(pixel>>5)&63,b=pixel&31;
        rgb[0]=(uint8_t)((r<<3)|(r>>2));rgb[1]=(uint8_t)((g<<2)|(g>>4));rgb[2]=(uint8_t)((b<<3)|(b>>2));
    }
}

void if_set_rgb(if_image *image,unsigned x,unsigned y,const uint8_t rgb[3]) {
    size_t index=(size_t)y*image->w+x;
    if (image->format==IF_GRAYSCALE) image->data[index]=(uint8_t)((77u*rgb[0]+150u*rgb[1]+29u*rgb[2]+128u)>>8);
    else {
        uint16_t pixel=(uint16_t)(((rgb[0]>>3)<<11)|((rgb[1]>>2)<<5)|(rgb[2]>>3));
        image->data[2*index]=(uint8_t)pixel;image->data[2*index+1]=(uint8_t)(pixel>>8);
    }
}

int if_decode(const uint8_t *data,size_t size,const if_header *header,if_image *image) {
    size_t bytes;
    if (if_size(header->w,header->h,header->format,&bytes)||!image->data||image->w!=header->w||
        image->h!=header->h||image->format!=header->format) return IF_BOUNDS;
    if (header->kind==7) return if_png_decode(data,size,image);
    if (header->kind==8) {
        for (unsigned y=0;y<image->h;++y) {
            size_t row=header->offset+(header->top_down?y:image->h-1-y)*header->stride;
            for (unsigned x=0;x<image->w;++x) {
                size_t p=row+x*(header->bits/8);
                uint8_t rgb[3]={data[p+2],data[p+1],data[p]};if_set_rgb(image,x,y,rgb);
            }
        }
        return IF_OK;
    }
    if (header->kind<1||header->kind>6) return IF_UNSUPPORTED;
    size_t p=header->offset;
    unsigned channels=header->format==IF_RGB565?3:1;
    if (header->kind==4) {
        size_t stride=(image->w+7u)/8u;
        if (p>size||stride*image->h>size-p) return IF_INVALID;
        for (unsigned y=0;y<image->h;++y) for (unsigned x=0;x<image->w;++x) {
            image->data[(size_t)y*image->w+x]=(data[p+y*stride+x/8]&(0x80u>>(x&7)))?0:255;
        }
        return IF_OK;
    }
    size_t sample_bytes=header->maxval>255?2:1;
    if (header->kind>=5 && (p>size||(size_t)image->w*image->h*channels*sample_bytes>size-p)) return IF_INVALID;
    for (unsigned y=0;y<image->h;++y) for (unsigned x=0;x<image->w;++x) {
        uint8_t rgb[3];
        for (unsigned c=0;c<channels;++c) {
            unsigned sample;
            if (header->kind<=3) {
                if (if_number(data,size,&p,&sample)) return IF_INVALID;
            } else if (sample_bytes==2) { sample=(unsigned)data[p]<<8|data[p+1];p+=2; }
            else sample=data[p++];
            if (sample>header->maxval) return IF_INVALID;
            rgb[c]=(uint8_t)((sample*255u+header->maxval/2)/header->maxval);
            if (header->kind==1) rgb[c]=(uint8_t)(255-rgb[c]);
        }
        if (channels==1) rgb[1]=rgb[2]=rgb[0];
        if_set_rgb(image,x,y,rgb);
    }
    return IF_OK;
}

int if_draw(if_image *dst,const if_image *src,if_roi roi,int x,int y,unsigned w,unsigned h,unsigned hint) {
    if (!dst->data||!src->data||!w||!h||w>IF_MAX_DIM||h>IF_MAX_DIM||roi.x<0||roi.y<0||
        !roi.w||!roi.h||(unsigned)roi.x>src->w||roi.w>src->w-(unsigned)roi.x||
        (unsigned)roi.y>src->h||roi.h>src->h-(unsigned)roi.y||
        hint&~(IF_BILINEAR|IF_CENTER|IF_SCALE_ASPECT_IGNORE|IF_BLACK_BACKGROUND)) return IF_BOUNDS;
    if (hint&IF_BLACK_BACKGROUND) {
        size_t size;if (if_size(dst->w,dst->h,dst->format,&size)) return IF_BOUNDS;
        memset(dst->data,0,size);
    }
    int start_x=x<0?0:x,start_y=y<0?0:y;
    int64_t end_x=(int64_t)x+w,end_y=(int64_t)y+h;
    if (end_x>(int64_t)dst->w) end_x=dst->w;
    if (end_y>(int64_t)dst->h) end_y=dst->h;
    for (int dy=start_y;dy<end_y;++dy) for (int dx=start_x;dx<end_x;++dx) {
        float sx=((float)((int64_t)dx-x)+.5f)*(float)roi.w/w-.5f;
        float sy=((float)((int64_t)dy-y)+.5f)*(float)roi.h/h-.5f;
        if (sx<0) sx=0;
        if (sy<0) sy=0;
        if (sx>roi.w-1) sx=(float)(roi.w-1);
        if (sy>roi.h-1) sy=(float)(roi.h-1);
        uint8_t rgb[3];
        if (hint&IF_BILINEAR) {
            unsigned x0=(unsigned)sx,y0=(unsigned)sy,x1=x0+1<roi.w?x0+1:x0,y1=y0+1<roi.h?y0+1:y0;
            uint8_t a[3],b[3],c[3],d[3];
            if_get_rgb(src,roi.x+x0,roi.y+y0,a);if_get_rgb(src,roi.x+x1,roi.y+y0,b);
            if_get_rgb(src,roi.x+x0,roi.y+y1,c);if_get_rgb(src,roi.x+x1,roi.y+y1,d);
            float fx=sx-x0,fy=sy-y0;
            for (unsigned k=0;k<3;++k) rgb[k]=(uint8_t)((a[k]*(1-fx)+b[k]*fx)*(1-fy)+(c[k]*(1-fx)+d[k]*fx)*fy+.5f);
        } else if_get_rgb(src,roi.x+(unsigned)(sx+.5f),roi.y+(unsigned)(sy+.5f),rgb);
        if_set_rgb(dst,(unsigned)dx,(unsigned)dy,rgb);
    }
    return IF_OK;
}

int if_to_tensor(const if_image *src,char dtype,void *output,size_t bytes) {
    if (dtype!='f'&&dtype!='b'&&dtype!='B') return IF_UNSUPPORTED;
    size_t image_bytes;
    if (if_size(src->w,src->h,src->format,&image_bytes)||!src->data||!output) return IF_BOUNDS;
    unsigned channels=src->format==IF_GRAYSCALE?1:3;
    size_t expected=(size_t)src->w*src->h*channels*(dtype=='f'?sizeof(float):1);
    if (expected>IF_MAX_BYTES||bytes<expected) return IF_BOUNDS;
    // Caller snapshots source if ranges overlap; no typed unaligned accesses.
    for (unsigned y=0;y<src->h;++y) for (unsigned x=0;x<src->w;++x) {
        uint8_t rgb[3];if_get_rgb(src,x,y,rgb);
        for (unsigned c=0;c<channels;++c) {
            size_t p=((size_t)y*src->w+x)*channels+c;
            if (dtype=='f') {float value=rgb[c];memcpy((uint8_t *)output+p*sizeof(float),&value,sizeof(value));}
            else ((uint8_t *)output)[p]=dtype=='b'?(uint8_t)(rgb[c]^0x80):rgb[c];
        }
    }
    return IF_OK;
}


// These operations never walk an unbounded off-image geometry. Rectangles and
// circles visit only clipped destination pixels; lines clip before Bresenham.
#include "image_font.h"
static int if_valid(const if_image *im) {
    size_t bytes;
    return im && im->data && if_size(im->w,im->h,im->format,&bytes)==IF_OK;
}
static void if_put(if_image *im,unsigned x,unsigned y,unsigned color) {
    size_t p=(size_t)y*im->w+x;
    if (im->format==IF_RGB565) {im->data[2*p]=(uint8_t)color;im->data[2*p+1]=(uint8_t)(color>>8);}
    else im->data[p]=(uint8_t)color;
}
static void if_fill_rect(if_image *im,int64_t x,int64_t y,int64_t w,int64_t h,unsigned color) {
    int64_t right=x+w,bottom=y+h;
    if (x<0) x=0;
    if (y<0) y=0;
    if (right>im->w) right=im->w;
    if (bottom>im->h) bottom=im->h;
    for (int64_t yy=y;yy<bottom;++yy) for (int64_t xx=x;xx<right;++xx) if_put(im,(unsigned)xx,(unsigned)yy,color);
}
int if_draw_rectangle(if_image *dst,int x,int y,int w,int h,unsigned color,unsigned thickness,int fill) {
    if (!if_valid(dst)||w<0||h<0||thickness>IF_MAX_DIM) return IF_BOUNDS;
    if (!w||!h) return IF_OK;
    if (fill) if_fill_rect(dst,x,y,w,h,color);
    else if (thickness) {
        int64_t t=thickness;
        if (2*t>=w||2*t>=h) if_fill_rect(dst,x,y,w,h,color);
        else {
            if_fill_rect(dst,x,y,w,t,color);if_fill_rect(dst,x,(int64_t)y+h-t,w,t,color);
            if_fill_rect(dst,x,(int64_t)y+t,t,h-2*t,color);if_fill_rect(dst,(int64_t)x+w-t,(int64_t)y+t,t,h-2*t,color);
        }
    }
    return IF_OK;
}
static int if_clip_test(double p,double q,double *lo,double *hi) {
    if (!p) return q>=0;
    double r=q/p;
    if (p<0) {if (r>*hi) return 0;if (r>*lo) *lo=r;}
    else {if (r<*lo) return 0;if (r<*hi) *hi=r;}
    return 1;
}
int if_draw_line(if_image *dst,int x0,int y0,int x1,int y1,unsigned color,unsigned thickness) {
    if (!if_valid(dst)||thickness>IF_MAX_DIM) return IF_BOUNDS;
    if (!thickness) return IF_OK;
    // Expand clipping for the square brush, then round to the nearest pixel.
    double ax=x0,ay=y0,dx=(double)x1-x0,dy=(double)y1-y0,lo=0,hi=1;
    int pad=(int)thickness/2;
    if (!if_clip_test(-dx,ax+pad,&lo,&hi)||!if_clip_test(dx,dst->w-1.0+pad-ax,&lo,&hi)||
        !if_clip_test(-dy,ay+pad,&lo,&hi)||!if_clip_test(dy,dst->h-1.0+pad-ay,&lo,&hi)) return IF_OK;
    x0=(int)lround(ax+lo*dx);y0=(int)lround(ay+lo*dy);
    x1=(int)lround(ax+hi*dx);y1=(int)lround(ay+hi*dy);
    int ix=x1>x0?x1-x0:x0-x1,iy=y1>y0?y1-y0:y0-y1;
    int sx=x0<x1?1:-1,sy=y0<y1?1:-1,err=ix-iy;
    for (;;) {
        if_fill_rect(dst,(int64_t)x0-pad,(int64_t)y0-pad,thickness,thickness,color);
        if (x0==x1&&y0==y1) break;
        int twice=2*err;
        if (twice>-iy) {err-=iy;x0+=sx;}
        if (twice<ix) {err+=ix;y0+=sy;}
    }
    return IF_OK;
}
int if_draw_circle(if_image *dst,int x,int y,int radius,unsigned color,unsigned thickness,int fill) {
    if (!if_valid(dst)||radius<0||radius>(int)IF_MAX_DIM||thickness>IF_MAX_DIM) return IF_BOUNDS;
    if (!fill&&!thickness) return IF_OK;
    int64_t outer=radius,inner=(int64_t)radius-thickness;
    int64_t left=(int64_t)x-outer,top=(int64_t)y-outer,right=(int64_t)x+outer,bottom=(int64_t)y+outer;
    if (left<0) left=0;
    if (top<0) top=0;
    if (right>=dst->w) right=dst->w-1;
    if (bottom>=dst->h) bottom=dst->h-1;
    for (int64_t yy=top;yy<=bottom;++yy) for (int64_t xx=left;xx<=right;++xx) {
        int64_t dx=xx-x,dy=yy-y,d2=dx*dx+dy*dy;
        if (d2<=outer*outer&&(fill||inner<0||d2>inner*inner)) if_put(dst,(unsigned)xx,(unsigned)yy,color);
    }
    return IF_OK;
}
int if_draw_string(if_image *dst,int x,int y,const char *text,size_t length,unsigned color,float scale,int x_spacing,int y_spacing) {
    if (!if_valid(dst)||!text||!isfinite(scale)||scale<=0||scale>16||length>IF_MAX_BYTES||
        x_spacing<0||x_spacing>(int)IF_MAX_DIM||y_spacing<0||y_spacing>(int)IF_MAX_DIM) return IF_BOUNDS;
    // Reject unsupported encoding before changing any pixels.
    for (size_t i=0;i<length;++i) if ((unsigned char)text[i]>126||((unsigned char)text[i]<32&&text[i]!='\n'&&text[i]!='\r'&&text[i]!='\t')) return IF_UNSUPPORTED;
    int gw=(int)ceilf(8*scale),gh=(int)ceilf(10*scale);
    int64_t xx=x,yy=y,step=gw+x_spacing;
    for (size_t i=0;i<length;++i) {
        unsigned char c=(unsigned char)text[i];
        if (c=='\r') {xx=x;continue;}
        if (c=='\n') {xx=x;yy+=gh+y_spacing;continue;}
        if (c=='\t') {xx+=4*step;continue;}
        const if_glyph *g=&if_font[c-32];
        // Only visit visible glyph pixels even for extreme starting positions.
        for (int py=0;py<gh;++py) if (yy+py>=0&&yy+py<dst->h) {
            unsigned row=(unsigned)(py/scale);if (row>9) row=9;
            for (int px=0;px<gw;++px) if (xx+px>=0&&xx+px<dst->w) {
                unsigned col=(unsigned)(px/scale);if (col>7) col=7;
                if (g->data[row]&(0x80u>>col)) if_put(dst,(unsigned)(xx+px),(unsigned)(yy+py),color);
            }
        }
        xx+=step;
    }
    return IF_OK;
}
int if_filter(if_image *dst,const if_image *src,unsigned radius,int median,float percentile) {
    if (!if_valid(dst)||!if_valid(src)||dst->data==src->data||dst->w!=src->w||dst->h!=src->h||
        dst->format!=src->format||radius>7||!isfinite(percentile)||percentile<0||percentile>1) return IF_BOUNDS;
    for (unsigned y=0;y<src->h;++y) for (unsigned x=0;x<src->w;++x) {
        uint8_t values[3][225];unsigned sums[3]={0},n=0;
        for (int dy=-(int)radius;dy<=(int)radius;++dy) for (int dx=-(int)radius;dx<=(int)radius;++dx) {
            int sx=(int)x+dx,sy=(int)y+dy;
            if (sx<0) sx=0;
            if (sy<0) sy=0;
            if (sx>=(int)src->w) sx=(int)src->w-1;
            if (sy>=(int)src->h) sy=(int)src->h-1;
            uint8_t rgb[3];if_get_rgb(src,(unsigned)sx,(unsigned)sy,rgb);
            for (unsigned c=0;c<3;++c) {values[c][n]=rgb[c];sums[c]+=rgb[c];}
            ++n;
        }
        uint8_t rgb[3];
        for (unsigned c=0;c<3;++c) {
            if (median) {
                // At most 225 values, no heap allocation or variable stack size.
                unsigned counts[256]={0},target=(unsigned)((n-1)*percentile),total=0,v=0;
                for (unsigned i=0;i<n;++i) ++counts[values[c][i]];
                while (v<255&&total+counts[v]<=target) total+=counts[v++];
                rgb[c]=(uint8_t)v;
            } else rgb[c]=(uint8_t)((sums[c]+n/2)/n);
        }
        if_set_rgb(dst,x,y,rgb);
    }
    return IF_OK;
}
