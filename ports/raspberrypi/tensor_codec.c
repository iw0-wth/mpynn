/* SPDX-License-Identifier: MIT */
#include "tensor_codec.h"
#include <limits.h>
#include <string.h>
#include <float.h>
_Static_assert(sizeof(float) == 4 && FLT_RADIX == 2 && FLT_MANT_DIG == 24 && FLT_MAX_EXP == 128,
               "tensor codec requires IEEE binary32 float");

uint16_t uml_codec_float_to_half(float value) {
    uint32_t bits; memcpy(&bits, &value, 4);
    uint32_t sign = (bits >> 16) & 0x8000u;
    uint32_t exponent = (bits >> 23) & 255u, fraction = bits & 0x7fffffu;
    if (exponent == 255) return fraction ? 0x7e00u : (uint16_t)(sign | 0x7c00u);
    if (exponent < 102) return (uint16_t)sign; /* below half of min subnormal */
    if (exponent > 142) return (uint16_t)(sign | 0x7c00u);
    uint32_t mantissa, remainder, halfway;
    if (exponent < 113) {
        unsigned shift = 126u - exponent; /* 14..24, no undefined shift */
        fraction |= 0x800000u;
        mantissa = fraction >> shift;
        remainder = fraction & ((1u << shift) - 1u);
        halfway = 1u << (shift - 1u);
    } else {
        mantissa = ((exponent - 112u) << 10) | (fraction >> 13);
        remainder = fraction & 0x1fffu;
        halfway = 0x1000u;
    }
    if (remainder > halfway || (remainder == halfway && (mantissa & 1u))) ++mantissa;
    return (uint16_t)(sign | mantissa); /* carry includes normal/overflow boundaries */
}

float uml_codec_half_to_float(uint16_t half) {
    uint32_t sign = ((uint32_t)half & 0x8000u) << 16;
    uint32_t exponent = (half >> 10) & 31u, fraction = half & 1023u, bits;
    if (exponent == 31) bits = sign | 0x7f800000u | (fraction << 13);
    else if (exponent) bits = sign | ((exponent + 112u) << 23) | (fraction << 13);
    else if (!fraction) bits = sign;
    else {
        unsigned e = 113;
        while (!(fraction & 1024u)) { fraction <<= 1; --e; }
        bits = sign | (e << 23) | ((fraction & 1023u) << 13);
    }
    float value; memcpy(&value, &bits, 4); return value;
}

int uml_codec_store_half(void *destination, size_t bytes, float value) {
    if (!destination || bytes != 2) return -1;
    uint16_t h = uml_codec_float_to_half(value);
    uint8_t *p = destination; p[0] = (uint8_t)h; p[1] = (uint8_t)(h >> 8); return 0;
}
int uml_codec_load_half(const void *source, size_t bytes, float *value) {
    if (!source || !value || bytes != 2) return -1;
    const uint8_t *p = source;
    *value = uml_codec_half_to_float((uint16_t)(p[0] | ((uint16_t)p[1] << 8))); return 0;
}
int uml_codec_store_int32(void *destination, size_t bytes, int64_t value) {
    if (!destination || bytes != 4 || value < INT32_MIN || value > INT32_MAX) return -1;
    uint32_t bits = (uint32_t)value; uint8_t *p = destination;
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(bits >> (8 * i));
    return 0;
}
int uml_codec_load_int32(const void *source, size_t bytes, int32_t *value) {
    if (!source || !value || bytes != 4) return -1;
    const uint8_t *p = source; uint32_t bits = 0;
    for (unsigned i = 0; i < 4; ++i) bits |= (uint32_t)p[i] << (8 * i);
    /* Do signed arithmetic in int64: avoid implementation-defined uint32 cast. */
    *value = (int32_t)((int64_t)bits - ((bits & 0x80000000u) ? INT64_C(4294967296) : 0));
    return 0;
}
int uml_codec_layout(unsigned ndim, const size_t *shape, char dtype, size_t *elements, size_t *bytes) {
    size_t item = dtype == UML_CODEC_FLOAT16 ? 2 : dtype == UML_CODEC_INT32 ? 4 : 0;
    if (!item || ndim > UML_CODEC_MAX_DIMS || (ndim && !shape) || !elements || !bytes) return -1;
    size_t count = 1;
    for (unsigned d = 0; d < ndim; ++d) {
        if (!shape[d] || count > UML_CODEC_MAX_BYTES / item / shape[d]) return -1;
        count *= shape[d];
    }
    *elements = count; *bytes = count * item; return 0;
}

#ifndef UML_CODEC_CORE_ONLY
#include "py/runtime.h"
#include "py/objarray.h"
#include "py/objtuple.h"
#include "py/objlist.h"
#include "py/objint.h"
#include "ndarray.h"

