// SPDX-License-Identifier: MIT
#ifndef MPYNN_TCP_STREAM_BRIDGE_H
#define MPYNN_TCP_STREAM_BRIDGE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Internal nonblocking API. 0 success, positive errno failure.
// Claim only a handle returned by tcp_connect_take on this platform transport.
// Success transfers the existing owner ref without retaining again; failure
// leaves it with the caller, who can retry or discard the unclaimed handle.
int mpynn_tcp_stream_claim(int handle, uint32_t *token);
// Dispose of an unclaimed take() handle: Disconnect, then release its owner ref
// even on Disconnect error. Do not reuse the handle after disposal. An already
// claimed handle returns BUSY; invalid arguments/context leave ownership intact.
int mpynn_tcp_stream_discard(int handle);
int mpynn_tcp_stream_local_port(uint32_t token, uint16_t *port);
// Non-mutating native terminal error snapshot, mapped to positive MP errno.
int mpynn_tcp_stream_get_error(uint32_t token, int *error);
// enabled must be 0 or 1. Never yields, allocates, or sends queued data.
// Circle historically sends without Nagle; the native default remains enabled.
int mpynn_tcp_stream_set_nodelay(uint32_t token, unsigned enabled);
// how: 0 read, 1 write, 2 both. Keeps the handle and its owner ref alive.
// Native failure leaves shutdown flags and cached receive data unchanged.
int mpynn_tcp_stream_shutdown(uint32_t token, unsigned how);
enum { MPYNN_TCP_POLL_RD=1, MPYNN_TCP_POLL_WR=4, MPYNN_TCP_POLL_ERR=8,
       MPYNN_TCP_POLL_HUP=16, MPYNN_TCP_POLL_NVAL=32 };
int mpynn_tcp_stream_poll(uint32_t token, unsigned requested, unsigned *events);
int mpynn_tcp_stream_read(uint32_t token, void *buffer, size_t length, size_t *received);
int mpynn_tcp_stream_write(uint32_t token, const void *buffer, size_t length, size_t *sent);
int mpynn_tcp_stream_close(uint32_t token);
int mpynn_tcp_stream_close_all(void);
#ifdef __cplusplus
}
#endif
#endif
