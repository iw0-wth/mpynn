// SPDX-License-Identifier: MIT
#ifndef MPYNN_TCP_LISTENER_BRIDGE_H
#define MPYNN_TCP_LISTENER_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Task-context, nonblocking C ABI: zero success, positive MicroPython errno.
// Two listeners, each with 1..4 retained native passive-open candidates.
// Port zero chooses one native ephemeral port for the entire backlog.
// Duplicate explicit bridge listener ports are rejected.
int mpynn_tcp_listener_open(uint16_t port, unsigned backlog, uint32_t *token);
int mpynn_tcp_listener_local_port(uint32_t token, uint16_t *port);
// ready is boolean (completed handshake, including peer FIN), not a queue count.
// Poll/accept retry vacant candidate allocation. A ready result takes precedence
// over maintenance errors; otherwise those errors are reported for this call.
int mpynn_tcp_listener_poll(uint32_t token, unsigned *ready);
// Success transfers one existing retained handle to the stream table. Failure
// leaves outputs untouched and claim failure preserves the candidate for retry.
// No ready candidate returns AGAIN unless candidate maintenance failed.
int mpynn_tcp_listener_accept(uint32_t token, uint32_t *stream_token,
                              uint8_t ip[4], uint16_t *port);
// Close invalidates the token even on native cleanup error, releases all owned
// candidates, and returns the first error. Accepted streams remain independent.
int mpynn_tcp_listener_close(uint32_t token);
int mpynn_tcp_listener_close_all(void);
#ifdef __cplusplus
}
#endif
#endif
