// SPDX-License-Identifier: MIT
// Native MicroPython binding for the caller-owned TFLM C ABI.
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "py/runtime.h"
#include "py/objlist.h"
#include "py/objtuple.h"
#include "py/objstr.h"
#include "py/stream.h"
#include "extmod/vfs.h"
#include "ndarray.h"
#include "uml_backend.h"
#include "tensor_codec.h"

#define UML_MODEL_MAX (32u * 1024u * 1024u)
#define UML_ARENA_DEFAULT (2u * 1024u * 1024u)
#define UML_ARENA_MAX (64u * 1024u * 1024u)
#define UML_TENSOR_COUNT_MAX (128u)

typedef struct {
    mp_obj_base_t base;
    void *model_raw, *state_raw, *arena_raw;
    void *model_data, *state, *arena;
    size_t model_size, arena_size, inputs, outputs;
    mp_obj_t input_shape, input_scale, input_zero_point, input_dtype;
    mp_obj_t output_shape, output_scale, output_zero_point, output_dtype;
    mp_obj_t postprocess;
    bool live, busy;
} uml_model_obj_t;

static const mp_obj_type_t uml_model_type;
// MicroPython's native-base __init__ wrapper calls make_new and replaces the
// native subobject. Block construction during callbacks too, so super().__init__
// cannot replace an in-flight model and expose a second lifetime accidentally.
static unsigned uml_prediction_depth;

static const char *uml_status_name(int status) {
    switch (status) {
        case UML_BACKEND_BAD_ARGUMENT: return "bad argument";
        case UML_BACKEND_STATE_TOO_SMALL: return "state storage too small";
        case UML_BACKEND_STATE_MISALIGNED: return "state misaligned";
        case UML_BACKEND_ARENA_MISALIGNED: return "arena misaligned";
        case UML_BACKEND_MODEL_INVALID: return "model invalid (FlatBuffers/schema verification)";
        case UML_BACKEND_SCHEMA_UNSUPPORTED: return "schema unsupported";
        case UML_BACKEND_TENSOR_ALLOCATION_FAILED: return "tensor allocation failed";
        case UML_BACKEND_INDEX_INVALID: return "tensor index invalid";
        case UML_BACKEND_TENSOR_UNSUPPORTED: return "tensor unsupported";
        case UML_BACKEND_INVOKE_FAILED: return "invoke failed";
        default: return "unknown backend error";
    }
}

static void uml_status(int status) {
    if (status != UML_BACKEND_OK) {
        mp_raise_msg_varg(&mp_type_RuntimeError,
                          MP_ERROR_TEXT("TFLM backend error %d (%s)"), status,
                          uml_status_name(status));
    }
}

static void *uml_aligned_alloc(void **owner, size_t bytes, size_t alignment) {
    if (!alignment || (alignment & (alignment - 1)) || alignment > 4096 ||
        bytes > SIZE_MAX - alignment + 1) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid backend storage size/alignment"));
    }
    *owner = m_new0(uint8_t, bytes + alignment - 1);
    return (void *)(((uintptr_t)*owner + alignment - 1) & ~(uintptr_t)(alignment - 1));
}

static void uml_release(uml_model_obj_t *self) {
    if (self->state != NULL) {
        // Also valid after a failed create; state remains rooted until destroy.
        uml_backend_destroy(self->state);
    }
    self->live = false;
    self->state = self->model_data = self->arena = NULL;
    self->state_raw = self->model_raw = self->arena_raw = NULL;
}

static void uml_require_live(uml_model_obj_t *self) {
    if (!self->live) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("model is deinitialized"));
    }
}

static size_t uml_dtype_size(char dtype) {
    switch (dtype) {
        case 'f': return sizeof(float);
        case 'i': return 4;
        case 'b': case 'B': return 1;
        case 'h': case 'H': return 2;
        default: mp_raise_ValueError(MP_ERROR_TEXT("unsupported tensor dtype"));
    }
}

