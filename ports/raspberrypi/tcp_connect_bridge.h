// SPDX-License-Identifier: MIT
#ifndef MPYNN_TCP_CONNECT_BRIDGE_H
#define MPYNN_TCP_CONNECT_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Requires the mpynn Circle Connect-waiter lifetime patch: upstream can delete
// a Closed connection in the same Process pass that wakes Connect after RST.
// CTCPConnection::IsTerminated now defers deletion while Connect is waiting.
// Host tests cover that ordering and bridge ownership, not real TCP/ARM switching.
// Used by the port socket adapter; native blocking work stays off the VM stack.
// Internal platform ABI, not a Python socket implementation. All calls require
// Circle TASK_LEVEL on the scheduler's core, and return 0 or positive errno.
// No call here yields except the separately scheduled worker's Connect.
enum mpynn_tcp_connect_state {
    MPYNN_TCP_CONNECT_PENDING = 0,
    MPYNN_TCP_CONNECT_SUCCEEDED = 1,
    MPYNN_TCP_CONNECT_FAILED = 2,
    MPYNN_TCP_CONNECT_ABANDONED = 3
};
// ip points to four IPv4 octets, copied before return. Reject unspecified,
// multicast/reserved addresses (first octet >=224), and ports outside 1..65535.
// At most four occupied jobs, including completed jobs awaiting take/cancel.
// Tokens have non-wrapping generations; exhausted slots are permanently retired.
// Output parameters are unchanged on API error.
// Non-mutating native TCP occupancy query for explicit adapter bind. Requires
// TASK_LEVEL and a running transport; no worker, handle, allocation or yield.
// Output is unchanged on error. Port zero is not an explicit reservation.
int mpynn_tcp_port_in_use(uint16_t port, unsigned *in_use);
int mpynn_tcp_connect_start(const uint8_t ip[4], unsigned port, uint32_t *token);
// Same ownership/deadline model; pass recorded wildcard bind port (zero=ephemeral).
// Nonzero port conflicts with native TCP entries or active jobs return ADDRINUSE.
// Worker rechecks before creation; binding reservation before start is separate.
int mpynn_tcp_connect_start_bound(const uint8_t ip[4], unsigned port,
                                  uint16_t local_port, uint32_t *token);
// Pure snapshot: no scheduling, network access, cleanup or ownership transfer.
// error is positive errno only for FAILED, otherwise zero.
int mpynn_tcp_connect_poll(uint32_t token, unsigned *state, int *error);
// INTERNAL ownership transfer: only SUCCEEDED can be taken. Transfers one TCP
// owner ref without releasing it. Caller MUST transfer it with stream_claim or
// dispose of it with stream_discard on the same platform-lifetime transport.
// PENDING/ABANDONED -> AGAIN; FAILED -> stored errno (job remains until cancel).
int mpynn_tcp_connect_take(uint32_t token, int *handle);
// Non-yielding atomic transfer to a stream. On failure the job retains ownership
// and output is unchanged, allowing retry on MFILE or cancellation.
int mpynn_tcp_connect_finish(uint32_t token, uint32_t *stream_token);
// Running/queued job: mark abandoned, retain slot until worker finishes. Repeated
// cancel succeeds while abandoned. Completed job: Disconnect success handle,
// release its owner ref, then release slot (also on Disconnect error).
// Released tokens return BADF.
int mpynn_tcp_connect_cancel(uint32_t token);
// Cancel all VM-owned jobs, not handles already transferred by take().
// Pending jobs retain slots until native completion; never destroy live workers.
int mpynn_tcp_connect_cancel_all(void);
#ifdef __cplusplus
}
#endif
#endif
