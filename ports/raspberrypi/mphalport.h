// SPDX-License-Identifier: MIT
#ifndef MPYNN_MPHALPORT_H
#define MPYNN_MPHALPORT_H
#include "py/mpconfig.h"
#include "py/obj.h"
#include "shared/runtime/interrupt_char.h"
#include "irq.h"
// Fixed BCM pad identity required by extmod's SPI protocol declarations.
// Upstream software buses use the same BCM identity and resource registry.
typedef mp_obj_t mp_hal_pin_obj_t;
#include "soft_bus_hal.h"
#define MICROPY_BEGIN_ATOMIC_SECTION() mpynn_irq_save()
#define MICROPY_END_ATOMIC_SECTION(state) mpynn_irq_restore(state)
mp_uint_t mp_hal_ticks_ms(void);
mp_uint_t mp_hal_ticks_us(void);
mp_uint_t mp_hal_ticks_cpu(void);
void mp_hal_delay_ms(mp_uint_t ms);
void mp_hal_delay_us(mp_uint_t us);
#endif
