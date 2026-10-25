// SPDX-License-Identifier: MIT
#ifndef MPYNN_SOCKET_PORT_H
#define MPYNN_SOCKET_PORT_H
#include "py/obj.h"
// Port implementation captures one monotonic deadline for all sendall chunks.
mp_obj_t mpynn_socket_sendall(mp_obj_t self_in, mp_obj_t buffer_in);
// Inspect the local endpoint without opening a fresh native socket. A pending
// TCP connect is checked once; ENOTCONN means it has no stream handle yet.
mp_obj_t mpynn_socket_getsockname(mp_obj_t self);
// Return the saved peer, promoting a pending TCP connect without blocking.
mp_obj_t mpynn_socket_getpeername(mp_obj_t self);
// TCP shutdown modes 0/1/2 retain ownership until close(). WR queues a real FIN
// after accepted writes and keeps RX usable; RD discards only local receive data.
mp_obj_t mpynn_socket_shutdown(mp_obj_t self, mp_obj_t how);
// Inspect known options without selecting a NIC or changing native IO state.
#define MPYNN_SOCKET_SO_ERROR (0x1007)
#define MPYNN_SOCKET_SO_TYPE (0x1008)
#define MPYNN_SOCKET_IPPROTO_TCP (6)
#define MPYNN_SOCKET_TCP_NODELAY (1)
#define MPYNN_SOCKET_AI_PASSIVE (1)
#define MPYNN_SOCKET_AI_NUMERICHOST (4)
#define MPYNN_SOCKET_AI_NUMERICSERV (0x400)
mp_obj_t mpynn_socket_getsockopt(size_t n_args, const mp_obj_t *args);
#endif
