// SPDX-License-Identifier: MIT
#ifndef MPYNN_MACHINE_PIN_H
#define MPYNN_MACHINE_PIN_H
#include "py/obj.h"
#ifdef __cplusplus
extern "C" {
#endif
extern const mp_obj_type_t machine_pin_type;
mp_obj_t mp_pin_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args);
// Call before mp_deinit() on every VM exit; only releases machine.Pin-owned pads.
void machine_pin_deinit_all(void);
/* Native HAL helpers. They use the process-wide Pin owner token and raise
 * MicroPython exceptions on invalid ids, ownership conflicts, or bad context. */
unsigned machine_pin_get_id(mp_obj_t pin);
void machine_pin_hal_configure(unsigned id, int mode, int pull, int value);
int machine_pin_hal_read(unsigned id);
void machine_pin_hal_write(unsigned id, int value);
/* Run deferred GPIO callbacks in VM/task context; call from mpynn_event_poll. */
void machine_pin_irq_poll(void);
#ifdef __cplusplus
}
#endif
#endif
