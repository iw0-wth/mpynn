// SPDX-License-Identifier: MIT
// Included by standard MicroPython extmod/modmachine.c, not compiled separately.
#include <string.h>
#include <stdio.h>
#include "py/mperrno.h"
#include "py/gc.h"
#include "machine_bridge.h"
#include "machine_pin.h"
#include "machine_spi.h"
#include "machine_i2c.h"
#include "machine_timer.h"
extern const mp_obj_type_t machine_timer_type;
#include "circle_bridge.h"
#include "network_bridge.h"
#include "rtc_bridge.h"
#include "shared/timeutils/timeutils.h"
#include "ethernet_bridge.h"
#include "storage_info.c"
#include "memory_info.h"
#include "vc4_runtime.h"

static void mp_machine_idle(void) {
    // Cooperative idle in this milestone, not a claimed low-power sleep mode.
    // Do not call the scheduler from a user IRQ-masked critical section.
    if (mpynn_irq_is_enabled()) mp_event_handle_nowait();
}
static mp_obj_t mpynn_reset(void) {
    mpynn_machine_reset();
}
static MP_DEFINE_CONST_FUN_OBJ_0(mpynn_reset_obj, mpynn_reset);

/* machine.vc4() reads the per-process TFLM offload switch;
 * machine.vc4(True/False) changes it. Set this before constructing models so
 * Prepare allocates (or skips) persistent VC4 weight buffers accordingly. */
static mp_obj_t mpynn_vc4(size_t n_args, const mp_obj_t *args) {
    if (n_args == 0) return mp_obj_new_bool(vc4_is_enabled());
    int enabled = mp_obj_is_true(args[0]);
    vc4_status_t status = vc4_set_enabled(enabled);
    if (status != VC4_STATUS_OK) {
        mp_raise_msg_varg(&mp_type_RuntimeError,
                          MP_ERROR_TEXT("VC4 switch failed: %s"),
                          vc4_status_string(status));
    }
    return mp_obj_new_bool(vc4_is_enabled());
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mpynn_vc4_obj, 0, 1, mpynn_vc4);

static void require_irqs(void) {
    // Firmware mailbox/clock calls are not part of the IRQ-masked Pin fast path.
    if (!mpynn_irq_is_enabled()) mp_raise_OSError(MP_EBUSY);
}
static mp_obj_t mpynn_unique_id(void) {
    require_irqs();
    uint8_t serial[8];
    int status = mpynn_machine_serial(serial);
    if (status) mp_raise_OSError(MP_EIO);
    return mp_obj_new_bytes(serial, sizeof(serial));
}
static MP_DEFINE_CONST_FUN_OBJ_0(mpynn_unique_id_obj, mpynn_unique_id);
static mp_obj_t mpynn_freq(size_t n_args, const mp_obj_t *args) {
    (void)args;
    if (n_args) mp_raise_NotImplementedError(MP_ERROR_TEXT("frequency changes are not supported"));
    require_irqs();
    uint32_t hz = mpynn_machine_frequency();
    if (!hz) mp_raise_OSError(MP_EIO);
    return mp_obj_new_int_from_uint(hz);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mpynn_freq_obj, 0, 1, mpynn_freq);

static mp_obj_t mpynn_board_info(void) {
    // Port-specific diagnostic API, not a replacement for standard machine APIs.
    const char *name = mpynn_machine_name();
    mp_obj_t info = mp_obj_new_dict(0);
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_model), mp_obj_new_str(name, strlen(name)));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_revision), mp_obj_new_int_from_uint(mpynn_machine_revision()));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_ram_mb), mp_obj_new_int_from_uint(mpynn_machine_ram_mb()));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_build_id), mp_obj_new_str(mpynn_port_build_id(), 64));
    return info;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mpynn_board_info_obj, mpynn_board_info);
static mp_obj_t mpynn_memory_info(void) {
    mp_obj_t info = mp_obj_new_dict(0);
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_circle_low_free), mp_obj_new_int_from_ull(mpynn_circle_low_free()));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_gc_heap), mp_obj_new_int_from_ull(mpynn_gc_heap_size()));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_circle_reserve), mp_obj_new_int_from_ull(mpynn_circle_heap_reserve()));
    gc_info_t gc;
    gc_info(&gc);
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_gc_free), mp_obj_new_int_from_ull(gc.free));
    return info;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mpynn_memory_info_obj, mpynn_memory_info);