static void codec_layout(unsigned ndim, const size_t *source, char dtype,
                         size_t *shape, size_t *count, size_t *bytes) {
    if (uml_codec_layout(ndim, source, dtype, count, bytes)) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid tensor shape/dtype/size"));
    }
    for (unsigned d = 0; d < ndim; ++d) shape[d] = source[d];
}
static mp_obj_t codec_bytearray(size_t bytes) {
    mp_obj_t size = mp_obj_new_int_from_uint(bytes);
    return mp_call_function_1(MP_OBJ_FROM_PTR(&mp_type_bytearray), size);
}
static bool codec_raw(mp_obj_t value) {
    return mp_obj_is_type(value, &mp_type_bytes) || mp_obj_is_type(value, &mp_type_bytearray)
        || mp_obj_is_type(value, &mp_type_memoryview);
}
static void codec_copy(mp_obj_t destination, mp_obj_t source, size_t bytes) {
    mp_buffer_info_t from, to;
    mp_get_buffer_raise(source, &from, MP_BUFFER_READ);
    mp_get_buffer_raise(destination, &to, MP_BUFFER_WRITE);
    if (from.len != bytes || to.len != bytes) {
        mp_raise_ValueError(MP_ERROR_TEXT("tensor buffer size mismatch"));
    }
    memcpy(to.buf, from.buf, bytes);
}
static void codec_scalar(uint8_t *destination, char dtype, mp_obj_t value) {
    bool integer = mp_obj_is_int(value); /* excludes bool */
    if (dtype == UML_CODEC_INT32) {
        if (!integer) mp_raise_TypeError(MP_ERROR_TEXT("int32 requires integer values"));
        /* The checked signed32 byte conversion handles both smallint and MPZ,
         * independent of host word size. Do not use binary_set_val truncation. */
        mp_obj_int_to_bytes(value, 4, destination, false, true, true);
    } else {
        if (!integer && !mp_obj_is_float(value)) {
            mp_raise_TypeError(MP_ERROR_TEXT("float16 requires real numeric values"));
        }
        uml_codec_store_half(destination, 2, mp_obj_get_float_to_f(value));
    }
}
/* No Python hooks or allocation after the ndarray owner and scratch are rooted. */
static void codec_ndarray(mp_obj_t value, uint8_t *destination, unsigned ndim,
                          const size_t *shape, size_t count, char dtype) {
    ndarray_obj_t *array = MP_OBJ_TO_PTR(value);
    unsigned rank = ndim ? ndim : 1;
    if (rank > ULAB_MAX_DIMS || array->ndim != rank || array->len != count) {
        mp_raise_ValueError(MP_ERROR_TEXT("ndarray shape mismatch"));
    }
    bool is_float = array->dtype == NDARRAY_FLOAT;
    if (!is_float && array->dtype != NDARRAY_INT8 && array->dtype != NDARRAY_UINT8
        && array->dtype != NDARRAY_INT16 && array->dtype != NDARRAY_UINT16) {
        mp_raise_TypeError(MP_ERROR_TEXT("unsupported ndarray dtype"));
    }
    if (dtype == UML_CODEC_INT32 && is_float) {
        mp_raise_TypeError(MP_ERROR_TEXT("int32 requires integer ndarray"));
    }
    unsigned offset = ULAB_MAX_DIMS - rank;
    for (unsigned d = 0; d < rank; ++d) {
        if (array->shape[offset + d] != (ndim ? shape[d] : 1)) {
            mp_raise_ValueError(MP_ERROR_TEXT("ndarray shape mismatch"));
        }
    }
    /* ulab views have signed int32 strides. Bound cumulative offsets before
     * pointer arithmetic; actual allocation validity is ulab's owner contract. */
    int64_t low = 0, high = 0;
    for (unsigned d = offset; d < ULAB_MAX_DIMS; ++d) {
        int64_t extent = (int64_t)(array->shape[d] - 1) * array->strides[d];
        if (extent < 0) low += extent; else high += extent;
    }
    if (!array->array || low < PTRDIFF_MIN || high > PTRDIFF_MAX) {
        mp_raise_ValueError(MP_ERROR_TEXT("ndarray offset overflow"));
    }
    for (size_t i = 0; i < count; ++i) {
        size_t index = i; int64_t position = 0;
        for (unsigned d = ULAB_MAX_DIMS; d > offset; --d) {
            unsigned axis = d - 1;
            position += (int64_t)(index % array->shape[axis]) * array->strides[axis];
            index /= array->shape[axis];
        }
        mp_float_t number = ndarray_get_float_value((uint8_t *)array->array + (ptrdiff_t)position, array->dtype);
        if (dtype == UML_CODEC_FLOAT16) uml_codec_store_half(destination + 2 * i, 2, (float)number);
        else uml_codec_store_int32(destination + 4 * i, 4, (int64_t)number); /* <=16-bit input */
    }
}
mp_obj_t uml_codec_pack(mp_obj_t value, unsigned ndim, const size_t *source_shape, char dtype) {
    size_t shape[UML_CODEC_MAX_DIMS], count, bytes;
    codec_layout(ndim, source_shape, dtype, shape, &count, &bytes);
    mp_obj_t result = codec_bytearray(bytes);
    if (codec_raw(value)) { codec_copy(result, value, bytes); return result; }
    if (mp_obj_is_callable(value)) {
        mp_obj_t dims[UML_CODEC_MAX_DIMS];
        for (unsigned d = 0; d < ndim; ++d) dims[d] = mp_obj_new_int_from_uint(shape[d]);
        mp_obj_t args[] = {result, mp_obj_new_tuple(ndim, dims), mp_obj_new_int((unsigned char)dtype)};
        mp_call_function_n_kw(value, 3, 0, args);
        mp_buffer_info_t buffer; mp_get_buffer_raise(result, &buffer, MP_BUFFER_READ);
        if (buffer.len != bytes) mp_raise_ValueError(MP_ERROR_TEXT("callable resized tensor buffer"));
        return result;
    }
    mp_buffer_info_t buffer;
    if (mp_obj_is_type(value, &ulab_ndarray_type)) {
        mp_get_buffer_raise(result, &buffer, MP_BUFFER_WRITE);
        codec_ndarray(value, buffer.buf, ndim, shape, count, dtype);
        return result;
    }
    bool sequence = mp_obj_is_type(value, &mp_type_list) || mp_obj_is_type(value, &mp_type_tuple);
    if (!sequence && !mp_obj_is_type(value, &mp_type_array)) {
        mp_raise_TypeError(MP_ERROR_TEXT("expected ndarray/list/tuple/array/raw/callable"));
    }
    /* Allocate before reading mutable list items, then snapshot with no allocation. */
    mp_obj_t snapshot = mp_obj_new_tuple(count, NULL);
    mp_obj_tuple_t *tuple = MP_OBJ_TO_PTR(snapshot);
    if (sequence) {
        size_t length; mp_obj_t *items;
        mp_obj_get_array(value, &length, &items);
        if (length != count) mp_raise_ValueError(MP_ERROR_TEXT("tensor element count mismatch"));
        memcpy(tuple->items, items, count * sizeof(mp_obj_t));
    } else {
        mp_obj_iter_buf_t iter_buf; mp_obj_t iterator = mp_getiter(value, &iter_buf);
        for (size_t i = 0; i < count; ++i) {
            mp_obj_t item = mp_iternext(iterator);
            if (item == MP_OBJ_STOP_ITERATION) mp_raise_ValueError(MP_ERROR_TEXT("tensor element count mismatch"));
            tuple->items[i] = item;
        }
        if (mp_iternext(iterator) != MP_OBJ_STOP_ITERATION) mp_raise_ValueError(MP_ERROR_TEXT("tensor element count mismatch"));
    }
    for (size_t i = 0; i < count; ++i) {
        /* Scalar conversion can allocate: stage locally and reacquire destination. */
        uint8_t encoded[4]; codec_scalar(encoded, dtype, tuple->items[i]);
        mp_get_buffer_raise(result, &buffer, MP_BUFFER_WRITE);
        if (buffer.len != bytes) mp_raise_ValueError(MP_ERROR_TEXT("tensor buffer resized"));
        size_t item = dtype == UML_CODEC_FLOAT16 ? 2 : 4;
        memcpy((uint8_t *)buffer.buf + i * item, encoded, item);
    }
    return result;
}
mp_obj_t uml_codec_unpack(mp_obj_t raw, unsigned ndim, const size_t *source_shape,
                          char dtype, int raw_output) {
    size_t shape[UML_CODEC_MAX_DIMS], count, bytes;
    codec_layout(ndim, source_shape, dtype, shape, &count, &bytes);
    if (!codec_raw(raw)) mp_raise_TypeError(MP_ERROR_TEXT("expected raw bytes-like tensor"));
    if (raw_output) {
        mp_obj_t result = codec_bytearray(bytes); codec_copy(result, raw, bytes); return result;
    }
    unsigned rank = ndim ? ndim : 1;
    if (rank > ULAB_MAX_DIMS || count > INT32_MAX / sizeof(mp_float_t)) {
        mp_raise_ValueError(MP_ERROR_TEXT("float ndarray stride overflow"));
    }
    size_t dims[ULAB_MAX_DIMS] = {0};
    if (!ndim) dims[ULAB_MAX_DIMS - 1] = 1;
    for (unsigned d = 0; d < ndim; ++d) dims[ULAB_MAX_DIMS - ndim + d] = shape[d];
    ndarray_obj_t *array = ndarray_new_dense_ndarray(rank, dims, NDARRAY_FLOAT);
    mp_buffer_info_t source; mp_get_buffer_raise(raw, &source, MP_BUFFER_READ);
    if (source.len != bytes) mp_raise_ValueError(MP_ERROR_TEXT("tensor buffer size mismatch"));
    for (size_t i = 0; i < count; ++i) {
        if (dtype == UML_CODEC_FLOAT16) {
            float number; uml_codec_load_half((const uint8_t *)source.buf + 2 * i, 2, &number);
            ((mp_float_t *)array->array)[i] = number;
        } else {
            int32_t number; uml_codec_load_int32((const uint8_t *)source.buf + 4 * i, 4, &number);
            ((mp_float_t *)array->array)[i] = (mp_float_t)number;
        }
    }
    return MP_OBJ_FROM_PTR(array);
}
#endif
