// SPDX-License-Identifier: MIT
#ifndef MPYNN_RPI1B_BOARD_CONFIG_H
#define MPYNN_RPI1B_BOARD_CONFIG_H
#define MICROPY_HW_BOARD_NAME "mpynn Raspberry Pi 1B"
#define MICROPY_HW_MCU_NAME "BCM2835 ARM1176JZF-S"
// Keep this much of Circle's allocator free for network/USB/SD runtime work;
// the MicroPython GC heap takes the remaining measured low-memory heap.
#define MPYNN_CIRCLE_HEAP_RESERVE (32u * 1024u * 1024u)
#define MPYNN_GC_HEAP_MIN (16u * 1024u * 1024u)
#define MPYNN_STACK_LIMIT (64u * 1024u)
#define MPYNN_UART_BAUD (115200)
#endif
