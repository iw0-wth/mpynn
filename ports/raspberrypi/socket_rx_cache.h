// SPDX-License-Identifier: MIT
#ifndef MPYNN_SOCKET_RX_CACHE_H
#define MPYNN_SOCKET_RX_CACHE_H
#include <stddef.h>
#include <string.h>

// One owned Circle-style buffer per TCP socket. Feed from transport.Receive,
// NOT CSocket::Receive (which deletes unread tails). Never copy ownership.
// UDP must not use this stream cache: datagram truncation has different semantics.
template<class Buffer> class MpynnSocketRxCache {
public:
    MpynnSocketRxCache() : buffer_(nullptr), offset_(0) {}
    ~MpynnSocketRxCache() { clear(); }
    MpynnSocketRxCache(const MpynnSocketRxCache &) = delete;
    MpynnSocketRxCache &operator=(const MpynnSocketRxCache &) = delete;

    // Success transfers ownership. Failure leaves ownership with the caller.
    bool adopt(Buffer *buffer) {
        if (buffer_ || !buffer || !buffer->GetPtr() || !buffer->GetLength()) return false;
        buffer_ = buffer;
        offset_ = 0;
        return true;
    }
    size_t available() const {
        return buffer_ ? buffer_->GetLength() - offset_ : 0;
    }
    size_t read(void *output, size_t length) {
        if (!output || !length) return 0;
        size_t count = available();
        if (count > length) count = length;
        if (count) {
            memcpy(output, static_cast<const unsigned char *>(buffer_->GetPtr()) + offset_, count);
            offset_ += count;
            if (!available()) clear();
        }
        return count;
    }
    void clear() {
        delete buffer_;
        buffer_ = nullptr;
        offset_ = 0;
    }
private:
    Buffer *buffer_;
    size_t offset_;
};
#endif
