// SPDX-License-Identifier: MIT
// Included by modmachine_port.c, not compiled as a separate translation unit.
#include "py/runtime.h"
#include "py/mperrno.h"
#include "sdcard_bridge.h"

static mp_obj_t mpynn_storage_info(void) {
    // Snapshot only: no SD reads/writes, synchronization, or readiness probes.
    // Counters include failed requests, but sectors count successful transfers.
    // The last failure is sticky; last_stage is 0 validation, 1 seek, 2 transfer.
    mpynn_sd_diagnostics_t snapshot;
    if (mpynn_sd_diagnostics(&snapshot) != 0) {
        mp_raise_OSError(MP_EBUSY);
    }

    mp_obj_t info = mp_obj_new_dict(12);
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_read_requests), mp_obj_new_int_from_ull(snapshot.read_requests));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_write_requests), mp_obj_new_int_from_ull(snapshot.write_requests));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_read_sectors), mp_obj_new_int_from_ull(snapshot.read_sectors));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_write_sectors), mp_obj_new_int_from_ull(snapshot.write_sectors));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_failures), mp_obj_new_int_from_ull(snapshot.failures));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_last_block), mp_obj_new_int_from_ull(snapshot.last_block));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_last_length), mp_obj_new_int_from_ull(snapshot.last_length));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_last_status), mp_obj_new_int(snapshot.last_status));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_last_result), mp_obj_new_int(snapshot.last_result));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_last_writing), mp_obj_new_int_from_uint(snapshot.last_writing));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_last_stage), mp_obj_new_int_from_uint(snapshot.last_stage));
    mp_obj_dict_store(info, MP_OBJ_NEW_QSTR(MP_QSTR_ready), mp_obj_new_int_from_uint(snapshot.ready));
    return info;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mpynn_storage_info_obj, mpynn_storage_info);
