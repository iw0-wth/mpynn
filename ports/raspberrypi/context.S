/* SPDX-License-Identifier: MIT */
.syntax unified
.arm
.fpu vfp
.text
.align 2
.global mpynn_setjmp
.type mpynn_setjmp, %function
mpynn_setjmp:
    stmia r0!, {r4-r11, sp, lr}
    vstmia r0, {d8-d15}
    mov r0, #0
    bx lr
.size mpynn_setjmp, .-mpynn_setjmp

.global mpynn_longjmp
.type mpynn_longjmp, %function
mpynn_longjmp:
    add r2, r0, #40
    vldmia r2, {d8-d15}
    ldmia r0, {r4-r11, sp, lr}
    cmp r1, #0
    moveq r1, #1
    mov r0, r1
    bx lr
.size mpynn_longjmp, .-mpynn_longjmp
.section .note.GNU-stack,"",%progbits
