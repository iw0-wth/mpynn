// SPDX-License-Identifier: MIT
#ifndef MPYNN_RASPBERRYPI_IRQ_H
#define MPYNN_RASPBERRYPI_IRQ_H
#include <stdint.h>
// Save only the IRQ-mask bit, not the entire CPSR (which includes mode/flags).
// The small token cannot allocate an MP integer while interrupts are masked.
static inline uint32_t mpynn_irq_save(void) {
    uint32_t state;
    __asm__ volatile ("mrs %0, cpsr\n\tcpsid i" : "=r" (state) :: "memory", "cc");
    return state & 0x80u;
}
static inline void mpynn_irq_restore(uint32_t state) {
    if (state & 0x80u) {
        __asm__ volatile ("cpsid i" ::: "memory", "cc");
    } else {
        __asm__ volatile ("cpsie i" ::: "memory", "cc");
    }
}
static inline int mpynn_irq_is_enabled(void) {
    uint32_t state;
    __asm__ volatile ("mrs %0, cpsr" : "=r" (state) :: "memory");
    return !(state & 0x80u);
}
#endif
