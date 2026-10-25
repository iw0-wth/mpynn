// SPDX-License-Identifier: MIT
#include <circle/timer.h>
#include <circle/synchronize.h>
#include <circle/types.h>
#include "machine_timer.h"

namespace {
struct TimerSlot {
    TKernelTimerHandle handle;
    volatile unsigned armed;
    volatile unsigned pending;
    volatile unsigned queued;
    volatile uint32_t generation;
    unsigned ticks;
    unsigned periodic;
};
static TimerSlot slots[MPYNN_TIMER_SLOTS];
static void cancel_locked(TimerSlot *slot);

static void timer_irq(TKernelTimerHandle handle, void *param, void *) {
    // This is called by Circle from the timer IRQ.  It must remain bounded and
    // contain no allocator, scheduler, or Python access.
    TimerSlot *slot = static_cast<TimerSlot *>(param);
    if (slot != nullptr && slot >= slots && slot < slots + MPYNN_TIMER_SLOTS
        && slot->armed && slot->handle == handle) {
        slot->pending = 1;
        // Circle consumes this one-shot kernel timer immediately after the
        // handler returns; do not leave a stale handle for cancellation.
        slot->handle = 0;
    }
}

static void cancel_locked(TimerSlot *slot) {
    if (slot->handle != 0) {
        CTimer *timer = CTimer::Get();
        if (timer != nullptr) timer->CancelKernelTimer(slot->handle);
        slot->handle = 0;
    }
    slot->armed = 0;
    slot->pending = 0;
    slot->queued = 0;
}

static int arm_locked(TimerSlot *slot) {
    CTimer *timer = CTimer::Get();
    if (timer == nullptr || slot->ticks == 0) return MPYNN_TIMER_BUSY;
    TKernelTimerHandle handle = timer->StartKernelTimer(slot->ticks, timer_irq, slot);
    if (handle == 0) return MPYNN_TIMER_BUSY;
    slot->handle = handle;
    slot->armed = 1;
    return MPYNN_TIMER_OK;
}
}

extern "C" int mpynn_timer_slot_acquire(unsigned *index) {
    if (index == nullptr) return MPYNN_TIMER_INVALID;
    EnterCritical(IRQ_LEVEL);
    for (unsigned i = 0; i < MPYNN_TIMER_SLOTS; ++i) {
        if (!slots[i].armed && !slots[i].pending && !slots[i].queued && slots[i].generation == 0) {
            slots[i].generation = 1;
            *index = i;
            LeaveCritical();
            return MPYNN_TIMER_OK;
        }
    }
    LeaveCritical();
    return MPYNN_TIMER_BUSY;
}

extern "C" void mpynn_timer_slot_release(unsigned index) {
    if (index >= MPYNN_TIMER_SLOTS) return;
    EnterCritical(IRQ_LEVEL);
    cancel_locked(&slots[index]);
    slots[index].generation = 0;
    slots[index].ticks = 0;
    slots[index].periodic = 0;
    LeaveCritical();
}

extern "C" int mpynn_timer_start(unsigned index, unsigned ticks, unsigned periodic,
                                  uint32_t generation) {
    if (index >= MPYNN_TIMER_SLOTS || ticks == 0 || periodic > 1 || generation == 0) {
        return MPYNN_TIMER_INVALID;
    }
    EnterCritical(IRQ_LEVEL);
    TimerSlot *slot = &slots[index];
    cancel_locked(slot);
    slot->generation = generation;
    slot->ticks = ticks;
    slot->periodic = periodic;
    int status = arm_locked(slot);
    LeaveCritical();
    return status;
}

extern "C" int mpynn_timer_stop(unsigned index) {
    if (index >= MPYNN_TIMER_SLOTS) return MPYNN_TIMER_INVALID;
    EnterCritical(IRQ_LEVEL);
    cancel_locked(&slots[index]);
    // Make already-enqueued VM trampolines stale even if their Python object
    // remains reachable and is subsequently reused.
    uint32_t generation = (slots[index].generation + 1) & 0x01ffffffu;
    slots[index].generation = generation ? generation : 1;
    LeaveCritical();
    return MPYNN_TIMER_OK;
}

extern "C" int mpynn_timer_event(unsigned index, uint32_t *generation) {
    if (index >= MPYNN_TIMER_SLOTS || generation == nullptr) return MPYNN_TIMER_INVALID;
    EnterCritical(IRQ_LEVEL);
    TimerSlot *slot = &slots[index];
    unsigned ready = slot->pending && slot->armed && !slot->queued;
    if (ready) *generation = slot->generation;
    LeaveCritical();
    return ready ? MPYNN_TIMER_OK : MPYNN_TIMER_BUSY;
}

extern "C" int mpynn_timer_event_claim(unsigned index, uint32_t generation) {
    if (index >= MPYNN_TIMER_SLOTS || generation == 0) return MPYNN_TIMER_INVALID;
    EnterCritical(IRQ_LEVEL);
    TimerSlot *slot = &slots[index];
    int ok = slot->pending && slot->armed && !slot->queued && slot->generation == generation;
    if (ok) { slot->pending = 0; slot->queued = 1; }
    LeaveCritical();
    return ok ? MPYNN_TIMER_OK : MPYNN_TIMER_BUSY;
}

extern "C" void mpynn_timer_event_release(unsigned index, uint32_t generation) {
    if (index >= MPYNN_TIMER_SLOTS) return;
    EnterCritical(IRQ_LEVEL);
    TimerSlot *slot = &slots[index];
    if (slot->generation == generation && slot->armed && slot->queued) {
        slot->queued = 0;
        slot->pending = 1;
    }
    LeaveCritical();
}

extern "C" void mpynn_timer_complete(unsigned index, uint32_t generation) {
    if (index >= MPYNN_TIMER_SLOTS) return;
    EnterCritical(IRQ_LEVEL);
    TimerSlot *slot = &slots[index];
    if (slot->generation != generation) {
        // A stale scheduler trampoline must not touch the newly initialised
        // generation's queued state.
        LeaveCritical();
        return;
    }
    slot->queued = 0;
    if (!slot->armed) {
        LeaveCritical();
        return;
    }
    if (slot->periodic) {
        // The expired one-shot kernel timer is gone; arm the next one only now,
        // in VM/task context after the Python callback has returned.
        (void)arm_locked(slot);
    } else {
        slot->armed = 0;
    }
    LeaveCritical();
}

extern "C" int mpynn_timer_deinit_all(void) {
    EnterCritical(IRQ_LEVEL);
    for (unsigned i = 0; i < MPYNN_TIMER_SLOTS; ++i) {
        cancel_locked(&slots[i]);
        // VM scheduler queues are discarded by soft reset; make every native
        // slot available to the fresh VM while old tokens remain mismatched.
        slots[i].generation = 0;
    }
    LeaveCritical();
    return MPYNN_TIMER_OK;
}
