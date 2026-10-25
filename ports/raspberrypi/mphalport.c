// SPDX-License-Identifier: MIT
#include "py/runtime.h"
#include "py/mphal.h"
#include "py/stream.h"
#include "shared/runtime/interrupt_char.h"
#include "circle_bridge.h"
#include "machine_timer.h"
#include "machine_pin.h"
#include "../../modules/audio/audio_file.h"

// Circle IRQ-buffered UART -> bounded VM-side ring. No Python in an IRQ.
static unsigned char rx[256];
static unsigned rx_in, rx_out;
volatile unsigned mpynn_console_rx_dropped;
void mpynn_console_reset(void) { rx_in = rx_out = 0; }
static void poll_console(void) {
    for (unsigned count = 0; count < 32; ++count) {
        unsigned next = (rx_in + 1) % sizeof(rx);
        int ch = mpynn_console_read();
        if (ch < 0) break;
        if (ch == mp_interrupt_char) {
            mp_sched_keyboard_interrupt();
        } else if (next != rx_out) {
            // On overflow discard ordinary input, but always consume Ctrl-C.
            rx[rx_in] = (unsigned char)ch;
            rx_in = next;
        } else {
            ++mpynn_console_rx_dropped;
        }
    }
}
void mpynn_poll_io(void) {
    mpynn_platform_poll();
    poll_console();
    mpynn_timer_poll();
    machine_pin_irq_poll();
    audio_file_poll();
}
void mpynn_event_poll(void) {
    mpynn_poll_io();
    mp_handle_pending(MP_HANDLE_PENDING_CALLBACKS_AND_EXCEPTIONS);
}
int mp_hal_stdin_rx_chr(void) {
    for (;;) {
        mpynn_event_poll();
        if (rx_in != rx_out) {
            int ch = rx[rx_out];
            rx_out = (rx_out + 1) % sizeof(rx);
            return ch;
        }
    }
}
uintptr_t mp_hal_stdio_poll(uintptr_t flags) {
    poll_console();
    return ((rx_in != rx_out ? MP_STREAM_POLL_RD : 0) | MP_STREAM_POLL_WR) & flags;
}
mp_uint_t mp_hal_stdout_tx_strn(const char *text, size_t size) {
    size_t done = 0;
    while (done < size) {
        size_t chunk = size - done;
        if (chunk > 64) chunk = 64;
        size_t n = mpynn_console_write(text + done, chunk);
        if (!n) break;
        done += n;
        // Do not raise during exception printing or arbitrary C print callers.
        mpynn_poll_io();
    }
    return done;
}
mp_uint_t mp_hal_ticks_us(void) { return (mp_uint_t)mpynn_ticks_us64(); }
mp_uint_t mp_hal_ticks_ms(void) { return (mp_uint_t)(mpynn_ticks_us64() / 1000); }
// Defined resolution is microseconds, not CPU cycles.
mp_uint_t mp_hal_ticks_cpu(void) { return mp_hal_ticks_us(); }
void mp_hal_delay_us(mp_uint_t us) {
    uint64_t start = mpynn_ticks_us64();
    if (us < 1000) {
        while (mpynn_ticks_us64() - start < us) { }
    } else {
        while (mpynn_ticks_us64() - start < us) mpynn_event_poll();
    }
}
void mp_hal_delay_ms(mp_uint_t ms) {
    uint64_t start = mpynn_ticks_us64();
    while (mpynn_ticks_us64() - start < (uint64_t)ms * 1000) {
        mpynn_event_poll();
    }
}
