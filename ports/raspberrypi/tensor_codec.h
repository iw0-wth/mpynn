/* SPDX-License-Identifier: MIT */
#ifndef OPENMV_RASPBERRYPI_TENSOR_CODEC_H
#define OPENMV_RASPBERRYPI_TENSOR_CODEC_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Tensor storage codes, NOT ulab dtypes. Wire bytes are explicitly little endian. */
#define UML_CODEC_FLOAT16 'e'
#define UML_CODEC_INT32 'i'
#define UML_CODEC_MAX_BYTES (64u * 1024u * 1024u)
#define UML_CODEC_MAX_DIMS 4u
/* No allocation, alignment requirement, or host floating-point rounding dependency.
 * Conversion stages through IEEE binary32; NaN encodes as canonical 0x7e00.
 * Finite overflow becomes signed infinity; rounding is nearest, ties to even. */
uint16_t uml_codec_float_to_half(float value);
float uml_codec_half_to_float(uint16_t bits);
/* Return 0 on success, -1 on null/invalid/range/size input. Exact byte lengths.
 * Destinations remain untouched on error. Unaligned storage is supported. */
int uml_codec_store_half(void *destination, size_t bytes, float value);
int uml_codec_load_half(const void *source, size_t bytes, float *value);
int uml_codec_store_int32(void *destination, size_t bytes, int64_t value);
int uml_codec_load_int32(const void *source, size_t bytes, int32_t *value);
/* Validate positive shape product and bounds; ndim=0 denotes one scalar.
 * shape may be NULL only for ndim=0. Output arguments untouched on error. */
int uml_codec_layout(unsigned ndim, const size_t *shape, char dtype,
                     size_t *elements, size_t *bytes);
#ifndef UML_CODEC_CORE_ONLY
#include "py/obj.h"
/* C helpers only: not registered as a Python module or linked by parent build.
 * shape is copied before allocation/callback; caller supplies a readable shape.
 * pack accepts ndarray, flat list/tuple, numeric array.array, raw bytes-like,
 * or callback(owned_zeroed_bytearray, shape_tuple, ord(dtype)).
 * i requires exact integer values (bool and floats rejected), checked signed32.
 * e accepts exact int/float, stages through binary32. Raw bytes preserve all bits.
 * ndarray scalar input uses shape (1,). Other ndarray shapes match exactly.
 * Returned bytearray/ndarray always owns its data, never borrows arena storage.
 * unpack accepts raw bytes-like only; raw_output!=0 preserves exact bits, else
 * emits float ndarray (int32 values outside +/-2**24 may round on float32 ports).
 * Caller must keep any model busy/lifetime guard active across these helpers.
 * Validation raises ValueError/TypeError/OverflowError via MicroPython NLR. */
mp_obj_t uml_codec_pack(mp_obj_t value, unsigned ndim, const size_t *shape, char dtype);
mp_obj_t uml_codec_unpack(mp_obj_t raw, unsigned ndim, const size_t *shape,
                          char dtype, int raw_output);
#endif
#ifdef __cplusplus
}
#endif
#endif
