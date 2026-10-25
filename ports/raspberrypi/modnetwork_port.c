// SPDX-License-Identifier: MIT
// Standard MicroPython network adapter: UDP, TCP clients and listeners.
// Hostname resolution is still under implementation.
#include "py/runtime.h"
#include "py/mperrno.h"
#include <stdio.h>
#include "py/objtuple.h"
#include "network_bridge.h"
#include "modnetwork_port.h"
#include "extmod/modnetwork.h"
extern const mod_network_nic_protocol_t mpynn_udp_nic_protocol;

typedef struct {
    mp_obj_base_t base;
} mp_network_lan_obj_t;
static const mp_network_lan_obj_t lan_singleton = {{ &mp_network_lan_type }};

static mp_obj_t lan_make_new(const mp_obj_type_t *type, size_t n_args,
                             size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 0, 0, false);
    (void)type; (void)args;
    // One physical interface, no per-wrapper mutable state. Standard network
    // registration deduplicates this pointer; VM reset clears only its NIC list.
    mp_obj_t object = MP_OBJ_FROM_PTR(&lan_singleton);
    mod_network_register_nic(object);
    return object;
}
static mp_obj_t lan_active(size_t n_args, const mp_obj_t *args) {
    mp_arg_check_num(n_args, 0, 1, 2, false);
    mpynn_network_state_t state;
    if (mpynn_network_snapshot(&state) != 0) mp_raise_OSError(MP_EBUSY);
    if (n_args == 2) {
        if (!mp_obj_is_true(args[1])) mp_raise_NotImplementedError(MP_ERROR_TEXT("LAN cannot be deactivated"));
        if (!state.initialized) mp_raise_OSError(MP_ENODEV);
        return mp_const_none;
    }
    return mp_obj_new_bool(state.initialized);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(lan_active_obj, 1, 2, lan_active);
static mp_obj_t lan_isconnected(mp_obj_t self_in) {
    (void)self_in;
    mpynn_network_state_t state;
    if (mpynn_network_snapshot(&state) != 0) mp_raise_OSError(MP_EBUSY);
    return mp_obj_new_bool(state.initialized && state.running);
}
static MP_DEFINE_CONST_FUN_OBJ_1(lan_isconnected_obj, lan_isconnected);
static void lan_parse_ipv4(mp_obj_t value, uint8_t address[4]) {
    if (!mp_obj_is_str(value)) {
        mp_raise_TypeError(MP_ERROR_TEXT("IPv4 address must be a string"));
    }
    size_t length;
    const char *text = mp_obj_str_get_data(value, &length);
    size_t pos = 0;
    for (size_t group = 0; group < 4; ++group) {
        unsigned octet = 0;
        size_t digits = 0;
        while (pos < length && text[pos] >= '0' && text[pos] <= '9') {
            octet = octet * 10 + (unsigned)(text[pos++] - '0');
            if (++digits > 3 || octet > 255) {
                mp_raise_ValueError(MP_ERROR_TEXT("invalid IPv4 address"));
            }
        }
        if (digits == 0 || (group < 3 ? pos == length || text[pos++] != '.' : pos != length)) {
            mp_raise_ValueError(MP_ERROR_TEXT("invalid IPv4 address"));
        }
        address[group] = (uint8_t)octet;
    }
}
static mp_obj_t lan_ifconfig(size_t n_args, const mp_obj_t *args) {
    if (n_args == 2) {
        int error;
        if (mp_obj_is_str(args[1])) {
            size_t length;
            const char *text = mp_obj_str_get_data(args[1], &length);
            if (length != 4 || text[0] != 'd' || text[1] != 'h' || text[2] != 'c' || text[3] != 'p') {
                mp_raise_ValueError(MP_ERROR_TEXT("expected 'dhcp'"));
            }
            error = mpynn_network_configure(NULL);
        } else {
            mp_obj_t *values;
            mp_obj_get_array_fixed_n(args[1], 4, &values);
            // Parse into local storage before applying anything to the interface.
            mpynn_network_state_t requested = {0};
            uint8_t *addresses[4] = {requested.ip, requested.netmask, requested.gateway, requested.dns};
            for (size_t i = 0; i < 4; ++i) {
                lan_parse_ipv4(values[i], addresses[i]);
            }
            error = mpynn_network_configure(&requested);
        }
        if (error != 0) mp_raise_OSError(error);
        return mp_const_none;
    }
    mpynn_network_state_t state;
    if (mpynn_network_snapshot(&state) != 0) mp_raise_OSError(MP_EBUSY);
    mp_obj_t values[4];
    char text[4][16];
    const uint8_t *addresses[4] = {state.ip, state.netmask, state.gateway, state.dns};
    for (size_t i = 0; i < 4; ++i) {
        int n = snprintf(text[i], sizeof(text[i]), "%u.%u.%u.%u",
            (unsigned)addresses[i][0], (unsigned)addresses[i][1],
            (unsigned)addresses[i][2], (unsigned)addresses[i][3]);
        values[i] = mp_obj_new_str(text[i], n);
    }
    return mp_obj_new_tuple(4, values);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(lan_ifconfig_obj, 1, 2, lan_ifconfig);
static mp_obj_t lan_status(size_t n_args, const mp_obj_t *args) {
    (void)args;
    mp_arg_check_num(n_args, 0, 1, 2, false);
    if (n_args == 2) mp_raise_ValueError(MP_ERROR_TEXT("unknown status key"));
    mpynn_network_state_t state;
    if (mpynn_network_snapshot(&state) != 0) mp_raise_OSError(MP_EBUSY);
    return mp_obj_new_int(state.running ? 1 : 0);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(lan_status_obj, 1, 2, lan_status);
static const mp_rom_map_elem_t lan_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_active), MP_ROM_PTR(&lan_active_obj) },
    { MP_ROM_QSTR(MP_QSTR_isconnected), MP_ROM_PTR(&lan_isconnected_obj) },
    { MP_ROM_QSTR(MP_QSTR_ifconfig), MP_ROM_PTR(&lan_ifconfig_obj) },
    { MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&lan_status_obj) },
};
static MP_DEFINE_CONST_DICT(lan_locals, lan_locals_table);
MP_DEFINE_CONST_OBJ_TYPE(mp_network_lan_type, MP_QSTR_LAN, MP_TYPE_FLAG_NONE,
    make_new, lan_make_new, protocol, &mpynn_udp_nic_protocol, locals_dict, &lan_locals);
