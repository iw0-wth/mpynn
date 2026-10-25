// SPDX-License-Identifier: MIT
// Cross-compiler configuration overlay; keep vendored MicroPython untouched.
#include "../../../lib/micropython/mpy-cross/mpconfigport.h"
#undef MICROPY_ENABLE_DOC_STRING
#define MICROPY_ENABLE_DOC_STRING (1)
