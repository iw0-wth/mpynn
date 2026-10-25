// SPDX-License-Identifier: MIT
#ifndef MPYNN_SOCKET_DEADLINE_H
#define MPYNN_SOCKET_DEADLINE_H
#include <stdint.h>

// One deadline per Python socket operation, not one per transfer chunk.
// MicroPython convention: -1 blocking forever, 0 nonblocking, >0 milliseconds.
// Caller performs one IO attempt even if timeout=0, then checks the deadline
// before retrying. This helper never yields or calls Python/Circle itself.
class MpynnSocketDeadline {
public:
    MpynnSocketDeadline(int32_t timeout_ms, uint64_t start_us)
        : start_(start_us), duration_(timeout_ms > 0 ? (uint64_t)timeout_ms * 1000 : 0),
          infinite_(timeout_ms < 0) {}
    bool expired(uint64_t now_us) const {
        return !infinite_ && (uint64_t)(now_us - start_) >= duration_;
    }
    uint64_t remaining_us(uint64_t now_us) const {
        if (infinite_) return UINT64_MAX;
        uint64_t elapsed = now_us - start_;
        return elapsed >= duration_ ? 0 : duration_ - elapsed;
    }
private:
    uint64_t start_, duration_;
    bool infinite_;
};
#endif
