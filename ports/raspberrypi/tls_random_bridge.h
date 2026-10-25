// SPDX-License-Identifier: MIT
#ifndef MPYNN_TLS_RANDOM_BRIDGE_H
#define MPYNN_TLS_RANDOM_BRIDGE_H
#include <stddef.h>
#include <time.h>
#ifdef __cplusplus
extern "C" {
#endif

// Nonzero length requires a valid writable buffer and Circle TASK_LEVEL.
// Violations halt: this void HAL API cannot report entropy failure to mbedTLS.
// Zero length is a no-op, including with NULL or in interrupt context.
void mp_hal_get_random(size_t length, void *buffer);

// Integration point: override this weak provider only when trusted UTC exists.
// Return 1 and write Unix seconds on success, 0 when RTC/UTC is unavailable.
// Must be callable from the VM task; do not substitute uptime or build time.
int mpynn_tls_get_utc(time_t *unix_seconds);
int mpynn_tls_time_is_valid(void);
time_t mpynn_tls_time(time_t *timer);

#ifdef __cplusplus
}
#endif
#endif