static size_t uml_validate_tensor(const uml_tensor_info *info) {
    if (info->ndim > ULAB_MAX_DIMS || info->data == NULL) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid tensor rank/data"));
    }
    size_t elements = 1;
    for (unsigned d = 0; d < info->ndim; ++d) {
        if (info->shape[d] <= 0 || elements > SIZE_MAX / (size_t)info->shape[d]) {
            mp_raise_ValueError(MP_ERROR_TEXT("invalid tensor shape"));
        }
        elements *= (size_t)info->shape[d];
    }
    size_t itemsize = uml_dtype_size(info->dtype);
    if (elements > SIZE_MAX / itemsize || elements * itemsize != info->bytes ||
        (info->dtype != 'f' && info->dtype != 'i' && (!(info->scale > 0) || !isfinite(info->scale)))) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid tensor bytes/quantization"));
    }
    return elements;
}

static uml_tensor_info uml_tensor(uml_model_obj_t *self, int output, size_t index) {
    uml_tensor_info info = {0};
    uml_status(uml_backend_tensor_info(self->state, output, index, &info));
    uml_validate_tensor(&info);
    return info;
}

static mp_obj_t uml_shape(const uml_tensor_info *info) {
    mp_obj_t shape[ULAB_MAX_DIMS];
    for (unsigned d = 0; d < info->ndim; ++d) {
        shape[d] = mp_obj_new_int(info->shape[d]);
    }
    return mp_obj_new_tuple(info->ndim, shape);
}

static void uml_metadata(uml_model_obj_t *self, int output) {
    size_t count = output ? self->outputs : self->inputs;
    mp_obj_t shapes = mp_obj_new_tuple(count, NULL);
    mp_obj_t scales = mp_obj_new_tuple(count, NULL);
    mp_obj_t zeros = mp_obj_new_tuple(count, NULL);
    mp_obj_t dtypes = mp_obj_new_tuple(count, NULL);
    for (size_t i = 0; i < count; ++i) {
        uml_tensor_info info = uml_tensor(self, output, i);
        ((mp_obj_tuple_t *)MP_OBJ_TO_PTR(shapes))->items[i] = uml_shape(&info);
        ((mp_obj_tuple_t *)MP_OBJ_TO_PTR(scales))->items[i] = mp_obj_new_float(info.scale);
        ((mp_obj_tuple_t *)MP_OBJ_TO_PTR(zeros))->items[i] = mp_obj_new_int(info.zero_point);
        ((mp_obj_tuple_t *)MP_OBJ_TO_PTR(dtypes))->items[i] = mp_obj_new_str(&info.dtype, 1);
    }
    if (output) {
        self->output_shape = shapes; self->output_scale = scales;
        self->output_zero_point = zeros; self->output_dtype = dtypes;
    } else {
        self->input_shape = shapes; self->input_scale = scales;
        self->input_zero_point = zeros; self->input_dtype = dtypes;
    }
}

static void uml_load_model(uml_model_obj_t *self, mp_obj_t source) {
    if (!mp_obj_is_str(source)) {
        mp_buffer_info_t buffer;
        mp_get_buffer_raise(source, &buffer, MP_BUFFER_READ);
        if (!buffer.len || buffer.len > UML_MODEL_MAX) {
            mp_raise_ValueError(MP_ERROR_TEXT("model size out of bounds"));
        }
        self->model_size = buffer.len;
        self->model_data = uml_aligned_alloc(&self->model_raw, buffer.len, 16);
        memcpy(self->model_data, buffer.buf, buffer.len);
        return;
    }
    mp_obj_t open_args[] = {source, MP_OBJ_NEW_QSTR(MP_QSTR_rb)};
    mp_obj_t file = mp_vfs_open(2, open_args, (mp_map_t *)&mp_const_empty_map);
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        int error = 0;
        mp_off_t size = mp_stream_seek(file, 0, MP_SEEK_END, &error);
        if (size == (mp_off_t)-1) { mp_raise_OSError(error); }
        if (size <= 0 || (uint64_t)size > UML_MODEL_MAX) {
            mp_raise_ValueError(MP_ERROR_TEXT("model size out of bounds"));
        }
        if (mp_stream_seek(file, 0, MP_SEEK_SET, &error) == (mp_off_t)-1) {
            mp_raise_OSError(error);
        }
        self->model_size = (size_t)size;
        self->model_data = uml_aligned_alloc(&self->model_raw, self->model_size, 16);
        mp_uint_t received = mp_stream_read_exactly(file, self->model_data, self->model_size, &error);
        if (error) { mp_raise_OSError(error); }
        if (received != self->model_size) {
            mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("short model read"));
        }
        nlr_pop();
    } else {
        // Closing must not replace the original load exception.
        nlr_buf_t close_nlr;
        if (nlr_push(&close_nlr) == 0) { mp_stream_close(file); nlr_pop(); }
        nlr_jump(nlr.ret_val);
    }
    mp_stream_close(file);
}

