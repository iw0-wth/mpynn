// SPDX-License-Identifier: MIT
// Decode through the unchanged OpenMV LodePNG 20220109 source using GC storage.
#include "image_core.h"
#include "lodepng.h"
#include "py/gc.h"

// These allocators never collect or raise while the codec holds temporary
// pointers. LodePNG returns an error on exhaustion, releases its temporaries,
// and the caller can then raise safely. Total live codec allocation is bounded.
static size_t if_png_allocated;
void *lodepng_malloc(size_t size) {
    if (!size) size=1;
    if (size>IF_MAX_BYTES||if_png_allocated>IF_MAX_BYTES-size) return NULL;
    void *ptr=gc_alloc(size,0);
    if (ptr) {
        size_t actual=gc_nbytes(ptr);
        if (actual>IF_MAX_BYTES-if_png_allocated) {gc_free(ptr);return NULL;}
        if_png_allocated+=actual;
    }
    return ptr;
}
void lodepng_free(void *ptr) {
    if (ptr) {size_t size=gc_nbytes(ptr);if_png_allocated-=size;gc_free(ptr);}
}
void *lodepng_realloc(void *ptr,size_t size) {
    if (!ptr) return lodepng_malloc(size);
    if (!size) {lodepng_free(ptr);return NULL;}
    size_t old=gc_nbytes(ptr);
    if (size>IF_MAX_BYTES||if_png_allocated-old>IF_MAX_BYTES-size) return NULL;
    // Reserve rounding space: GC blocks are at most four machine words.
    size_t slack=4*sizeof(uintptr_t)-1;
    if (size>IF_MAX_BYTES-slack||if_png_allocated-old>IF_MAX_BYTES-size-slack) return NULL;
    void *resized=gc_realloc(ptr,size,true);
    if (resized) if_png_allocated=if_png_allocated-old+gc_nbytes(resized);
    return resized;
}

int if_png_decode(const uint8_t *data,size_t size,if_image *output) {
    LodePNGState state;
    lodepng_state_init(&state);
    state.info_raw.colortype=LCT_RGBA;
    state.info_raw.bitdepth=8;
    state.decoder.zlibsettings.max_output_size=IF_MAX_BYTES;
    unsigned width=0,height=0;
    unsigned char *rgba=NULL;
    if_png_allocated=0;
    unsigned error=lodepng_decode(&rgba,&width,&height,&state,data,size);
    if (!error&&(width!=output->w||height!=output->h)) error=93;
    if (!error) {
        for (unsigned y=0;y<height;++y) for (unsigned x=0;x<width;++x) {
            const uint8_t *p=rgba+4*((size_t)y*width+x);
            // Composite alpha over black for the RGB565 image format.
            uint8_t rgb[3]={(uint8_t)((p[0]*p[3]+127)/255),
                (uint8_t)((p[1]*p[3]+127)/255),(uint8_t)((p[2]*p[3]+127)/255)};
            if_set_rgb(output,x,y,rgb);
        }
    }
    lodepng_free(rgba);
    lodepng_state_cleanup(&state);
    return error?(error==83?IF_NOMEM:IF_INVALID):IF_OK;
}
