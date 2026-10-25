// SPDX-License-Identifier: MIT
#ifndef MPYNN_UDP_BRIDGE_H
#define MPYNN_UDP_BRIDGE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Internal API: nonblocking, positive MP errno on failure, 0 success.
// Tokens are generation-tagged; callers never own a Circle pointer.
int mpynn_udp_open(uint32_t *token);
// Wildcard IPv4 local bind; port 0 requests an ephemeral port.
int mpynn_udp_open_bound(uint16_t local_port, uint32_t *token);
// Set a local interface address on an open wildcard-bound handle.
int mpynn_udp_bind_local(uint32_t token, const uint8_t ip[4]);
int mpynn_udp_local_port(uint32_t token, uint16_t *port);
// Take pending errno without receiving/clearing queued data. API failures return
// positive errno and leave *error unchanged; success writes 0 or positive errno.
int mpynn_udp_take_error(uint32_t token, int *error);
enum { MPYNN_UDP_POLL_RD=1, MPYNN_UDP_POLL_WR=4, MPYNN_UDP_POLL_ERR=8,
       MPYNN_UDP_POLL_HUP=16, MPYNN_UDP_POLL_NVAL=32 };
// Invalid token: success with NVAL (poll semantics), not an IO operation.
int mpynn_udp_poll(uint32_t token, unsigned requested, unsigned *events);
int mpynn_udp_close(uint32_t token);
int mpynn_udp_broadcast(uint32_t token, int enabled);
// Update default peer without replacing the native handle or local port.
int mpynn_udp_connect(uint32_t token, const uint8_t ip[4], uint16_t port);
int mpynn_udp_send(uint32_t token, const void *data, size_t length);
// Task-level reset cleanup: attempts every close, returns first error.
int mpynn_udp_close_all(void);
int mpynn_udp_sendto(uint32_t token, const void *data, size_t length,
                     const uint8_t ip[4], uint16_t port);
int mpynn_udp_recvfrom(uint32_t token, void *data, size_t capacity,
                       size_t *received, uint8_t ip[4], uint16_t *port);
#ifdef __cplusplus
}
#endif
#endif
