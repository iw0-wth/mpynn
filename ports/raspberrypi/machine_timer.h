// SPDX-License-Identifier: MIT
#ifndef MPYNN_MACHINE_TIMER_H
#define MPYNN_MACHINE_TIMER_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define MPYNN_TIMER_SLOTS 8
#define MPYNN_TIMER_OK 0
#define MPYNN_TIMER_INVALID -1
#define MPYNN_TIMER_BUSY -2

/* Circle HZ is 100: one kernel tick is exactly 10 ms. */
int mpynn_timer_slot_acquire(unsigned *slot);
void mpynn_timer_slot_release(unsigned slot);
int mpynn_timer_start(unsigned slot, unsigned ticks, unsigned periodic, uint32_t generation);
int mpynn_timer_stop(unsigned slot);
/* Return a latched event without consuming it. */
int mpynn_timer_event(unsigned slot, uint32_t *generation);
/* Claim only the event observed for this generation. */
int mpynn_timer_event_claim(unsigned slot, uint32_t generation);
/* Return a claimed event when the scheduler queue is full. */
void mpynn_timer_event_release(unsigned slot, uint32_t generation);
/* Called in task/VM context after a scheduled callback has run. */
void mpynn_timer_complete(unsigned slot, uint32_t generation);
/* Invalidate every queued/native timer (soft reset and shutdown). */
int mpynn_timer_deinit_all(void);
void mpynn_timer_poll(void);
#ifdef __cplusplus
}
#endif
#endif
