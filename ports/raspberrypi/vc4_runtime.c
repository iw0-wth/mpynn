/* SPDX-License-Identifier: MIT
 *
 * Port-owned VideoCore IV runtime boundary.
 *
 * Host/non-BCM builds deliberately report VC4 unavailable. BCM2835 ARM builds
 * compile the Circle-backed implementation from vc4_runtime_bcm2835.cpp instead.
 * This file still provides the explicit CPU reference matvec used by tests.
 */
#include "vc4_runtime.h"

#include <stddef.h>
#include <stdint.h>

#define VC4_STATUS_INITIAL VC4_STATUS_UNAVAILABLE

static vc4_status_t g_runtime_status = VC4_STATUS_INITIAL;
static int g_runtime_enabled = 1;

static int vc4_is_power_of_two(uint32_t value)
{
    return value != 0u && (value & (value - 1u)) == 0u;
}

static int vc4_matvec_shape_valid(uint32_t output_depth,
                                  uint32_t input_depth,
                                  uint32_t worker_count)
{
    return output_depth != 0u && (output_depth % 16u) == 0u &&
           input_depth != 0u && worker_count != 0u &&
           worker_count <= VC4_MAX_WORKERS;
}

static int vc4_cpu_matvec_shape_valid(uint32_t output_depth,
                                      uint32_t input_depth)
{
    return output_depth != 0u && input_depth != 0u;
}

static int vc4_matvec_size_valid(uint32_t output_depth,
                                 uint32_t input_depth)
{
    /* Guard the row-major index arithmetic on 32-bit target builds. */
    const uint64_t elements = (uint64_t)output_depth * (uint64_t)input_depth;
    return elements <= (uint64_t)(UINT32_MAX / (uint32_t)sizeof(float));
}

#ifndef MPYNN_VC4_BCM2835
vc4_status_t vc4_init(void)
{
    /*
     * Do not probe undocumented registers or infer support from CPU
     * architecture.  A later port-owned implementation can replace this body
     * after mailbox, bus allocation, cache/barrier, and dispatch are proven.
     */
    g_runtime_status = VC4_STATUS_UNAVAILABLE;
    return g_runtime_status;
}

vc4_status_t vc4_runtime_status(void)
{
    return g_runtime_status;
}

int vc4_is_available(void)
{
    /* The host stub remains unavailable regardless of the Python switch. */
    return 0;
}

vc4_status_t vc4_set_enabled(int enabled)
{
    g_runtime_enabled = enabled != 0;
    return VC4_STATUS_OK;
}

int vc4_is_enabled(void)
{
    return g_runtime_enabled;
}

vc4_status_t vc4_reset_diagnostics(void)
{
    return VC4_STATUS_UNAVAILABLE;
}

vc4_status_t vc4_shutdown(void)
{
    /* No resources were acquired by the unsupported stub. */
    g_runtime_status = VC4_STATUS_UNAVAILABLE;
    return g_runtime_status;
}

const char *vc4_status_string(vc4_status_t status)
{
    switch (status) {
    case VC4_STATUS_OK:
        return "ok";
    case VC4_STATUS_UNAVAILABLE:
        return "vc4 unavailable";
    case VC4_STATUS_INVALID_ARGUMENT:
        return "invalid argument";
    case VC4_STATUS_INVALID_SHAPE:
        return "invalid matvec shape";
    case VC4_STATUS_NO_MEMORY:
        return "out of memory";
    case VC4_STATUS_TIMEOUT:
        return "vc4 dispatch timeout";
    case VC4_STATUS_IO_ERROR:
        return "vc4 io error";
    case VC4_STATUS_NOT_INITIALIZED:
        return "vc4 not initialized";
    case VC4_STATUS_UNSUPPORTED:
        return "vc4 operation unsupported";
    case VC4_STATUS_ERROR:
        return "vc4 error";
    default:
        return "unknown vc4 status";
    }
}

vc4_status_t vc4_alloc(uint32_t bytes, uint32_t alignment, uint32_t flags,
                       vc4_buffer_t *buffer)
{
    (void)flags;

    if (buffer == NULL || bytes == 0u || !vc4_is_power_of_two(alignment)) {
        return VC4_STATUS_INVALID_ARGUMENT;
    }

    /* Never overwrite a caller's live handle. */
    if (buffer->cpu != NULL || buffer->bus != 0u || buffer->handle != 0u ||
        buffer->bytes != 0u) {
        return VC4_STATUS_INVALID_ARGUMENT;
    }

    return VC4_STATUS_UNAVAILABLE;
}

vc4_status_t vc4_copy_to_buffer(vc4_buffer_t *buffer, const void *source,
                                uint32_t bytes)
{
    if (buffer == NULL || source == NULL || bytes == 0u ||
        bytes > buffer->bytes || buffer->cpu == NULL) {
        return VC4_STATUS_INVALID_ARGUMENT;
    }
    return VC4_STATUS_UNAVAILABLE;
}

