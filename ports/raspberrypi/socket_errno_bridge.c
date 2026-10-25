// SPDX-License-Identifier: MIT
#include "socket_errors.h"
#include "socket_errno_bridge.h"
_Static_assert(MPYNN_IO == MP_EIO && MPYNN_BADF == MP_EBADF &&
    MPYNN_AGAIN == MP_EAGAIN && MPYNN_BUSY == MP_EBUSY &&
    MPYNN_NODEV == MP_ENODEV && MPYNN_INVAL == MP_EINVAL &&
    MPYNN_MFILE == MP_EMFILE && MPYNN_NOTCONN == MP_ENOTCONN &&
    MPYNN_ADDRINUSE == MP_EADDRINUSE && MPYNN_PIPE == MP_EPIPE,
    "C++ bridge error ABI must match MicroPython");
int mpynn_socket_error_from_circle(int result) {
    return mpynn_socket_errno(result);
}
