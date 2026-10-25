// SPDX-License-Identifier: MIT
#include "py/runtime.h"
#include "py/objstr.h"
#include "py/mperrno.h"
#include "py/smallint.h"
#include "py/mphal.h"
#include "extmod/vfs.h"
#include "machine_sdcard.h"
#include "sdcard_bridge.h"

typedef struct {
    mp_obj_base_t base;
    bool readonly;
} machine_sdcard_obj_t;

static int sd_errno(int status) {
    switch (status) {
        case MPYNN_SD_OK: return 0;
        case MPYNN_SD_NOT_READY: return MP_ENODEV;
        case MPYNN_SD_INVALID: case MPYNN_SD_RANGE: return MP_EINVAL;
        case MPYNN_SD_BUSY: case MPYNN_SD_CONTEXT: return MP_EBUSY;
        default: return MP_EIO;
    }
}
static int sd_context(void) {
    return mpynn_irq_is_enabled() ? 0 : MP_EBUSY;
}
static mp_obj_t sdcard_make_new(const mp_obj_type_t *type, size_t n_args,
                              size_t n_kw, const mp_obj_t *all_args) {
    enum { ARG_id, ARG_readonly };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_id, MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_readonly, MP_ARG_KW_ONLY | MP_ARG_BOOL, {.u_bool = true} },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args, MP_ARRAY_SIZE(allowed), allowed, args);
    if (args[ARG_id].u_int != 0) mp_raise_ValueError(MP_ERROR_TEXT("only onboard SDCard(0) is available"));
    int err = sd_context();
    if (err) mp_raise_OSError(err);
    if (!mpynn_sd_ready()) mp_raise_OSError(MP_ENODEV);
    uint64_t count = 0;
    int capacity_error = sd_errno(mpynn_sd_block_count(&count));
    if (capacity_error) mp_raise_OSError(capacity_error);
    // vfs_blockdev.c passes each block number as an MP small int; oofatfs
    // also converts the sector count to signed mp_int_t. Reject unaddressable
    // cards here instead of failing halfway through filesystem access.
    if (count == 0 || count > (uint64_t)MP_SMALL_INT_MAX) mp_raise_OSError(MP_EFBIG);
    machine_sdcard_obj_t *self = mp_obj_malloc(machine_sdcard_obj_t, type);
    self->readonly = args[ARG_readonly].u_bool;
    return MP_OBJ_FROM_PTR(self);
}
static mp_obj_t sdcard_readblocks(mp_obj_t self_in, mp_obj_t block_in, mp_obj_t buffer_in) {
    (void)self_in;
    mp_uint_t block = mp_obj_get_uint(block_in);
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(buffer_in, &buffer, MP_BUFFER_WRITE);
    int err = sd_context();
    if (!err) err = sd_errno(mpynn_sd_read(block, buffer.buf, buffer.len));
    return MP_OBJ_NEW_SMALL_INT(-err);
}
static MP_DEFINE_CONST_FUN_OBJ_3(sdcard_readblocks_obj, sdcard_readblocks);
static mp_obj_t sdcard_writeblocks(mp_obj_t self_in, mp_obj_t block_in, mp_obj_t buffer_in) {
    machine_sdcard_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_uint_t block = mp_obj_get_uint(block_in);
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(buffer_in, &buffer, MP_BUFFER_READ);
    int err = self->readonly ? MP_EROFS : sd_context();
    if (!err) err = sd_errno(mpynn_sd_write(block, buffer.buf, buffer.len));
    return MP_OBJ_NEW_SMALL_INT(-err);
}
static MP_DEFINE_CONST_FUN_OBJ_3(sdcard_writeblocks_obj, sdcard_writeblocks);
static mp_obj_t sdcard_ioctl(mp_obj_t self_in, mp_obj_t cmd_in, mp_obj_t arg_in) {
    (void)self_in; (void)arg_in;
    mp_int_t cmd = mp_obj_get_int(cmd_in);
    int err = sd_context();
    if (err) return MP_OBJ_NEW_SMALL_INT(-err);
    switch (cmd) {
        case MP_BLOCKDEV_IOCTL_INIT:
            return MP_OBJ_NEW_SMALL_INT(mpynn_sd_ready() ? 0 : -MP_ENODEV);
        case MP_BLOCKDEV_IOCTL_DEINIT:
        case MP_BLOCKDEV_IOCTL_SYNC:
            // Platform owns controller; a VFS object must not tear it down.
            return MP_OBJ_NEW_SMALL_INT(-sd_errno(mpynn_sd_sync()));
        case MP_BLOCKDEV_IOCTL_BLOCK_COUNT: {
            uint64_t count = 0;
            err = sd_errno(mpynn_sd_block_count(&count));
            if (err) mp_raise_OSError(err);
            if (count == 0 || count > (uint64_t)MP_SMALL_INT_MAX) mp_raise_OSError(MP_EFBIG);
            return MP_OBJ_NEW_SMALL_INT((mp_int_t)count);
        }
        case MP_BLOCKDEV_IOCTL_BLOCK_SIZE:
            return MP_OBJ_NEW_SMALL_INT(512);
        default:
            return mp_const_none;
    }
}
static MP_DEFINE_CONST_FUN_OBJ_3(sdcard_ioctl_obj, sdcard_ioctl);
static const mp_rom_map_elem_t sdcard_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_readblocks), MP_ROM_PTR(&sdcard_readblocks_obj) },
    { MP_ROM_QSTR(MP_QSTR_writeblocks), MP_ROM_PTR(&sdcard_writeblocks_obj) },
    { MP_ROM_QSTR(MP_QSTR_ioctl), MP_ROM_PTR(&sdcard_ioctl_obj) },
};
static MP_DEFINE_CONST_DICT(sdcard_locals, sdcard_locals_table);
MP_DEFINE_CONST_OBJ_TYPE(machine_sdcard_type, MP_QSTR_SDCard, MP_TYPE_FLAG_NONE,
    make_new, sdcard_make_new, locals_dict, &sdcard_locals);

bool mpynn_storage_mount(void) {
    if (!mpynn_sd_ready()) return false;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_obj_t device_args[] = {MP_OBJ_NEW_QSTR(MP_QSTR_readonly), mp_const_false};
        mp_obj_t device = sdcard_make_new(&machine_sdcard_type, 0, 1, device_args);
        // The onboard SD is boot storage, analogous to MCU internal flash:
        // mount it as the root VFS, writable by default, without formatting.
        mp_obj_t args[] = {device, mp_obj_new_str("/", 1)};
        mp_obj_t kw_table[] = {MP_OBJ_NEW_QSTR(MP_QSTR_readonly), mp_const_false};
        mp_map_t kwargs;
        mp_map_init_fixed_table(&kwargs, 1, kw_table);
        // Standard VFS detects FAT/MBR; readonly=False and default mkfs=False.
        mp_vfs_mount(2, args, &kwargs);
        mp_vfs_chdir(args[1]);
        nlr_pop();
        return true;
    }
    mp_printf(&mp_plat_print, "SD mount failed; UART REPL available (no format attempted)\n");
    mp_obj_print_exception(&mp_plat_print, MP_OBJ_FROM_PTR(nlr.ret_val));
    return false;
}
void mpynn_storage_sync(void) {
    // gc_sweep_all has already closed/finalized native FAT file objects and freed
    // the VM heap. Never dereference vfs_mount_table here: it is now stale.
    // Circle remains alive and has no additional block write cache.
    if (mpynn_sd_ready()) (void)mpynn_sd_sync();
}