vc4_status_t vc4_upload_weights_fp32(vc4_buffer_t *buffer, const float *source,
                                    uint32_t output_depth, uint32_t input_depth)
{
    if (!vc4_matvec_shape_valid(output_depth, input_depth, 1u) ||
        !vc4_matvec_size_valid(output_depth, input_depth)) return VC4_STATUS_INVALID_SHAPE;
    return vc4_copy_to_buffer(buffer, source, output_depth * input_depth * (uint32_t)sizeof(float));
}

vc4_status_t vc4_free(vc4_buffer_t *buffer)
{
    if (buffer == NULL) {
        return VC4_STATUS_INVALID_ARGUMENT;
    }

    /* Freeing an already empty buffer is safe and useful in fallback cleanup. */
    if (buffer->cpu == NULL && buffer->bus == 0u && buffer->handle == 0u &&
        buffer->bytes == 0u) {
        return VC4_STATUS_OK;
    }

    /* The unsupported stub does not own or unlock arbitrary caller buffers. */
    return VC4_STATUS_UNAVAILABLE;
}

vc4_status_t vc4_launch(uint32_t code_bus, const uint32_t *uniform_bus,
                        uint32_t count, uint32_t timeout_us)
{
    uint32_t i;

    if (code_bus == 0u || (code_bus & 7u) != 0u || uniform_bus == NULL ||
        count == 0u || count > VC4_MAX_WORKERS || timeout_us == 0u) {
        return VC4_STATUS_INVALID_ARGUMENT;
    }
    for (i = 0u; i < count; ++i) {
        if (uniform_bus[i] == 0u || (uniform_bus[i] & 3u) != 0u) {
            return VC4_STATUS_INVALID_ARGUMENT;
        }
    }

    /* No MMIO writes and, importantly, no unbounded polling on this path. */
    return VC4_STATUS_UNAVAILABLE;
}

int vc4_should_offload_fp32(uint32_t output_depth, uint32_t input_depth)
{
    (void)output_depth;
    (void)input_depth;
    return 0;
}

vc4_status_t vc4_matvec_fp32(const float *weights_cpu, uint32_t weights_bus,
                             const float *input, uint32_t output_depth,
                             uint32_t input_depth, uint32_t worker_count,
                             float *output)
{
    (void)weights_bus;

    if (!vc4_matvec_shape_valid(output_depth, input_depth, worker_count) ||
        !vc4_matvec_size_valid(output_depth, input_depth) ||
        weights_cpu == NULL || input == NULL || output == NULL) {
        return (!vc4_matvec_shape_valid(output_depth, input_depth,
                                        worker_count) ||
                !vc4_matvec_size_valid(output_depth, input_depth))
                   ? VC4_STATUS_INVALID_SHAPE
                   : VC4_STATUS_INVALID_ARGUMENT;
    }

    /* Explicitly unsupported: callers must invoke vc4_cpu_matvec_fp32(). */
    return VC4_STATUS_UNAVAILABLE;
}

vc4_status_t vc4_release_weights(const float *weights_cpu,
                                 uint32_t output_depth,
                                 uint32_t input_depth)
{
    (void)output_depth;
    (void)input_depth;
    return weights_cpu == NULL ? VC4_STATUS_INVALID_ARGUMENT
                               : VC4_STATUS_UNAVAILABLE;
}

#endif /* !MPYNN_VC4_BCM2835 */

vc4_status_t vc4_cpu_matvec_fp32(const float *weights, const float *input,
                                  uint32_t output_depth, uint32_t input_depth,
                                  float *output)
{
    uint32_t row;
    uint32_t col;

    if (!vc4_cpu_matvec_shape_valid(output_depth, input_depth) ||
        !vc4_matvec_size_valid(output_depth, input_depth)) {
        return VC4_STATUS_INVALID_SHAPE;
    }
    if (weights == NULL || input == NULL || output == NULL) {
        return VC4_STATUS_INVALID_ARGUMENT;
    }

    for (row = 0u; row < output_depth; ++row) {
        float sum = 0.0f;
        const float *weight_row = weights + (size_t)row * input_depth;
        for (col = 0u; col < input_depth; ++col) {
            sum += weight_row[col] * input[col];
        }
        output[row] = sum;
    }
    return VC4_STATUS_OK;
}

vc4_status_t vc4_matvec_fp32_cpu(const float *weights, const float *input,
                                  uint32_t output_depth, uint32_t input_depth,
                                  float *output)
{
    return vc4_cpu_matvec_fp32(weights, input, output_depth, input_depth,
                               output);
}
