// SPDX-License-Identifier: MIT
#ifndef MPYNN_MACHINE_SDCARD_H
#define MPYNN_MACHINE_SDCARD_H
#include "py/obj.h"
extern const mp_obj_type_t machine_sdcard_type;
// Mount the existing boot card read-only. Returns false on absent/invalid FAT;
// never formats, never writes, never prevents entry to the UART REPL.
bool mpynn_storage_mount(void);
// Called after gc_sweep_all; must not access any GC-owned VFS objects.
void mpynn_storage_sync(void);
#endif
