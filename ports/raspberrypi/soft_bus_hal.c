// SPDX-License-Identifier: MIT
#include "py/mphal.h"
#include "machine_pin.h"
#include "gpio_bridge.h"
#include "soft_bus_hal.h"

/* machine_pin owns the single GPIO registry.  The soft buses use that same
 * owner token, so a Pin configured by the user and a bus adapter cannot
 * silently take the pad away from one another. */
extern unsigned machine_pin_get_id(mp_obj_t pin_in);
extern void machine_pin_hal_configure(unsigned id, int mode, int pull, int value);
extern int machine_pin_hal_read(unsigned id);
extern void machine_pin_hal_write(unsigned id, int value);

mp_hal_pin_obj_t mpynn_hal_get_pin_obj(mp_obj_t pin_in) {
    return pin_in;
}

unsigned mp_hal_pin_name(mp_hal_pin_obj_t pin) {
    return machine_pin_get_id(pin);
}

void mp_hal_pin_input(mp_hal_pin_obj_t pin) {
    machine_pin_hal_configure(machine_pin_get_id(pin), MPYNN_GPIO_IN, -1, -1);
}

void mp_hal_pin_output(mp_hal_pin_obj_t pin) {
    machine_pin_hal_configure(machine_pin_get_id(pin), MPYNN_GPIO_OUT, -1, -1);
}

void mp_hal_pin_open_drain(mp_hal_pin_obj_t pin) {
    /* Released open-drain state is an input. */
    machine_pin_hal_configure(machine_pin_get_id(pin), MPYNN_GPIO_IN, -1, -1);
}

void mp_hal_pin_od_low(mp_hal_pin_obj_t pin) {
    /* configure() preloads the low latch before enabling output. */
    machine_pin_hal_configure(machine_pin_get_id(pin), MPYNN_GPIO_OUT, -1, 0);
}

void mp_hal_pin_od_high(mp_hal_pin_obj_t pin) {
    /* Releasing an open-drain line must never drive a logic one. */
    machine_pin_hal_configure(machine_pin_get_id(pin), MPYNN_GPIO_IN, -1, -1);
}

void mp_hal_delay_us_fast(mp_uint_t us) {
    mp_uint_t start = mp_hal_ticks_us();
    while ((mp_uint_t)(mp_hal_ticks_us() - start) < us) {
        /* Deliberately no mp_event_handle_nowait()/mp_hal_delay_us(): bus
         * edges must not be interrupted by VM callbacks. */
    }
}
