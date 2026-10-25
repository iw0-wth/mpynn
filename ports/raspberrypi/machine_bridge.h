// SPDX-License-Identifier: MIT
#ifndef MPYNN_MACHINE_BRIDGE_H
#define MPYNN_MACHINE_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int mpynn_machine_serial(uint8_t serial[8]);
uint32_t mpynn_machine_frequency(void);
uint32_t mpynn_machine_revision(void);
uint32_t mpynn_machine_ram_mb(void);
const char *mpynn_machine_name(void);
const char *mpynn_port_build_id(void);
void mpynn_machine_reset(void) __attribute__((noreturn));
#ifdef __cplusplus
}
#endif
#endif
