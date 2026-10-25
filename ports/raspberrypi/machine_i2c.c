// SPDX-License-Identifier: MIT
#include <string.h>
#include "py/runtime.h"
#include "py/mperrno.h"
#include "py/mphal.h"
#include "machine_i2c.h"

typedef struct {
    mp_obj_base_t base;
    unsigned freq;
} machine_i2c_obj_t;

static void i2c_check(int result) {
    if (result >= 0) return;
    switch (result) {
        case MPYNN_I2C_INVALID: mp_raise_OSError(MP_EINVAL);
        case MPYNN_I2C_BUSY: case MPYNN_I2C_CONTEXT: mp_raise_OSError(MP_EBUSY);
        case MPYNN_I2C_NOT_READY: case MPYNN_I2C_BOARD: mp_raise_OSError(MP_ENODEV);
        case MPYNN_I2C_NACK: mp_raise_OSError(MP_ENODEV);
        case MPYNN_I2C_TIMEOUT: mp_raise_OSError(MP_ETIMEDOUT);
        default: mp_raise_OSError(MP_EIO);
    }
}
static void i2c_context(void) {
    if (!mpynn_irq_is_enabled()) mp_raise_OSError(MP_EBUSY);
}
static unsigned i2c_addr(mp_obj_t value) {
    mp_int_t addr = mp_obj_get_int(value);
    if (addr < 0 || addr >= 128) mp_raise_ValueError(MP_ERROR_TEXT("7-bit I2C address required"));
    return addr;
}
static size_t i2c_len(mp_obj_t value) {
    mp_int_t len = mp_obj_get_int(value);
    if (len < 0 || (mp_uint_t)len > MPYNN_I2C_MAX_TRANSFER)
        mp_raise_ValueError(MP_ERROR_TEXT("I2C length must be 0..65535"));
    return len;
}
static void i2c_buffer_length(size_t len) {
    if (len > MPYNN_I2C_MAX_TRANSFER)
        mp_raise_ValueError(MP_ERROR_TEXT("I2C transfer exceeds 65535 bytes"));
}
static void i2c_stop(size_t n_args, const mp_obj_t *args, size_t index) {
    if (n_args > index && !mp_obj_is_true(args[index]))
        mp_raise_NotImplementedError(MP_ERROR_TEXT("stop=False is unsupported"));
}
static void i2c_init_helper(machine_i2c_obj_t *self, size_t n_args,
    const mp_obj_t *pos_args, mp_map_t *kw_args) {
    enum { ARG_freq, ARG_timeout };
    static const mp_arg_t allowed[] = {
        {MP_QSTR_freq, MP_ARG_INT, {.u_int = 400000}},
        {MP_QSTR_timeout, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = MPYNN_I2C_TIMEOUT_US}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, args);
    mp_int_t freq = args[ARG_freq].u_int;
    if (freq != 100000 && freq != 400000)
        mp_raise_ValueError(MP_ERROR_TEXT("I2C freq must be 100000 or 400000"));
    if (args[ARG_timeout].u_int != MPYNN_I2C_TIMEOUT_US)
        mp_raise_NotImplementedError(MP_ERROR_TEXT("I2C timeout is fixed at 100000 us"));
    i2c_context();
    i2c_check(mpynn_i2c_init(self, freq, MPYNN_I2C_TIMEOUT_US));
    self->freq = freq;
}
static mp_obj_t i2c_make_new(const mp_obj_type_t *type, size_t n_args,
    size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 1, 2, true);
    if (mp_obj_get_int(args[0]) != 1)
        mp_raise_ValueError(MP_ERROR_TEXT("only I2C(1), BCM2/BCM3, is supported"));
    i2c_context();
    machine_i2c_obj_t *self = mp_obj_malloc_with_finaliser(machine_i2c_obj_t, type);
    self->freq = 0;
    mp_map_t kw_args;
    mp_map_init_fixed_table(&kw_args, n_kw, args + n_args);
    i2c_init_helper(self, n_args - 1, args + 1, &kw_args);
    return MP_OBJ_FROM_PTR(self);
}
static mp_obj_t i2c_init(size_t n_args, const mp_obj_t *args, mp_map_t *kw_args) {
    i2c_init_helper(MP_OBJ_TO_PTR(args[0]), n_args - 1, args + 1, kw_args);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(i2c_init_obj, 1, i2c_init);
static mp_obj_t i2c_deinit(mp_obj_t self) {
    i2c_context();
    i2c_check(mpynn_i2c_deinit(MP_OBJ_TO_PTR(self), 0));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(i2c_deinit_obj, i2c_deinit);
static mp_obj_t i2c_finalise(mp_obj_t self) {
    // No allocation/exception/MMIO if GC executes with IRQs masked. Native
    // deferred cleanup never dereferences the soon-to-be-freed object.
    (void)mpynn_i2c_deinit(MP_OBJ_TO_PTR(self), 1);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(i2c_finalise_obj, i2c_finalise);
static mp_obj_t i2c_readfrom(size_t n_args, const mp_obj_t *args) {
    unsigned addr = i2c_addr(args[1]);
    size_t len = i2c_len(args[2]);
    i2c_stop(n_args, args, 3);
    i2c_context();
    vstr_t buffer;
    vstr_init_len(&buffer, len);
    int result = mpynn_i2c_read(MP_OBJ_TO_PTR(args[0]), addr, buffer.buf, len);
    if (result < 0) { vstr_clear(&buffer); i2c_check(result); }
    return mp_obj_new_bytes_from_vstr(&buffer);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(i2c_readfrom_obj, 3, 4, i2c_readfrom);
static mp_obj_t i2c_readfrom_into(size_t n_args, const mp_obj_t *args) {
    unsigned addr = i2c_addr(args[1]);
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(args[2], &buffer, MP_BUFFER_WRITE);
    i2c_buffer_length(buffer.len);
    i2c_stop(n_args, args, 3);
    i2c_context();
    i2c_check(mpynn_i2c_read(MP_OBJ_TO_PTR(args[0]), addr, buffer.buf, buffer.len));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(i2c_readfrom_into_obj, 3, 4, i2c_readfrom_into);
static mp_obj_t i2c_writeto(size_t n_args, const mp_obj_t *args) {
    unsigned addr = i2c_addr(args[1]);
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(args[2], &buffer, MP_BUFFER_READ);
    i2c_buffer_length(buffer.len);
    i2c_stop(n_args, args, 3);
    i2c_context();
    int result = mpynn_i2c_write(MP_OBJ_TO_PTR(args[0]), addr, buffer.buf, buffer.len);
    i2c_check(result);
    return MP_OBJ_NEW_SMALL_INT(result);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(i2c_writeto_obj, 3, 4, i2c_writeto);
static mp_obj_t i2c_scan(mp_obj_t self) {
    i2c_context();
    mp_obj_t result = mp_obj_new_list(0, NULL);
    for (unsigned addr = 8; addr < 0x78; ++addr) {
        int status = mpynn_i2c_write(MP_OBJ_TO_PTR(self), addr, NULL, 0);
        if (status == MPYNN_I2C_NACK) continue;
        i2c_check(status);
        mp_obj_list_append(result, MP_OBJ_NEW_SMALL_INT(addr));
        // Deliberately no event/pending callback dispatch during synchronous scan.
    }
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_1(i2c_scan_obj, i2c_scan);
static const mp_arg_t mem_allowed[] = {
    {MP_QSTR_addr, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL}},
    {MP_QSTR_memaddr, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0}},
    {MP_QSTR_arg, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL}},
    {MP_QSTR_addrsize, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 8}},
};
static size_t mem_prefix(const mp_arg_val_t *args, uint8_t prefix[2]) {
    mp_int_t size = args[3].u_int, addr = args[1].u_int;
    if (size != 8 && size != 16)
        mp_raise_NotImplementedError(MP_ERROR_TEXT("addrsize must be 8 or 16"));
    if (addr < 0 || addr > (size == 8 ? 255 : 65535))
        mp_raise_ValueError(MP_ERROR_TEXT("memaddr does not fit addrsize"));
    if (size == 16) { prefix[0] = addr >> 8; prefix[1] = addr; return 2; }
    prefix[0] = addr;
    return 1;
}
static mp_obj_t i2c_readfrom_mem(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    mp_arg_val_t args[MP_ARRAY_SIZE(mem_allowed)];
    mp_arg_parse_all(n_args - 1, pos_args + 1, kw_args, MP_ARRAY_SIZE(mem_allowed), mem_allowed, args);
    unsigned addr = i2c_addr(args[0].u_obj);
    uint8_t prefix[2];
    size_t prefix_len = mem_prefix(args, prefix), len = i2c_len(args[2].u_obj);
    i2c_context();
    vstr_t buffer;
    vstr_init_len(&buffer, len);
    int result = mpynn_i2c_write_read(MP_OBJ_TO_PTR(pos_args[0]), addr, prefix, prefix_len, buffer.buf, len);
    if (result < 0) { vstr_clear(&buffer); i2c_check(result); }
    return mp_obj_new_bytes_from_vstr(&buffer);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(i2c_readfrom_mem_obj, 1, i2c_readfrom_mem);
static mp_obj_t i2c_readfrom_mem_into(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    mp_arg_val_t args[MP_ARRAY_SIZE(mem_allowed)];
    mp_arg_parse_all(n_args - 1, pos_args + 1, kw_args, MP_ARRAY_SIZE(mem_allowed), mem_allowed, args);
    unsigned addr = i2c_addr(args[0].u_obj);
    uint8_t prefix[2];
    size_t prefix_len = mem_prefix(args, prefix);
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(args[2].u_obj, &buffer, MP_BUFFER_WRITE);
    i2c_buffer_length(buffer.len);
    i2c_context();
    i2c_check(mpynn_i2c_write_read(MP_OBJ_TO_PTR(pos_args[0]), addr, prefix, prefix_len, buffer.buf, buffer.len));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(i2c_readfrom_mem_into_obj, 1, i2c_readfrom_mem_into);
static mp_obj_t i2c_writeto_mem(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    mp_arg_val_t args[MP_ARRAY_SIZE(mem_allowed)];
    mp_arg_parse_all(n_args - 1, pos_args + 1, kw_args, MP_ARRAY_SIZE(mem_allowed), mem_allowed, args);
    unsigned addr = i2c_addr(args[0].u_obj);
    uint8_t prefix[2];
    size_t prefix_len = mem_prefix(args, prefix);
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(args[2].u_obj, &buffer, MP_BUFFER_READ);
    i2c_buffer_length(buffer.len);
    if (buffer.len > MPYNN_I2C_MAX_TRANSFER - prefix_len)
        mp_raise_ValueError(MP_ERROR_TEXT("I2C memory write exceeds 65535 bytes"));
    i2c_context();
    vstr_t joined;
    vstr_init_len(&joined, prefix_len + buffer.len);
    memcpy(joined.buf, prefix, prefix_len);
    if (buffer.len) memcpy(joined.buf + prefix_len, buffer.buf, buffer.len);
    int result = mpynn_i2c_write(MP_OBJ_TO_PTR(pos_args[0]), addr, joined.buf, joined.len);
    vstr_clear(&joined);
    i2c_check(result);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(i2c_writeto_mem_obj, 1, i2c_writeto_mem);
static mp_obj_t i2c_unsupported(size_t n_args, const mp_obj_t *args) {
    mp_raise_NotImplementedError(MP_ERROR_TEXT("raw/segmented I2C operations are unsupported"));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(i2c_unsupported_obj, 1, 4, i2c_unsupported);
static const mp_rom_map_elem_t i2c_locals_table[] = {
    {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&i2c_init_obj)},
    {MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&i2c_deinit_obj)},
    {MP_ROM_QSTR(MP_QSTR___del__), MP_ROM_PTR(&i2c_finalise_obj)},
    {MP_ROM_QSTR(MP_QSTR_scan), MP_ROM_PTR(&i2c_scan_obj)},
    {MP_ROM_QSTR(MP_QSTR_readfrom), MP_ROM_PTR(&i2c_readfrom_obj)},
    {MP_ROM_QSTR(MP_QSTR_readfrom_into), MP_ROM_PTR(&i2c_readfrom_into_obj)},
    {MP_ROM_QSTR(MP_QSTR_writeto), MP_ROM_PTR(&i2c_writeto_obj)},
    {MP_ROM_QSTR(MP_QSTR_readfrom_mem), MP_ROM_PTR(&i2c_readfrom_mem_obj)},
    {MP_ROM_QSTR(MP_QSTR_readfrom_mem_into), MP_ROM_PTR(&i2c_readfrom_mem_into_obj)},
    {MP_ROM_QSTR(MP_QSTR_writeto_mem), MP_ROM_PTR(&i2c_writeto_mem_obj)},
    {MP_ROM_QSTR(MP_QSTR_start), MP_ROM_PTR(&i2c_unsupported_obj)},
    {MP_ROM_QSTR(MP_QSTR_stop), MP_ROM_PTR(&i2c_unsupported_obj)},
    {MP_ROM_QSTR(MP_QSTR_readinto), MP_ROM_PTR(&i2c_unsupported_obj)},
    {MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&i2c_unsupported_obj)},
    {MP_ROM_QSTR(MP_QSTR_writevto), MP_ROM_PTR(&i2c_unsupported_obj)},
};
static MP_DEFINE_CONST_DICT(i2c_locals, i2c_locals_table);
MP_DEFINE_CONST_OBJ_TYPE(machine_i2c_type, MP_QSTR_I2C, MP_TYPE_FLAG_NONE,
    make_new, i2c_make_new, locals_dict, &i2c_locals);