static mp_obj_t uml_model_make_new(const mp_obj_type_t *type, size_t n_args,
                                  size_t n_kw, const mp_obj_t *all_args) {
    (void)type;
    if (uml_prediction_depth) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("cannot initialize a model during prediction"));
    }
    enum { ARG_path, ARG_postprocess, ARG_arena_size };
    static const mp_arg_t allowed[] = {
        {MP_QSTR_path, MP_ARG_OBJ | MP_ARG_REQUIRED, {.u_obj = MP_OBJ_NULL}},
        {MP_QSTR_postprocess, MP_ARG_OBJ, {.u_rom_obj = MP_ROM_NONE}},
        {MP_QSTR_arena_size, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = UML_ARENA_DEFAULT}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args, MP_ARRAY_SIZE(allowed), allowed, args);
    if (args[ARG_arena_size].u_int < 1024 || args[ARG_arena_size].u_int > (mp_int_t)UML_ARENA_MAX) {
        mp_raise_ValueError(MP_ERROR_TEXT("arena_size must be 1024..67108864"));
    }
    if (args[ARG_postprocess].u_obj != mp_const_none && !mp_obj_is_callable(args[ARG_postprocess].u_obj)) {
        mp_raise_TypeError(MP_ERROR_TEXT("postprocess must be callable"));
    }
    uml_model_obj_t *self = mp_obj_malloc_with_finaliser(uml_model_obj_t, &uml_model_type);
    memset((uint8_t *)self + sizeof(self->base), 0, sizeof(*self) - sizeof(self->base));
    self->postprocess = args[ARG_postprocess].u_obj;
    self->arena_size = (size_t)args[ARG_arena_size].u_int;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        uml_load_model(self, args[ARG_path].u_obj);
        self->arena = uml_aligned_alloc(&self->arena_raw, self->arena_size, 16);
        size_t state_size = uml_backend_state_size();
        if (!state_size || state_size > UML_ARENA_MAX) {
            mp_raise_ValueError(MP_ERROR_TEXT("backend state size out of bounds"));
        }
        self->state = uml_aligned_alloc(&self->state_raw, state_size, uml_backend_state_align());
        uml_status(uml_backend_create(self->state, state_size, self->model_data,
                                     self->model_size, self->arena, self->arena_size));
        self->inputs = uml_backend_input_count(self->state);
        self->outputs = uml_backend_output_count(self->state);
        if (!self->inputs || !self->outputs || self->inputs > UML_TENSOR_COUNT_MAX ||
            self->outputs > UML_TENSOR_COUNT_MAX) {
            mp_raise_ValueError(MP_ERROR_TEXT("unsupported tensor count"));
        }
        uml_metadata(self, 0);
        uml_metadata(self, 1);
        self->live = true;
        nlr_pop();
    } else {
        uml_release(self);
        nlr_jump(nlr.ret_val);
    }
    return MP_OBJ_FROM_PTR(self);
}

// Saturate before converting, avoiding undefined float-to-int conversions.
// Quantization rounds half away from zero and handles signed zero_points.
static int32_t uml_quantize(float value, float scale, int32_t zero, int32_t low, int32_t high) {
    float q = roundf(value / scale) + (float)zero;
    if (isnan(q)) { mp_raise_ValueError(MP_ERROR_TEXT("NaN quantized input")); }
    if (q <= (float)low) { return low; }
    if (q >= (float)high) { return high; }
    return (int32_t)q;
}

