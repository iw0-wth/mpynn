// SPDX-License-Identifier: MIT
#ifndef MPYNN_SOFT_BUS_HAL_H
#define MPYNN_SOFT_BUS_HAL_H

#include "py/mpconfig.h"
#include "py/obj.h"

/* The Raspberry Pi port represents a pin by its BCM number.  Pin ownership,
 * board validation and all MMIO are kept in machine_pin.c/gpio_bridge.cpp;
 * these adapters deliberately do not maintain a second owner registry. */
#ifndef MP_HAL_PIN_FMT
#define MP_HAL_PIN_FMT "%u"
#endif
/* mp_hal_get_pin_obj is defined as a macro by py/mphal.h on this port. */
#ifndef mp_hal_get_pin_obj
mp_hal_pin_obj_t mpynn_hal_get_pin_obj(mp_obj_t pin_in);
#define mp_hal_get_pin_obj(pin) mpynn_hal_get_pin_obj(pin)
#endif
unsigned mp_hal_pin_name(mp_hal_pin_obj_t pin);
void mp_hal_pin_input(mp_hal_pin_obj_t pin);
void mp_hal_pin_output(mp_hal_pin_obj_t pin);
void mp_hal_pin_open_drain(mp_hal_pin_obj_t pin);
void mp_hal_pin_od_low(mp_hal_pin_obj_t pin);
void mp_hal_pin_od_high(mp_hal_pin_obj_t pin);

/* Unlike mp_hal_delay_us(), this path must not run the VM event hook: a
 * callback must not be able to change a bus pin halfway through a bit. */
void mp_hal_delay_us_fast(mp_uint_t us);

#endif /* MPYNN_SOFT_BUS_HAL_H */
