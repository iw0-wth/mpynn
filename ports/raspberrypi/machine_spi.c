// SPDX-License-Identifier: MIT
#include <string.h>
#include "py/runtime.h"
#include "py/mperrno.h"
#include "extmod/modmachine.h"
#include "machine_spi.h"

typedef struct {
    mp_obj_base_t base;
    unsigned baudrate, polarity, phase;
} machine_spi_obj_t;
// SPI0 has a single stable identity. Its C++ lifetime is independent of GC.
static machine_spi_obj_t spi0 = {{&machine_spi_type}, 1000000, 0, 0};
static void spi_raise(int status) {
    switch (status) {
        case MPYNN_SPI_OK: return;
        case MPYNN_SPI_INVALID: mp_raise_ValueError(MP_ERROR_TEXT("invalid SPI parameters or buffer"));
        case MPYNN_SPI_BUSY: mp_raise_OSError(MP_EBUSY);
        case MPYNN_SPI_UNINITIALIZED: mp_raise_OSError(MP_ENODEV);
        case MPYNN_SPI_TIMEOUT: mp_raise_OSError(MP_ETIMEDOUT);
        case MPYNN_SPI_BOARD: mp_raise_NotImplementedError(MP_ERROR_TEXT("unsupported SPI board"));
        default: mp_raise_OSError(MP_EIO);
    }
}
static void spi_init_helper(machine_spi_obj_t *self, size_t n_args,
    const mp_obj_t *pos_args, mp_map_t *kw_args, bool defaults) {
    enum { BAUD, POL, PHASE, BITS, FIRST, SCK, MOSI, MISO };
    static const mp_arg_t allowed[] = {
        {MP_QSTR_baudrate, MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL}},
        {MP_QSTR_polarity, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL}},
        {MP_QSTR_phase, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL}},
        {MP_QSTR_bits, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = 8}},
        {MP_QSTR_firstbit, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = MICROPY_PY_MACHINE_SPI_MSB}},
        {MP_QSTR_sck, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_obj = mp_const_none}},
        {MP_QSTR_mosi, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_obj = mp_const_none}},
        {MP_QSTR_miso, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_obj = mp_const_none}},
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, args);
    mp_int_t baud = defaults ? 1000000 : self->baudrate;
    mp_int_t polarity = defaults ? 0 : self->polarity;
    mp_int_t phase = defaults ? 0 : self->phase;
    if (args[BAUD].u_obj != MP_OBJ_NULL) baud = mp_obj_get_int(args[BAUD].u_obj);
    if (args[POL].u_obj != MP_OBJ_NULL) polarity = mp_obj_get_int(args[POL].u_obj);
    if (args[PHASE].u_obj != MP_OBJ_NULL) phase = mp_obj_get_int(args[PHASE].u_obj);
    if (baud < 4000 || baud > 125000000 || polarity < 0 || polarity > 1 || phase < 0 || phase > 1) {
        spi_raise(MPYNN_SPI_INVALID);
    }
    if (args[BITS].u_int != 8 || args[FIRST].u_int != MICROPY_PY_MACHINE_SPI_MSB) {
        mp_raise_NotImplementedError(MP_ERROR_TEXT("SPI supports 8-bit MSB only"));
    }
    // Routing changes are deliberately unsupported, not ignored or applied to
    // unclaimed pads. The fixed routing is SCK11/MOSI10/MISO9.
    if (args[SCK].u_obj != mp_const_none || args[MOSI].u_obj != mp_const_none || args[MISO].u_obj != mp_const_none) {
        mp_raise_NotImplementedError(MP_ERROR_TEXT("SPI0 uses fixed pins; omit sck/mosi/miso"));
    }
    spi_raise(mpynn_spi_init((unsigned)baud, (unsigned)polarity, (unsigned)phase));
    // Commit print/re-init state only after the bridge successfully initializes.
    self->baudrate = baud; self->polarity = polarity; self->phase = phase;
}
static mp_obj_t spi_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    (void)type;
    mp_arg_check_num(n_args, n_kw, 1, 2, true);
    if (mp_obj_get_int(args[0]) != 0) mp_raise_ValueError(MP_ERROR_TEXT("only SPI(0) is defined"));
    mp_map_t kw_args;
    mp_map_init_fixed_table(&kw_args, n_kw, args + n_args);
    spi_init_helper(&spi0, n_args - 1, args + 1, &kw_args, true);
    return MP_OBJ_FROM_PTR(&spi0);
}
static void spi_print(const mp_print_t *print, mp_obj_t self_in, mp_print_kind_t kind) {
    (void)kind;
    machine_spi_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_printf(print, "SPI(0, baudrate=%u, polarity=%u, phase=%u, bits=8, firstbit=MSB, sck=11, mosi=10, miso=9)",
        self->baudrate, self->polarity, self->phase);
}
static void spi_protocol_init(mp_obj_base_t *obj, size_t n_args, const mp_obj_t *args, mp_map_t *kw_args) {
    spi_init_helper((machine_spi_obj_t *)obj, n_args, args, kw_args, false);
}
static mp_obj_t spi_init(size_t n_args, const mp_obj_t *args, mp_map_t *kw_args) {
    spi_protocol_init(MP_OBJ_TO_PTR(args[0]), n_args - 1, args + 1, kw_args);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(spi_init_obj, 1, spi_init);
static void spi_protocol_deinit(mp_obj_base_t *obj) {
    (void)obj;
    spi_raise(mpynn_spi_deinit());
}
static mp_obj_t spi_deinit(mp_obj_t self) {
    spi_protocol_deinit(MP_OBJ_TO_PTR(self));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(spi_deinit_obj, spi_deinit);
static void spi_protocol_transfer(mp_obj_base_t *obj, size_t len, const uint8_t *src, uint8_t *dest) {
    (void)obj;
    spi_raise(mpynn_spi_transfer(len, src, dest));
}
static void spi_check_length(size_t len) {
    if (len > 0xFFFF) mp_raise_ValueError(MP_ERROR_TEXT("SPI transfer exceeds 65535 bytes"));
}
static mp_obj_t spi_read(size_t n_args, const mp_obj_t *args) {
    spi_raise(mpynn_spi_check());
    mp_int_t length = mp_obj_get_int(args[1]);
    if (length < 0) mp_raise_ValueError(MP_ERROR_TEXT("negative SPI read length"));
    spi_check_length(length);
    unsigned fill = n_args == 3 ? mp_obj_get_int(args[2]) : 0;
    vstr_t data;
    vstr_init_len(&data, length);
    memset(data.buf, fill, data.len);
    // No C++ frame remains live when an MP exception is raised. Free the
    // temporary allocation explicitly on error, so repeated timeouts don't leak.
    int result = mpynn_spi_transfer(data.len, (uint8_t *)data.buf, (uint8_t *)data.buf);
    if (result) { vstr_clear(&data); spi_raise(result); }
    return mp_obj_new_bytes_from_vstr(&data);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(spi_read_obj, 2, 3, spi_read);
static mp_obj_t spi_readinto(size_t n_args, const mp_obj_t *args) {
    spi_raise(mpynn_spi_check());
    mp_buffer_info_t data;
    mp_get_buffer_raise(args[1], &data, MP_BUFFER_WRITE);
    spi_check_length(data.len);
    unsigned fill = n_args == 3 ? mp_obj_get_int(args[2]) : 0;
    memset(data.buf, fill, data.len);
    spi_raise(mpynn_spi_transfer(data.len, data.buf, data.buf));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(spi_readinto_obj, 2, 3, spi_readinto);
static mp_obj_t spi_write(mp_obj_t self, mp_obj_t buffer) {
    (void)self;
    spi_raise(mpynn_spi_check());
    mp_buffer_info_t data;
    mp_get_buffer_raise(buffer, &data, MP_BUFFER_READ);
    spi_raise(mpynn_spi_transfer(data.len, data.buf, NULL));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(spi_write_obj, spi_write);
static mp_obj_t spi_write_readinto(mp_obj_t self, mp_obj_t src_in, mp_obj_t dest_in) {
    (void)self;
    spi_raise(mpynn_spi_check());
    mp_buffer_info_t src, dest;
    mp_get_buffer_raise(src_in, &src, MP_BUFFER_READ);
    mp_get_buffer_raise(dest_in, &dest, MP_BUFFER_WRITE);
    if (src.len != dest.len) mp_raise_ValueError(MP_ERROR_TEXT("buffers must be the same length"));
    spi_raise(mpynn_spi_transfer(src.len, src.buf, dest.buf));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(spi_write_readinto_obj, spi_write_readinto);
static const mp_machine_spi_p_t spi_protocol = {
    .init = spi_protocol_init, .deinit = spi_protocol_deinit, .transfer = spi_protocol_transfer,
};
static const mp_rom_map_elem_t spi_locals_table[] = {
    {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&spi_init_obj)},
    {MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&spi_deinit_obj)},
    {MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&spi_read_obj)},
    {MP_ROM_QSTR(MP_QSTR_readinto), MP_ROM_PTR(&spi_readinto_obj)},
    {MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&spi_write_obj)},
    {MP_ROM_QSTR(MP_QSTR_write_readinto), MP_ROM_PTR(&spi_write_readinto_obj)},
    {MP_ROM_QSTR(MP_QSTR_MSB), MP_ROM_INT(MICROPY_PY_MACHINE_SPI_MSB)},
    {MP_ROM_QSTR(MP_QSTR_LSB), MP_ROM_INT(MICROPY_PY_MACHINE_SPI_LSB)},
};
static MP_DEFINE_CONST_DICT(spi_locals, spi_locals_table);
MP_DEFINE_CONST_OBJ_TYPE(machine_spi_type, MP_QSTR_SPI, MP_TYPE_FLAG_NONE,
    make_new, spi_make_new, print, spi_print, protocol, &spi_protocol, locals_dict, &spi_locals);
