// SPDX-License-Identifier: MIT
#include <circle/bcmrandom.h>
#include <circle/synchronize.h>
#include "circle_bridge.h"
#include "tls_random_bridge.h"

extern "C" void mp_hal_get_random(size_t length, void *buffer) {
    if (length == 0) {
        return;
    }
    if (buffer == nullptr || CurrentExecutionLevel() != TASK_LEVEL) {
        mpynn_platform_halt();
    }
    // Construct after the context check: Circle's constructor initializes MMIO
    // under a TASK_LEVEL spinlock. Circle owns the shared initialization state.
    CBcmRandomNumberGenerator rng;
    unsigned char *out = static_cast<unsigned char *>(buffer);
    while (length != 0) {
        const uint32_t word = rng.GetNumber();
        // Byte stores allow unaligned buffers without violating strict aliasing.
        for (unsigned byte = 0; byte < sizeof(word) && length != 0; ++byte) {
            *out++ = static_cast<unsigned char>(word >> (8 * byte));
            --length;
        }
    }
    // Circle GetNumber blocks until hardware supplies data; it exposes no
    // timeout/error status. Never replace a stalled RNG with software entropy.
}