static void uml_store(void *data, size_t index, const uml_tensor_info *info, float value) {
    switch (info->dtype) {
        case 'f': ((float *)data)[index] = value; break;
        case 'b': ((int8_t *)data)[index] = uml_quantize(value, info->scale, info->zero_point, INT8_MIN, INT8_MAX); break;
        case 'B': ((uint8_t *)data)[index] = uml_quantize(value, info->scale, info->zero_point, 0, UINT8_MAX); break;
        case 'h': ((int16_t *)data)[index] = uml_quantize(value, info->scale, info->zero_point, INT16_MIN, INT16_MAX); break;
        case 'H': ((uint16_t *)data)[index] = uml_quantize(value, info->scale, info->zero_point, 0, UINT16_MAX); break;
    }
}

static void uml_array_input(const uml_tensor_info *info, ndarray_obj_t *array) {
    if (array->dtype == NDARRAY_COMPLEX || array->ndim != info->ndim) {
        mp_raise_ValueError(MP_ERROR_TEXT("input shape/dtype does not match tensor"));
    }
    size_t offset = ULAB_MAX_DIMS - array->ndim;
    size_t elements = uml_validate_tensor(info);
    if (array->len != elements) { mp_raise_ValueError(MP_ERROR_TEXT("input size does not match tensor")); }
    for (unsigned d = 0; d < info->ndim; ++d) {
        if (array->shape[offset + d] != (size_t)info->shape[d]) {
            mp_raise_ValueError(MP_ERROR_TEXT("input shape does not match tensor"));
        }
    }
    for (size_t i = 0; i < elements; ++i) {
        size_t remaining = i;
        ptrdiff_t byte_offset = 0;
        for (unsigned d = info->ndim; d > 0; --d) {
            size_t axis = offset + d - 1;
            byte_offset += (ptrdiff_t)(remaining % array->shape[axis]) * array->strides[axis];
            remaining /= array->shape[axis];
        }
        float value = ndarray_get_float_value((uint8_t *)array->array + byte_offset, array->dtype);
        uml_store(info->data, i, info, value);
    }
}

static void uml_input(uml_model_obj_t *self, size_t index, mp_obj_t value) {
    uml_tensor_info info = uml_tensor(self, 0, index);
    if (info.dtype == 'i') {
        size_t shape[UML_CODEC_MAX_DIMS];
        for (unsigned d = 0; d < info.ndim; ++d) shape[d] = (size_t)info.shape[d];
        // Conversion is transactional and never passes an arena pointer to Python.
        mp_obj_t scratch = uml_codec_pack(value, info.ndim, shape, 'i');
        mp_buffer_info_t buffer;
        mp_get_buffer_raise(scratch, &buffer, MP_BUFFER_READ);
        if (buffer.len != info.bytes) mp_raise_ValueError(MP_ERROR_TEXT("int32 tensor buffer size mismatch"));
        memcpy(info.data, buffer.buf, info.bytes);
    } else if (mp_obj_is_callable(value)) {
        // A normal bytearray owns this memory even if the callback retains it.
        // Never let a Python object borrow a pointer into the backend arena.
        mp_obj_t bytearray_args[] = {mp_obj_new_int_from_uint(info.bytes)};
        mp_obj_t scratch = mp_call_function_n_kw(MP_OBJ_FROM_PTR(&mp_type_bytearray), 1, 0, bytearray_args);
        mp_obj_t call_args[] = {scratch, uml_shape(&info), mp_obj_new_int((unsigned char)info.dtype)};
        mp_call_function_n_kw(value, 3, 0, call_args);
        mp_buffer_info_t buffer;
        mp_get_buffer_raise(scratch, &buffer, MP_BUFFER_READ);
        if (buffer.len != info.bytes) {
            mp_raise_ValueError(MP_ERROR_TEXT("callable changed input buffer size"));
        }
        memcpy(info.data, buffer.buf, info.bytes);
    } else if (mp_obj_is_type(value, &ulab_ndarray_type)) {
        uml_array_input(&info, MP_OBJ_TO_PTR(value));
    } else {
        mp_raise_TypeError(MP_ERROR_TEXT("input must be an ndarray or callable"));
    }
}

