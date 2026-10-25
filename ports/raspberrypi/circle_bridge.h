// SPDX-License-Identifier: MIT
#ifndef MPYNN_CIRCLE_BRIDGE_H
#define MPYNN_CIRCLE_BRIDGE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int mpynn_console_read(void);
size_t mpynn_console_write(const char *data, size_t length);
uint64_t mpynn_ticks_us64(void);
void mpynn_platform_poll(void);
size_t mpynn_log_read(char *buffer, size_t length);
/* Non-consuming snapshots may include the entire 16 KiB Circle log ring. */
size_t mpynn_log_read_ex(char *buffer, size_t length, int clear);
void mpynn_platform_halt(void) __attribute__((noreturn));
void mpynn_vm_run(void *heap, size_t heap_size) __attribute__((noreturn));
#ifdef __cplusplus
}
#endif
#endif
