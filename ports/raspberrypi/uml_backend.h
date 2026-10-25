/* SPDX-License-Identifier: MIT */
#ifndef OPENMV_RASPBERRYPI_UML_BACKEND_H
#define OPENMV_RASPBERRYPI_UML_BACKEND_H

/*
 * C ABI for the Raspberry Pi 1B TFLM backend.
 *
 * The caller owns the model bytes, state storage, and tensor arena.  No
 * allocation, exception, RTTI, MicroPython, or Circle API is used here.
 */
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct uml_backend_context uml_backend_context_t;

typedef struct uml_tensor_info {
    void *data;
    size_t bytes;
    unsigned ndim;
    int32_t shape[4];
    /* Storage codes: f=float32, i=raw signed32, B/b/H/h=quantized.
     * Independent of ulab ndarray dtype; public float16 is unsupported. */
    char dtype;
    float scale;
    int32_t zero_point;
} uml_tensor_info;

typedef enum uml_backend_status {
    UML_BACKEND_OK = 0,
    UML_BACKEND_BAD_ARGUMENT = -1,
    UML_BACKEND_STATE_TOO_SMALL = -2,
    UML_BACKEND_STATE_MISALIGNED = -3,
    UML_BACKEND_ARENA_MISALIGNED = -4,
    UML_BACKEND_MODEL_INVALID = -5,
    UML_BACKEND_SCHEMA_UNSUPPORTED = -6,
    UML_BACKEND_TENSOR_ALLOCATION_FAILED = -7,
    UML_BACKEND_INDEX_INVALID = -8,
    UML_BACKEND_TENSOR_UNSUPPORTED = -9,
    UML_BACKEND_INVOKE_FAILED = -10
} uml_backend_status;

/* State storage is caller-owned and must be at least this size/alignment. */
size_t uml_backend_state_size(void);
size_t uml_backend_state_align(void);

/*
 * Constructs the context in state_storage. model_data and arena are borrowed
 * for the lifetime of the context. The model must remain alive until destroy.
 */
int uml_backend_create(void *state_storage, size_t state_size,
                       const void *model_data, size_t model_size,
                       void *arena, size_t arena_size);

/* Safe to call more than once after a successful or failed create. */
int uml_backend_destroy(void *state_storage);

size_t uml_backend_input_count(const void *state_storage);
size_t uml_backend_output_count(const void *state_storage);

/* input_output is zero for an input tensor and nonzero for an output tensor. */
int uml_backend_tensor_info(const void *state_storage, int input_output,
                            size_t index, uml_tensor_info *info);

int uml_backend_invoke(void *state_storage);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* OPENMV_RASPBERRYPI_UML_BACKEND_H */
