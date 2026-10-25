// SPDX-License-Identifier: MIT
// Narrow compatibility header for the unchanged OpenMV LodePNG sources.
// No imlib image types, framebuffer, sensor, SIMD, or IDE dependencies.
#ifndef MPYNN_IMAGE_FILE_LODEPNG_CONFIG_H
#define MPYNN_IMAGE_FILE_LODEPNG_CONFIG_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#define IMLIB_ENABLE_PNG_DECODER
#define LODEPNG_NO_COMPILE_ANCILLARY_CHUNKS
#define LODEPNG_NO_COMPILE_DISK
#define LODEPNG_NO_COMPILE_CPP
#endif