static float uml_output_value(const uml_tensor_info *info, size_t index) {
    float value;
    switch (info->dtype) {
        case 'f': return ((const float *)info->data)[index];
        case 'i': {
            int32_t integer;
            if (uml_codec_load_int32((const uint8_t *)info->data + 4 * index, 4, &integer)) {
                mp_raise_ValueError(MP_ERROR_TEXT("invalid int32 output"));
            }
            // NDARRAY_FLOAT uses the port float precision; raw_output preserves bits.
            return (float)integer;
        }
        case 'b': value = ((const int8_t *)info->data)[index]; break;
        case 'B': value = ((const uint8_t *)info->data)[index]; break;
        case 'h': value = ((const int16_t *)info->data)[index]; break;
        default: value = ((const uint16_t *)info->data)[index]; break;
    }
    return (value - (float)info->zero_point) * info->scale;
}

static mp_obj_t uml_outputs(uml_model_obj_t *self, bool raw_output) {
    mp_obj_t outputs = mp_obj_new_list(self->outputs, NULL);
    for (size_t i = 0; i < self->outputs; ++i) {
        uml_tensor_info info = uml_tensor(self, 1, i);
        size_t elements = uml_validate_tensor(&info);
        if (raw_output) {
            // Copies arena bytes into independently owned storage for every dtype.
            mp_obj_t raw = mp_obj_new_bytearray(info.bytes, info.data);
            ((mp_obj_list_t *)MP_OBJ_TO_PTR(outputs))->items[i] = raw;
            continue;
        }
        size_t shape[ULAB_MAX_DIMS] = {0};
        // ulab represents a scalar tensor as a one-element vector.
        unsigned rank = info.ndim ? info.ndim : 1;
        if (!info.ndim) { shape[ULAB_MAX_DIMS - 1] = 1; }
        for (unsigned d = 0; d < info.ndim; ++d) { shape[ULAB_MAX_DIMS - info.ndim + d] = info.shape[d]; }
        ndarray_obj_t *array = ndarray_new_dense_ndarray(rank, shape, NDARRAY_FLOAT);
        for (size_t j = 0; j < elements; ++j) {
            ((mp_float_t *)array->array)[j] = uml_output_value(&info, j);
        }
        ((mp_obj_list_t *)MP_OBJ_TO_PTR(outputs))->items[i] = MP_OBJ_FROM_PTR(array);
    }
    return outputs;
}

static mp_obj_t uml_model_predict(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kwargs) {
    static const mp_arg_t allowed[] = {
        {MP_QSTR_callback, MP_ARG_OBJ, {.u_rom_obj = MP_ROM_NONE}},
        {MP_QSTR_raw_output, MP_ARG_BOOL | MP_ARG_KW_ONLY, {.u_bool = false}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args - 2, pos_args + 2, kwargs, MP_ARRAY_SIZE(allowed), allowed, args);
    uml_model_obj_t *self = MP_OBJ_TO_PTR(pos_args[0]);
    uml_require_live(self);
    if (self->busy) { mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("model is busy")); }
    if (!mp_obj_is_type(pos_args[1], &mp_type_list) && !mp_obj_is_type(pos_args[1], &mp_type_tuple)) {
        mp_raise_TypeError(MP_ERROR_TEXT("inputs must be a list or tuple"));
    }
    size_t count;
    mp_obj_t *inputs;
    mp_obj_get_array(pos_args[1], &count, &inputs);
    if (count != self->inputs) { mp_raise_ValueError(MP_ERROR_TEXT("input count does not match model")); }
    mp_obj_t callback = args[0].u_obj == mp_const_none ? self->postprocess : args[0].u_obj;
    if (callback != mp_const_none && !mp_obj_is_callable(callback)) {
        mp_raise_TypeError(MP_ERROR_TEXT("callback must be callable"));
    }
    // Snapshot input references: a callback may resize or mutate the caller's
    // list, invalidating its backing items pointer while prediction is active.
    mp_obj_t input_snapshot = mp_obj_new_tuple(count, inputs);
    self->busy = true;
    ++uml_prediction_depth;
    nlr_buf_t nlr;
    mp_obj_t result;
    if (nlr_push(&nlr) == 0) {
        for (size_t i = 0; i < count; ++i) {
            uml_input(self, i, ((mp_obj_tuple_t *)MP_OBJ_TO_PTR(input_snapshot))->items[i]);
        }
        uml_status(uml_backend_invoke(self->state));
        result = uml_outputs(self, args[1].u_bool);
        if (callback != mp_const_none) {
            mp_obj_t call_args[] = {pos_args[0], pos_args[1], result};
            result = mp_call_function_n_kw(callback, 3, 0, call_args);
        }
        nlr_pop();
    } else {
        self->busy = false;
        --uml_prediction_depth;
        nlr_jump(nlr.ret_val);
    }
    self->busy = false;
    --uml_prediction_depth;
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(uml_model_predict_obj, 2, uml_model_predict);

static mp_obj_t uml_model_deinit(mp_obj_t self_in) {
    uml_model_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->busy) { mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("model is busy")); }
    uml_release(self);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(uml_model_deinit_obj, uml_model_deinit);

