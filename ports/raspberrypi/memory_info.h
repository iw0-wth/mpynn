// SPDX-License-Identifier: MIT
#ifndef MPYNN_RPI_MEMORY_INFO_H
#define MPYNN_RPI_MEMORY_INFO_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
size_t mpynn_circle_low_free(void);
size_t mpynn_gc_heap_size(void);
size_t mpynn_circle_heap_reserve(void);
#ifdef __cplusplus
}
#endif
#endif
