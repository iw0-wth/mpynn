// SPDX-License-Identifier: MIT
#ifndef MPYNN_MACHINE_I2C_H
#define MPYNN_MACHINE_I2C_H
#include <stddef.h>
#include <stdint.h>
#define MPYNN_I2C_TIMEOUT_US 100000u
#define MPYNN_I2C_MAX_TRANSFER 65535u
#ifdef __cplusplus
extern "C" {
#endif
enum mpynn_i2c_error {
    MPYNN_I2C_INVALID = -1, MPYNN_I2C_BUSY = -2, MPYNN_I2C_CONTEXT = -3,
    MPYNN_I2C_NOT_READY = -4, MPYNN_I2C_NACK = -5, MPYNN_I2C_TIMEOUT = -6,
    MPYNN_I2C_IO = -7, MPYNN_I2C_BOARD = -8
};
/* Task-context-only, synchronous, no callbacks or MP exceptions through C++.
 * owner is a GC object's stable identity, NOT a native GC root. The finaliser
 * closes it or marks it for deferred cleanup if IRQs are masked. No native
 * cleanup dereferences owner. Device 1/config 0 exclusively uses BCM2/BCM3.
 */
int mpynn_i2c_init(const void *owner, unsigned freq, unsigned timeout_us);
int mpynn_i2c_deinit(const void *owner, int defer);
int mpynn_i2c_deinit_all(void);
int mpynn_i2c_read(const void *owner, unsigned addr, void *buf, size_t len);
int mpynn_i2c_write(const void *owner, unsigned addr, const void *buf, size_t len);
int mpynn_i2c_write_read(const void *owner, unsigned addr,
    const void *prefix, size_t prefix_len, void *buf, size_t len);
#ifdef __cplusplus
}
#else
#include "py/obj.h"
extern const mp_obj_type_t machine_i2c_type;
#endif
#endif
