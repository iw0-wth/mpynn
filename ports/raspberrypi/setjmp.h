// SPDX-License-Identifier: MIT
// Private MicroPython context ABI. Symbol names intentionally do not collide
// with Circle's integer-only setjmp implementation or newlib's jmp_buf.
#ifndef MPYNN_SETJMP_H
#define MPYNN_SETJMP_H
#include <stdint.h>
typedef struct {
    uint32_t core[10]; // r4-r11, sp, lr
    uint64_t vfp[8];   // d8-d15 (AAPCS callee-saved)
} jmp_buf[1];
int mpynn_setjmp(jmp_buf env) __attribute__((returns_twice));
void mpynn_longjmp(jmp_buf env, int value) __attribute__((noreturn));
#define setjmp mpynn_setjmp
#define longjmp mpynn_longjmp
#endif
