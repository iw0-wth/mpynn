// SPDX-License-Identifier: MIT
#include "py/runtime.h"
#include "py/mphal.h"
#include "py/mperrno.h"
#include "extmod/modmachine.h"
#include "machine_timer.h"

/* Circle HZ=100.  A native slot owns its object while it is active. */
MP_REGISTER_ROOT_POINTER(mp_obj_t mpynn_timer_roots[MPYNN_TIMER_SLOTS]);

#define MPYNN_TIMER_GEN_MASK ((uint32_t)0x01ffffffu)
typedef struct _mpynn_timer_obj_t {
    mp_obj_base_t base;
    int8_t slot;
    uint8_t periodic;
    uint32_t generation;
    uint32_t period_ms;
    mp_obj_t callback;
} mpynn_timer_obj_t;

const mp_obj_type_t machine_timer_type;
static uint32_t next_generation[MPYNN_TIMER_SLOTS];
static mp_obj_t mpynn_timer_init_helper(mpynn_timer_obj_t *, size_t, const mp_obj_t *, mp_map_t *);

static void timer_raise(int status) {
    if (status == MPYNN_TIMER_INVALID) mp_raise_ValueError(MP_ERROR_TEXT("invalid Timer"));
    if (status == MPYNN_TIMER_BUSY) mp_raise_OSError(MP_EBUSY);
    mp_raise_OSError(MP_EIO);
}

static unsigned timer_ticks(uint64_t period_ms) {
    /* Exact roundup to Circle's 10-ms kernel tick, never truncation. */
    uint64_t ticks = (period_ms + 9) / 10;
    if (ticks == 0) ticks = 1;
    if (ticks > 0x7fffffffu) mp_raise_ValueError(MP_ERROR_TEXT("period too large"));
    return (unsigned)ticks;
}

static uint32_t timer_new_generation(unsigned slot) {
    uint32_t generation = (next_generation[slot] + 1) & MPYNN_TIMER_GEN_MASK;
    if (generation == 0) generation = 1;
    next_generation[slot] = generation;
    return generation;
}

