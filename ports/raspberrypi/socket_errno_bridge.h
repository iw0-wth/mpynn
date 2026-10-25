// SPDX-License-Identifier: MIT
#ifndef MPYNN_SOCKET_ERRNO_BRIDGE_H
#define MPYNN_SOCKET_ERRNO_BRIDGE_H
// Fixed internal MicroPython errno ABI, verified by socket_errno_bridge.c.
// Keep Python headers out of freestanding Circle C++ translation units.
enum { MPYNN_IO=5, MPYNN_BADF=9, MPYNN_AGAIN=11, MPYNN_BUSY=16,
       MPYNN_NODEV=19, MPYNN_INVAL=22, MPYNN_MFILE=24, MPYNN_PIPE=32,
       MPYNN_ADDRINUSE=98, MPYNN_NOTCONN=107 };
#ifdef __cplusplus
extern "C" {
#endif
int mpynn_socket_error_from_circle(int result);
#ifdef __cplusplus
}
#endif
#endif