// Default is a retained snapshot of the whole bounded log ring. Reading logs
// must not erase the evidence; callers explicitly opt into consuming clear=True.
static mp_obj_t mpynn_logs(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    static const mp_arg_t allowed[] = {
        {MP_QSTR_clear, MP_ARG_BOOL | MP_ARG_KW_ONLY, {.u_bool = false}},
        {MP_QSTR_limit, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = 16384}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, args);
    require_irqs();
    mp_int_t limit = args[1].u_int;
    if (limit < 1 || limit > 16384) {
        mp_raise_ValueError(MP_ERROR_TEXT("log limit must be 1..16384"));
    }
    vstr_t buffer;
    vstr_init_len(&buffer, (size_t)limit);
    buffer.len = mpynn_log_read_ex(buffer.buf, (size_t)limit, args[0].u_bool);
    return mp_obj_new_bytes_from_vstr(&buffer);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(mpynn_logs_obj, 0, mpynn_logs);

static mp_obj_t mpynn_vc4_reset_diagnostics(void) {
    require_irqs();
    vc4_status_t status = vc4_reset_diagnostics();
    if (status != VC4_STATUS_OK) {
        mp_raise_msg_varg(&mp_type_RuntimeError,
                          MP_ERROR_TEXT("VC4 diagnostics reset failed: %s"),
                          vc4_status_string(status));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mpynn_vc4_reset_diagnostics_obj, mpynn_vc4_reset_diagnostics);

static mp_obj_t network_address(const uint8_t value[4]) {
    char text[16];
    int length = snprintf(text, sizeof(text), "%u.%u.%u.%u",
        (unsigned)value[0], (unsigned)value[1], (unsigned)value[2], (unsigned)value[3]);
    return mp_obj_new_str(text, length);
}
static mp_obj_t mpynn_network_info(void) {
    // Read-only port diagnostics until the standard network.LAN adapter exists.
    require_irqs();
    uint8_t mac[6] = {0};
    unsigned link = 0, speed = 0;
    int eth = mpynn_eth_snapshot(mac, &link, &speed);
    if (eth != 0 && eth != -1) mp_raise_OSError(MP_EBUSY);
    mpynn_network_state_t state;
    if (mpynn_network_snapshot(&state)) mp_raise_OSError(MP_EBUSY);
    mp_obj_t addresses[] = {network_address(state.ip), network_address(state.netmask),
        network_address(state.gateway), network_address(state.dns)};
    mp_obj_t info = mp_obj_new_dict(0);
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_present), mp_obj_new_bool(eth == 0));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_initialized), mp_obj_new_bool(state.initialized));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_link), mp_obj_new_bool(link));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_isconnected), mp_obj_new_bool(eth == 0 && link && state.running));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_dhcp), mp_obj_new_bool(state.dhcp));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_mac), eth == 0 ? mp_obj_new_bytes(mac, sizeof(mac)) : mp_const_none);
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_speed_code), eth == 0 ? mp_obj_new_int_from_uint(speed) : mp_const_none);
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_ifconfig), mp_obj_new_tuple(4, addresses));
    return info;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mpynn_network_info_obj, mpynn_network_info);

