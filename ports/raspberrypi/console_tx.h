// SPDX-License-Identifier: MIT
#ifndef MPYNN_CONSOLE_TX_H
#define MPYNN_CONSOLE_TX_H
#include <stddef.h>
#include <stdint.h>

// Circle IRQ Write is nonblocking: zero means its TX ring is full, not EOF.
// Wait for progress without calling Python or changing the caller's IRQ mask.
// Writer returns a signed byte count; Clock is a monotonic microsecond clock.
template <typename Writer, typename Clock, typename Poll>
size_t mpynn_console_write_all(const char *data, size_t length,
                              Writer write, Clock clock, Poll poll,
                              uint64_t stall_timeout_us = 250000) {
    size_t done = 0;
    uint64_t progress = clock();
    while (done < length) {
        int result = write(data + done, length - done);
        if (result < 0 || (size_t)result > length - done) break;
        if (result > 0) {
            done += (size_t)result;
            progress = clock();
        } else if (clock() - progress >= stall_timeout_us) {
            break;
        }
        if (done < length) poll();
    }
    return done;
}
#endif