static mp_obj_t timer_dispatch(mp_obj_t arg) {
    uint32_t encoded = (uint32_t)mp_obj_get_int(arg);
    unsigned slot = encoded & (MPYNN_TIMER_SLOTS - 1);
    uint32_t generation = encoded >> 3;
    if (slot >= MPYNN_TIMER_SLOTS || generation == 0) return mp_const_none;
    mp_obj_t self = MP_STATE_VM(mpynn_timer_roots[slot]);
    if (self == MP_OBJ_NULL) return mp_const_none;
    mpynn_timer_obj_t *obj = MP_OBJ_TO_PTR(self);
    if (obj->slot != (int8_t)slot || obj->generation != generation || obj->callback == mp_const_none) {
        mpynn_timer_complete(slot, generation);
        return mp_const_none;
    }
    mp_obj_t callback = obj->callback;
    uint8_t periodic = obj->periodic;
    mp_call_function_1_protected(callback, self);
    /* Reinit/deinit changes generation, making this completion harmless. */
    mpynn_timer_complete(slot, generation);
    /* A one-shot releases its explicit root only after its callback returns. */
    if (!periodic && obj->slot == (int8_t)slot && obj->generation == generation) {
        MP_STATE_VM(mpynn_timer_roots[slot]) = MP_OBJ_NULL;
        mpynn_timer_slot_release(slot);
        obj->slot = -1;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(timer_dispatch_obj, timer_dispatch);

void mpynn_timer_poll(void) {
    for (unsigned slot = 0; slot < MPYNN_TIMER_SLOTS; ++slot) {
        uint32_t generation;
        if (mpynn_timer_event(slot, &generation) != MPYNN_TIMER_OK) continue;
        if (mpynn_timer_event_claim(slot, generation) != MPYNN_TIMER_OK) continue;
        mp_obj_t arg = MP_OBJ_NEW_SMALL_INT((mp_int_t)((generation << 3) | slot));
        if (!mp_sched_schedule(MP_OBJ_FROM_PTR(&timer_dispatch_obj), arg)) {
            /* Queue-full is lossless: leave the IRQ event pending for retry. */
            mpynn_timer_event_release(slot, generation);
        }
    }
}

static mp_obj_t timer_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw,
                               const mp_obj_t *args) {
    mpynn_timer_obj_t *self = mp_obj_malloc(mpynn_timer_obj_t, type);
    self->slot = -1;
    self->periodic = 1;
    self->generation = 0;
    self->period_ms = 1000;
    self->callback = mp_const_none;
    if (n_args > 0) {
        if (mp_obj_get_int(args[0]) != -1) mp_raise_ValueError(MP_ERROR_TEXT("Timer doesn't exist"));
        --n_args; ++args;
    }
    if (n_args || n_kw) {
        mp_map_t kw;
        mp_map_init_fixed_table(&kw, n_kw, args + n_args);
        /* init() owns all argument validation and start behavior. */
        mp_obj_t init_args[1] = {MP_OBJ_FROM_PTR(self)};
        (void)init_args;
        // Positional arguments after id are intentionally unsupported.
        if (n_args) mp_raise_TypeError(MP_ERROR_TEXT("Timer arguments must be keyword-only"));
        // Call helper below with no positional arguments.
        mp_obj_t none = MP_OBJ_FROM_PTR(self);
        (void)none;
        mpynn_timer_init_helper(self, 0, NULL, &kw);
    }
    return MP_OBJ_FROM_PTR(self);
}

static mp_obj_t mpynn_timer_init_helper(mpynn_timer_obj_t *self, size_t n_args,
                                        const mp_obj_t *pos_args, mp_map_t *kw_args) {
    (void)n_args; (void)pos_args;
    enum { MODE, CALLBACK, PERIOD, FREQ, HARD };
    static const mp_arg_t allowed[] = {
        {MP_QSTR_mode, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 1}},
        {MP_QSTR_callback, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL}},
        {MP_QSTR_period, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = -1}},
        {MP_QSTR_freq, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL}},
        {MP_QSTR_hard, MP_ARG_KW_ONLY | MP_ARG_BOOL, {.u_bool = false}},
    };
    mp_arg_val_t values[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(0, NULL, kw_args, MP_ARRAY_SIZE(allowed), allowed, values);
    if (values[HARD].u_bool) mp_raise_ValueError(MP_ERROR_TEXT("hard Timer callbacks are unsupported"));
    if (values[MODE].u_int != 0 && values[MODE].u_int != 1) mp_raise_ValueError(MP_ERROR_TEXT("invalid Timer mode"));

    uint64_t period_ms = self->period_ms;
    if (values[FREQ].u_obj != MP_OBJ_NULL && values[FREQ].u_obj != mp_const_none) {
        mp_float_t frequency = mp_obj_get_float(values[FREQ].u_obj);
        if (!(frequency > 0) || frequency != frequency || frequency > (mp_float_t)1e9) {
            mp_raise_ValueError(MP_ERROR_TEXT("invalid Timer frequency"));
        }
        period_ms = (uint64_t)(1000.0 / frequency);
        if ((mp_float_t)period_ms * frequency < (mp_float_t)1000) ++period_ms;
    } else if (values[PERIOD].u_int != -1) {
        if (values[PERIOD].u_int < 0) mp_raise_ValueError(MP_ERROR_TEXT("invalid Timer period"));
        period_ms = (uint64_t)values[PERIOD].u_int;
    }
    if (period_ms < 10) period_ms = 10;
    (void)timer_ticks(period_ms);

    if (values[CALLBACK].u_obj != MP_OBJ_NULL) self->callback = values[CALLBACK].u_obj;
    self->periodic = (uint8_t)(values[MODE].u_int == 1);
    self->period_ms = (uint32_t)period_ms;

    if (self->slot >= 0) {
        (void)mpynn_timer_stop((unsigned)self->slot);
        self->generation = timer_new_generation((unsigned)self->slot);
    } else {
        unsigned slot = 0;
        int acquired = mpynn_timer_slot_acquire(&slot);
        if (acquired != MPYNN_TIMER_OK) timer_raise(acquired);
        self->slot = (int8_t)slot;
        self->generation = timer_new_generation(slot);
    }
    if (self->callback == mp_const_none) {
        /* An unarmed Timer consumes no bounded native slot. */
        unsigned slot = (unsigned)self->slot;
        MP_STATE_VM(mpynn_timer_roots[slot]) = MP_OBJ_NULL;
        mpynn_timer_slot_release(slot);
        self->slot = -1;
        return mp_const_none;
    }
    MP_STATE_VM(mpynn_timer_roots[(unsigned)self->slot]) = MP_OBJ_FROM_PTR(self);
    int status = mpynn_timer_start((unsigned)self->slot, timer_ticks(period_ms), self->periodic, self->generation);
    if (status != MPYNN_TIMER_OK) {
        MP_STATE_VM(mpynn_timer_roots[(unsigned)self->slot]) = MP_OBJ_NULL;
        mpynn_timer_slot_release((unsigned)self->slot);
        self->slot = -1;
        timer_raise(status);
    }
    return mp_const_none;
}

static mp_obj_t timer_init(size_t n_args, const mp_obj_t *args, mp_map_t *kw_args) {
    return mpynn_timer_init_helper(MP_OBJ_TO_PTR(args[0]), n_args - 1, args + 1, kw_args);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(timer_init_obj, 1, timer_init);

static mp_obj_t timer_deinit(mp_obj_t self_in) {
    mpynn_timer_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->slot >= 0) {
        unsigned slot = (unsigned)self->slot;
        (void)mpynn_timer_stop(slot);
        MP_STATE_VM(mpynn_timer_roots[slot]) = MP_OBJ_NULL;
        mpynn_timer_slot_release(slot);
        self->slot = -1;
        self->generation = timer_new_generation(slot);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(timer_deinit_obj, timer_deinit);

static const mp_rom_map_elem_t timer_locals_table[] = {
    {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&timer_init_obj)},
    {MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&timer_deinit_obj)},
    {MP_ROM_QSTR(MP_QSTR_ONE_SHOT), MP_ROM_INT(0)},
    {MP_ROM_QSTR(MP_QSTR_PERIODIC), MP_ROM_INT(1)},
};
static MP_DEFINE_CONST_DICT(timer_locals, timer_locals_table);
MP_DEFINE_CONST_OBJ_TYPE(machine_timer_type, MP_QSTR_Timer, MP_TYPE_FLAG_NONE,
    make_new, timer_make_new, locals_dict, &timer_locals);
