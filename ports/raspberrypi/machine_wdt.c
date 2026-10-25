// SPDX-License-Identifier: MIT
#include "py/runtime.h"
#include "py/mperrno.h"
#include "extmod/modmachine.h"
#include "machine_wdt.h"

// One stable Python identity and owner token; independent of GC heap lifetime.
static const mp_obj_base_t wdt0 = {&machine_wdt_type};
static void wdt_raise(int status) {
    switch (status) {
        case MPYNN_WDT_OK: return;
        case MPYNN_WDT_INVALID: mp_raise_ValueError(MP_ERROR_TEXT("WDT ID must be 0; timeout is 1..15 seconds"));
        case MPYNN_WDT_BUSY: mp_raise_OSError(MP_EBUSY);
        case MPYNN_WDT_UNINITIALIZED: mp_raise_OSError(MP_ENODEV);
        default: mp_raise_OSError(MP_EIO);
    }
}
static mp_obj_t wdt_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    (void)type;
    enum { ID, TIMEOUT };
    static const mp_arg_t allowed[] = {
        {MP_QSTR_id, MP_ARG_INT, {.u_int = 0}},
        // No default timeout: WDT() obtains an unarmed reference. Explicit zero,
        // None, negatives, milliseconds-style values and >15 are not accepted.
        {MP_QSTR_timeout, MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args, MP_ARRAY_SIZE(allowed), allowed, args);
    bool arm = args[TIMEOUT].u_obj != MP_OBJ_NULL;
    mp_int_t seconds = arm ? mp_obj_get_int(args[TIMEOUT].u_obj) : 0;
    if (args[ID].u_int != 0 || (arm && (seconds < 1 || seconds > MPYNN_WDT_MAX_SECONDS))) {
        wdt_raise(MPYNN_WDT_INVALID);
    }
    wdt_raise(mpynn_wdt_init(&wdt0, 0, (int)seconds, arm));
    return MP_OBJ_FROM_PTR(&wdt0);
}
static mp_obj_t wdt_feed(mp_obj_t self) {
    wdt_raise(mpynn_wdt_feed(MP_OBJ_TO_PTR(self)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(wdt_feed_obj, wdt_feed);
static mp_obj_t wdt_deinit(mp_obj_t self) {
    wdt_raise(mpynn_wdt_deinit(MP_OBJ_TO_PTR(self)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(wdt_deinit_obj, wdt_deinit);
static mp_obj_t wdt_is_running(mp_obj_t self) {
    unsigned running, left;
    wdt_raise(mpynn_wdt_snapshot(MP_OBJ_TO_PTR(self), &running, &left));
    return mp_obj_new_bool(running);
}
static MP_DEFINE_CONST_FUN_OBJ_1(wdt_is_running_obj, wdt_is_running);
static mp_obj_t wdt_time_left(mp_obj_t self) {
    unsigned running, left;
    wdt_raise(mpynn_wdt_snapshot(MP_OBJ_TO_PTR(self), &running, &left));
    return mp_obj_new_int_from_uint(left);
}
static MP_DEFINE_CONST_FUN_OBJ_1(wdt_time_left_obj, wdt_time_left);
static const mp_rom_map_elem_t wdt_locals_table[] = {
    {MP_ROM_QSTR(MP_QSTR_feed), MP_ROM_PTR(&wdt_feed_obj)},
    // Port extension: restart means rearm the saved timeout, never immediate reboot.
    {MP_ROM_QSTR(MP_QSTR_restart), MP_ROM_PTR(&wdt_feed_obj)},
    {MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&wdt_deinit_obj)},
    {MP_ROM_QSTR(MP_QSTR_is_running), MP_ROM_PTR(&wdt_is_running_obj)},
    {MP_ROM_QSTR(MP_QSTR_time_left), MP_ROM_PTR(&wdt_time_left_obj)},
};
static MP_DEFINE_CONST_DICT(wdt_locals, wdt_locals_table);
MP_DEFINE_CONST_OBJ_TYPE(machine_wdt_type, MP_QSTR_WDT, MP_TYPE_FLAG_NONE,
    make_new, wdt_make_new, locals_dict, &wdt_locals);
