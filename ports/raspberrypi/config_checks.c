// SPDX-License-Identifier: MIT
// Compile-only contracts for the real Pi 1B port configuration and context ABI.
#include <stddef.h>
#include "py/mpconfig.h"
#include "setjmp.h"

#if !defined(__arm__) || defined(__thumb__) || __ARM_ARCH != 6
#error "RPI1B must compile as ARMv6 ARM state"
#endif
#ifndef __ARM_PCS_VFP
#error "RPI1B must use the hard-float procedure call ABI"
#endif
_Static_assert(sizeof(void *) == 4, "Pi 1 ABI requires 32-bit pointers");
_Static_assert(MICROPY_PY_FSTRINGS == 1, "f-strings must be enabled");
_Static_assert(MICROPY_PY_TSTRINGS == 1, "template strings must be enabled");
_Static_assert(MICROPY_MODULE_BUILTIN_SUBPACKAGES == 1, "string.templatelib requires subpackages");
_Static_assert(MICROPY_ENABLE_GC == 1, "GC required");
_Static_assert(MICROPY_ENABLE_DOC_STRING == 1, "module doc strings required for REPL/demo help");
_Static_assert(MICROPY_ENABLE_SCHEDULER == 1, "scheduler required");
_Static_assert(MICROPY_NLR_SETJMP == 1, "use the VFP-safe private NLR context");
_Static_assert(MICROPY_GCREGS_SETJMP == 1, "GC must capture the private context");
_Static_assert(MICROPY_FLOAT_IMPL == MICROPY_FLOAT_IMPL_FLOAT, "float32 AI baseline");
_Static_assert(MICROPY_LONGINT_IMPL == MICROPY_LONGINT_IMPL_MPZ, "full precision ints");
_Static_assert(MICROPY_PY_CSI == 0 && MICROPY_PY_CSI_NG == 0, "no camera modules");
_Static_assert(MICROPY_PY_PROTOCOL == 0, "no OpenMV IDE protocol");
_Static_assert(MICROPY_PY_ML && MICROPY_PY_ML_TFLM, "native UML TFLM binding required");
_Static_assert(MICROPY_PY_ULAB && MODULE_ULAB_ENABLED, "native ulab required");
_Static_assert(MICROPY_PY_MACHINE == 1, "machine base required");
_Static_assert(MICROPY_PY_MACHINE_WDT == 1, "port-owned watchdog required");
_Static_assert(MICROPY_PY_SYS_EXIT == 1, "standard soft reset needs SystemExit");
_Static_assert(MICROPY_PY_MACHINE_DISABLE_IRQ_ENABLE_IRQ == 1, "IRQ state control required");
_Static_assert(MICROPY_PY_MACHINE_MEMX == 0, "do not bypass pin ownership with raw MMIO");
_Static_assert(MICROPY_VFS && MICROPY_VFS_FAT && MICROPY_READER_VFS, "SD FAT VFS required");
_Static_assert(MICROPY_PY_MACHINE_SDCARD == 0, "boot SD is internal VFS storage, not machine.SDCard");
_Static_assert(MICROPY_FATFS_NORTC == 1, "no unimplemented RTC timestamp hook");
_Static_assert(sizeof(jmp_buf) == 104, "context.S buffer size must match");
_Static_assert(offsetof(__typeof__(((jmp_buf){0})[0]), vfp) == 40, "context.S VFP offset");
_Static_assert(_Alignof(jmp_buf) >= 8, "VFP context must be aligned");
