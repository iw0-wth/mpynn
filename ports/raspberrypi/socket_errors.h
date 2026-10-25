// SPDX-License-Identifier: MIT
#ifndef MPYNN_SOCKET_ERRORS_H
#define MPYNN_SOCKET_ERRORS_H
#include <circle/net/error.h>
#include "py/mperrno.h"

// Convert a Circle operation result into a positive MicroPython errno.
// Nonnegative results are not errors. In particular, Receive(...DONTWAIT)==0
// needs operation-specific handling: this function cannot infer EOF/EAGAIN.
static inline int mpynn_socket_errno(int result) {
    if (result >= 0) return 0;
    // Compare negative constants rather than negate result (INT_MIN is valid
    // input here and must not cause signed overflow).
    switch (result) {
        case -NET_ERROR_WOULD_BLOCK: return MP_EWOULDBLOCK;
        case -NET_ERROR_PERMISSION_DENIED: return MP_EACCES;
        case -NET_ERROR_INVALID_VALUE: return MP_EINVAL;
        // Internal MP errno has no EPROTO/EPROTONOSUPPORT definitions.
        case -NET_ERROR_PROTOCOL_NOT_SUPPORTED:
        case -NET_ERROR_OPERATION_NOT_SUPPORTED: return MP_EOPNOTSUPP;
        case -NET_ERROR_CONNECTION_RESET: return MP_ECONNRESET;
        case -NET_ERROR_IS_CONNECTED: return MP_EISCONN;
        case -NET_ERROR_NOT_CONNECTED: return MP_ENOTCONN;
        case -NET_ERROR_CONNECTION_TIMED_OUT: return MP_ETIMEDOUT;
        case -NET_ERROR_CONNECTION_REFUSED: return MP_ECONNREFUSED;
        case -NET_ERROR_DESTINATION_UNREACHABLE: return MP_EHOSTUNREACH;
        case -NET_ERROR_PROTOCOL_ERROR:
        case -NET_ERROR_IO:
        case -NET_ERROR_UNKNOWN:
        default: return MP_EIO;
    }
}
#endif