// Software UTC clock for the Pi1 system timer. It starts at 2000-01-01 each
// cold boot and is not persistent; it is valid for TLS only after explicit set.
static const mp_obj_type_t mpynn_rtc_type;
static const mp_obj_base_t mpynn_rtc_singleton = { &mpynn_rtc_type };
static mp_obj_t mpynn_rtc_make_new(const mp_obj_type_t *type, size_t n_args,
    size_t n_kw, const mp_obj_t *args) {
    (void)type;
    mp_arg_check_num(n_args, n_kw, 0, 1, false);
    if (n_args && mp_obj_get_int(args[0]) != 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("only RTC(0) is defined"));
    }
    return MP_OBJ_FROM_PTR(&mpynn_rtc_singleton);
}
static mp_obj_t mpynn_rtc_datetime(size_t n_args, const mp_obj_t *args) {
    mp_arg_check_num(n_args, 0, 1, 2, false);
    if (n_args == 1) {
        uint32_t seconds; unsigned valid, source;
        if (mpynn_rtc_get_utc(&seconds, &valid, &source)) {
            mp_raise_OSError(MP_EIO);
        }
        timeutils_struct_time_t t;
        timeutils_seconds_since_1970_to_struct_time(seconds, &t);
        mp_obj_t values[8] = {
            mp_obj_new_int(t.tm_year), mp_obj_new_int(t.tm_mon), mp_obj_new_int(t.tm_mday),
            mp_obj_new_int(t.tm_wday), mp_obj_new_int(t.tm_hour), mp_obj_new_int(t.tm_min),
            mp_obj_new_int(t.tm_sec), mp_obj_new_int(0)
        };
        return mp_obj_new_tuple(8, values);
    }
    size_t length;
    mp_obj_t *items;
    mp_obj_get_array(args[1], &length, &items);
    if (length < 7 || length > 8) mp_raise_ValueError(MP_ERROR_TEXT("datetime tuple"));
    mp_int_t year=mp_obj_get_int(items[0]), month=mp_obj_get_int(items[1]);
    mp_int_t day=mp_obj_get_int(items[2]), hour=mp_obj_get_int(items[4]);
    mp_int_t minute=mp_obj_get_int(items[5]), second=mp_obj_get_int(items[6]);
    if (year < 1970 || year > 2038 || month < 1 || month > 12 || day < 1 ||
        day > (mp_int_t)timeutils_days_in_month(year, month) || hour < 0 || hour > 23 ||
        minute < 0 || minute > 59 || second < 0 || second > 59) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid datetime"));
    }
    if (length == 8 && mp_obj_get_int(items[7]) != 0) mp_raise_NotImplementedError(MP_ERROR_TEXT("subseconds"));
    timeutils_timestamp_t timestamp = timeutils_seconds_since_1970(year, month, day, hour, minute, second);
    if (timestamp > INT32_MAX) mp_raise_ValueError(MP_ERROR_TEXT("datetime exceeds Circle UTC range"));
    if (mpynn_rtc_set_utc((uint32_t)timestamp)) mp_raise_OSError(MP_EIO);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mpynn_rtc_datetime_obj, 1, 2, mpynn_rtc_datetime);
static mp_obj_t mpynn_rtc_init(size_t n_args, const mp_obj_t *args) {
    mp_arg_check_num(n_args, 0, 2, 2, false);
    size_t length;
    mp_obj_t *items;
    mp_obj_get_array(args[1], &length, &items);
    if (length != 8) mp_raise_ValueError(MP_ERROR_TEXT("init needs 8 fields"));
    // init: year/month/day/hour/minute/second/microsecond/tzinfo.
    // Per machine.RTC contract, microsecond and tzinfo are ignored. Calendar
    // validation and supported UTC range are shared with datetime's setter.
    mp_obj_t date[8] = {items[0], items[1], items[2], MP_OBJ_NEW_SMALL_INT(0),
        items[3], items[4], items[5], MP_OBJ_NEW_SMALL_INT(0)};
    mp_obj_t call[2] = {args[0], mp_obj_new_tuple(8, date)};
    return mpynn_rtc_datetime(2, call);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mpynn_rtc_init_obj, 1, 2, mpynn_rtc_init);
static const mp_rom_map_elem_t mpynn_rtc_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_datetime), MP_ROM_PTR(&mpynn_rtc_datetime_obj) },
    { MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&mpynn_rtc_init_obj) },
};
static MP_DEFINE_CONST_DICT(mpynn_rtc_locals, mpynn_rtc_locals_table);
static MP_DEFINE_CONST_OBJ_TYPE(mpynn_rtc_type, MP_QSTR_RTC, MP_TYPE_FLAG_NONE,
    make_new, mpynn_rtc_make_new, locals_dict, &mpynn_rtc_locals);

#define MICROPY_PY_MACHINE_EXTRA_GLOBALS \
    { MP_ROM_QSTR(MP_QSTR_vc4), MP_ROM_PTR(&mpynn_vc4_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_vc4_reset_diagnostics), MP_ROM_PTR(&mpynn_vc4_reset_diagnostics_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_storage_info), MP_ROM_PTR(&mpynn_storage_info_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_RTC), MP_ROM_PTR(&mpynn_rtc_type) }, \
    { MP_ROM_QSTR(MP_QSTR_network_info), MP_ROM_PTR(&mpynn_network_info_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_memory_info), MP_ROM_PTR(&mpynn_memory_info_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_logs), MP_ROM_PTR(&mpynn_logs_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_Pin), MP_ROM_PTR(&machine_pin_type) }, \
    { MP_ROM_QSTR(MP_QSTR_Timer), MP_ROM_PTR(&machine_timer_type) }, \
    { MP_ROM_QSTR(MP_QSTR_reset), MP_ROM_PTR(&mpynn_reset_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_unique_id), MP_ROM_PTR(&mpynn_unique_id_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_freq), MP_ROM_PTR(&mpynn_freq_obj) }, \
    { MP_ROM_QSTR(MP_QSTR_board_info), MP_ROM_PTR(&mpynn_board_info_obj) },
