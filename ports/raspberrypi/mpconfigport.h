// SPDX-License-Identifier: MIT
#ifndef MPYNN_RASPBERRYPI_MPCONFIGPORT_H
#define MPYNN_RASPBERRYPI_MPCONFIGPORT_H
#include <stdint.h>
#include <alloca.h>
#include "board_config.h"

#define MICROPY_CONFIG_ROM_LEVEL (MICROPY_CONFIG_ROM_LEVEL_BASIC_FEATURES)
#define MICROPY_ENABLE_COMPILER (1)
#define MICROPY_ENABLE_GC (1)
#define MICROPY_ENABLE_FINALISER (1)
#define MICROPY_STACK_CHECK (1)
#define MICROPY_HELPER_REPL (1)
#define MICROPY_REPL_AUTO_INDENT (1)
#define MICROPY_ENABLE_SCHEDULER (1)
#define MICROPY_KBD_EXCEPTION (1)
#define MICROPY_PY_FSTRINGS (1)
#define MICROPY_PY_TSTRINGS (1)
#ifndef MICROPY_MODULE_FROZEN_MPY
#define MICROPY_MODULE_FROZEN_MPY (1)
#endif
#ifndef MICROPY_MODULE_FROZEN_STR
#define MICROPY_MODULE_FROZEN_STR (1)
#endif
#ifndef MICROPY_QSTR_EXTRA_POOL
#define MICROPY_QSTR_EXTRA_POOL mp_qstr_frozen_const_pool
#endif
#define MICROPY_LONGINT_IMPL (MICROPY_LONGINT_IMPL_MPZ)
#define MICROPY_FLOAT_IMPL (MICROPY_FLOAT_IMPL_FLOAT)
#define MICROPY_USE_INTERNAL_ERRNO (1)
#define MICROPY_USE_INTERNAL_PRINTF (1)
#define MICROPY_PY_SYS_PLATFORM "raspberrypi"
#define MICROPY_PY_SYS_STDFILES (1)
#define MICROPY_PY_BUILTINS_HELP (1)
#define MICROPY_PY_BUILTINS_HELP_MODULES (1)
#define MICROPY_PY_TIME (1)
#define MICROPY_PY_TIME_GMTIME_LOCALTIME_MKTIME (1)
#define MICROPY_PY_TIME_TIME_TIME_NS (1)
#define MICROPY_EPOCH_IS_1970 (1)
#define MICROPY_PY_TIME_INCLUDEFILE "modtime_port.c"
#define MICROPY_PY_JSON (1)
#define MICROPY_PY_SELECT (1)
// No native emitter/threads until their ARMv6 and GC contracts are validated.
#define MICROPY_EMIT_THUMB (0)
#define MICROPY_EMIT_ARM (0)
#define MICROPY_PY_THREAD (0)
// Storage is enabled; network and inference await their real adapters.
#define MICROPY_VFS (1)
#define MICROPY_READER_VFS (1)
#define MICROPY_PY_OS (1)
#define MICROPY_PY_OS_SYNC (1)
#define MICROPY_PY_OS_URANDOM (0)
#define MICROPY_FATFS_ENABLE_LFN (1)
#define MICROPY_FATFS_RPATH (2)
#define MICROPY_FATFS_NORTC (1)
#define MICROPY_PY_MACHINE_SDCARD (0)
#define MICROPY_PY_MACHINE (1)
#define MICROPY_PY_MACHINE_I2C (1)
#define MICROPY_PY_MACHINE_SOFTI2C (1)
#define MICROPY_PY_MACHINE_SPI (1)
#define MICROPY_PY_MACHINE_SOFTSPI (1)
#define MICROPY_PY_MACHINE_WDT (1)
#define MICROPY_PY_MACHINE_TIMER (1)
#define MICROPY_PY_SYS_EXIT (1)
#define MICROPY_PY_MACHINE_INCLUDEFILE "modmachine_port.c"
#define MICROPY_PY_MACHINE_BARE_METAL_FUNCS (0)
#define MICROPY_PY_MACHINE_RESET (0)
#define MICROPY_PY_MACHINE_MEMX (0)
#define MICROPY_PY_MACHINE_SIGNAL (0)
#define MICROPY_PY_MACHINE_DISABLE_IRQ_ENABLE_IRQ (1)
#define MICROPY_PY_NETWORK (1)
#define MICROPY_PY_SOCKET (1)
#define MICROPY_PY_SOCKET_EXTENDED_STATE (1)
#define MICROPY_PORT_SOCKET_SENDALL mpynn_socket_sendall
#define MICROPY_PORT_SOCKET_GETPEERNAME mpynn_socket_getpeername
#define MICROPY_PORT_SOCKET_GETSOCKNAME mpynn_socket_getsockname
#define MICROPY_PORT_SOCKET_SHUTDOWN mpynn_socket_shutdown
#define MICROPY_PORT_SOCKET_GETSOCKOPT mpynn_socket_getsockopt
#ifndef MICROPY_PY_SSL
#define MICROPY_PY_SSL (1)
#endif
#ifndef MICROPY_SSL_MBEDTLS
#define MICROPY_SSL_MBEDTLS (1)
#endif
#define MICROPY_TRACKED_ALLOC (1)
#define MICROPY_PY_BUILTINS_MEMORYVIEW (1)
#define MICROPY_PY_NETWORK_HOSTNAME_DEFAULT "mpynn"
#define MICROPY_PY_NETWORK_HOSTNAME_MAX_LEN (32)
#define MICROPY_PORT_NETWORK_INTERFACES \
    { MP_ROM_QSTR(MP_QSTR_LAN), MP_ROM_PTR(&mp_network_lan_type) },
#define MICROPY_PY_NETWORK_MODULE_GLOBALS_INCLUDEFILE "modnetwork_globals.h"
#define MICROPY_PY_NETWORK_INCLUDEFILE "modnetwork_port.h"
#define MICROPY_PY_ML (1)
#define MICROPY_PY_ML_TFLM (1)
#define MICROPY_PY_ULAB (1)
#define MICROPY_PY_CSI (0)
#define MICROPY_PY_CSI_NG (0)
#define MICROPY_PY_PROTOCOL (0)

// Standard ARM nlrthumb's ARM-state branch omits VFP callee-saved registers.
// Use a port-local, VFP-safe setjmp ABI for NLR and conservative GC capture.
#define MICROPY_NLR_SETJMP (1)
#define MICROPY_GCREGS_SETJMP (1)
void mpynn_event_poll(void);
void mpynn_poll_io(void);
#define MICROPY_INTERNAL_EVENT_HOOK mpynn_poll_io()
#define MICROPY_VM_HOOK_LOOP do { mpynn_event_poll(); } while (0);
// VM's local NLR handler has already been popped at RETURN: no exceptions here.
#define MICROPY_VM_HOOK_RETURN do { mpynn_poll_io(); } while (0);
#define MP_STATE_PORT MP_STATE_VM
typedef long mp_off_t;
#endif
