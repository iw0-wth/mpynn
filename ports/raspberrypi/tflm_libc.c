// SPDX-License-Identifier: MIT
// The reference TFLM archive uses libc only for diagnostics and numeric parsing.
// Circle owns stdio and VM lifetime; never let a kernel terminate the firmware.
#include <stdio.h>
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <limits.h>
#include <errno.h>
#include <reent.h>
#include "py/runtime.h"

struct _reent mpynn_newlib_reent;
struct _reent *_impure_ptr = &mpynn_newlib_reent;
#include "py/mphal.h"

size_t fwrite(const void *data, size_t size, size_t count, FILE *stream) {
    (void)stream; // TFLM/KissFFT diagnostic stdout/stderr only, not VFS FILEs.
    if (!size || !count) return 0;
    if (count > SIZE_MAX / size) return 0;
    mp_hal_stdout_tx_strn(data, size * count);
    return count;
}

MP_NORETURN void abort(void) {
    mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("TFLM native abort"));
}

MP_NORETURN void exit(int status) {
    mp_raise_msg_varg(&mp_type_RuntimeError, MP_ERROR_TEXT("TFLM native exit %d"), status);
}

static int tflm_digit(unsigned char ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'z') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'Z') return ch - 'A' + 10;
    return -1;
}

long long strtoll(const char *text, char **end, int base) {
    const char *p = text;
    if (end) *end = (char *)text;
    if (base != 0 && (base < 2 || base > 36)) { errno = EINVAL; return 0; }
    while (*p == ' ' || (*p >= '\t' && *p <= '\r')) ++p;
    bool negative = false;
    if (*p == '+' || *p == '-') { negative = *p == '-'; ++p; }
    if ((base == 0 || base == 16) && p[0] == '0' && (p[1] == 'x' || p[1] == 'X') &&
        tflm_digit((unsigned char)p[2]) >= 0 && tflm_digit((unsigned char)p[2]) < 16) {
        p += 2; base = 16;
    } else if (base == 0) {
        base = *p == '0' ? 8 : 10;
    }
    const unsigned long long limit = negative ? (unsigned long long)LLONG_MAX + 1u : (unsigned long long)LLONG_MAX;
    unsigned long long value = 0;
    bool any = false, overflow = false;
    for (;;) {
        int digit = tflm_digit((unsigned char)*p);
        if (digit < 0 || digit >= base) break;
        any = true;
        if (value > (limit - (unsigned)digit) / (unsigned)base) overflow = true;
        else if (!overflow) value = value * (unsigned)base + (unsigned)digit;
        ++p;
    }
    if (!any) return 0;
    if (end) *end = (char *)p;
    if (overflow) { errno = ERANGE; return negative ? LLONG_MIN : LLONG_MAX; }
    if (negative && value == (unsigned long long)LLONG_MAX + 1u) return LLONG_MIN;
    return negative ? -(long long)value : (long long)value;
}

void *bsearch(const void *key, const void *base, size_t count, size_t size, int (*compare)(const void *, const void *)) {
    if (!size || count > SIZE_MAX / size) return NULL;
    const uint8_t *items = (const uint8_t *)base;
    size_t low = 0, high = count;
    while (low < high) {
        size_t mid = low + (high - low) / 2;
        int result = compare(key, items + mid * size);
        if (result == 0) return (void *)(items + mid * size);
        if (result < 0) high = mid;
        else low = mid + 1;
    }
    return NULL;
}

MP_NORETURN void __assert_func(const char *file, int line, const char *function, const char *condition) {
    (void)file; (void)line; (void)function; (void)condition;
    mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("TFLM native assertion"));
}