static void uml_model_attr(mp_obj_t self_in, qstr attr, mp_obj_t *dest) {
    uml_model_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (dest[0] != MP_OBJ_NULL) { return; }
    switch (attr) {
        case MP_QSTR_input_shape: dest[0] = self->input_shape; break;
        case MP_QSTR_input_scale: dest[0] = self->input_scale; break;
        case MP_QSTR_input_zero_point: dest[0] = self->input_zero_point; break;
        case MP_QSTR_input_dtype: dest[0] = self->input_dtype; break;
        case MP_QSTR_output_shape: dest[0] = self->output_shape; break;
        case MP_QSTR_output_scale: dest[0] = self->output_scale; break;
        case MP_QSTR_output_zero_point: dest[0] = self->output_zero_point; break;
        case MP_QSTR_output_dtype: dest[0] = self->output_dtype; break;
        case MP_QSTR_postprocess: dest[0] = self->postprocess; break;
        case MP_QSTR_len: dest[0] = mp_obj_new_int_from_uint(self->model_size); break;
        case MP_QSTR_ram: case MP_QSTR_memory_size: dest[0] = mp_obj_new_int_from_uint(self->arena_size); break;
        case MP_QSTR_num_outputs: dest[0] = mp_obj_new_int_from_uint(self->outputs); break;
        case MP_QSTR_num_inputs: dest[0] = mp_obj_new_int_from_uint(self->inputs); break;
        default: dest[1] = MP_OBJ_SENTINEL; break;
    }
}

static const mp_rom_map_elem_t uml_model_locals_table[] = {
    {MP_ROM_QSTR(MP_QSTR_predict), MP_ROM_PTR(&uml_model_predict_obj)},
    {MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&uml_model_deinit_obj)},
    {MP_ROM_QSTR(MP_QSTR___del__), MP_ROM_PTR(&uml_model_deinit_obj)},
};
static MP_DEFINE_CONST_DICT(uml_model_locals, uml_model_locals_table);
static MP_DEFINE_CONST_OBJ_TYPE(uml_model_type, MP_QSTR_Model, MP_TYPE_FLAG_NONE,
    make_new, uml_model_make_new, attr, uml_model_attr, locals_dict, &uml_model_locals);
static const mp_rom_map_elem_t uml_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_uml)},
    {MP_ROM_QSTR(MP_QSTR_Model), MP_ROM_PTR(&uml_model_type)},
};
static MP_DEFINE_CONST_DICT(uml_globals, uml_globals_table);
const mp_obj_module_t uml_module = {{&mp_type_module}, (mp_obj_dict_t *)&uml_globals};
MP_REGISTER_MODULE(MP_QSTR_uml, uml_module);
