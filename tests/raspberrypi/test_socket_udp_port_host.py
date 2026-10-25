# SPDX-License-Identifier: MIT
"""Execute the real UDP/TCP NIC adapter with a tiny host MP ABI and bridge doubles.

No VM, Circle, hardware or actual network is used. Including the production C
translation unit also exercises its static functions and registered protocol.
Only a missing host compiler skips; compilation and scenario failures fail.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "ports/raspberrypi/socket_udp_port.c"
COMPILER = Path("E:/msys64/ucrt64/bin/gcc.exe")

HEADERS = {
    "py/obj.h": '#pragma once\n#include "py/runtime.h"\n',
    "py/runtime.h": r"""
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
typedef unsigned char byte;
typedef uintptr_t mp_uint_t;
typedef intptr_t mp_int_t;
typedef void *mp_obj_t;
mp_int_t mp_obj_get_int(mp_obj_t obj);
mp_obj_t mp_obj_new_int(mp_int_t value);
mp_obj_t mp_obj_new_bytes(const byte *data, size_t length);
#define MP_ERROR_TEXT(message) message
_Noreturn void mp_raise_ValueError(const char *message);
#define MP_OBJ_TO_PTR(obj) ((void *)(obj))
#define MP_OBJ_FROM_PTR(ptr) ((mp_obj_t)(ptr))
#define MP_BUFFER_READ 1
#define MP_BUFFER_WRITE 2
typedef struct { void *buf; size_t len; int typecode; } mp_buffer_info_t;
extern const mp_obj_t mp_const_none;
void mp_get_buffer_raise(mp_obj_t obj, mp_buffer_info_t *info, unsigned flags);
_Noreturn void mp_raise_OSError(int code);
void *host_alloc(size_t size);
void host_free(void *p);
#define m_new0(type, count) ((type *)host_alloc(sizeof(type) * (count)))
#define m_del(type, ptr, count) host_free(ptr)
void mp_event_handle_nowait(void);
""",
    "py/mperrno.h": r"""
#pragma once
#define MP_EINTR 4
#define MP_EISCONN 106
#define MP_ENOTCONN 107
#define MP_ECONNREFUSED 111
#define MP_EALREADY 114
#define MP_EINPROGRESS 115
#define MP_EBADF 9
#define MP_EAGAIN 11
#define MP_ENOMEM 12
#define MP_EMFILE 24
#define MP_EADDRINUSE 98
#define MP_EBUSY 16
#define MP_EINVAL 22
#define MP_EIO 5
#define MP_EPIPE 32
#define MP_EOPNOTSUPP 95
#define MP_EAFNOSUPPORT 97
#define MP_ENETDOWN 100
#define MP_ETIMEDOUT 110
""",
    "py/nlr.h": r"""
#pragma once
#include <setjmp.h>
typedef struct nlr_buf_t { jmp_buf jb; void *ret_val; struct nlr_buf_t *prev; } nlr_buf_t;
static nlr_buf_t *nlr_top;
#define nlr_push(n) (((n)->prev = nlr_top), (nlr_top = (n)), setjmp((n)->jb))
static void nlr_pop(void) { nlr_top = nlr_top->prev; }
static _Noreturn void nlr_jump(void *value) {
    nlr_buf_t *n = nlr_top; if (!n) abort();
    nlr_top = n->prev; n->ret_val = value; longjmp(n->jb, 1);
}
""",
    "shared/netutils/netutils.h": r"""
#pragma once
#include "py/runtime.h"
typedef enum { NETUTILS_LITTLE, NETUTILS_BIG } netutils_endian_t;
mp_obj_t netutils_format_inet_addr(uint8_t *ip, mp_uint_t port, netutils_endian_t endian);
""",
    "py/mphal.h": "#pragma once\nvoid mp_hal_delay_ms(unsigned ms);\n",
    "py/stream.h": r"""
#pragma once
#define MP_STREAM_POLL 3
#define MP_STREAM_POLL_RD 1
#define MP_STREAM_POLL_WR 4
#define MP_STREAM_POLL_ERR 8
#define MP_STREAM_POLL_HUP 16
#define MP_STREAM_POLL_NVAL 32
""",
    "extmod/modnetwork.h": r"""
#pragma once
#include "py/runtime.h"
#define MOD_NETWORK_SOL_SOCKET 0x0FFF
#define MOD_NETWORK_SO_BROADCAST 0x0020
// Match lib/micropython/extmod/modnetwork.h, not the host OS socket ABI.
#define MOD_NETWORK_SO_SNDTIMEO 0x1005
#define MOD_NETWORK_SO_RCVTIMEO 0x1006
#define MOD_NETWORK_AF_INET 2
#define MOD_NETWORK_SOCK_STREAM 1
#define MOD_NETWORK_SS_LISTENING 1
#define MOD_NETWORK_SS_CONNECTED 2
#define MOD_NETWORK_SOCK_DGRAM 2
#define MOD_NETWORK_SS_CLOSED 3
#define MOD_NETWORK_SS_NEW 0
typedef struct _mod_network_socket_obj_t {
    void *_private;
    int domain, type, proto, state;
    bool bound;
    int32_t timeout;
} mod_network_socket_obj_t;
typedef struct {
    int (*gethostbyname)(mp_obj_t, const char *, mp_uint_t, uint8_t *);
    void (*deinit)(void);
    int (*socket)(mod_network_socket_obj_t *, int *);
    void (*close)(mod_network_socket_obj_t *);
    int (*bind)(mod_network_socket_obj_t *, byte *, mp_uint_t, int *);
    int (*listen)(mod_network_socket_obj_t *, mp_int_t, int *);
    int (*accept)(mod_network_socket_obj_t *, mod_network_socket_obj_t *, byte *, mp_uint_t *, int *);
    int (*connect)(mod_network_socket_obj_t *, byte *, mp_uint_t, int *);
    mp_uint_t (*send)(mod_network_socket_obj_t *, const byte *, mp_uint_t, int *);
    mp_uint_t (*recv)(mod_network_socket_obj_t *, byte *, mp_uint_t, int *);
    mp_uint_t (*sendto)(mod_network_socket_obj_t *, const byte *, mp_uint_t, byte *, mp_uint_t, int *);
    mp_uint_t (*recvfrom)(mod_network_socket_obj_t *, byte *, mp_uint_t, byte *, mp_uint_t *, int *);
    int (*setsockopt)(mod_network_socket_obj_t *, mp_uint_t, mp_uint_t, const void *, mp_uint_t, int *);
    int (*settimeout)(mod_network_socket_obj_t *, mp_uint_t, int *);
    int (*ioctl)(mod_network_socket_obj_t *, mp_uint_t, mp_uint_t, int *);
} mod_network_nic_protocol_t;
""",
}

HARNESS = r"""
#include "socket_udp_port.c"
// DNS resolution has a separate real-source harness; verify table dispatch here.
int mpynn_gethostbyname(mp_obj_t nic, const char *name, mp_uint_t len, uint8_t *out) {
    (void)nic; (void)name; (void)len; (void)out; return MP_ENETDOWN;
}
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)
#define ERR(expr, code) do { error = 0; CHECK((expr) == -1); CHECK(error == (code)); } while (0)
#define UERR(expr, code) do { error = 0; CHECK((expr) == (mp_uint_t)-1); CHECK(error == (code)); } while (0)
typedef struct { char ip[16]; mp_uint_t port; } formatted_peer_t;
static formatted_peer_t formatted_peer;
static unsigned format_calls;
mp_obj_t netutils_format_inet_addr(uint8_t *ip, mp_uint_t port, netutils_endian_t endian) {
    CHECK(endian == NETUTILS_BIG); ++format_calls;
    CHECK(snprintf(formatted_peer.ip, sizeof(formatted_peer.ip), "%u.%u.%u.%u",
        (unsigned)ip[0], (unsigned)ip[1], (unsigned)ip[2], (unsigned)ip[3]) > 0);
    formatted_peer.port = port;
    return MP_OBJ_FROM_PTR(&formatted_peer);
}
static void peer_raises(mod_network_socket_obj_t *s, int code) {
    unsigned before = format_calls;
    nlr_buf_t outer;
    if (nlr_push(&outer) == 0) {
        mpynn_socket_getpeername(MP_OBJ_FROM_PTR(s));
        nlr_pop(); CHECK(false);
    } else CHECK(outer.ret_val == (void *)(intptr_t)code);
    CHECK(nlr_top == NULL && format_calls == before);
}
static void peer_is(mod_network_socket_obj_t *s, const char *ip, mp_uint_t port) {
    unsigned before = format_calls;
    formatted_peer_t *result = MP_OBJ_TO_PTR(mpynn_socket_getpeername(MP_OBJ_FROM_PTR(s)));
    CHECK(result == &formatted_peer && format_calls == before + 1);
    CHECK(!strcmp(result->ip, ip) && result->port == port && nlr_top == NULL);
}
static const mod_network_nic_protocol_t *nic = &mpynn_udp_nic_protocol;
static void *allocations[64];
static unsigned allocation_count, opens, closes, sends, recvs, polls, events, delays, deinits;
static unsigned udp_bind_local_calls;
static int udp_bind_local_error;
static byte udp_bound_ip[4];
static int open_error, send_error, recv_error, poll_error;
static unsigned connects, connected_sends;
static unsigned udp_error_queries;
static int udp_pending_error, udp_error_query_error;
static int connect_error;
static bool connected_peer;
static uint8_t connected_ip[4];
static uint16_t connected_port;
static size_t udp_recv_count = 3, sent_length;
static unsigned consumed_packets;
static bool live, success_after_delay;
static uint16_t bound_port;
static uint16_t udp_ephemeral_port = 49152;
static unsigned udp_local_queries, stream_local_queries, network_snapshots;
static int udp_local_error, stream_local_error, snapshot_error;
static uint16_t stream_local_port = 49153;
static mpynn_network_state_t network_state = {
    .initialized = 1, .running = 1, .ip = {198, 51, 100, 7}
};
int mpynn_network_snapshot(mpynn_network_state_t *out) {
    CHECK(out != NULL); ++network_snapshots;
    if (snapshot_error) return snapshot_error;
    *out = network_state; return 0;
}
static unsigned requested, poll_events;
static uint64_t now;
static mod_network_socket_obj_t *close_on_event;
static byte wildcard[4], peer[4] = {192, 0, 2, 1}, buffer[16];
static int error;
static mp_uint_t peer_port;
static byte none_sentinel;
const mp_obj_t mp_const_none = &none_sentinel;
static mp_buffer_info_t sendall_buffer = {buffer, 8, 'B'};
static unsigned buffer_requests;
static void (*event_callback)(void);
void mp_get_buffer_raise(mp_obj_t obj, mp_buffer_info_t *info, unsigned flags) {
    CHECK(obj != NULL && flags == MP_BUFFER_READ); ++buffer_requests;
    *info = *(mp_buffer_info_t *)obj;
    CHECK(info->buf == buffer && info->len <= sizeof(buffer));
}
enum { HOST_TYPE_ERROR = -1001, HOST_VALUE_ERROR = -1002, HOST_MEMORY_ERROR = -1003 };
static byte nonint_sentinel;
static bool fail_option_result;
static unsigned int_conversions, int_results, bytes_results;
static mp_int_t integer_result;
static struct { size_t length; byte data[sizeof(mp_int_t)]; } bytes_result;
mp_int_t mp_obj_get_int(mp_obj_t obj) {
    ++int_conversions;
    if (obj == &nonint_sentinel) nlr_jump((void *)(intptr_t)HOST_TYPE_ERROR);
    return (mp_int_t)obj;
}
mp_obj_t mp_obj_new_int(mp_int_t value) {
    if (fail_option_result) nlr_jump((void *)(intptr_t)HOST_MEMORY_ERROR);
    ++int_results; integer_result = value; return MP_OBJ_FROM_PTR(&integer_result);
}
mp_obj_t mp_obj_new_bytes(const byte *data, size_t length) {
    if (fail_option_result) nlr_jump((void *)(intptr_t)HOST_MEMORY_ERROR);
    CHECK(length > 0 && length <= sizeof(mp_int_t)); ++bytes_results;
    bytes_result.length = length; memcpy(bytes_result.data, data, length);
    return MP_OBJ_FROM_PTR(&bytes_result);
}
_Noreturn void mp_raise_ValueError(const char *message) {
    CHECK(message != NULL); nlr_jump((void *)(intptr_t)HOST_VALUE_ERROR);
}
_Noreturn void mp_raise_OSError(int code) { nlr_jump((void *)(intptr_t)code); }
void *host_alloc(size_t size) {
    CHECK(allocation_count < 64);
    void *p = calloc(1, size); CHECK(p != NULL);
    allocations[allocation_count++] = p; return p;
}
static unsigned freed;
void host_free(void *p) {
    for (unsigned i = 0; i < allocation_count; ++i)
        if (allocations[i] == p) { allocations[i] = NULL; ++freed; free(p); return; }
    CHECK(false);
}
int mpynn_udp_open_bound(uint16_t port, uint32_t *token) {
    ++opens; bound_port = port;
    if (open_error) return open_error;
    CHECK(!live); live = true; *token = 0x12345678; return 0;
}
int mpynn_udp_bind_local(uint32_t token, const uint8_t ip[4]) {
    CHECK(live && token == 0x12345678 && ip != NULL);
    ++udp_bind_local_calls;
    if (udp_bind_local_error) return udp_bind_local_error;
    memcpy(udp_bound_ip, ip, 4);
    return 0;
}
int mpynn_udp_local_port(uint32_t token, uint16_t *out) {
    CHECK(out != NULL); ++udp_local_queries;
    if (udp_local_error) return udp_local_error;
    if (!live || token != 0x12345678) return MP_EBADF;
    *out = bound_port ? bound_port : udp_ephemeral_port; return 0;
}
int mpynn_udp_take_error(uint32_t token, int *out) {
    CHECK(out != NULL); ++udp_error_queries;
    if (udp_error_query_error) return udp_error_query_error;
    if (!live || token != 0x12345678) return MP_EBADF;
    CHECK(udp_pending_error >= 0);
    *out = udp_pending_error; udp_pending_error = 0; return 0;
}
int mpynn_udp_close(uint32_t token) {
    CHECK(live && token == 0x12345678); ++closes; live = connected_peer = false; return 0;
}
static int broadcast_error, broadcast_value, broadcast_calls;
int mpynn_udp_broadcast(uint32_t token, int enabled) {
    CHECK(live && token); ++broadcast_calls;
    if (broadcast_error) return broadcast_error;
    broadcast_value = enabled; return 0;
}
int mpynn_udp_close_all(void) { ++deinits; live = connected_peer = false; return 0; }
int mpynn_udp_connect(uint32_t token, const uint8_t ip[4], uint16_t port) {
    CHECK(live && token == 0x12345678); ++connects;
    if (!port || !ip || !(ip[0] || ip[1] || ip[2] || ip[3])) return MP_EINVAL;
    if (connect_error) return connect_error;
    memcpy(connected_ip, ip, 4); connected_port = port; connected_peer = true;
    udp_pending_error = 0; // Successful native SetPeer discards the old peer's report.
    return 0;
}
int mpynn_udp_send(uint32_t token, const void *data, size_t length) {
    CHECK(live && token == 0x12345678 && connected_peer);
    ++connected_sends; CHECK(connected_sends < 100);
    CHECK(data == buffer && length <= sizeof(buffer)); sent_length = length;
    return success_after_delay && delays ? 0 : send_error;
}
int mpynn_udp_sendto(uint32_t token, const void *data, size_t length,
                     const uint8_t ip[4], uint16_t port) {
    CHECK(live && token == 0x12345678); ++sends; CHECK(sends < 100);
    CHECK(data == buffer && length <= sizeof(buffer));
    CHECK(memcmp(ip, peer, 4) == 0 && port == 9000);
    return success_after_delay && delays ? 0 : send_error;
}
int mpynn_udp_recvfrom(uint32_t token, void *data, size_t capacity,
                       size_t *received, uint8_t ip[4], uint16_t *port) {
    CHECK(live && token == 0x12345678); ++recvs; CHECK(recvs < 100);
    int result = success_after_delay && delays ? 0 : recv_error;
    if (result) return result;
    CHECK(data == buffer && capacity <= sizeof(buffer)); ++consumed_packets;
    *received = capacity < udp_recv_count ? capacity : udp_recv_count;
    CHECK(*received <= 3);
    if (*received) memcpy(data, "udp", *received);
    memcpy(ip, connected_peer ? connected_ip : peer, 4);
    *port = connected_peer ? connected_port : 9000; return 0;
}
int mpynn_udp_poll(uint32_t token, unsigned arg, unsigned *out) {
    CHECK(live && token == 0x12345678); ++polls;
    requested = arg; *out = poll_events; return poll_error;
}
static unsigned tcp_port_queries;
static int tcp_port_query_error;
static uint16_t native_occupied_port;
int mpynn_tcp_port_in_use(uint16_t port, unsigned *in_use) {
    CHECK(port && in_use); ++tcp_port_queries;
    if (tcp_port_query_error) return tcp_port_query_error;
    *in_use = port == native_occupied_port; return 0;
}
static bool tcp_job, tcp_live, tcp_ready, tcp_ready_after_delay, interrupt_event;
static unsigned tcp_starts, tcp_finishes, tcp_cancels, tcp_closes, tcp_reads, tcp_polls, tick_calls;
static uint16_t tcp_start_local_port;
static int tcp_start_error, tcp_error, tcp_read_error, tcp_write_error, tcp_poll_error;
static unsigned tcp_error_queries;
static int tcp_terminal_error, tcp_error_query_error;
static bool tcp_shutdown_rd, tcp_shutdown_wr;
static unsigned tcp_shutdown_calls;
static int tcp_shutdown_error;
static size_t tcp_read_count = 3, tcp_write_count = 2;
typedef struct { int error; size_t count; uint64_t advance; } write_step_t;
static write_step_t write_steps[32];
static unsigned write_step_count, tcp_writes;
static size_t write_offsets[32], write_lengths[32], written_bytes;
static uint64_t write_times[32];
static void write_step(int code, size_t count, uint64_t advance) {
    CHECK(write_step_count < 32);
    write_steps[write_step_count++] = (write_step_t){code, count, advance};
}
static int tcp_connect_start_common(const uint8_t ip[4], unsigned port,
                                    uint16_t local_port, uint32_t *out) {
    CHECK(!tcp_job && !tcp_live && ip && port == 9000);
    ++tcp_starts; tcp_start_local_port = local_port;
    if (tcp_start_error) return tcp_start_error;
    // Model an explicit reservation and a native ephemeral assignment.
    stream_local_port = local_port ? local_port : 49153;
    tcp_job = true; *out = 71; return 0;
}
int mpynn_tcp_connect_start(const uint8_t ip[4], unsigned port, uint32_t *out) {
    return tcp_connect_start_common(ip, port, 0, out);
}
int mpynn_tcp_connect_start_bound(const uint8_t ip[4], unsigned port,
                                  uint16_t local_port, uint32_t *out) {
    return tcp_connect_start_common(ip, port, local_port, out);
}
int mpynn_tcp_connect_finish(uint32_t token, uint32_t *out) {
    CHECK(tcp_job && token == 71); ++tcp_finishes;
    if (tcp_error) return tcp_error;
    if (!tcp_ready && !(tcp_ready_after_delay && delays)) return MP_EAGAIN;
    tcp_job = false; tcp_live = true;
    tcp_shutdown_rd = tcp_shutdown_wr = false; *out = 81; return 0;
}
int mpynn_tcp_connect_cancel(uint32_t token) {
    CHECK(tcp_job && token == 71); ++tcp_cancels; tcp_job = false; return 0;
}
int mpynn_tcp_connect_cancel_all(void) { tcp_job = false; return 0; }
int mpynn_tcp_stream_close_all(void) {
    tcp_live = tcp_shutdown_rd = tcp_shutdown_wr = false; return 0;
}
int mpynn_tcp_stream_close(uint32_t token) {
    CHECK(tcp_live && token == 81); ++tcp_closes;
    tcp_live = tcp_shutdown_rd = tcp_shutdown_wr = false; return 0;
}
int mpynn_tcp_stream_shutdown(uint32_t token, unsigned how) {
    CHECK(tcp_live && token == 81 && how <= 2); ++tcp_shutdown_calls;
    if (tcp_shutdown_error) return tcp_shutdown_error;
    if (tcp_terminal_error) return tcp_terminal_error;
    if (how != 1) tcp_shutdown_rd = true;
    if (how != 0) tcp_shutdown_wr = true;
    return 0;
}
int mpynn_tcp_stream_local_port(uint32_t token, uint16_t *out) {
    CHECK(out != NULL); ++stream_local_queries;
    if (stream_local_error) return stream_local_error;
    if (!tcp_live || token != 81) return MP_EBADF;
    *out = stream_local_port; return 0;
}
static unsigned nodelay_calls, nodelay_value;
static int nodelay_error;
static mod_network_socket_obj_t *nodelay_unpublished_socket;
static mod_network_socket_obj_t *nodelay_unpublished_child;
int mpynn_tcp_stream_set_nodelay(uint32_t token, unsigned enabled) {
    CHECK(tcp_live && token == 81 && enabled <= 1); ++nodelay_calls;
    if (nodelay_unpublished_socket) {
        CHECK(state(nodelay_unpublished_socket)->phase == TCP_PENDING);
        CHECK(nodelay_unpublished_socket->state != MOD_NETWORK_SS_CONNECTED);
    }
    if (nodelay_unpublished_child) {
        CHECK(nodelay_unpublished_child->_private != NULL); // Rooted before ownership transfer.
        CHECK(state(nodelay_unpublished_child)->phase != TCP_CONNECTED);
        CHECK(state(nodelay_unpublished_child)->nodelay_configured);
        CHECK(state(nodelay_unpublished_child)->nodelay == enabled);
        CHECK(nodelay_unpublished_child->state != MOD_NETWORK_SS_CONNECTED);
    }
    if (nodelay_error) return nodelay_error;
    nodelay_value = enabled; return 0;
}
int mpynn_tcp_stream_get_error(uint32_t token, int *out) {
    CHECK(tcp_live && token == 81 && out != NULL); ++tcp_error_queries;
    if (tcp_error_query_error) return tcp_error_query_error;
    *out = tcp_terminal_error; return 0;
}
int mpynn_tcp_stream_poll(uint32_t token, unsigned arg, unsigned *out) {
    CHECK(tcp_live && token == 81); ++tcp_polls;
    if (tcp_poll_error) return tcp_poll_error;
    unsigned ready = poll_events;
    if (tcp_shutdown_rd) ready |= MP_STREAM_POLL_RD;
    if (tcp_shutdown_wr || tcp_terminal_error) ready &= ~MP_STREAM_POLL_WR;
    if (tcp_terminal_error) ready |= MP_STREAM_POLL_ERR;
    *out = arg & ready; return 0;
}
int mpynn_tcp_stream_write(uint32_t token, const void *buf, size_t len, size_t *out) {
    CHECK(tcp_live && token == 81);
    const byte *data = buf;
    CHECK(data >= buffer && data <= buffer + sizeof(buffer));
    size_t offset = (size_t)(data - buffer);
    CHECK(len <= sizeof(buffer) - offset && tcp_writes < 32);
    unsigned index = tcp_writes++;
    write_offsets[index] = offset; write_lengths[index] = len; write_times[index] = now;
    if (tcp_shutdown_wr) return MP_EPIPE;
    if (tcp_terminal_error) return tcp_terminal_error;
    if (write_step_count) {
        CHECK(index < write_step_count);
        write_step_t step = write_steps[index]; now += step.advance;
        if (step.error) return step.error;
        *out = len < step.count ? len : step.count;
    } else {
        if (tcp_write_error && !(success_after_delay && delays)) return tcp_write_error;
        *out = len < tcp_write_count ? len : tcp_write_count;
    }
    written_bytes += *out; return 0;
}
int mpynn_tcp_stream_read(uint32_t token, void *buf, size_t len, size_t *out) {
    CHECK(tcp_live && token == 81 && buf == buffer); ++tcp_reads;
    // Native RD shutdown overrides even the bridge's already-cached data.
    if (tcp_shutdown_rd) { *out = 0; return 0; }
    if (tcp_terminal_error) return tcp_terminal_error;
    if (tcp_read_error && !(success_after_delay && delays)) return tcp_read_error;
    *out = len < tcp_read_count ? len : tcp_read_count; return 0;
}
static bool listener_live, listener_ready, listener_after_delay;
static unsigned listener_opens, listener_closes, listener_accepts, listener_polls, listener_deinits;
static unsigned listener_backlog, listener_local_queries;
static uint16_t listener_requested_port, listener_local_port, accepted_port = 9000;
static int listener_open_error, listener_local_error, listener_accept_error, listener_poll_error;
int mpynn_tcp_listener_open(uint16_t port, unsigned backlog, uint32_t *out) {
    ++listener_opens; CHECK(port == 0 || port == 4321 || port == 9000); listener_backlog = backlog;
    listener_requested_port = port;
    if (listener_open_error) return listener_open_error;
    CHECK(!listener_live); listener_live = true; *out = 91;
    listener_local_port = port ? port : 60001; return 0;
}
int mpynn_tcp_listener_local_port(uint32_t token, uint16_t *out) {
    CHECK(out != NULL && listener_live && token == 91); ++listener_local_queries;
    if (listener_local_error) return listener_local_error;
    *out = listener_local_port; return 0;
}
int mpynn_tcp_listener_accept(uint32_t token, uint32_t *out, uint8_t ip[4], uint16_t *port) {
    CHECK(listener_live && token == 91); ++listener_accepts; CHECK(listener_accepts < 100);
    if (listener_accept_error) return listener_accept_error;
    if (!listener_ready && !(listener_after_delay && delays)) return MP_EAGAIN;
    CHECK(!tcp_live); tcp_live = true; listener_ready = false;
    tcp_shutdown_rd = tcp_shutdown_wr = false;
    *out = 81; memcpy(ip, peer, 4); *port = accepted_port; return 0;
}
int mpynn_tcp_listener_poll(uint32_t token, unsigned *ready) {
    CHECK(listener_live && token == 91); ++listener_polls;
    if (listener_poll_error) return listener_poll_error;
    *ready = listener_ready; return 0;
}
int mpynn_tcp_listener_close(uint32_t token) {
    CHECK(listener_live && token == 91); ++listener_closes; listener_live = false; return 0;
}
int mpynn_tcp_listener_close_all(void) {
    ++listener_deinits; listener_live = false; return 0;
}
uint64_t mpynn_ticks_us64(void) { ++tick_calls; return now; }
void mp_hal_delay_ms(unsigned ms) { ++delays; CHECK(delays < 100); now += (uint64_t)ms * 1000; }
void mp_event_handle_nowait(void) {
    ++events; CHECK(events < 100);
    if (interrupt_event) nlr_jump((void *)123);
    if (event_callback) event_callback();
    if (close_on_event) {
        mod_network_socket_obj_t *s = close_on_event; close_on_event = NULL;
        void *old = s->_private;
        nic->close(s);
        /* Model collection immediately after close: stale access is invalid. */
        for (unsigned i = 0; i < allocation_count; ++i)
            if (allocations[i] == old) allocations[i] = NULL;
        free(old);
    }
}
static mod_network_socket_obj_t socket_new(void) {
    mod_network_socket_obj_t s = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_DGRAM, .state=MOD_NETWORK_SS_NEW, .timeout=-1};
    CHECK(nic->socket(&s, &error) == 0); CHECK(s._private != NULL); return s;
}
static mp_uint_t send_one(mod_network_socket_obj_t *s) {
    return nic->sendto(s, buffer, 3, peer, 9000, &error);
}
static mp_uint_t recv_one(mod_network_socket_obj_t *s) {
    byte ip[4] = {0}; peer_port = 0;
    mp_uint_t result = nic->recvfrom(s, buffer, sizeof(buffer), ip, &peer_port, &error);
    if (result != (mp_uint_t)-1) {
        CHECK(result == 3 && !memcmp(buffer, "udp", 3));
        CHECK(peer_port == 9000 && !memcmp(ip, peer, 4));
    }
    return result;
}
static void test_lazy(void) {
    mod_network_socket_obj_t s = socket_new(); CHECK(opens == 0);
    CHECK(nic->settimeout(&s, 0, &error) == 0 && opens == 0);
    nic->close(&s); nic->close(&s); CHECK(closes == 0 && !s._private);
    s = socket_new(); CHECK(send_one(&s) == 3); CHECK(opens == 1 && bound_port == 0);
    CHECK(recv_one(&s) == 3 && opens == 1);
    nic->close(&s); nic->close(&s); CHECK(closes == 1);
    unsigned before_alloc = allocation_count;
    ERR(nic->socket(&s, &error), MP_EBADF);
    CHECK(allocation_count == before_alloc && !s._private);
    UERR(send_one(&s), MP_EBADF); UERR(recv_one(&s), MP_EBADF);
    ERR(nic->bind(&s, wildcard, 0, &error), MP_EBADF); CHECK(opens == 1);
    nic->deinit(); CHECK(deinits == 1);
}
static void test_bind(void) {
    mod_network_socket_obj_t s = socket_new();
    ERR(nic->bind(&s, wildcard, 65536, &error), MP_EINVAL);
    ERR(nic->bind(&s, wildcard, (mp_uint_t)-1, &error), MP_EINVAL);
    ERR(nic->bind(&s, peer, 42, &error), MP_EINVAL); CHECK(opens == 0);
    open_error = MP_EBUSY; ERR(nic->bind(&s, wildcard, 42, &error), MP_EBUSY);
    CHECK(!s.bound && !state(&s)->opened);
    open_error = 0; CHECK(nic->bind(&s, wildcard, 65535, &error) == 0);
    CHECK(s.bound && bound_port == 65535);
    ERR(nic->bind(&s, wildcard, 42, &error), MP_EINVAL); nic->close(&s);
    s = socket_new(); CHECK(nic->bind(&s, wildcard, 0, &error) == 0);
    CHECK(s.bound && bound_port == 0); nic->close(&s);
}
static mod_network_socket_obj_t tcp_new(int timeout);
static void local_is(mod_network_socket_obj_t *s, const char *ip, mp_uint_t port);
static void test_local_bind(void) {
    memcpy(network_state.ip, (byte[4]){192, 168, 1, 7}, 4);
    byte requested_ip[4] = {192, 168, 1, 7};
    mod_network_socket_obj_t udp = socket_new();
    unsigned snapshots = network_snapshots;
    CHECK(nic->bind(&udp, requested_ip, 4321, &error) == 0);
    CHECK(network_snapshots == snapshots + 1 && opens == 1 && bound_port == 4321);
    CHECK(udp_bind_local_calls == 1 && !memcmp(udp_bound_ip, network_state.ip, 4));
    CHECK(!memcmp(state(&udp)->bind_ip, network_state.ip, 4));
    requested_ip[3] = 99;
    CHECK(!memcmp(state(&udp)->bind_ip, network_state.ip, 4));
    snapshots = network_snapshots;
    snapshot_error = -3;
    local_is(&udp, "192.168.1.7", 4321);
    CHECK(network_snapshots == snapshots && udp_local_queries == 1);
    snapshot_error = 0;
    CHECK(nic->connect(&udp, peer, 9000, &error) == 0);
    network_state.ip[3] = 8;
    local_is(&udp, "192.168.1.8", 4321);
    network_state.ip[3] = 7;
    nic->close(&udp);

    mod_network_socket_obj_t udp_ephemeral = socket_new();
    byte ephemeral_ip[4] = {192, 168, 1, 7};
    CHECK(nic->bind(&udp_ephemeral, ephemeral_ip, 0, &error) == 0);
    CHECK(!memcmp(state(&udp_ephemeral)->bind_ip, network_state.ip, 4) && bound_port == 0);
    local_is(&udp_ephemeral, "192.168.1.7", udp_ephemeral_port);
    nic->close(&udp_ephemeral);

    // Failed UDP open and invalid/snapshot binds do not publish a bind address.
    udp = socket_new();
    unsigned before_failed_open = opens;
    open_error = MP_EBUSY;
    ERR(nic->bind(&udp, network_state.ip, 0, &error), MP_EBUSY);
    CHECK(opens == before_failed_open + 1 && !memcmp(state(&udp)->bind_ip, (byte[4]){0}, 4) && !udp.bound);
    open_error = 0;
    udp_bind_local_error = MP_EBUSY;
    unsigned before_local_failure_closes = closes;
    ERR(nic->bind(&udp, network_state.ip, 4321, &error), MP_EBUSY);
    CHECK(!state(&udp)->opened && !udp.bound && !memcmp(state(&udp)->bind_ip, (byte[4]){0}, 4));
    CHECK(closes == before_local_failure_closes + 1);
    udp_bind_local_error = 0;
    byte wrong_ip[4] = {192, 168, 1, 8};
    ERR(nic->bind(&udp, wrong_ip, 4321, &error), MP_EINVAL);
    CHECK(!memcmp(state(&udp)->bind_ip, (byte[4]){0}, 4) && !udp.bound);
    snapshot_error = -2;
    ERR(nic->bind(&udp, network_state.ip, 4321, &error), MP_EBUSY);
    snapshot_error = 0; network_state.initialized = 0;
    ERR(nic->bind(&udp, network_state.ip, 4321, &error), MP_ENOTCONN);
    network_state.initialized = 1; network_state.running = 0;
    ERR(nic->bind(&udp, network_state.ip, 4321, &error), MP_ENOTCONN);
    network_state.running = 1;
    CHECK(!memcmp(state(&udp)->bind_ip, (byte[4]){0}, 4) && opens == before_failed_open + 2);
    // Wildcard bind must remain snapshot-free even without network readiness.
    network_state.running = 0; snapshot_error = -3;
    snapshots = network_snapshots;
    unsigned udp_opens = opens, local_binds = udp_bind_local_calls;
    CHECK(nic->bind(&udp, wildcard, 0, &error) == 0);
    CHECK(network_snapshots == snapshots && opens == udp_opens + 1 && !memcmp(state(&udp)->bind_ip, (byte[4]){0}, 4));
    CHECK(udp_bind_local_calls == local_binds);
    nic->close(&udp);
    mod_network_socket_obj_t tcp_wildcard = tcp_new(0);
    CHECK(nic->bind(&tcp_wildcard, wildcard, 0, &error) == 0);
    CHECK(network_snapshots == snapshots && !memcmp(state(&tcp_wildcard)->bind_ip, wildcard, 4));
    nic->close(&tcp_wildcard);
    network_state.running = 1; snapshot_error = 0;

    mod_network_socket_obj_t tcp = tcp_new(0);
    byte tcp_ip[4] = {192, 168, 1, 7};
    byte tcp_wrong_ip[4] = {192, 168, 1, 8};
    ERR(nic->bind(&tcp, tcp_wrong_ip, 4321, &error), MP_EINVAL);
    snapshot_error = -3;
    ERR(nic->bind(&tcp, tcp_ip, 4321, &error), MP_EBUSY);
    snapshot_error = 0; network_state.running = 0;
    ERR(nic->bind(&tcp, tcp_ip, 4321, &error), MP_ENOTCONN);
    network_state.running = 1;
    CHECK(!memcmp(state(&tcp)->bind_ip, (byte[4]){0}, 4) && !tcp.bound);
    snapshots = network_snapshots;
    CHECK(nic->bind(&tcp, tcp_ip, 4321, &error) == 0);
    CHECK(network_snapshots == snapshots + 1 && tcp_port_queries == 1);
    CHECK(!memcmp(state(&tcp)->bind_ip, network_state.ip, 4));
    tcp_ip[3] = 99;
    CHECK(!memcmp(state(&tcp)->bind_ip, network_state.ip, 4));
    snapshots = network_snapshots;
    snapshot_error = -3;
    local_is(&tcp, "192.168.1.7", 4321);
    CHECK(network_snapshots == snapshots);
    snapshot_error = 0;

    // A changed interface or unavailable snapshot rejects connect/listen before
    // any native operation, retaining the local bind and reservation.
    network_state.ip[3] = 8;
    udp_state_t bound_before = *state(&tcp);
    unsigned starts = tcp_starts, listeners = listener_opens;
    ERR(nic->connect(&tcp, peer, 9000, &error), MP_EINVAL);
    ERR(nic->listen(&tcp, 1, &error), MP_EINVAL);
    CHECK(tcp_starts == starts && listener_opens == listeners && tcp.bound);
    CHECK(state(&tcp)->phase == TCP_BOUND && state(&tcp)->bind_reservation);
    CHECK(!memcmp(state(&tcp), &bound_before, sizeof(bound_before)));
    network_state.ip[3] = 7; snapshot_error = -3;
    ERR(nic->connect(&tcp, peer, 9000, &error), MP_EBUSY);
    ERR(nic->listen(&tcp, 1, &error), MP_EBUSY);
    snapshot_error = 0; network_state.running = 0;
    ERR(nic->connect(&tcp, peer, 9000, &error), MP_ENOTCONN);
    ERR(nic->listen(&tcp, 1, &error), MP_ENOTCONN);
    network_state.running = 1; network_state.initialized = 0;
    ERR(nic->connect(&tcp, peer, 9000, &error), MP_ENOTCONN);
    ERR(nic->listen(&tcp, 1, &error), MP_ENOTCONN);
    network_state.initialized = 1;
    CHECK(tcp_starts == starts && listener_opens == listeners && tcp.bound);
    CHECK(!memcmp(state(&tcp), &bound_before, sizeof(bound_before)));
    listener_open_error = MP_ENOMEM;
    ERR(nic->listen(&tcp, 1, &error), MP_ENOMEM);
    CHECK(!memcmp(state(&tcp), &bound_before, sizeof(bound_before)) && tcp.bound);
    listener_open_error = 0;
    tcp_ready = true;
    CHECK(nic->listen(&tcp, 1, &error) == 0);
    CHECK(listener_opens == listeners + 2 && state(&tcp)->phase == TCP_LISTENING);
    snapshot_error = -3;
    unsigned saved_queries = listener_local_queries;
    snapshots = network_snapshots;
    local_is(&tcp, "192.168.1.7", 4321); // Bound/listening name uses saved bind IP.
    CHECK(network_snapshots == snapshots && listener_local_queries == saved_queries);
    snapshot_error = 0;
    mod_network_socket_obj_t child = {.type = MOD_NETWORK_SOCK_STREAM};
    byte child_ip[4]; mp_uint_t child_port;
    listener_ready = true; stream_local_port = 4321;
    CHECK(nic->accept(&tcp, &child, child_ip, &child_port, &error) == 0);
    network_state.ip[3] = 8;
    local_is(&child, "192.168.1.8", 4321);
    network_state.ip[3] = 7;
    nic->close(&child);
    nic->close(&tcp);

    mod_network_socket_obj_t connected = tcp_new(20);
    byte connected_bind_ip[4] = {192, 168, 1, 7};
    CHECK(nic->bind(&connected, connected_bind_ip, 4321, &error) == 0);
    udp_state_t connected_before = *state(&connected);
    tcp_start_error = MP_ENETDOWN;
    ERR(nic->connect(&connected, peer, 9000, &error), MP_ENETDOWN);
    CHECK(!memcmp(state(&connected), &connected_before, sizeof(connected_before)) && connected.bound);
    tcp_start_error = 0;
    tcp_ready = true;
    CHECK(nic->connect(&connected, peer, 9000, &error) == 0);
    network_state.ip[3] = 8;
    local_is(&connected, "192.168.1.8", 4321); // Connected names remain current-LAN based.
    network_state.ip[3] = 7;
    nic->close(&connected);

    mod_network_socket_obj_t tcp_ephemeral = tcp_new(0);
    unsigned queries_before_zero = tcp_port_queries;
    CHECK(nic->bind(&tcp_ephemeral, network_state.ip, 0, &error) == 0);
    CHECK(tcp_port_queries == queries_before_zero && !state(&tcp_ephemeral)->bind_reservation);
    CHECK(state(&tcp_ephemeral)->local_port == 0 && !memcmp(state(&tcp_ephemeral)->bind_ip, network_state.ip, 4));
    snapshot_error = -3;
    local_is(&tcp_ephemeral, "192.168.1.7", 0);
    snapshot_error = 0;
    CHECK(nic->listen(&tcp_ephemeral, 1, &error) == 0);
    local_is(&tcp_ephemeral, "192.168.1.7", 60001);
    nic->close(&tcp_ephemeral);

    mod_network_socket_obj_t reserved = tcp_new(0);
    byte reserved_ip[4] = {192, 168, 1, 7};
    native_occupied_port = 4321;
    ERR(nic->bind(&reserved, reserved_ip, 4321, &error), MP_EADDRINUSE);
    CHECK(!reserved.bound && !state(&reserved)->bind_reservation &&
        !memcmp(state(&reserved)->bind_ip, (byte[4]){0}, 4));
    native_occupied_port = 0;
    tcp_port_query_error = MP_EBUSY;
    ERR(nic->bind(&reserved, reserved_ip, 4321, &error), MP_EBUSY);
    CHECK(!reserved.bound && !state(&reserved)->bind_reservation &&
        !memcmp(state(&reserved)->bind_ip, (byte[4]){0}, 4));
    tcp_port_query_error = 0;
    nic->close(&reserved);

    mod_network_socket_obj_t conflict = tcp_new(0), local_udp = socket_new();
    byte local_ip[4] = {192, 168, 1, 7};
    CHECK(nic->bind(&conflict, wildcard, 4321, &error) == 0);
    CHECK(nic->bind(&local_udp, local_ip, 4321, &error) == 0);
    CHECK(!state(&local_udp)->bind_reservation && state(&conflict)->bind_reservation);
    mod_network_socket_obj_t another = tcp_new(0);
    ERR(nic->bind(&another, wildcard, 4321, &error), MP_EADDRINUSE);
    ERR(nic->bind(&another, local_ip, 4321, &error), MP_EADDRINUSE);
    CHECK(!another.bound && !memcmp(state(&another)->bind_ip, wildcard, 4));
    nic->close(&conflict);
    CHECK(nic->bind(&another, local_ip, 4321, &error) == 0);
    uint32_t replacement = state(&another)->bind_reservation;
    nic->close(&conflict); // Old close cannot free the local replacement owner.
    mod_network_socket_obj_t probe = tcp_new(0);
    ERR(nic->bind(&probe, wildcard, 4321, &error), MP_EADDRINUSE);
    CHECK(state(&another)->bind_reservation == replacement);
    nic->close(&probe); nic->close(&another); nic->close(&local_udp);
}
static void test_broadcast(void) {
    mod_network_socket_obj_t s = socket_new();
    mp_int_t on=1, off=0;
    CHECK(!state(&s)->broadcast);
    CHECK(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, &on, sizeof on, &error)==0);
    CHECK(opens==0 && broadcast_calls==0);
    broadcast_error=MP_EBUSY;
    UERR(send_one(&s), MP_EBUSY);
    CHECK(!state(&s)->opened && closes==1);
    broadcast_error=0;
    CHECK(send_one(&s)==3 && broadcast_value==1);
    broadcast_error=MP_EBUSY;
    ERR(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, &off, sizeof off, &error), MP_EBUSY);
    CHECK(state(&s)->broadcast);
    broadcast_error=0;
    CHECK(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, &off, sizeof off, &error)==0);
    CHECK(!state(&s)->broadcast && !broadcast_value);
    ERR(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, NULL, 0, &error), MP_EINVAL);
    nic->close(&s);
}
static void test_unsupported(void) {
    mod_network_socket_obj_t s = {.domain=99, .type=MOD_NETWORK_SOCK_DGRAM};
    ERR(nic->socket(&s, &error), MP_EAFNOSUPPORT);
    s.domain = MOD_NETWORK_AF_INET; s.type = 3;
    ERR(nic->socket(&s, &error), MP_EOPNOTSUPP);
    s.type = MOD_NETWORK_SOCK_DGRAM; s.proto = 6;
    ERR(nic->socket(&s, &error), MP_EOPNOTSUPP); CHECK(allocation_count == 0);
    s = socket_new();
    CHECK(nic->gethostbyname(NULL, "example.invalid", 15, buffer) == MP_ENETDOWN);
    ERR(nic->listen(&s, 1, &error), MP_EOPNOTSUPP);
    ERR(nic->accept(&s, &s, peer, &peer_port, &error), MP_EOPNOTSUPP);
    UERR(nic->send(&s, buffer, 3, &error), MP_ENOTCONN);
    CHECK(nic->recv(&s, buffer, 0, &error) == 0);
    ERR(nic->setsockopt(&s, 0, 0, buffer, 3, &error), MP_EOPNOTSUPP);
    CHECK(opens == 0); nic->close(&s);
    s.proto = 17; s.state = MOD_NETWORK_SS_NEW;
    CHECK(nic->socket(&s, &error) == 0); nic->close(&s);
}
static mp_uint_t connected_io(mod_network_socket_obj_t *s, bool receive) {
    mp_uint_t count = receive ? nic->recv(s, buffer, sizeof(buffer), &error)
                             : nic->send(s, buffer, 3, &error);
    if (count != (mp_uint_t)-1) {
        CHECK(count == 3);
        if (receive) CHECK(!memcmp(buffer, "udp", 3));
    }
    return count;
}
static void test_udp_connect(bool explicit_bind) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(!state(&s)->connected && !state(&s)->opened);
    UERR(nic->send(&s, buffer, 0, &error), MP_ENOTCONN);
    CHECK(nic->recv(&s, buffer, 0, &error) == 0);
    ERR(nic->connect(&s, peer, 65536, &error), MP_EINVAL);
    ERR(nic->connect(&s, peer, (mp_uint_t)-1, &error), MP_EINVAL);
    CHECK(!opens && !connects && !connected_sends && !recvs);
    if (explicit_bind) {
        CHECK(nic->bind(&s, wildcard, 4321, &error) == 0);
        CHECK(s.bound && !state(&s)->connected);
        UERR(nic->send(&s, buffer, 3, &error), MP_ENOTCONN);
        CHECK(nic->recv(&s, buffer, 0, &error) == 0);
    }
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    CHECK(opens == 1 && connects == 1 && closes == 0);
    CHECK(bound_port == (explicit_bind ? 4321 : 0) && s.bound == explicit_bind);
    CHECK(state(&s)->opened && state(&s)->connected && connected_peer);
    CHECK(s.state == MOD_NETWORK_SS_CONNECTED && connected_port == 9000);
    CHECK(!memcmp(connected_ip, peer, 4) && !events && !delays);
    CHECK(connected_io(&s, false) == 3 && connected_sends == 1 && sent_length == 3);
    CHECK(connected_io(&s, true) == 3 && recvs == 1 && consumed_packets == 1);

    byte next_peer[4] = {198, 51, 100, 2};
    connect_error = MP_ENETDOWN;
    ERR(nic->connect(&s, next_peer, 1234, &error), MP_ENETDOWN);
    connect_error = 0;
    ERR(nic->connect(&s, next_peer, 0, &error), MP_EINVAL);
    ERR(nic->connect(&s, wildcard, 1234, &error), MP_EINVAL);
    ERR(nic->connect(&s, next_peer, 65536, &error), MP_EINVAL);
    CHECK(connects == 4 && opens == 1 && closes == 0);
    CHECK(state(&s)->connected && s.state == MOD_NETWORK_SS_CONNECTED);
    CHECK(connected_peer && connected_port == 9000 && !memcmp(connected_ip, peer, 4));
    CHECK(connected_io(&s, false) == 3 && connected_io(&s, true) == 3);

    CHECK(nic->connect(&s, next_peer, 65535, &error) == 0);
    CHECK(connects == 5 && opens == 1 && closes == 0);
    CHECK(bound_port == (explicit_bind ? 4321 : 0) && s.bound == explicit_bind);
    CHECK(state(&s)->connected && connected_port == 65535);
    CHECK(!memcmp(connected_ip, next_peer, 4));
    CHECK(connected_io(&s, false) == 3 && connected_io(&s, true) == 3);
    // Explicit sendto still dispatches independently of the default peer.
    CHECK(send_one(&s) == 3 && sends == 1 && connected_sends == 3);
    CHECK(connected_port == 65535 && !memcmp(connected_ip, next_peer, 4));
    byte ip[4] = {0}; peer_port = 0;
    CHECK(nic->recvfrom(&s, buffer, sizeof(buffer), ip, &peer_port, &error) == 3);
    CHECK(peer_port == 65535 && !memcmp(ip, next_peer, 4));

    unsigned before_connect = connects, before_send = connected_sends, before_recv = recvs;
    nic->close(&s); nic->close(&s);
    CHECK(closes == 1 && !live && !connected_peer && !s._private);
    CHECK(s.state == MOD_NETWORK_SS_CLOSED);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EBADF);
    UERR(nic->send(&s, buffer, 3, &error), MP_EBADF);
    UERR(nic->recv(&s, buffer, 3, &error), MP_EBADF);
    UERR(nic->send(&s, buffer, 0, &error), MP_EBADF);
    UERR(nic->recv(&s, buffer, 0, &error), MP_EBADF);
    CHECK(connects == before_connect && connected_sends == before_send && recvs == before_recv);
    CHECK(opens == 1 && closes == 1);
}
static void test_udp_unconnected_recv(void) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(send_one(&s)==3 && !state(&s)->connected && opens==1);
    CHECK(nic->recv(&s,buffer,3,&error)==3);
    CHECK(!memcmp(buffer,"udp",3) && consumed_packets==1 && !connects);
    nic->settimeout(&s,0,&error); recv_error=MP_EAGAIN;
    UERR(nic->recv(&s,buffer,3,&error),MP_EAGAIN);
    recv_error=MP_ENETDOWN;
    UERR(nic->recv(&s,buffer,3,&error),MP_ENETDOWN);
    CHECK(!events && !delays && opens==1 && !connected_sends);
    nic->close(&s);CHECK(closes==1);
}
static void test_udp_connect_errors(void) {
    mod_network_socket_obj_t s = socket_new();
    open_error = MP_ENOMEM;
    ERR(nic->connect(&s, peer, 9000, &error), MP_ENOMEM);
    CHECK(opens == 1 && !connects && !live && !state(&s)->opened);
    CHECK(!state(&s)->connected && s.state == MOD_NETWORK_SS_NEW);
    open_error = 0;
    ERR(nic->connect(&s, peer, 0, &error), MP_EINVAL);
    ERR(nic->connect(&s, wildcard, 9000, &error), MP_EINVAL);
    connect_error = MP_EBUSY;
    ERR(nic->connect(&s, peer, 9000, &error), MP_EBUSY);
    connect_error = MP_EAGAIN;
    ERR(nic->connect(&s, peer, 9000, &error), MP_EAGAIN);
    CHECK(opens == 2 && connects == 4 && live && state(&s)->opened);
    CHECK(!state(&s)->connected && !connected_peer && s.state == MOD_NETWORK_SS_NEW);
    CHECK(!events && !delays && !s.bound);
    UERR(nic->send(&s, buffer, 3, &error), MP_ENOTCONN);
    CHECK(nic->recv(&s, buffer, 0, &error) == 0);
    CHECK(!connected_sends && !recvs);
    connect_error = 0;
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    CHECK(opens == 2 && connects == 5 && state(&s)->connected);
    CHECK(connected_io(&s, false) == 3 && connected_io(&s, true) == 3);
    nic->close(&s); nic->close(&s); CHECK(closes == 1 && !live);
}
static void test_udp_empty(void) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    CHECK(nic->send(&s, buffer, 0, &error) == 0);
    CHECK(connected_sends == 1 && sent_length == 0 && !sends);
    // recv(0) must not ask the bridge for a packet, even when it would block.
    recv_error = MP_EAGAIN;
    CHECK(nic->recv(&s, buffer, 0, &error) == 0);
    CHECK(!recvs && !consumed_packets && !events && !delays);
    recv_error = 0;
    CHECK(connected_io(&s, true) == 3 && recvs == 1 && consumed_packets == 1);
    udp_recv_count = 0; buffer[0] = 0xA5;
    CHECK(nic->recv(&s, buffer, sizeof(buffer), &error) == 0);
    CHECK(recvs == 2 && consumed_packets == 2 && buffer[0] == 0xA5);
    CHECK(nic->recv(&s, buffer, 0, &error) == 0);
    CHECK(recvs == 2 && consumed_packets == 2);
    udp_recv_count = 3;
    CHECK(connected_io(&s, true) == 3 && recvs == 3 && consumed_packets == 3);
    byte ip[4] = {0}; peer_port = 0;
    CHECK(nic->recvfrom(&s, buffer, 0, ip, &peer_port, &error) == 0);
    CHECK(recvs == 4 && consumed_packets == 4);
    CHECK(peer_port == 9000 && !memcmp(ip, peer, 4));
    nic->close(&s); CHECK(closes == 1);
}
static void test_udp_io(const char *mode, bool receive) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    send_error = recv_error = MP_EAGAIN;
    if (!strcmp(mode, "errors")) {
        s.timeout = 0;
        UERR(connected_io(&s, receive), MP_EAGAIN);
        send_error = recv_error = MP_ENETDOWN;
        UERR(connected_io(&s, receive), MP_ENETDOWN);
        CHECK(!events && !delays && !consumed_packets);
        CHECK((receive ? recvs : connected_sends) == 2);
    } else if (!strcmp(mode, "event-close")) {
        close_on_event = &s;
        UERR(connected_io(&s, receive), MP_EBADF);
        CHECK(events == 1 && !delays && closes == 1 && !s._private && !live);
        CHECK((receive ? recvs : connected_sends) == 1);
        CHECK(!consumed_packets);
        nic->close(&s); CHECK(closes == 1); return;
    } else if (!strcmp(mode, "retry")) {
        s.timeout = 20; success_after_delay = true;
        CHECK(connected_io(&s, receive) == 3);
        CHECK(events == 1 && delays == 1 && now == 1000);
        CHECK((receive ? recvs : connected_sends) == 2);
        CHECK(consumed_packets == (receive ? 1u : 0u));
    } else {
        CHECK(!strcmp(mode, "timeout") || !strcmp(mode, "deadline"));
        success_after_delay = !strcmp(mode, "deadline");
        s.timeout = success_after_delay ? 1 : 3;
        UERR(connected_io(&s, receive), MP_ETIMEDOUT);
        CHECK(now == (uint64_t)s.timeout * 1000);
        CHECK(events == (unsigned)s.timeout && delays == (unsigned)s.timeout);
        CHECK((receive ? recvs : connected_sends) == (unsigned)s.timeout);
        CHECK(!consumed_packets);
    }
    CHECK(opens == 1 && connects == 1 && state(&s)->connected && live);
    CHECK(s.state == MOD_NETWORK_SS_CONNECTED && closes == 0);
    nic->close(&s); nic->close(&s); CHECK(closes == 1 && !live);
}
static void test_errors(void) {
    mod_network_socket_obj_t s = socket_new();
    UERR(nic->sendto(&s, buffer, 3, peer, 0, &error), MP_EINVAL);
    UERR(nic->sendto(&s, buffer, 3, peer, 65536, &error), MP_EINVAL); CHECK(opens == 0);
    open_error = MP_ENOMEM; UERR(send_one(&s), MP_ENOMEM); UERR(recv_one(&s), MP_ENOMEM);
    CHECK(sends == 0 && recvs == 0); open_error = 0;
    send_error = MP_ENETDOWN; UERR(send_one(&s), MP_ENETDOWN);
    recv_error = MP_EBUSY; UERR(recv_one(&s), MP_EBUSY); CHECK(events == 0);
    CHECK(nic->settimeout(&s, 0, &error) == 0);
    send_error = recv_error = MP_EAGAIN;
    UERR(send_one(&s), MP_EAGAIN); UERR(recv_one(&s), MP_EAGAIN);
    CHECK(events == 0 && delays == 0); nic->close(&s);
}
static void test_timeout(bool receive, bool late_success) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(nic->settimeout(&s, (mp_uint_t)-1, &error) == 0 && s.timeout == -1);
    CHECK(nic->settimeout(&s, INT32_MAX, &error) == 0 && s.timeout == INT32_MAX);
    ERR(nic->settimeout(&s, (mp_uint_t)INT32_MAX + 1, &error), MP_EINVAL);
    CHECK(s.timeout == INT32_MAX);
    CHECK(nic->settimeout(&s, late_success ? 1 : 3, &error) == 0);
    send_error = recv_error = MP_EAGAIN; success_after_delay = late_success;
    UERR(receive ? recv_one(&s) : send_one(&s), MP_ETIMEDOUT);
    CHECK(events > 0 && delays > 0 && now >= (uint64_t)s.timeout * 1000);
    nic->close(&s);
}
static void test_retry_success(bool receive) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(nic->settimeout(&s, 20, &error) == 0);
    send_error = recv_error = MP_EAGAIN; success_after_delay = true;
    CHECK((receive ? recv_one(&s) : send_one(&s)) == 3);
    CHECK(events > 0 && delays > 0 && now < 20000); nic->close(&s);
}
static void test_event_close(bool receive) {
    mod_network_socket_obj_t s = socket_new();
    send_error = recv_error = MP_EAGAIN; close_on_event = &s;
    UERR(receive ? recv_one(&s) : send_one(&s), MP_EBADF);
    CHECK(events > 0 && closes == 1 && !s._private && !live);
    nic->close(&s); CHECK(closes == 1);
}
static void test_poll(void) {
    mod_network_socket_obj_t s = socket_new();
    ERR(nic->ioctl(&s, 999, 0, &error), MP_EINVAL); CHECK(opens == 0);
    open_error = MP_EBUSY;
    ERR(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_RD, &error), MP_EBUSY);
    CHECK(polls == 0); open_error = 0;
    const unsigned masks[] = {0, MP_STREAM_POLL_RD, MP_STREAM_POLL_WR,
        MP_STREAM_POLL_ERR, MP_STREAM_POLL_HUP, MP_STREAM_POLL_NVAL,
        MP_STREAM_POLL_RD | MP_STREAM_POLL_WR};
    for (unsigned i = 0; i < sizeof(masks)/sizeof(masks[0]); ++i) {
        poll_events = masks[i];
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, masks[i], &error) == (int)masks[i]);
        CHECK(requested == masks[i]);
    }
    CHECK(bound_port == 0); poll_error = MP_ENETDOWN;
    ERR(nic->ioctl(&s, MP_STREAM_POLL, 0, &error), MP_ENETDOWN);
    nic->close(&s); unsigned before = polls;
    CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_RD, &error) == MP_STREAM_POLL_NVAL);
    CHECK(polls == before);
}
static mod_network_socket_obj_t tcp_new(int timeout) {
    mod_network_socket_obj_t s = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM, .proto=6, .timeout=timeout};
    CHECK(nic->socket(&s, &error) == 0); return s;
}
typedef struct {
    unsigned allocs, udp_opens, tcp_opens, passive_opens, vm_events, vm_delays, formats;
} name_observation_t;
static name_observation_t observe_name(void) {
    return (name_observation_t){allocation_count, opens, tcp_starts, listener_opens,
        events, delays, format_calls};
}
static void name_has_no_side_effects(name_observation_t before, unsigned formats) {
    CHECK(allocation_count == before.allocs && opens == before.udp_opens);
    CHECK(tcp_starts == before.tcp_opens && listener_opens == before.passive_opens);
    CHECK(events == before.vm_events && delays == before.vm_delays);
    CHECK(format_calls == before.formats + formats && nlr_top == NULL);
}
static void local_raises(mod_network_socket_obj_t *s, int code) {
    name_observation_t before = observe_name();
    nlr_buf_t outer;
    if (nlr_push(&outer) == 0) {
        mpynn_socket_getsockname(MP_OBJ_FROM_PTR(s));
        nlr_pop(); CHECK(false);
    } else CHECK(outer.ret_val == (void *)(intptr_t)code);
    name_has_no_side_effects(before, 0);
}
static void local_is(mod_network_socket_obj_t *s, const char *ip, mp_uint_t port) {
    name_observation_t before = observe_name();
    formatted_peer_t *result = MP_OBJ_TO_PTR(mpynn_socket_getsockname(MP_OBJ_FROM_PTR(s)));
    if (strcmp(result->ip, ip) || result->port != port)
        fprintf(stderr, "getsockname expected %s:%lu, got %s:%lu\n", ip,
            (unsigned long)port, result->ip, (unsigned long)result->port);
    CHECK(result == &formatted_peer && !strcmp(result->ip, ip) && result->port == port);
    name_has_no_side_effects(before, 1);
}
static void test_getsock_fresh(void) {
    mod_network_socket_obj_t fresh = {.state = MOD_NETWORK_SS_NEW};
    local_is(&fresh, "0.0.0.0", 0);
    fresh.state = MOD_NETWORK_SS_CLOSED;
    local_raises(&fresh, MP_EBADF);
    mod_network_socket_obj_t s = socket_new();
    local_is(&s, "0.0.0.0", 0);
    nic->close(&s);
    local_raises(&s, MP_EBADF);
    s._private = &formatted_peer; // Closed must win over an invalid private pointer.
    local_raises(&s, MP_EBADF);
    s._private = NULL;
    s = tcp_new(0);
    local_is(&s, "0.0.0.0", 0);
    tcp_start_error = MP_ENETDOWN;
    ERR(nic->connect(&s, peer, 9000, &error), MP_ENETDOWN);
    local_is(&s, "0.0.0.0", 0);
    CHECK(!udp_local_queries && !stream_local_queries && !network_snapshots && !tcp_finishes);
    nic->close(&s);
    local_raises(&s, MP_EBADF);
}
static void test_getsock_udp(const char *mode) {
    mod_network_socket_obj_t s = socket_new();
    if (!strcmp(mode, "lazy")) CHECK(send_one(&s) == 3);
    else CHECK(nic->bind(&s, wildcard, !strcmp(mode, "bound") ? 4321 : 0, &error) == 0);
    uint16_t port = bound_port ? bound_port : udp_ephemeral_port;
    local_is(&s, "0.0.0.0", port);
    CHECK(udp_local_queries == 1 && !network_snapshots);
    // An unconnected native query must not depend on network snapshot/context.
    snapshot_error = -3;
    local_is(&s, "0.0.0.0", port);
    snapshot_error = 0;
    udp_local_error = MP_EBUSY;
    local_raises(&s, MP_EBUSY);
    udp_local_error = MP_ENETDOWN;
    local_raises(&s, MP_ENETDOWN);
    udp_local_error = 0;
    uint32_t token = state(&s)->token;
    state(&s)->token = token ^ 8; // Stale generation: propagate native EBADF.
    local_raises(&s, MP_EBADF);
    state(&s)->token = token;
    CHECK(!network_snapshots);
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    local_is(&s, "198.51.100.7", port);
    byte next_peer[4] = {203, 0, 113, 9};
    connect_error = MP_ENETDOWN;
    ERR(nic->connect(&s, next_peer, 1234, &error), MP_ENETDOWN);
    local_is(&s, "198.51.100.7", port);
    connect_error = 0;
    CHECK(nic->connect(&s, next_peer, 1234, &error) == 0);
    local_is(&s, "198.51.100.7", port);
    network_state.ip[3] = 8;
    local_is(&s, "198.51.100.8", port); // Fresh snapshot, not saved remote/local IP.
    unsigned before_snapshots = network_snapshots;
    udp_local_error = MP_EBADF;
    local_raises(&s, MP_EBADF);
    CHECK(network_snapshots == before_snapshots);
    udp_local_error = 0;
    snapshot_error = -3;
    local_raises(&s, MP_EBUSY);
    snapshot_error = -2;
    local_raises(&s, MP_EBUSY);
    snapshot_error = 0; network_state.initialized = 0;
    local_raises(&s, MP_ENOTCONN);
    network_state.initialized = 1; network_state.running = 0;
    local_raises(&s, MP_ENOTCONN);
    network_state.running = 1;
    local_is(&s, "198.51.100.8", port);
    CHECK(opens == 1 && !stream_local_queries && !tcp_finishes);
    nic->close(&s);
    before_snapshots = network_snapshots;
    unsigned before_queries = udp_local_queries;
    local_raises(&s, MP_EBADF);
    CHECK(network_snapshots == before_snapshots && udp_local_queries == before_queries);
}
static void test_getsock_tcp(const char *mode) {
    mod_network_socket_obj_t s = tcp_new(0);
    if (!strcmp(mode, "connected")) {
        s.timeout = 20; tcp_ready = true;
        CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    } else {
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        local_raises(&s, MP_ENOTCONN);
        local_raises(&s, MP_ENOTCONN);
        CHECK(tcp_finishes == 2 && !stream_local_queries && !network_snapshots && tcp_job);
        if (!strcmp(mode, "failed")) {
            tcp_error = MP_ECONNREFUSED;
            local_raises(&s, MP_ECONNREFUSED);
            CHECK(tcp_finishes == 3 && tcp_cancels == 1 && state(&s)->phase == TCP_FAILED);
            tcp_error = 0; tcp_ready = true;
            local_raises(&s, MP_ECONNREFUSED);
            CHECK(tcp_finishes == 3 && !stream_local_queries && !network_snapshots);
            nic->close(&s); local_raises(&s, MP_EBADF); return;
        }
        CHECK(!strcmp(mode, "pending")); tcp_ready = true;
    }
    unsigned before_finish = tcp_finishes;
    local_is(&s, "198.51.100.7", 49153);
    CHECK(tcp_finishes == before_finish + (!strcmp(mode, "pending") ? 1u : 0u));
    CHECK(!tcp_job && tcp_live && s.state == MOD_NETWORK_SS_CONNECTED);
    before_finish = tcp_finishes;
    local_is(&s, "198.51.100.7", 49153);
    CHECK(tcp_finishes == before_finish && stream_local_queries == 2);
    unsigned before_snapshots = network_snapshots;
    state(&s)->stream_token = 89;
    local_raises(&s, MP_EBADF);
    state(&s)->stream_token = 81;
    stream_local_error = MP_EBUSY;
    local_raises(&s, MP_EBUSY);
    stream_local_error = MP_ENETDOWN;
    local_raises(&s, MP_ENETDOWN);
    CHECK(network_snapshots == before_snapshots);
    stream_local_error = 0; snapshot_error = -3;
    local_raises(&s, MP_EBUSY);
    snapshot_error = 0; network_state.running = 0;
    local_raises(&s, MP_ENOTCONN);
    network_state.running = 1; network_state.initialized = 0;
    local_raises(&s, MP_ENOTCONN);
    network_state.initialized = 1;
    local_is(&s, "198.51.100.7", 49153);
    CHECK(!udp_local_queries && tcp_finishes == before_finish);
    nic->close(&s);
    unsigned before_queries = stream_local_queries;
    local_raises(&s, MP_EBADF);
    CHECK(stream_local_queries == before_queries);
}
static void test_getsock_accept(void) {
    mod_network_socket_obj_t s = tcp_new(0);
    mod_network_socket_obj_t child = {.type = MOD_NETWORK_SOCK_STREAM};
    CHECK(nic->bind(&s, wildcard, 9000, &error) == 0);
    snapshot_error = -3; // Bound/listening wildcard does not require network access.
    local_is(&s, "0.0.0.0", 9000);
    CHECK(!listener_opens);
    CHECK(nic->listen(&s, 1, &error) == 0);
    local_is(&s, "0.0.0.0", 9000);
    CHECK(!stream_local_queries && !network_snapshots && !tcp_finishes);
    snapshot_error = 0;
    listener_ready = true; accepted_port = 54321; stream_local_port = 9000;
    byte ip[4]; mp_uint_t port;
    CHECK(nic->accept(&s, &child, ip, &port, &error) == 0);
    CHECK(port == 54321 && state(&child)->local_port == 0);
    local_is(&child, "198.51.100.7", 9000);
    CHECK(stream_local_queries == 1 && !tcp_finishes);
    // Prove the child's native endpoint is consulted, not a cached listener port.
    stream_local_port = 9001;
    local_is(&child, "198.51.100.7", 9001);
    local_is(&s, "0.0.0.0", 9000);
    nic->close(&s);
    local_raises(&s, MP_EBADF);
    local_is(&child, "198.51.100.7", 9001);
    stream_local_error = MP_EBADF;
    local_raises(&child, MP_EBADF);
    stream_local_error = 0;
    nic->close(&child);
    local_raises(&child, MP_EBADF);
    CHECK(!tcp_finishes && !udp_local_queries);
}
static void test_getpeer_udp(void) {
    mod_network_socket_obj_t fresh = {.state = MOD_NETWORK_SS_NEW};
    peer_raises(&fresh, MP_ENOTCONN);
    fresh.state = MOD_NETWORK_SS_CLOSED;
    peer_raises(&fresh, MP_EBADF);
    mod_network_socket_obj_t s = socket_new();
    byte ip[4] = {192, 0, 2, 1}, rejected[4] = {203, 0, 113, 9};
    peer_raises(&s, MP_ENOTCONN);
    CHECK(!opens && !connects && !events && !delays);
    CHECK(nic->bind(&s, wildcard, 4321, &error) == 0);
    peer_raises(&s, MP_ENOTCONN);
    connect_error = MP_ENETDOWN;
    ERR(nic->connect(&s, rejected, 1234, &error), MP_ENETDOWN);
    peer_raises(&s, MP_ENOTCONN);
    CHECK(!memcmp(state(&s)->peer_ip, wildcard, 4) && !state(&s)->peer_port);
    connect_error = 0;
    CHECK(nic->connect(&s, ip, 9000, &error) == 0);
    memset(ip, 0xA5, sizeof(ip));
    peer_is(&s, "192.0.2.1", 9000);
    connect_error = MP_EBUSY;
    ERR(nic->connect(&s, rejected, 1234, &error), MP_EBUSY);
    peer_is(&s, "192.0.2.1", 9000);
    connect_error = 0;
    ERR(nic->connect(&s, rejected, 65536, &error), MP_EINVAL);
    peer_is(&s, "192.0.2.1", 9000);
    CHECK(nic->connect(&s, rejected, 65535, &error) == 0);
    memset(rejected, 0, sizeof(rejected));
    peer_is(&s, "203.0.113.9", 65535);
    CHECK(send_one(&s) == 3);
    peer_is(&s, "203.0.113.9", 65535);
    CHECK(!events && !delays && opens == 1);
    nic->close(&s);
    peer_raises(&s, MP_EBADF);
    // Closed takes precedence even if an inconsistent private pointer remains.
    s._private = &formatted_peer;
    peer_raises(&s, MP_EBADF);
    s._private = NULL;
}
static void test_getpeer_tcp(const char *mode) {
    mod_network_socket_obj_t s = tcp_new(0);
    byte ip[4] = {192, 0, 2, 1};
    peer_raises(&s, MP_ENOTCONN);
    CHECK(!tcp_starts && !tcp_finishes);
    if (!strcmp(mode, "start-error")) {
        tcp_start_error = MP_ENETDOWN;
        ERR(nic->connect(&s, ip, 9000, &error), MP_ENETDOWN);
        peer_raises(&s, MP_ENOTCONN);
        CHECK(!memcmp(state(&s)->peer_ip, wildcard, 4) && !state(&s)->peer_port);
        CHECK(!tcp_job && !tcp_finishes && !tcp_cancels);
    } else if (!strcmp(mode, "blocking")) {
        s.timeout = 20; tcp_ready_after_delay = true;
        CHECK(nic->connect(&s, ip, 9000, &error) == 0);
        memset(ip, 0xA5, sizeof(ip));
        unsigned before = tcp_finishes;
        peer_is(&s, "192.0.2.1", 9000);
        peer_is(&s, "192.0.2.1", 9000);
        CHECK(tcp_finishes == before && events == 1 && delays == 1);
    } else {
        ERR(nic->connect(&s, ip, 9000, &error), MP_EINPROGRESS);
        memset(ip, 0xA5, sizeof(ip));
        CHECK(!memcmp(state(&s)->peer_ip, peer, 4) && state(&s)->peer_port == 9000);
        peer_raises(&s, MP_ENOTCONN);
        peer_raises(&s, MP_ENOTCONN);
        CHECK(tcp_finishes == 2 && tcp_job && state(&s)->phase == TCP_PENDING);
        CHECK(!events && !delays && !tcp_cancels);
        if (!strcmp(mode, "failure")) {
            tcp_error = MP_ECONNREFUSED;
            peer_raises(&s, MP_ECONNREFUSED);
            CHECK(tcp_finishes == 3 && tcp_cancels == 1 && !tcp_job);
            tcp_error = 0; tcp_ready = true;
            peer_raises(&s, MP_ECONNREFUSED);
            ERR(nic->connect(&s, ip, 9000, &error), MP_ECONNREFUSED);
            CHECK(tcp_finishes == 3 && tcp_cancels == 1 && !tcp_live);
        } else {
            CHECK(!strcmp(mode, "promote")); tcp_ready = true;
            peer_is(&s, "192.0.2.1", 9000);
            CHECK(tcp_finishes == 3 && !tcp_job && tcp_live);
            CHECK(state(&s)->phase == TCP_CONNECTED && s.state == MOD_NETWORK_SS_CONNECTED);
            peer_is(&s, "192.0.2.1", 9000);
            CHECK(tcp_finishes == 3 && !tcp_cancels && !events && !delays);
        }
    }
    nic->close(&s);
    peer_raises(&s, MP_EBADF);
    CHECK(!tcp_job && !tcp_live);
}
static void sendall_raises(mod_network_socket_obj_t *s, int code) {
    nlr_buf_t outer;
    if (nlr_push(&outer) == 0) {
        mpynn_socket_sendall(MP_OBJ_FROM_PTR(s), MP_OBJ_FROM_PTR(&sendall_buffer));
        nlr_pop(); CHECK(false);
    } else CHECK(outer.ret_val == (void *)(intptr_t)code);
    CHECK(nlr_top == NULL);
}
static void sendall_ok(mod_network_socket_obj_t *s) {
    CHECK(mpynn_socket_sendall(MP_OBJ_FROM_PTR(s), MP_OBJ_FROM_PTR(&sendall_buffer)) == mp_const_none);
    CHECK(nlr_top == NULL);
}
static mod_network_socket_obj_t *callback_socket;
static int callback_timeout, callback_new_timeout;
static unsigned callback_calls;
static void callback_settimeout(void) {
    ++callback_calls; CHECK(callback_socket->timeout == callback_timeout);
    CHECK(nic->settimeout(callback_socket, (mp_uint_t)callback_new_timeout, &error) == 0);
    event_callback = NULL;
}
static void callback_expire(void) {
    CHECK(callback_socket->timeout == callback_timeout);
    ++callback_calls; now += 3000; event_callback = NULL;
}
static void callback_reenter(void) {
    CHECK(callback_socket->timeout == callback_timeout);
    ++callback_calls; event_callback = NULL;
    mp_buffer_info_t nested = {buffer, 1, 'B'};
    CHECK(mpynn_socket_sendall(MP_OBJ_FROM_PTR(callback_socket), MP_OBJ_FROM_PTR(&nested)) == mp_const_none);
    CHECK(callback_socket->timeout == callback_timeout);
}
static void test_sendall(const char *mode) {
    // Static socket storage remains defined after NLR longjmp from callbacks.
    static mod_network_socket_obj_t s;
    s = tcp_new(3); tcp_ready = true;
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    CHECK(tcp_live && !events && !delays);
    callback_socket = &s; callback_timeout = 3;
    if (!strcmp(mode, "partial-success")) {
        write_step(0, 3, 750); write_step(0, 3, 750); write_step(0, 2, 750);
        sendall_ok(&s);
        CHECK(tcp_writes == 3 && written_bytes == 8 && now == 2250);
        CHECK(write_offsets[0] == 0 && write_offsets[1] == 3 && write_offsets[2] == 6);
        CHECK(write_lengths[0] == 8 && write_lengths[1] == 5 && write_lengths[2] == 2);
        CHECK(events == 2 && !delays);
    } else if (!strcmp(mode, "partial-deadline") || !strcmp(mode, "exact-deadline")) {
        uint64_t advance = !strcmp(mode, "exact-deadline") ? 1000 : 1200;
        for (unsigned i = 0; i < 4; ++i) write_step(0, 2, advance);
        sendall_raises(&s, MP_ETIMEDOUT);
        CHECK(tcp_writes == 3 && written_bytes == 6 && now == advance * 3);
        CHECK(write_offsets[0] == 0 && write_offsets[1] == 2 && write_offsets[2] == 4);
        CHECK(write_times[0] == 0 && write_times[1] == advance && write_times[2] == advance * 2);
        CHECK(!delays);
    } else if (!strcmp(mode, "backpressure-deadline")) {
        write_step(0, 2, 600); write_step(MP_EAGAIN, 0, 400);
        write_step(MP_EAGAIN, 0, 0); write_step(0, 6, 0);
        sendall_raises(&s, MP_ETIMEDOUT);
        CHECK(tcp_writes == 3 && written_bytes == 2 && now == 3000);
        CHECK(write_offsets[1] == 2 && write_offsets[2] == 2);
        CHECK(write_lengths[1] == 6 && write_lengths[2] == 6);
        CHECK(events == 3 && delays == 2);
    } else if (!strcmp(mode, "backpressure-success")) {
        s.timeout = 5;
        write_step(0, 2, 1000); write_step(MP_EAGAIN, 0, 500);
        write_step(0, 2, 1000); write_step(0, 4, 500);
        sendall_ok(&s);
        CHECK(tcp_writes == 4 && written_bytes == 8 && now == 4000);
        CHECK(write_offsets[1] == 2 && write_offsets[2] == 2 && write_offsets[3] == 4);
        CHECK(events == 3 && delays == 1 && s.timeout == 5);
    } else if (!strcmp(mode, "callback-expiry")) {
        write_step(0, 2, 0); write_step(0, 6, 0); event_callback = callback_expire;
        sendall_raises(&s, MP_ETIMEDOUT);
        CHECK(tcp_writes == 1 && written_bytes == 2 && now == 3000);
        CHECK(callback_calls == 1 && events == 1 && !delays);
    } else if (!strcmp(mode, "empty")) {
        sendall_buffer.len = 0; sendall_ok(&s);
        CHECK(!tcp_writes && !events && !delays && buffer_requests == 1);
    } else if (!strcmp(mode, "zero-progress")) {
        write_step(0, 0, 0); sendall_raises(&s, MP_EPIPE);
        CHECK(tcp_writes == 1 && !written_bytes && !events && !delays);
    } else if (!strncmp(mode, "nonblocking-", 12)) {
        s.timeout = 0;
        if (!strcmp(mode + 12, "success")) {
            write_step(0, 8, 0); sendall_ok(&s); CHECK(written_bytes == 8);
        } else if (!strcmp(mode + 12, "partial")) {
            write_step(0, 2, 0); sendall_raises(&s, MP_EAGAIN); CHECK(written_bytes == 2);
        } else {
            CHECK(!strcmp(mode + 12, "eagain"));
            write_step(MP_EAGAIN, 0, 0); sendall_raises(&s, MP_EAGAIN);
            CHECK(!written_bytes);
        }
        CHECK(tcp_writes == 1 && !events && !delays && !s.timeout);
    } else if (!strcmp(mode, "infinite")) {
        s.timeout = -1;
        write_step(0, 2, 8000000); write_step(MP_EAGAIN, 0, 1000000);
        write_step(0, 6, 8000000); sendall_ok(&s);
        CHECK(tcp_writes == 3 && written_bytes == 8 && now == 17001000);
        CHECK(events == 2 && delays == 1 && s.timeout == -1);
    } else if (!strcmp(mode, "event-close")) {
        write_step(0, 2, 1000); write_step(0, 6, 0); close_on_event = &s;
        sendall_raises(&s, MP_EBADF);
        CHECK(tcp_writes == 1 && written_bytes == 2 && events == 1 && !delays);
        CHECK(tcp_closes == 1 && !tcp_live && !s._private && s.timeout == 3);
        nic->close(&s); CHECK(tcp_closes == 1); return;
    } else if (!strcmp(mode, "interrupt")) {
        write_step(0, 2, 1000); interrupt_event = true;
        sendall_raises(&s, 123);
        CHECK(tcp_writes == 1 && written_bytes == 2 && events == 1 && !delays);
        CHECK(tcp_live && !tcp_closes && !tcp_cancels);
        interrupt_event = false; sendall_buffer.len = 0; sendall_ok(&s);
    } else if (!strcmp(mode, "reentry")) {
        write_step(0, 2, 1000); write_step(0, 1, 1000);
        write_step(0, 2, 1000); write_step(0, 4, 0);
        event_callback = callback_reenter; sendall_raises(&s, MP_ETIMEDOUT);
        CHECK(tcp_writes == 3 && written_bytes == 5 && now == 3000);
        CHECK(write_offsets[0] == 0 && write_offsets[1] == 0 && write_offsets[2] == 2);
        CHECK(write_lengths[0] == 8 && write_lengths[1] == 1 && write_lengths[2] == 6);
        CHECK(callback_calls == 1 && buffer_requests == 2 && !delays);
    } else if (!strncmp(mode, "settimeout-", 11)) {
        if (!strcmp(mode + 11, "longer")) callback_new_timeout = 100;
        else if (!strcmp(mode + 11, "infinite")) callback_new_timeout = -1;
        else { CHECK(!strcmp(mode + 11, "nonblocking")); callback_new_timeout = 0; }
        write_step(0, 2, 1000); write_step(MP_EAGAIN, 0, 0);
        write_step(MP_EAGAIN, 0, 0); write_step(0, 6, 0);
        event_callback = callback_settimeout; sendall_raises(&s, MP_ETIMEDOUT);
        CHECK(tcp_writes == 3 && written_bytes == 2 && now == 3000);
        CHECK(callback_calls == 1 && events == 3 && delays == 2);
        CHECK(s.timeout == callback_new_timeout);
        nic->close(&s); CHECK(tcp_closes == 1); return;
    } else CHECK(!"unknown sendall scenario");
    if (strcmp(mode, "backpressure-success") && strcmp(mode, "infinite") && strncmp(mode, "nonblocking-", 12))
        CHECK(s.timeout == 3);
    CHECK(tcp_live && !tcp_closes && !tcp_cancels);
    nic->close(&s); nic->close(&s); CHECK(tcp_closes == 1 && !tcp_live);
}
static void test_sendall_pending(const char *mode) {
    static mod_network_socket_obj_t s;
    s = tcp_new(0); ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    s.timeout = 3;
    if (!strcmp(mode, "interrupt")) interrupt_event = true;
    else CHECK(!strcmp(mode, "timeout"));
    sendall_raises(&s, interrupt_event ? 123 : MP_ETIMEDOUT);
    CHECK(!tcp_writes && !tcp_job && !tcp_live && tcp_cancels == 1 && s.timeout == 3);
    if (!interrupt_event) CHECK(now == 3000 && events == 3 && delays == 3);
    else CHECK(events == 1 && !delays);
    nic->close(&s); CHECK(tcp_cancels == 1);
}
static void test_sendall_udp(const char *mode) {
    mod_network_socket_obj_t s = socket_new();
    if (!strcmp(mode, "unconnected")) {
        sendall_raises(&s, MP_ENOTCONN); CHECK(!connected_sends && !opens);
    } else {
        CHECK(nic->connect(&s, peer, 9000, &error) == 0); s.timeout = 3;
        if (!strcmp(mode, "empty")) {
            sendall_buffer.len = 0; sendall_ok(&s); CHECK(!connected_sends);
        } else {
            CHECK(!strcmp(mode, "retry")); send_error = MP_EAGAIN; success_after_delay = true;
            sendall_ok(&s); CHECK(connected_sends == 2 && sent_length == 8);
            CHECK(events == 1 && delays == 1 && now == 1000);
        }
        CHECK(s.timeout == 3);
    }
    nic->close(&s);
    sendall_raises(&s, MP_EBADF); CHECK(!s._private);
}
static void test_tcp(const char *mode) {
    // Static storage keeps socket state defined across the interrupt longjmp.
    static mod_network_socket_obj_t s;
    s = tcp_new(0);
    ERR(nic->bind(&s, wildcard, 65536, &error), MP_EINVAL);
    UERR(send_one(&s), MP_EOPNOTSUPP); UERR(recv_one(&s), MP_EOPNOTSUPP);
    UERR(nic->send(&s, buffer, 3, &error), MP_ENOTCONN);
    if (!strcmp(mode, "blocking")) {
        s.timeout = 20; tcp_ready_after_delay = true;
        CHECK(nic->connect(&s, peer, 9000, &error) == 0);
        CHECK(events && delays && s.state == MOD_NETWORK_SS_CONNECTED);
    } else if (!strcmp(mode, "timeout")) {
        s.timeout = 1; tcp_ready_after_delay = true;
        ERR(nic->connect(&s, peer, 9000, &error), MP_ETIMEDOUT);
        CHECK(now == 1000 && tcp_cancels == 1 && !tcp_job);
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, 0, &error) == MP_STREAM_POLL_ERR);
        UERR(nic->recv(&s, buffer, 3, &error), MP_ETIMEDOUT);
        nic->close(&s); return;
    } else if (!strcmp(mode, "interrupt")) {
        s.timeout = -1; interrupt_event = true;
        nlr_buf_t outer;
        if (nlr_push(&outer) == 0) {
            nic->connect(&s, peer, 9000, &error); nlr_pop(); CHECK(false);
        } else CHECK(outer.ret_val == (void *)123);
        CHECK(tcp_cancels == 1 && !tcp_job); nic->close(&s); return;
    } else if (!strcmp(mode, "event-close")) {
        s.timeout = -1; close_on_event = &s;
        ERR(nic->connect(&s, peer, 9000, &error), MP_EBADF);
        CHECK(!s._private && tcp_cancels == 1); return;
    } else {
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        ERR(nic->connect(&s, peer, 9000, &error), MP_EALREADY);
        CHECK(tcp_starts == 1 && !events);
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_WR, &error) == 0);
        UERR(nic->send(&s, buffer, 3, &error), MP_EAGAIN);
        if (!strcmp(mode, "close")) {
            nic->close(&s); nic->close(&s); CHECK(tcp_cancels == 1); return;
        }
        if (!strcmp(mode, "failure")) {
            tcp_error = MP_ECONNREFUSED;
            CHECK(nic->ioctl(&s, MP_STREAM_POLL, 0, &error) == MP_STREAM_POLL_ERR);
            UERR(nic->send(&s, buffer, 3, &error), MP_ECONNREFUSED);
            CHECK(tcp_cancels == 1 && !tcp_job); nic->close(&s); return;
        }
        if (!strcmp(mode, "pending-io-timeout")) {
            s.timeout = 2;
            UERR(nic->recv(&s, buffer, 3, &error), MP_ETIMEDOUT);
            CHECK(tcp_cancels == 1 && !tcp_job && now == 2000);
            nic->close(&s); return;
        }
        if (!strcmp(mode, "pending-io-close")) {
            s.timeout = -1; close_on_event = &s;
            UERR(nic->send(&s, buffer, 3, &error), MP_EBADF);
            CHECK(tcp_cancels == 1 && !s._private); return;
        }
        tcp_ready = true;
        if (!strcmp(mode, "send-promote")) CHECK(nic->send(&s, buffer, 3, &error) == 2);
        else if (!strcmp(mode, "recv-promote")) CHECK(nic->recv(&s, buffer, 3, &error) == 3);
        else CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_WR, &error) == MP_STREAM_POLL_WR);
    }
    CHECK(s.state == MOD_NETWORK_SS_CONNECTED);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EISCONN);
    CHECK(nic->send(&s, buffer, 3, &error) == 2);
    CHECK(nic->recv(&s, buffer, 3, &error) == 3);
    tcp_read_count = 0; CHECK(nic->recv(&s, buffer, 3, &error) == 0);
    s.timeout = 0; tcp_read_error = tcp_write_error = MP_EAGAIN;
    UERR(nic->send(&s, buffer, 3, &error), MP_EAGAIN);
    UERR(nic->recv(&s, buffer, 3, &error), MP_EAGAIN);
    s.timeout = 2; delays = 0; now = 0;
    UERR(nic->recv(&s, buffer, 3, &error), MP_ETIMEDOUT);
    CHECK(tcp_live && tcp_cancels == 0 && now == 2000);
    delays = 0; success_after_delay = true;
    CHECK(nic->send(&s, buffer, 3, &error) == 2);
    nic->close(&s); nic->close(&s); CHECK(tcp_closes == 1 && !tcp_live && !tcp_job);
}
static void reservation_conflict(mod_network_socket_obj_t *other, uint16_t port) {
    unsigned starts = tcp_starts, passive = listener_opens, udp = opens;
    unsigned vm_events = events, vm_delays = delays, allocs = allocation_count;
    ERR(nic->bind(other, wildcard, port, &error), MP_EADDRINUSE);
    CHECK(!other->bound && state(other)->phase == TCP_IDLE);
    CHECK(!state(other)->bind_reservation && !state(other)->local_port);
    CHECK(tcp_starts == starts && listener_opens == passive && opens == udp);
    CHECK(events == vm_events && delays == vm_delays && allocation_count == allocs);
}
static void test_tcp_reservation(const char *mode) {
    mod_network_socket_obj_t owner = tcp_new(0), other = tcp_new(0);
    if (!strcmp(mode, "native")) {
        native_occupied_port = 4321;
        reservation_conflict(&owner, 4321);
        CHECK(!tcp_starts && !listener_opens && !opens);
        native_occupied_port = 0;
    }
    if (!strcmp(mode, "query-error")) {
        tcp_port_query_error = MP_EBUSY;
        ERR(nic->bind(&owner, wildcard, 4321, &error), MP_EBUSY);
        CHECK(!owner.bound && state(&owner)->phase == TCP_IDLE);
        CHECK(!state(&owner)->bind_reservation && !state(&owner)->local_port);
        tcp_port_query_error = 0;
    }
    if (!strcmp(mode, "ephemeral")) {
        tcp_port_query_error = MP_EBUSY; native_occupied_port = 4321;
        CHECK(nic->bind(&owner, wildcard, 0, &error) == 0);
        CHECK(nic->bind(&other, wildcard, 0, &error) == 0);
        CHECK(!tcp_port_queries && !state(&owner)->bind_reservation && !state(&other)->bind_reservation);
        ERR(nic->connect(&owner, peer, 9000, &error), MP_EINPROGRESS);
        CHECK(tcp_start_local_port == 0);
        CHECK(nic->listen(&other, 1, &error) == 0 && listener_requested_port == 0);
        CHECK(state(&other)->local_port == 60001 && !state(&other)->bind_reservation);
        nic->close(&owner); nic->close(&other); return;
    }
    if (!strcmp(mode, "capacity")) {
        mod_network_socket_obj_t sockets[TCP_BIND_SLOTS];
        for (unsigned i = 0; i < TCP_BIND_SLOTS; ++i) {
            sockets[i] = tcp_new(0);
            CHECK(nic->bind(&sockets[i], wildcard, 10000 + i, &error) == 0);
        }
        ERR(nic->bind(&owner, wildcard, 4321, &error), MP_EMFILE);
        CHECK(!owner.bound && !state(&owner)->bind_reservation);
        reservation_conflict(&owner, 10000); // Conflict wins over table exhaustion.
        CHECK(nic->bind(&other, wildcard, 0, &error) == 0);
        nic->close(&sockets[0]);
        CHECK(nic->bind(&owner, wildcard, 4321, &error) == 0);
        for (unsigned i = 1; i < TCP_BIND_SLOTS; ++i) nic->close(&sockets[i]);
        nic->close(&owner); nic->close(&other); return;
    }
    CHECK(nic->bind(&owner, wildcard, 4321, &error) == 0);
    CHECK(owner.bound && state(&owner)->bind_reservation);
    CHECK(!tcp_starts && !listener_opens && !opens && !events && !delays);
    unsigned query_count = tcp_port_queries;
    ERR(nic->bind(&owner, wildcard, 4321, &error), MP_EINVAL);
    CHECK(tcp_port_queries == query_count);
    reservation_conflict(&other, 4321);
    if (!strcmp(mode, "udp")) {
        mod_network_socket_obj_t datagram = socket_new();
        CHECK(nic->bind(&datagram, wildcard, 4321, &error) == 0);
        CHECK(!state(&datagram)->bind_reservation && bound_port == 4321);
        nic->close(&datagram);
        reservation_conflict(&other, 4321);
    } else if (!strcmp(mode, "connect") || !strcmp(mode, "finish-failure") ||
               !strcmp(mode, "timeout") || !strcmp(mode, "pending")) {
        ERR(nic->connect(&owner, peer, 9000, &error), MP_EINPROGRESS);
        CHECK(state(&owner)->phase == TCP_PENDING && tcp_start_local_port == 4321);
        reservation_conflict(&other, 4321);
        if (!strcmp(mode, "finish-failure")) {
            tcp_error = MP_ECONNREFUSED;
            peer_raises(&owner, MP_ECONNREFUSED);
            CHECK(state(&owner)->phase == TCP_FAILED && tcp_cancels == 1);
        } else if (!strcmp(mode, "timeout")) {
            owner.timeout = 1;
            UERR(nic->recv(&owner, buffer, 3, &error), MP_ETIMEDOUT);
            CHECK(state(&owner)->phase == TCP_FAILED && tcp_cancels == 1);
        } else if (!strcmp(mode, "connect")) {
            tcp_ready = true; peer_is(&owner, "192.0.2.1", 9000);
            CHECK(state(&owner)->phase == TCP_CONNECTED);
        }
        reservation_conflict(&other, 4321);
    } else if (!strcmp(mode, "start-error")) {
        tcp_start_error = MP_ENETDOWN;
        ERR(nic->connect(&owner, peer, 9000, &error), MP_ENETDOWN);
        CHECK(state(&owner)->phase == TCP_BOUND && !tcp_job);
        reservation_conflict(&other, 4321);
        tcp_start_error = 0;
        CHECK(nic->listen(&owner, 1, &error) == 0);
        reservation_conflict(&other, 4321);
    } else if (!strcmp(mode, "listen") || !strcmp(mode, "listen-error") ||
               !strcmp(mode, "listen-query-error") || !strcmp(mode, "accept")) {
        if (!strcmp(mode, "listen-error")) {
            listener_open_error = MP_ENOMEM;
            ERR(nic->listen(&owner, 1, &error), MP_ENOMEM);
            CHECK(state(&owner)->phase == TCP_BOUND && !listener_live);
            reservation_conflict(&other, 4321);
            listener_open_error = 0;
        } else if (!strcmp(mode, "listen-query-error")) {
            listener_local_error = MP_EBUSY;
            ERR(nic->listen(&owner, 1, &error), MP_EBUSY);
            CHECK(state(&owner)->phase == TCP_BOUND && !listener_live && listener_closes == 1);
            reservation_conflict(&other, 4321);
            listener_local_error = 0;
        }
        CHECK(nic->listen(&owner, 1, &error) == 0);
        reservation_conflict(&other, 4321);
        if (!strcmp(mode, "accept")) {
            mod_network_socket_obj_t child = {.type=MOD_NETWORK_SOCK_STREAM};
            byte ip[4]; mp_uint_t port;
            listener_ready = true;
            CHECK(nic->accept(&owner, &child, ip, &port, &error) == 0);
            CHECK(!state(&child)->bind_reservation);
            nic->close(&child);
            reservation_conflict(&other, 4321); // Child close must not release parent.
            listener_ready = true;
            CHECK(nic->accept(&owner, &child, ip, &port, &error) == 0);
            nic->close(&owner);
            CHECK(nic->bind(&other, wildcard, 4321, &error) == 0);
            nic->close(&child); // Nor release a later owner's reservation.
            mod_network_socket_obj_t probe = tcp_new(0);
            reservation_conflict(&probe, 4321);
            nic->close(&probe); nic->close(&other); return;
        }
    } else if (!strcmp(mode, "deinit")) {
        uint32_t old_token = state(&owner)->bind_reservation;
        nic->deinit();
        for (unsigned i = 0; i < TCP_BIND_SLOTS; ++i) CHECK(!tcp_bind_slots[i].port);
        CHECK(nic->bind(&other, wildcard, 4321, &error) == 0);
        CHECK(state(&other)->bind_reservation != old_token);
        nic->close(&owner); // A stale pre-reset close cannot steal the new owner.
        mod_network_socket_obj_t probe = tcp_new(0);
        reservation_conflict(&probe, 4321);
        nic->deinit();
        CHECK(nic->bind(&probe, wildcard, 4321, &error) == 0);
        nic->close(&other); nic->close(&probe); return;
    } else CHECK(!strcmp(mode, "bind") || !strcmp(mode, "native") || !strcmp(mode, "query-error"));
    nic->close(&owner);
    CHECK(nic->bind(&other, wildcard, 4321, &error) == 0);
    nic->close(&owner); // Idempotent close cannot release other owner's slot.
    mod_network_socket_obj_t probe = tcp_new(0);
    reservation_conflict(&probe, 4321);
    nic->close(&other);
    CHECK(nic->bind(&probe, wildcard, 4321, &error) == 0);
    nic->close(&probe);
}
static void test_tcp_bound(const char *mode) {
    static mod_network_socket_obj_t s;
    bool explicit_bind = !strncmp(mode, "explicit-", 9);
    bool ephemeral_bind = !strncmp(mode, "ephemeral-", 10);
    CHECK(explicit_bind || ephemeral_bind);
    const char *case_name = mode + (explicit_bind ? 9 : 10);
    s = tcp_new(0);
    mp_uint_t local_port = explicit_bind ? 4321 : 0;
    CHECK(nic->bind(&s, wildcard, local_port, &error) == 0);
    CHECK(s.bound && state(&s)->phase == TCP_BOUND && state(&s)->local_port == local_port);
    CHECK(tcp_start_local_port == 0 && !tcp_starts && !tcp_finishes && !tcp_job && !tcp_live);

    if (!strcmp(case_name, "start-error")) {
        tcp_start_error = MP_ENETDOWN;
        ERR(nic->connect(&s, peer, 9000, &error), MP_ENETDOWN);
        CHECK(s.bound && s.state == MOD_NETWORK_SS_NEW);
        CHECK(state(&s)->phase == TCP_BOUND && state(&s)->local_port == local_port);
        CHECK(!memcmp(state(&s)->peer_ip, wildcard, 4) && !state(&s)->peer_port);
        CHECK(tcp_starts == 1 && tcp_start_local_port == local_port);
        CHECK(!tcp_job && !tcp_live && !tcp_finishes && !tcp_cancels);
        tcp_start_error = 0; tcp_ready = true;
        CHECK(nic->listen(&s, 1, &error) == 0);
        CHECK(s.state == MOD_NETWORK_SS_LISTENING && state(&s)->phase == TCP_LISTENING);
        nic->close(&s); CHECK(listener_closes == 1 && !listener_live);

        mod_network_socket_obj_t retry = tcp_new(20);
        CHECK(nic->bind(&retry, wildcard, local_port, &error) == 0);
        int retry_result = nic->connect(&retry, peer, 9000, &error);
        CHECK(retry_result == 0);
        CHECK(tcp_start_local_port == local_port && state(&retry)->phase == TCP_CONNECTED);
        nic->close(&retry); return;
    }
    if (!strcmp(case_name, "timeout")) {
        s.timeout = 1; tcp_ready_after_delay = true;
        ERR(nic->connect(&s, peer, 9000, &error), MP_ETIMEDOUT);
        CHECK(s.bound && state(&s)->phase == TCP_FAILED && state(&s)->local_port == local_port);
        CHECK(tcp_start_local_port == local_port && tcp_cancels == 1 && !tcp_job && !tcp_live);
        CHECK(!memcmp(state(&s)->peer_ip, peer, 4) && state(&s)->peer_port == 9000);
        peer_raises(&s, MP_ETIMEDOUT);
        nic->close(&s); return;
    }
    if (!strcmp(case_name, "interrupt")) {
        s.timeout = -1; interrupt_event = true;
        nlr_buf_t outer;
        if (nlr_push(&outer) == 0) {
            nic->connect(&s, peer, 9000, &error); nlr_pop(); CHECK(false);
        } else CHECK(outer.ret_val == (void *)123);
        interrupt_event = false;
        CHECK(s.bound && state(&s)->phase == TCP_FAILED && state(&s)->local_port == local_port);
        CHECK(tcp_cancels == 1 && !tcp_job && !tcp_live);
        nic->close(&s); return;
    }
    if (!strcmp(case_name, "close")) {
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        CHECK(s.bound && state(&s)->phase == TCP_PENDING && tcp_start_local_port == local_port);
        nic->close(&s); nic->close(&s);
        CHECK(s.bound && !s._private && tcp_cancels == 1 && !tcp_job && !tcp_live);
        return;
    }
    if (!strcmp(case_name, "pending-io-timeout")) {
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        s.timeout = 2;
        UERR(nic->recv(&s, buffer, 3, &error), MP_ETIMEDOUT);
        CHECK(s.bound && tcp_cancels == 1 && !tcp_job && !tcp_live && now == 2000);
        CHECK(state(&s)->phase == TCP_FAILED && state(&s)->local_port == local_port);
        nic->close(&s); return;
    }
    if (!strcmp(case_name, "pending-io-close")) {
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        s.timeout = -1; close_on_event = &s;
        UERR(nic->recv(&s, buffer, 3, &error), MP_EBADF);
        CHECK(tcp_cancels == 1 && !s._private && !tcp_job && !tcp_live);
        nic->close(&s); return;
    }

    bool blocking = !strcmp(case_name, "blocking");
    CHECK(!blocking ? !strcmp(case_name, "nonblocking") : true);
    if (blocking) {
        s.timeout = 20; tcp_ready_after_delay = true;
        CHECK(nic->connect(&s, peer, 9000, &error) == 0);
        CHECK(events == 1 && delays == 1);
    } else {
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        CHECK(s.bound && state(&s)->phase == TCP_PENDING && state(&s)->local_port == local_port);
        local_raises(&s, MP_ENOTCONN);
        peer_raises(&s, MP_ENOTCONN);
        CHECK(tcp_start_local_port == local_port && tcp_finishes == 2 && tcp_job);
        tcp_ready = true;
    }
    CHECK(tcp_start_local_port == local_port && s.bound);
    CHECK(state(&s)->peer_port == 9000 && !memcmp(state(&s)->peer_ip, peer, 4));
    local_is(&s, "198.51.100.7", explicit_bind ? 4321 : 49153);
    peer_is(&s, "192.0.2.1", 9000);
    CHECK(state(&s)->phase == TCP_CONNECTED && s.state == MOD_NETWORK_SS_CONNECTED);
    CHECK(!tcp_job && tcp_live);
    local_is(&s, "198.51.100.7", explicit_bind ? 4321 : 49153);
    nic->close(&s); nic->close(&s);
    CHECK(s.bound && !s._private && !tcp_job && !tcp_live && tcp_closes == 1);
}
static void test_listener_idle(const char *mode) {
    mod_network_socket_obj_t s = tcp_new(0);
    mod_network_socket_obj_t child = {.type = MOD_NETWORK_SOCK_STREAM};
    byte ip[4] = {0}; mp_uint_t port = 123;
    CHECK(!s.bound && state(&s)->phase == TCP_IDLE && !state(&s)->local_port);
    CHECK(!state(&s)->bind_reservation && state(&s)->nodelay && !state(&s)->nodelay_configured);
    void *private_state = s._private;
    unsigned allocs = allocation_count;
    local_is(&s, "0.0.0.0", 0);
    CHECK(!listener_opens && !listener_local_queries);

    bool open_fail = !strcmp(mode, "open-error") || !strcmp(mode, "open-close");
    bool query_fail = !strcmp(mode, "query-error") || !strcmp(mode, "query-close") || !strcmp(mode, "query-bind");
    if (open_fail || query_fail) {
        if (open_fail) listener_open_error = MP_ENOMEM;
        else listener_local_error = MP_EIO;
        ERR(nic->listen(&s, 2, &error), open_fail ? MP_ENOMEM : MP_EIO);
        CHECK(listener_opens == 1 && listener_requested_port == 0 && listener_backlog == 2);
        CHECK(listener_local_queries == (open_fail ? 0u : 1u));
        CHECK(listener_closes == (open_fail ? 0u : 1u) && !listener_live);
        CHECK(s._private == private_state && allocation_count == allocs);
        CHECK(!s.bound && s.state == MOD_NETWORK_SS_NEW);
        CHECK(state(&s)->phase == TCP_IDLE && !state(&s)->local_port && !state(&s)->bind_reservation);
        CHECK(!events && !delays && !opens && !tcp_starts && !tcp_port_queries);
        local_is(&s, "0.0.0.0", 0);
        ERR(nic->accept(&s, &child, ip, &port, &error), MP_EINVAL);
        CHECK(!child._private && !listener_accepts && port == 123);
        if (!strcmp(mode, "open-close") || !strcmp(mode, "query-close")) {
            nic->close(&s); nic->close(&s);
            CHECK(listener_closes == (open_fail ? 0u : 1u) && !s._private);
            ERR(nic->listen(&s, 2, &error), MP_EBADF);
            CHECK(listener_opens == 1); return;
        }
        listener_open_error = listener_local_error = 0;
        if (!strcmp(mode, "query-bind")) {
            CHECK(nic->bind(&s, wildcard, 4321, &error) == 0);
            CHECK(s.bound && state(&s)->phase == TCP_BOUND && state(&s)->local_port == 4321);
        }
    }
    bool configured = !strcmp(mode, "nodelay0") || !strcmp(mode, "nodelay1");
    if (configured) {
        mp_int_t enabled = !strcmp(mode, "nodelay1");
        CHECK(nic->setsockopt(&s, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY,
            &enabled, sizeof(enabled), &error) == 0);
        CHECK(state(&s)->nodelay == (bool)enabled && state(&s)->nodelay_configured && !nodelay_calls);
    }
    mp_int_t backlog = 2;
    if (!strncmp(mode, "backlog-", 8)) backlog = (mp_int_t)strtol(mode + 8, NULL, 10);
    unsigned before_opens = listener_opens, before_queries = listener_local_queries;
    unsigned before_closes = listener_closes;
    CHECK(nic->listen(&s, backlog, &error) == 0);
    CHECK(listener_opens == before_opens + 1 && listener_local_queries == before_queries + 1);
    CHECK(listener_backlog == (unsigned)(backlog <= 0 ? 1 : backlog > 4 ? 4 : backlog));
    uint16_t assigned = !strcmp(mode, "query-bind") ? 4321 : 60001;
    CHECK(listener_requested_port == (!strcmp(mode, "query-bind") ? 4321 : 0));
    CHECK(state(&s)->local_port == assigned && s.bound && listener_live);
    CHECK(state(&s)->phase == TCP_LISTENING && s.state == MOD_NETWORK_SS_LISTENING);
    CHECK(s._private == private_state && allocation_count == allocs && !events && !delays);
    CHECK(state(&s)->nodelay_configured == configured && !nodelay_calls);
    snapshot_error = -3;
    local_is(&s, "0.0.0.0", assigned);
    listener_local_port = assigned + 1; listener_local_error = MP_EBUSY;
    local_is(&s, "0.0.0.0", assigned);
    CHECK(listener_local_queries == before_queries + 1 && !network_snapshots);
    ERR(nic->listen(&s, 2, &error), MP_EINVAL);
    CHECK(listener_opens == before_opens + 1);

    snapshot_error = 0; listener_ready = true; stream_local_port = assigned;
    CHECK(nic->accept(&s, &child, ip, &port, &error) == 0);
    CHECK(state(&child)->phase == TCP_CONNECTED && child.state == MOD_NETWORK_SS_CONNECTED);
    CHECK(state(&child)->nodelay == state(&s)->nodelay);
    CHECK(state(&child)->nodelay_configured == configured && !state(&child)->bind_reservation);
    CHECK(nodelay_calls == (configured ? 1u : 0u));
    if (configured) CHECK(nodelay_value == state(&s)->nodelay);
    CHECK(child.timeout == -1 && port == accepted_port && !memcmp(ip, peer, sizeof(ip)));
    local_is(&child, "198.51.100.7", assigned);
    stream_local_port = assigned + 2;
    local_is(&child, "198.51.100.7", assigned + 2);
    CHECK(stream_local_queries == 2 && !tcp_finishes && !events && !delays);
    nic->close(&s); nic->close(&s);
    CHECK(listener_closes == before_closes + 1 && !listener_live && tcp_live);
    CHECK(nic->send(&child, buffer, 3, &error) == 2);
    nic->close(&child); nic->close(&child);
    CHECK(tcp_closes == 1 && !tcp_live && !s._private && !child._private);
}
static void test_listener_invalid_phase(const char *mode) {
    mod_network_socket_obj_t s = tcp_new(0);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    if (!strcmp(mode, "connected")) {
        tcp_ready = true;
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_WR, &error) == MP_STREAM_POLL_WR);
        CHECK(state(&s)->phase == TCP_CONNECTED && tcp_live);
    } else if (!strcmp(mode, "failed")) {
        tcp_error = MP_ECONNREFUSED;
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, 0, &error) == MP_STREAM_POLL_ERR);
        CHECK(state(&s)->phase == TCP_FAILED && !tcp_job);
    } else CHECK(!strcmp(mode, "pending") && state(&s)->phase == TCP_PENDING && tcp_job);
    udp_state_t before = *state(&s);
    unsigned starts = tcp_starts, finishes = tcp_finishes, cancels = tcp_cancels;
    unsigned queries = stream_local_queries, allocs = allocation_count;
    int old_state = s.state; bool old_bound = s.bound;
    ERR(nic->listen(&s, 2, &error), MP_EINVAL);
    CHECK(!memcmp(state(&s), &before, sizeof(before)) && s.state == old_state && s.bound == old_bound);
    CHECK(!listener_opens && !listener_local_queries && !listener_closes && !events && !delays);
    CHECK(tcp_starts == starts && tcp_finishes == finishes && tcp_cancels == cancels);
    CHECK(stream_local_queries == queries && allocation_count == allocs);
    nic->close(&s); nic->close(&s);
    CHECK(!tcp_job && !tcp_live && !s._private);
}
static void test_listener(const char *mode) {
    static mod_network_socket_obj_t s, child;
    s = tcp_new(0);
    child = (mod_network_socket_obj_t){.type=MOD_NETWORK_SOCK_STREAM, .timeout=777};
    byte ip[4] = {0}; peer_port = 123;
    // Idle listen succeeds in its own scenarios; keep this socket for explicit bind.
    ERR(nic->accept(&s, &child, ip, &peer_port, &error), MP_EINVAL);
    CHECK(!child._private);
    ERR(nic->bind(&s, wildcard, (mp_uint_t)-1, &error), MP_EINVAL);
    ERR(nic->bind(&s, wildcard, 65536, &error), MP_EINVAL);
    ERR(nic->bind(&s, peer, 9000, &error), MP_EINVAL);
    CHECK(nic->bind(&s, wildcard, 9000, &error) == 0);
    CHECK(s.bound && state(&s)->local_port == 9000 && state(&s)->phase == TCP_BOUND);
    CHECK(!opens && !listener_opens && !tcp_starts);
    ERR(nic->bind(&s, wildcard, 9000, &error), MP_EINVAL);
    CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_RD, &error) == 0);
    listener_open_error = MP_ENOMEM;
    ERR(nic->listen(&s, 0, &error), MP_ENOMEM);
    CHECK(state(&s)->phase == TCP_BOUND && !listener_live);
    listener_open_error = 0;
    CHECK(nic->listen(&s, !strcmp(mode, "max-backlog") ? 99 : 0, &error) == 0);
    CHECK(listener_backlog == (!strcmp(mode, "max-backlog") ? 4u : 1u));
    CHECK(listener_requested_port == 9000 && listener_local_queries == 1);
    CHECK(state(&s)->local_port == 9000 && listener_closes == 0);
    CHECK(s.state == MOD_NETWORK_SS_LISTENING && state(&s)->phase == TCP_LISTENING);
    unsigned before = listener_opens;
    ERR(nic->listen(&s, 2, &error), MP_EINVAL); CHECK(listener_opens == before);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EOPNOTSUPP);
    UERR(send_one(&s), MP_EOPNOTSUPP); UERR(recv_one(&s), MP_EOPNOTSUPP);
    UERR(nic->send(&s, buffer, 3, &error), MP_ENOTCONN);
    if (!strcmp(mode, "poll")) {
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_RD | MP_STREAM_POLL_WR, &error) == 0);
        listener_ready = true;
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_RD | MP_STREAM_POLL_WR, &error) == MP_STREAM_POLL_RD);
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_WR, &error) == 0);
        listener_poll_error = MP_ENOMEM;
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, 0, &error) == MP_STREAM_POLL_ERR);
        CHECK(!events); nic->close(&s);
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_RD, &error) == MP_STREAM_POLL_NVAL);
        return;
    }
    if (!strcmp(mode, "deinit")) {
        nic->deinit(); CHECK(listener_deinits == 1 && !listener_live); return;
    }
    if (!strcmp(mode, "eagain") || !strcmp(mode, "error")) {
        peer_port = 123;
        if (!strcmp(mode, "error")) listener_accept_error = MP_ENOMEM;
        unsigned before_free = freed;
        ERR(nic->accept(&s, &child, ip, &peer_port, &error), listener_accept_error ? MP_ENOMEM : MP_EAGAIN);
        CHECK(!child._private && freed == before_free + 1 && !tcp_live);
        CHECK(peer_port == 123 && listener_accepts == 1 && !events);
        listener_accept_error = 0; listener_ready = true;
    } else if (!strcmp(mode, "timeout") || !strcmp(mode, "deadline")) {
        s.timeout = !strcmp(mode, "deadline") ? 1 : 3;
        listener_after_delay = !strcmp(mode, "deadline");
        ERR(nic->accept(&s, &child, ip, &peer_port, &error), MP_ETIMEDOUT);
        CHECK(!child._private && freed == 1 && !tcp_live && listener_live);
        CHECK(now == (uint64_t)s.timeout * 1000);
        if (listener_after_delay) CHECK(listener_accepts == 1);
        nic->close(&s); return;
    } else if (!strcmp(mode, "event-close")) {
        s.timeout = -1; close_on_event = &s;
        ERR(nic->accept(&s, &child, ip, &peer_port, &error), MP_EBADF);
        CHECK(!child._private && !s._private && !tcp_live && !listener_live && freed == 1);
        CHECK(listener_accepts == 1 && listener_closes == 1); return;
    } else if (!strcmp(mode, "interrupt")) {
        s.timeout = -1; interrupt_event = true;
        nlr_buf_t outer;
        if (nlr_push(&outer) == 0) {
            nic->accept(&s, &child, ip, &peer_port, &error); nlr_pop(); CHECK(false);
        } else CHECK(outer.ret_val == (void *)123);
        CHECK(!child._private && freed == 1 && !tcp_live && listener_live);
        nic->close(&s); return;
    } else if (!strcmp(mode, "retry")) {
        s.timeout = 20; listener_after_delay = true;
    } else listener_ready = true;
    CHECK(nic->accept(&s, &child, ip, &peer_port, &error) == 0);
    CHECK(tcp_live && listener_live && child._private);
    CHECK(state(&child)->kind == MOD_NETWORK_SOCK_STREAM && state(&child)->phase == TCP_CONNECTED);
    CHECK(state(&child)->stream_token == 81 && child.state == MOD_NETWORK_SS_CONNECTED && child.timeout == -1);
    CHECK(peer_port == 9000 && !memcmp(ip, peer, 4));
    CHECK(nic->send(&child, buffer, 3, &error) == 2);
    CHECK(nic->recv(&child, buffer, 3, &error) == 3);
    if (!strcmp(mode, "child-close")) {
        nic->close(&child); CHECK(!tcp_live && listener_live && listener_closes == 0);
        nic->close(&s);
    } else {
        nic->close(&s); CHECK(tcp_live && !listener_live && tcp_closes == 0);
        CHECK(nic->send(&child, buffer, 3, &error) == 2); nic->close(&child);
    }
    nic->close(&s); nic->close(&child);
    CHECK(listener_closes == 1 && tcp_closes == 1 && !tcp_live && !listener_live);
}
static void test_listener_ephemeral(const char *mode) {
    mod_network_socket_obj_t s = tcp_new(0);
    mod_network_socket_obj_t child = {.type = MOD_NETWORK_SOCK_STREAM};
    byte ip[4] = {0}; mp_uint_t port = 123;
    CHECK(nic->bind(&s, wildcard, 0, &error) == 0);
    CHECK(s.bound && s.state == MOD_NETWORK_SS_NEW);
    CHECK(state(&s)->phase == TCP_BOUND && state(&s)->local_port == 0);
    snapshot_error = -3; // Wildcard local names need neither a snapshot nor a native query.
    local_is(&s, "0.0.0.0", 0);
    peer_raises(&s, MP_ENOTCONN);
    CHECK(!listener_opens && !listener_local_queries && !stream_local_queries);
    CHECK(!opens && !tcp_starts && !network_snapshots);
    ERR(nic->bind(&s, wildcard, 9000, &error), MP_EINVAL);

    if (strcmp(mode, "success")) {
        bool open_irq = !strcmp(mode, "open-irq");
        int expected = !strcmp(mode, "query-error") ? MP_EIO : MP_EBUSY;
        if (open_irq) listener_open_error = expected;
        else listener_local_error = expected;
        ERR(nic->listen(&s, 2, &error), expected);
        CHECK(listener_opens == 1 && listener_requested_port == 0 && listener_backlog == 2);
        CHECK(listener_local_queries == (open_irq ? 0u : 1u));
        CHECK(listener_closes == (open_irq ? 0u : 1u) && !listener_live);
        CHECK(s.bound && s.state == MOD_NETWORK_SS_NEW);
        CHECK(state(&s)->phase == TCP_BOUND && state(&s)->local_port == 0);
        local_is(&s, "0.0.0.0", 0);
        peer_raises(&s, MP_ENOTCONN);
        ERR(nic->accept(&s, &child, ip, &port, &error), MP_EINVAL);
        CHECK(!child._private && !listener_accepts && port == 123);
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_RD, &error) == 0);
        listener_open_error = listener_local_error = 0;
    }
    unsigned before_opens = listener_opens, before_queries = listener_local_queries;
    unsigned before_closes = listener_closes;
    CHECK(nic->listen(&s, 2, &error) == 0);
    CHECK(listener_opens == before_opens + 1 && listener_local_queries == before_queries + 1);
    CHECK(listener_requested_port == 0 && listener_backlog == 2 && listener_live);
    CHECK(s.state == MOD_NETWORK_SS_LISTENING && state(&s)->phase == TCP_LISTENING);
    CHECK(state(&s)->local_port == 60001);
    local_is(&s, "0.0.0.0", 60001);
    local_is(&s, "0.0.0.0", 60001);
    peer_raises(&s, MP_ENOTCONN);
    listener_local_port = 60002; listener_local_error = MP_EBUSY;
    local_is(&s, "0.0.0.0", 60001); // Saved assigned port, not another listener query.
    CHECK(listener_local_queries == before_queries + 1 && !network_snapshots);
    ERR(nic->listen(&s, 2, &error), MP_EINVAL);
    CHECK(listener_opens == before_opens + 1);

    snapshot_error = 0; listener_ready = true;
    accepted_port = 54321; stream_local_port = 60001;
    CHECK(nic->accept(&s, &child, ip, &port, &error) == 0);
    CHECK(port == 54321 && !memcmp(ip, peer, sizeof(ip)));
    CHECK(state(&child)->phase == TCP_CONNECTED && state(&child)->local_port == 0);
    memset(ip, 0xA5, sizeof(ip)); port = 0;
    peer_is(&child, "192.0.2.1", 54321);
    local_is(&child, "198.51.100.7", 60001);
    stream_local_port = 60003;
    local_is(&child, "198.51.100.7", 60003); // Accepted endpoint queries stay independent.
    local_is(&s, "0.0.0.0", 60001);
    peer_raises(&s, MP_ENOTCONN);
    CHECK(listener_local_queries == before_queries + 1 && stream_local_queries == 2);
    CHECK(!tcp_finishes && !events && !delays);
    nic->close(&s);
    CHECK(listener_closes == before_closes + 1 && !listener_live && tcp_live);
    local_raises(&s, MP_EBADF);
    peer_is(&child, "192.0.2.1", 54321);
    local_is(&child, "198.51.100.7", 60003);
    CHECK(nic->send(&child, buffer, 3, &error) == 2);
    nic->close(&child); nic->close(&s);
    CHECK(listener_closes == before_closes + 1 && tcp_closes == 1);
}
static void test_getpeer_accept(void) {
    mod_network_socket_obj_t s = tcp_new(0);
    mod_network_socket_obj_t child = {.type = MOD_NETWORK_SOCK_STREAM};
    byte ip[4] = {0}; mp_uint_t port = 0;
    peer_raises(&s, MP_ENOTCONN);
    CHECK(nic->bind(&s, wildcard, 9000, &error) == 0);
    peer_raises(&s, MP_ENOTCONN);
    CHECK(nic->listen(&s, 1, &error) == 0);
    peer_raises(&s, MP_ENOTCONN);
    CHECK(!listener_accepts && !listener_polls && !tcp_starts && !tcp_finishes);
    listener_ready = true; accepted_port = 54321;
    CHECK(nic->accept(&s, &child, ip, &port, &error) == 0);
    CHECK(!memcmp(ip, peer, 4) && port == 54321);
    memset(ip, 0xA5, sizeof(ip)); port = 0;
    peer_is(&child, "192.0.2.1", 54321);
    peer_raises(&s, MP_ENOTCONN);
    CHECK(!tcp_finishes && !events && !delays);
    nic->close(&s);
    peer_raises(&s, MP_EBADF);
    peer_is(&child, "192.0.2.1", 54321);
    nic->close(&child);
    peer_raises(&child, MP_EBADF);
    CHECK(listener_closes == 1 && tcp_closes == 1 && !tcp_finishes);
}
// Valid pending TCP SO_ERROR may finish once/cancel on failure; opened UDP may
// consume one pending native error only when its adapter report cache is empty.
// All options forbid waits, IO, opens, adapter allocation and unrelated changes.
typedef struct { unsigned values[33], finishes, cancels, stream_closes, setters; } option_observation_t;
static option_observation_t observe_option(void) {
    return (option_observation_t){{allocation_count, freed, opens, closes, sends,
        recvs, polls, events, delays, deinits, connects, connected_sends,
        udp_local_queries, stream_local_queries, network_snapshots, tcp_port_queries,
        tcp_starts, tcp_reads, tcp_writes,
        tcp_polls, listener_opens, listener_closes, listener_accepts, listener_polls,
        listener_deinits, listener_local_queries, tick_calls, format_calls,
        buffer_requests, consumed_packets, (unsigned)broadcast_calls, udp_bind_local_calls,
        tcp_shutdown_calls},
        tcp_finishes, tcp_cancels, tcp_closes, nodelay_calls};
}
static mp_obj_t option_call(mod_network_socket_obj_t *s, size_t n_args,
                           const mp_obj_t *args, int expected_error) {
    mod_network_socket_obj_t before = *s;
    udp_state_t private_before = {0};
    bool inspect_private = s->state != MOD_NETWORK_SS_CLOSED && state(s) != NULL;
    if (inspect_private) private_before = *state(s);
    option_observation_t counters = observe_option();
    unsigned ints = int_results, bytes = bytes_results, error_queries = tcp_error_queries;
    unsigned udp_queries = udp_error_queries;
    int pending_before = udp_pending_error;
    mp_int_t integer_before = integer_result;
    byte bytes_before[sizeof(bytes_result)], data_before[sizeof(buffer)], peer_before[4];
    memcpy(bytes_before, &bytes_result, sizeof(bytes_result));
    memcpy(data_before, buffer, sizeof(buffer));
    memcpy(peer_before, connected_ip, sizeof(connected_ip));
    bool peer_connected_before = connected_peer;
    uint16_t peer_port_before = connected_port;
    unsigned poll_events_before = poll_events, requested_before = requested;
    mp_obj_t result = NULL;
    nlr_buf_t outer;
    if (nlr_push(&outer) == 0) {
        result = mpynn_socket_getsockopt(n_args, args);
        nlr_pop(); CHECK(expected_error == 0);
    } else {
        CHECK(expected_error != 0 && outer.ret_val == (void *)(intptr_t)expected_error);
        CHECK(int_results == ints && bytes_results == bytes);
    }
    option_observation_t after = observe_option();
    CHECK(!memcmp(counters.values, after.values, sizeof(counters.values)));
    // Allocation failure may follow completion/native observation but must retain
    // the cached report until a result object has actually been constructed.
    bool observed_error = (!expected_error || expected_error == HOST_MEMORY_ERROR) &&
        args[2] == (mp_obj_t)MPYNN_SOCKET_SO_ERROR;
    bool consumed = observed_error && !expected_error;
    bool valid_udp_error = before.state != MOD_NETWORK_SS_CLOSED &&
        before.domain == MOD_NETWORK_AF_INET && before.type == MOD_NETWORK_SOCK_DGRAM &&
        (before.proto == 0 || before.proto == 17) &&
        args[1] == (mp_obj_t)MOD_NETWORK_SOL_SOCKET &&
        args[2] == (mp_obj_t)MPYNN_SOCKET_SO_ERROR &&
        (n_args == 3 || (args[3] != &nonint_sentinel &&
         (mp_int_t)args[3] >= 0 && (mp_uint_t)args[3] <= sizeof(mp_int_t)));
    bool query_udp = valid_udp_error && inspect_private && private_before.opened &&
        private_before.so_error == 0;
    bool udp_bridge_failed = query_udp &&
        (udp_error_query_error || !live || private_before.token != 0x12345678);
    CHECK(udp_error_queries == udp_queries + (query_udp ? 1u : 0u));
    CHECK(udp_pending_error == (query_udp && !udp_bridge_failed ? 0 : pending_before));
    CHECK(!memcmp(buffer, data_before, sizeof(buffer)));
    CHECK(!memcmp(connected_ip, peer_before, sizeof(connected_ip)));
    CHECK(connected_peer == peer_connected_before && connected_port == peer_port_before);
    CHECK(poll_events == poll_events_before && requested == requested_before);
    if (expected_error) {
        CHECK(integer_result == integer_before);
        CHECK(!memcmp(&bytes_result, bytes_before, sizeof(bytes_result)));
    }
    bool finish_pending = observed_error && inspect_private && private_before.phase == TCP_PENDING;
    bool failed = finish_pending && tcp_error != 0 && tcp_error != MP_EAGAIN;
    bool acquired = finish_pending && !tcp_error &&
        (tcp_ready || (tcp_ready_after_delay && delays));
    bool apply_nodelay = acquired && private_before.nodelay_configured;
    bool option_failed = apply_nodelay && nodelay_error;
    bool completed = acquired && !option_failed;
    CHECK(after.finishes == counters.finishes + (finish_pending ? 1u : 0u));
    CHECK(after.cancels == counters.cancels + (failed ? 1u : 0u));
    CHECK(after.setters == counters.setters + (apply_nodelay ? 1u : 0u));
    CHECK(after.stream_closes == counters.stream_closes + (option_failed ? 1u : 0u));
    mod_network_socket_obj_t expected_socket = before;
    udp_state_t expected_private = private_before;
    if (completed) {
        expected_socket.state = MOD_NETWORK_SS_CONNECTED;
        expected_private.phase = TCP_CONNECTED;
        expected_private.connect_token = 0;
        expected_private.stream_token = 81;
        CHECK(!tcp_job && tcp_live);
    } else if (failed || option_failed) {
        int terminal_error = option_failed ? nodelay_error : tcp_error;
        expected_private.phase = TCP_FAILED;
        expected_private.connect_token = 0;
        expected_private.stream_token = 0;
        expected_private.sticky_error = terminal_error;
        expected_private.so_error = terminal_error;
        expected_private.so_error_native_checked = true;
        CHECK(!tcp_job && !tcp_live);
    } else if (finish_pending) {
        CHECK(tcp_job && !tcp_live);
        CHECK(state(s)->phase == TCP_PENDING && state(s)->connect_token == 71);
        CHECK(!state(s)->stream_token && !state(s)->sticky_error);
    }
    bool query_native = observed_error && inspect_private &&
        expected_private.phase == TCP_CONNECTED && !private_before.so_error_native_checked;
    CHECK(tcp_error_queries == error_queries + (query_native ? 1u : 0u));
    if (observed_error && inspect_private) {
        if (query_native && tcp_terminal_error) {
            expected_private.so_error_native_checked = true;
            if (!expected_private.so_error) expected_private.so_error = tcp_terminal_error;
        }
        if (query_udp && !udp_bridge_failed) expected_private.so_error = pending_before;
        if (consumed) expected_private.so_error = 0;
        CHECK(state(s)->so_error == expected_private.so_error);
        CHECK(state(s)->so_error_native_checked == expected_private.so_error_native_checked);
    }
    CHECK(!memcmp(s, &expected_socket, sizeof(expected_socket)));
    if (inspect_private) {
        // Validate every allowed transition explicitly, then the full remainder:
        // peer, binding/reservation, listener, UDP and adapter identity stay intact.
        CHECK(state(s)->phase == expected_private.phase);
        CHECK(state(s)->connect_token == expected_private.connect_token);
        CHECK(state(s)->stream_token == expected_private.stream_token);
        CHECK(state(s)->sticky_error == expected_private.sticky_error);
        CHECK(!memcmp(state(s), &expected_private, sizeof(expected_private)));
    }
    CHECK(nlr_top == NULL);
    return result;
}
static void option_at_level_is(mod_network_socket_obj_t *s, mp_int_t level,
                               mp_int_t opt, mp_int_t value, mp_int_t length) {
    mp_obj_t args[] = {MP_OBJ_FROM_PTR(s), (mp_obj_t)level,
        (mp_obj_t)opt, (mp_obj_t)length};
    unsigned ints = int_results, bytes = bytes_results, conversions = int_conversions;
    mp_obj_t result = option_call(s, length < 0 ? 3 : 4, args, 0);
    CHECK(int_conversions == conversions + (length < 0 ? 2u : 3u));
    if (length <= 0) {
        if (result != &integer_result || integer_result != value)
            fprintf(stderr, "option %ld: expected %ld, got %ld\n",
                (long)opt, (long)value, (long)integer_result);
        CHECK(result == &integer_result && integer_result == value);
        CHECK(int_results == ints + 1 && bytes_results == bytes);
    } else {
        CHECK(result == &bytes_result && bytes_result.length == (size_t)length);
        CHECK(!memcmp(bytes_result.data, &value, (size_t)length));
        CHECK(bytes_results == bytes + 1 && int_results == ints);
    }
}
static void option_is(mod_network_socket_obj_t *s, mp_int_t opt, mp_int_t value,
                      mp_int_t length) {
    option_at_level_is(s, MOD_NETWORK_SOL_SOCKET, opt, value, length);
}
static void nodelay_forms(mod_network_socket_obj_t *s, bool value) {
    option_at_level_is(s, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY, value, -1);
    for (mp_int_t length = 0; length <= (mp_int_t)sizeof(mp_int_t); ++length)
        option_at_level_is(s, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY, value, length);
}
static void option_forms(mod_network_socket_obj_t *s, mp_int_t opt, mp_int_t value) {
    option_is(s, opt, value, -1);
    for (mp_int_t length = 0; length <= (mp_int_t)sizeof(mp_int_t); ++length)
        option_is(s, opt, value, length);
}
static void option_raises(mod_network_socket_obj_t *s, mp_obj_t level, mp_obj_t opt,
                          mp_obj_t length, int code) {
    const mp_obj_t args[] = {MP_OBJ_FROM_PTR(s), level, opt, length};
    option_call(s, 4, args, code);
}
static void option_errno(mod_network_socket_obj_t *s, mp_int_t level, mp_int_t opt,
                         mp_int_t length, int code) {
    option_raises(s, (mp_obj_t)level, (mp_obj_t)opt, (mp_obj_t)length, code);
}
// Set-side assertions are as strict as option_call: one native setter only on a
// valid connected TCP request, no wait/IO/allocation, rollback on native failure.
static void nodelay_set_raw(mod_network_socket_obj_t *s, mp_uint_t level, mp_uint_t opt,
                            const void *value, mp_uint_t len, int expected_error) {
    mod_network_socket_obj_t socket_before = *s;
    udp_state_t private_before = {0};
    bool inspect = s->state != MOD_NETWORK_SS_CLOSED && state(s);
    if (inspect) private_before = *state(s);
    option_observation_t before = observe_option();
    unsigned queries = tcp_error_queries;
    bool valid = inspect && private_before.kind == MOD_NETWORK_SOCK_STREAM &&
        level == MPYNN_SOCKET_IPPROTO_TCP && opt == MPYNN_SOCKET_TCP_NODELAY &&
        value && len == sizeof(mp_int_t);
    bool call_native = valid && private_before.phase == TCP_CONNECTED;
    int result = nic->setsockopt(s, level, opt, value, len, &error);
    CHECK(result == (expected_error ? -1 : 0));
    if (expected_error) CHECK(error == expected_error);
    option_observation_t after = observe_option();
    CHECK(!memcmp(before.values, after.values, sizeof(before.values)));
    CHECK(after.finishes == before.finishes && after.cancels == before.cancels);
    CHECK(after.stream_closes == before.stream_closes);
    CHECK(after.setters == before.setters + (call_native ? 1u : 0u));
    CHECK(tcp_error_queries == queries);
    CHECK(!memcmp(s, &socket_before, sizeof(socket_before)));
    if (inspect) {
        udp_state_t expected = private_before;
        if (!expected_error) {
            mp_int_t number; memcpy(&number, value, sizeof(number));
            expected.nodelay = number != 0;
            expected.nodelay_configured = true;
        }
        CHECK(!memcmp(state(s), &expected, sizeof(expected)));
    }
}
static void nodelay_set(mod_network_socket_obj_t *s, mp_int_t value, int expected_error) {
    nodelay_set_raw(s, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY,
        &value, sizeof(value), expected_error);
}
static void test_nodelay_validation(void) {
    CHECK(MPYNN_SOCKET_IPPROTO_TCP == 6 && MPYNN_SOCKET_TCP_NODELAY == 1);
    mod_network_socket_obj_t fresh = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM, .state=MOD_NETWORK_SS_NEW};
    nodelay_forms(&fresh, true); // Default queried even before NIC selection.
    fresh.proto = 6; nodelay_forms(&fresh, true);
    fresh.type = MOD_NETWORK_SOCK_DGRAM; fresh.proto = 0;
    option_errno(&fresh, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_TCP_NODELAY, 0, MP_EOPNOTSUPP);
    mod_network_socket_obj_t s = tcp_new(0), u = socket_new();
    CHECK(state(&s)->nodelay && !state(&s)->nodelay_configured && !nodelay_calls);
    nodelay_forms(&s, true);
    mp_int_t value = 0;
    nodelay_set_raw(&u, 6, 1, &value, sizeof(value), MP_EOPNOTSUPP);
    nodelay_set_raw(&s, 0, 1, &value, sizeof(value), MP_EOPNOTSUPP);
    nodelay_set_raw(&s, MOD_NETWORK_SOL_SOCKET, 1, &value, sizeof(value), MP_EOPNOTSUPP);
    nodelay_set_raw(&s, 6, 99, &value, sizeof(value), MP_EOPNOTSUPP);
    nodelay_set_raw(&s, 6, 1, NULL, sizeof(value), MP_EINVAL);
    for (mp_uint_t size=0; size <= sizeof(value)+1; ++size)
        if (size != sizeof(value)) nodelay_set_raw(&s, 6, 1, &value, size, MP_EINVAL);
    nodelay_forms(&s, true); CHECK(!state(&s)->nodelay_configured);
    option_errno(&s, 0, 1, 0, MP_EOPNOTSUPP);
    option_errno(&s, 6, 99, 0, MP_EOPNOTSUPP);
    option_errno(&s, 6, 1, -1, HOST_VALUE_ERROR);
    option_errno(&s, 6, 1, sizeof(mp_int_t)+1, HOST_VALUE_ERROR);
    option_raises(&s, &nonint_sentinel, (mp_obj_t)1, NULL, HOST_TYPE_ERROR);
    option_raises(&s, (mp_obj_t)6, &nonint_sentinel, NULL, HOST_TYPE_ERROR);
    option_raises(&s, (mp_obj_t)6, (mp_obj_t)1, &nonint_sentinel, HOST_TYPE_ERROR);
    byte unaligned[sizeof(mp_int_t)+1]; memcpy(unaligned+1, &value, sizeof(value));
    nodelay_set_raw(&s, 6, 1, unaligned+1, sizeof(value), 0); nodelay_forms(&s, false);
    nodelay_set(&s, -9, 0); nodelay_forms(&s, true);
    nodelay_set(&s, 0, 0); nodelay_forms(&s, false);
    CHECK(!nodelay_calls && !opens && !tcp_starts);
    nic->close(&u); nic->close(&s);
    option_errno(&s, 6, 1, 0, MP_EBADF);
    s._private=(void *)1;
    nodelay_set_raw(&s, 6, 1, NULL, 0, MP_EBADF);
    option_raises(&s, &nonint_sentinel, &nonint_sentinel, &nonint_sentinel, MP_EBADF);
    s._private=NULL;
}
static void test_nodelay_connect(const char *mode) {
    bool defaults = !strcmp(mode, "default");
    bool failure = !strcmp(mode, "fail0") || !strcmp(mode, "fail1");
    bool bind_first = !strcmp(mode, "bound0") || !strcmp(mode, "bound1");
    bool pending_set = !strcmp(mode, "pending0") || !strcmp(mode, "pending1");
    bool blocking = !strcmp(mode, "blocking0") || !strcmp(mode, "blocking1");
    bool enabled = mode[strlen(mode)-1] == '1';
    mod_network_socket_obj_t s=tcp_new(blocking ? 20 : 0);
    if (!defaults && !pending_set) nodelay_set(&s, enabled, 0);
    if (bind_first) CHECK(nic->bind(&s, wildcard, 4321, &error) == 0);
    CHECK(!nodelay_calls);
    if (blocking) {
        tcp_ready=true; nodelay_unpublished_socket=&s;
        CHECK(nic->connect(&s, peer, 9000, &error)==0);
        nodelay_unpublished_socket=NULL;
        CHECK(nodelay_calls==1 && nodelay_value==enabled);
        CHECK(state(&s)->phase==TCP_CONNECTED && tcp_live && !tcp_job);
    } else {
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        if (pending_set) nodelay_set(&s, enabled, 0);
        CHECK(!nodelay_calls);
        nodelay_forms(&s, defaults ? true : enabled);
        option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1); // still pending, no setter
        CHECK(state(&s)->phase==TCP_PENDING && tcp_finishes==1 && !nodelay_calls);
        tcp_ready=true; nodelay_unpublished_socket=&s;
        if (failure) nodelay_error=MP_EIO;
        option_is(&s, MPYNN_SOCKET_SO_ERROR, failure ? MP_EIO : 0, -1);
        nodelay_unpublished_socket=NULL;
        CHECK(tcp_finishes==2 && tcp_cancels==0);
        CHECK(nodelay_calls==(defaults ? 0u : 1u));
        if (failure) {
            CHECK(tcp_closes==1 && !tcp_live && !tcp_job);
            CHECK(!state(&s)->stream_token && state(&s)->phase==TCP_FAILED);
            CHECK(state(&s)->sticky_error==MP_EIO);
            option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
            peer_raises(&s, MP_EIO);
            nodelay_forms(&s, enabled); // requested option remains, connection failed
            nic->close(&s); CHECK(tcp_closes==1); return;
        }
        CHECK(state(&s)->phase==TCP_CONNECTED && tcp_live && !tcp_job);
        if (!defaults) CHECK(nodelay_value==enabled);
    }
    nodelay_forms(&s, defaults ? true : enabled);
    unsigned setters=nodelay_calls, finishes=tcp_finishes;
    peer_is(&s,"192.0.2.1",9000); option_is(&s,MPYNN_SOCKET_SO_ERROR,0,-1);
    CHECK(nodelay_calls==setters && tcp_finishes==finishes);
    CHECK(nic->recv(&s, buffer, 3, &error)==3);
    CHECK(nic->send(&s, buffer, 3, &error)==2);
    nic->close(&s); CHECK(tcp_closes==1);
}
static void test_nodelay_live(void) {
    mod_network_socket_obj_t s=tcp_new(0);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    tcp_ready=true; option_is(&s,MPYNN_SOCKET_SO_ERROR,0,-1);
    CHECK(state(&s)->phase==TCP_CONNECTED && !nodelay_calls);
    nodelay_set(&s,0,0); nodelay_forms(&s,false); CHECK(nodelay_value==0);
    nodelay_error=MP_EBUSY;
    nodelay_set(&s,1,MP_EBUSY); nodelay_forms(&s,false); CHECK(nodelay_value==0);
    nodelay_error=0;
    nodelay_set(&s,7,0); nodelay_forms(&s,true); CHECK(nodelay_value==1);
    nodelay_error=MP_EIO;
    nodelay_set(&s,0,MP_EIO); nodelay_forms(&s,true); CHECK(nodelay_value==1);
    nodelay_error=0;
    nodelay_set(&s,0,0); nodelay_forms(&s,false);
    CHECK(nodelay_calls==5 && !tcp_closes && !tcp_cancels && !events && !delays);
    option_is(&s,MPYNN_SOCKET_SO_ERROR,0,-1);
    CHECK(nic->send(&s,buffer,3,&error)==2 && nic->recv(&s,buffer,3,&error)==3);
    nic->close(&s);
}
static void test_nodelay_accept(const char *mode) {
    bool defaults=!strcmp(mode,"default");
    bool failure=!strcmp(mode,"fail0") || !strcmp(mode,"fail1");
    bool enabled=mode[strlen(mode)-1]=='1';
    mod_network_socket_obj_t s=tcp_new(0);
    if (!defaults) nodelay_set(&s,enabled,0);
    CHECK(nic->bind(&s,wildcard,9000,&error)==0);
    CHECK(nic->listen(&s,1,&error)==0); CHECK(!nodelay_calls);
    nodelay_forms(&s,defaults ? true : enabled);
    mod_network_socket_obj_t child={.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM,.proto=6,.state=MOD_NETWORK_SS_NEW};
    byte ip[4]={9,9,9,9}; mp_uint_t port=123;
    listener_ready=true; nodelay_unpublished_child=&child;
    if (failure) nodelay_error=MP_EIO;
    if (failure) {
        unsigned free_before=freed;
        ERR(nic->accept(&s,&child,ip,&port,&error),MP_EIO);
        CHECK(!child._private && child.state==MOD_NETWORK_SS_NEW);
        CHECK(port==123 && freed==free_before+1);
        CHECK(!tcp_live && tcp_closes==1 && listener_live);
        nodelay_error=0;
        listener_ready=true;
        CHECK(nic->accept(&s,&child,ip,&port,&error)==0);
        CHECK(tcp_live && nodelay_calls==2 && nodelay_value==enabled);
    } else {
        CHECK(nic->accept(&s,&child,ip,&port,&error)==0);
        CHECK(nodelay_calls==(defaults ? 0u : 1u));
        if (!defaults) CHECK(nodelay_value==enabled);
    }
    nodelay_unpublished_child=NULL;
    CHECK(child.state==MOD_NETWORK_SS_CONNECTED && state(&child)->phase==TCP_CONNECTED);
    CHECK(state(&child)->nodelay==(defaults ? true : enabled));
    CHECK(state(&child)->nodelay_configured==!defaults && !state(&child)->bind_reservation);
    nodelay_forms(&child,defaults ? true : enabled);
    CHECK(port==accepted_port && !memcmp(ip,peer,4));
    nodelay_set(&s,!state(&child)->nodelay,0); // listener cache only; existing child unchanged
    nodelay_forms(&child,defaults ? true : enabled);
    nic->close(&s); CHECK(tcp_live && !listener_live);
    CHECK(nic->recv(&child,buffer,3,&error)==3 && nic->send(&child,buffer,3,&error)==2);
    nic->close(&child); CHECK(tcp_closes==(failure ? 2u : 1u));
}

static void test_getsockopt_validation(void) {
    mod_network_socket_obj_t s = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_DGRAM, .state=MOD_NETWORK_SS_NEW};
    option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_DGRAM);
    option_forms(&s, MOD_NETWORK_SO_BROADCAST, 0); // No NIC/private state yet.
    s.proto = 17; option_is(&s, MPYNN_SOCKET_SO_TYPE, 2, -1);
    s.type = MOD_NETWORK_SOCK_STREAM; s.proto = 0;
    option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
    s.proto = 6; option_is(&s, MPYNN_SOCKET_SO_TYPE, 1, -1);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, 0, MP_EOPNOTSUPP);
    const mp_int_t bad_levels[] = {0, -1, MOD_NETWORK_SOL_SOCKET + 1, INTPTR_MAX};
    for (unsigned i = 0; i < sizeof(bad_levels)/sizeof(bad_levels[0]); ++i)
        option_errno(&s, bad_levels[i], MPYNN_SOCKET_SO_TYPE, 0, MP_EOPNOTSUPP);
    const mp_int_t bad_options[] = {0, -1, MPYNN_SOCKET_SO_TYPE + 1, INTPTR_MAX};
    for (unsigned i = 0; i < sizeof(bad_options)/sizeof(bad_options[0]); ++i)
        option_errno(&s, MOD_NETWORK_SOL_SOCKET, bad_options[i], 0, MP_EOPNOTSUPP);
    option_raises(&s, &nonint_sentinel, (mp_obj_t)MPYNN_SOCKET_SO_TYPE, NULL, HOST_TYPE_ERROR);
    option_raises(&s, (mp_obj_t)MOD_NETWORK_SOL_SOCKET, &nonint_sentinel, NULL, HOST_TYPE_ERROR);
    option_raises(&s, (mp_obj_t)MOD_NETWORK_SOL_SOCKET, (mp_obj_t)MPYNN_SOCKET_SO_TYPE,
        &nonint_sentinel, HOST_TYPE_ERROR);
    const mp_int_t bad_lengths[] = {-1, (mp_int_t)sizeof(mp_int_t) + 1, INTPTR_MAX, INTPTR_MIN};
    for (unsigned i = 0; i < sizeof(bad_lengths)/sizeof(bad_lengths[0]); ++i)
        option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_TYPE, bad_lengths[i], HOST_VALUE_ERROR);
    s.domain = 99;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_TYPE, 0, MP_EAFNOSUPPORT);
    s.domain = MOD_NETWORK_AF_INET; s.type = 3;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_TYPE, 0, MP_EOPNOTSUPP);
    s.type = MOD_NETWORK_SOCK_STREAM; s.proto = 17;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_TYPE, 0, MP_EOPNOTSUPP);
    s.type = MOD_NETWORK_SOCK_DGRAM; s.proto = 6;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, 0, MP_EOPNOTSUPP);
    s.domain = 99; s.type = 3; s.state = MOD_NETWORK_SS_CLOSED;
    s._private = (void *)1; // Closed wins without touching an invalid private pointer.
    unsigned conversions = int_conversions;
    option_raises(&s, &nonint_sentinel, &nonint_sentinel, &nonint_sentinel, MP_EBADF);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_TYPE, -1, MP_EBADF);
    CHECK(int_conversions == conversions && !allocation_count);
}
static void test_getsockopt_broadcast(bool bound) {
    mod_network_socket_obj_t s = socket_new();
    mp_int_t on = 1, off = 0;
    option_forms(&s, MOD_NETWORK_SO_BROADCAST, 0);
    option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_DGRAM);
    CHECK(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST,
        &on, sizeof(on), &error) == 0);
    option_forms(&s, MOD_NETWORK_SO_BROADCAST, 1);
    ERR(nic->setsockopt(&s, 0, MOD_NETWORK_SO_BROADCAST, &off, sizeof(off), &error), MP_EOPNOTSUPP);
    ERR(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, 0, &off, sizeof(off), &error), MP_EOPNOTSUPP);
    ERR(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, NULL, 0, &error), MP_EINVAL);
    option_is(&s, MOD_NETWORK_SO_BROADCAST, 1, -1);
    CHECK(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST,
        &off, sizeof(off), &error) == 0);
    option_forms(&s, MOD_NETWORK_SO_BROADCAST, 0);
    CHECK(!opens && !broadcast_calls);
    CHECK(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST,
        &on, sizeof(on), &error) == 0);
    if (bound) CHECK(nic->bind(&s, wildcard, 4321, &error) == 0);
    else CHECK(send_one(&s) == 3);
    CHECK(opens == 1 && broadcast_calls == 1 && broadcast_value == 1);
    option_forms(&s, MOD_NETWORK_SO_BROADCAST, 1);
    option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_DGRAM);
    broadcast_error = MP_EBUSY;
    ERR(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST,
        &off, sizeof(off), &error), MP_EBUSY);
    option_forms(&s, MOD_NETWORK_SO_BROADCAST, 1); // Rejected native update rolls back.
    broadcast_error = 0;
    CHECK(nic->setsockopt(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST,
        &off, sizeof(off), &error) == 0);
    option_forms(&s, MOD_NETWORK_SO_BROADCAST, 0);
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_DGRAM);
    option_is(&s, MOD_NETWORK_SO_BROADCAST, 0, -1);
    nic->close(&s);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_TYPE, 0, MP_EBADF);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, 0, MP_EBADF);
}
static void test_getsockopt_tcp(const char *mode) {
    mod_network_socket_obj_t s = tcp_new(0);
    option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
    if (!strcmp(mode, "listener") || !strcmp(mode, "accepted")) {
        CHECK(nic->bind(&s, wildcard, 9000, &error) == 0);
        option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
        CHECK(nic->listen(&s, 1, &error) == 0);
        option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
        if (!strcmp(mode, "accepted")) {
            mod_network_socket_obj_t child = {.domain=MOD_NETWORK_AF_INET,
                .type=MOD_NETWORK_SOCK_STREAM, .proto=6};
            listener_ready = true; byte ip[4]; mp_uint_t port;
            CHECK(nic->accept(&s, &child, ip, &port, &error) == 0);
            option_forms(&child, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
            option_errno(&child, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, 0, MP_EOPNOTSUPP);
            nic->close(&child);
            option_errno(&child, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_TYPE, 0, MP_EBADF);
        }
    } else {
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
        tcp_ready = true;
        option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
        CHECK(tcp_job && !tcp_live && !tcp_finishes && state(&s)->phase == TCP_PENDING);
        if (!strcmp(mode, "connected")) {
            peer_is(&s, "192.0.2.1", 9000);
            option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
        } else if (!strcmp(mode, "failed")) {
            tcp_error = MP_ECONNREFUSED;
            peer_raises(&s, MP_ECONNREFUSED);
            option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
        } else CHECK(!strcmp(mode, "pending"));
    }
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, 0, MP_EOPNOTSUPP);
    nic->close(&s);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_TYPE, 0, MP_EBADF);
}
static void test_getsockopt_error_defaults(void) {
    CHECK(MPYNN_SOCKET_SO_ERROR == 0x1007);
    mod_network_socket_obj_t fresh = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM, .state=MOD_NETWORK_SS_NEW};
    option_is(&fresh, MPYNN_SOCKET_SO_ERROR, 0, -1);
    option_is(&fresh, MPYNN_SOCKET_SO_ERROR, 0, 0);
    CHECK(!allocation_count && !tcp_starts);
    fresh.type = MOD_NETWORK_SOCK_DGRAM;
    option_forms(&fresh, MPYNN_SOCKET_SO_ERROR, 0);
    CHECK(!fresh._private && !allocation_count && !udp_error_queries && !opens);
    fail_option_result = true;
    option_errno(&fresh, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 1, HOST_MEMORY_ERROR);
    fail_option_result = false;
    CHECK(!fresh._private && !allocation_count && !udp_error_queries && !opens);
    mod_network_socket_obj_t udp = socket_new();
    mp_int_t on = 1;
    CHECK(nic->setsockopt(&udp, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST,
        &on, sizeof(on), &error) == 0);
    option_forms(&udp, MPYNN_SOCKET_SO_ERROR, 0);
    CHECK(!state(&udp)->opened && !udp_error_queries);
    option_is(&udp, MOD_NETWORK_SO_BROADCAST, 1, -1);
    option_is(&udp, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_DGRAM, -1);
    CHECK(!opens && !broadcast_calls);
    nic->close(&udp);
    option_errno(&udp, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_EBADF);
    mod_network_socket_obj_t s = tcp_new(0);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(nic->bind(&s, wildcard, 9000, &error) == 0);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, 0);
    CHECK(nic->listen(&s, 1, &error) == 0);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    mod_network_socket_obj_t child = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM, .proto=6};
    listener_ready = true; byte ip[4]; mp_uint_t port;
    CHECK(nic->accept(&s, &child, ip, &port, &error) == 0);
    option_is(&child, MPYNN_SOCKET_SO_ERROR, 0, -1);
    option_is(&child, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM, -1);
    nic->close(&child); nic->close(&s);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_EBADF);
    s._private = (void *)1; // Closed wins before conversions/private-state access.
    unsigned conversions = int_conversions;
    option_raises(&s, &nonint_sentinel, &nonint_sentinel, &nonint_sentinel, MP_EBADF);
    CHECK(int_conversions == conversions);
    s._private = NULL;
}
static void test_getsockopt_error_udp_native(const char *mode, mp_int_t length) {
    mod_network_socket_obj_t s = socket_new();
    bool connected = !strcmp(mode, "connected");
    if (connected) CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    else if (!strcmp(mode, "bound")) CHECK(nic->bind(&s, wildcard, 4321, &error) == 0);
    else { CHECK(!strcmp(mode, "lazy")); CHECK(send_one(&s) == 3); }
    s.timeout = 20; // Native observation never yields, even on a blocking socket.
    poll_events = MP_STREAM_POLL_RD | MP_STREAM_POLL_WR | MP_STREAM_POLL_ERR;
    memset(buffer, 0xA5, sizeof(buffer));
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(udp_error_queries == 1 && !udp_pending_error && !state(&s)->so_error);
    udp_pending_error = MP_ECONNREFUSED;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ECONNREFUSED, length);
    CHECK(udp_error_queries == 2 && !udp_pending_error && !state(&s)->so_error);
    // UDP errors are transient: a later datagram can produce another report.
    udp_pending_error = MP_ENETDOWN;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ENETDOWN, length);
    CHECK(udp_error_queries == 3 && !udp_pending_error && !state(&s)->so_error);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, 0);
    CHECK(udp_error_queries == 4 && !state(&s)->so_error_native_checked);
    // Even an inconsistent TCP latch must not suppress fresh UDP observations.
    state(&s)->so_error_native_checked = true;
    udp_pending_error = MP_ECONNREFUSED;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ECONNREFUSED, 1);
    CHECK(udp_error_queries == 5 && state(&s)->so_error_native_checked);
    CHECK(state(&s)->opened && state(&s)->connected == connected && live);
    CHECK(!events && !delays && !recvs && !consumed_packets && !polls);
    nic->close(&s);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_EBADF);
}
static void test_getsockopt_error_udp_allocation(mp_int_t length) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    udp_pending_error = MP_ECONNREFUSED;
    fail_option_result = true;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, length, HOST_MEMORY_ERROR);
    CHECK(udp_error_queries == 1 && !udp_pending_error);
    CHECK(state(&s)->so_error == MP_ECONNREFUSED && !state(&s)->so_error_native_checked);
    // A new native report stays pending while the cached older report is retried.
    udp_pending_error = MP_ENETDOWN;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, length, HOST_MEMORY_ERROR);
    CHECK(udp_error_queries == 1 && udp_pending_error == MP_ENETDOWN);
    fail_option_result = false;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ECONNREFUSED, length);
    CHECK(udp_error_queries == 1 && !state(&s)->so_error && udp_pending_error == MP_ENETDOWN);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ENETDOWN, length);
    CHECK(udp_error_queries == 2 && !udp_pending_error && !state(&s)->so_error);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(udp_error_queries == 3);
    nic->close(&s);
}
static void test_getsockopt_error_udp_reconnect(mp_int_t length) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    byte next_peer[4] = {198, 51, 100, 9};
    udp_pending_error = MP_ECONNREFUSED;
    fail_option_result = true;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, length, HOST_MEMORY_ERROR);
    fail_option_result = false;
    CHECK(udp_error_queries == 1 && state(&s)->so_error == MP_ECONNREFUSED);
    udp_pending_error = MP_ENETDOWN;
    connect_error = MP_EBUSY;
    ERR(nic->connect(&s, next_peer, 1234, &error), MP_EBUSY);
    CHECK(state(&s)->so_error == MP_ECONNREFUSED && udp_pending_error == MP_ENETDOWN);
    CHECK(udp_error_queries == 1 && state(&s)->peer_port == 9000);
    CHECK(!memcmp(state(&s)->peer_ip, peer, 4) && !memcmp(connected_ip, peer, 4));
    CHECK(connected_port == 9000);
    connect_error = 0;
    CHECK(nic->connect(&s, next_peer, 1234, &error) == 0);
    CHECK(!state(&s)->so_error && !udp_pending_error && udp_error_queries == 1);
    CHECK(state(&s)->peer_port == 1234 && connected_port == 1234);
    CHECK(!memcmp(state(&s)->peer_ip, next_peer, 4));
    CHECK(!memcmp(connected_ip, next_peer, 4));
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, length);
    CHECK(udp_error_queries == 2);
    udp_pending_error = MP_ECONNREFUSED;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ECONNREFUSED, length);
    CHECK(udp_error_queries == 3 && !state(&s)->so_error && !udp_pending_error);
    CHECK(opens == 1 && connects == 3 && !closes && !events && !delays);
    nic->close(&s);
}
static void test_getsockopt_error_udp_validation(void) {
    mod_network_socket_obj_t s = socket_new();
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    udp_pending_error = MP_ECONNREFUSED;
    option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_DGRAM);
    option_forms(&s, MOD_NETWORK_SO_BROADCAST, 0);
    option_errno(&s, 0, MPYNN_SOCKET_SO_ERROR, 0, MP_EOPNOTSUPP);
    option_errno(&s, MPYNN_SOCKET_IPPROTO_TCP, MPYNN_SOCKET_SO_ERROR, 0, MP_EOPNOTSUPP);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, 0, 0, MP_EOPNOTSUPP);
    option_raises(&s, &nonint_sentinel, (mp_obj_t)MPYNN_SOCKET_SO_ERROR, NULL, HOST_TYPE_ERROR);
    option_raises(&s, (mp_obj_t)MOD_NETWORK_SOL_SOCKET, &nonint_sentinel, NULL, HOST_TYPE_ERROR);
    option_raises(&s, (mp_obj_t)MOD_NETWORK_SOL_SOCKET, (mp_obj_t)MPYNN_SOCKET_SO_ERROR,
        &nonint_sentinel, HOST_TYPE_ERROR);
    const mp_int_t bad_lengths[] = {-1, (mp_int_t)sizeof(mp_int_t) + 1, INTPTR_MAX, INTPTR_MIN};
    for (unsigned i = 0; i < sizeof(bad_lengths)/sizeof(bad_lengths[0]); ++i)
        option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, bad_lengths[i], HOST_VALUE_ERROR);
    s.domain = 99;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_EAFNOSUPPORT);
    s.domain = MOD_NETWORK_AF_INET; s.type = 3;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_EOPNOTSUPP);
    s.type = MOD_NETWORK_SOCK_DGRAM; s.proto = 6;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_EOPNOTSUPP);
    s.proto = 17;
    CHECK(!udp_error_queries && udp_pending_error == MP_ECONNREFUSED);
    // Positive bridge status is an exception, not a pending SO_ERROR value.
    udp_error_query_error = MP_EBUSY;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 1, MP_EBUSY);
    CHECK(udp_error_queries == 1 && udp_pending_error == MP_ECONNREFUSED && !state(&s)->so_error);
    udp_error_query_error = MP_ENETDOWN;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_ENETDOWN);
    CHECK(udp_error_queries == 2 && udp_pending_error == MP_ECONNREFUSED);
    udp_error_query_error = 0;
    uint32_t token = state(&s)->token;
    state(&s)->token = token ^ 8;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_EBADF);
    CHECK(udp_error_queries == 3 && udp_pending_error == MP_ECONNREFUSED);
    state(&s)->token = token;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ECONNREFUSED, -1);
    CHECK(udp_error_queries == 4 && !udp_pending_error);
    nic->close(&s);
    s.domain = 99; s.type = 3; s._private = (void *)1;
    unsigned conversions = int_conversions;
    option_raises(&s, &nonint_sentinel, &nonint_sentinel, &nonint_sentinel, MP_EBADF);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, -1, MP_EBADF);
    CHECK(int_conversions == conversions && udp_error_queries == 4);
    s._private = NULL;
}
static void test_getsockopt_error_udp_sync(const char *mode) {
    mod_network_socket_obj_t s = socket_new();
    bool connected = !strncmp(mode, "connected-", 10);
    bool receive = strstr(mode, "recv") != NULL;
    bool sendto = !strcmp(mode, "sendto");
    CHECK(connected || sendto || !strcmp(mode, "recvfrom"));
    if (connected) CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    else CHECK(nic->bind(&s, wildcard, 0, &error) == 0);
    s.timeout = 0; send_error = recv_error = MP_ECONNREFUSED;
    if (connected) UERR(connected_io(&s, receive), MP_ECONNREFUSED);
    else if (sendto) UERR(send_one(&s), MP_ECONNREFUSED);
    else UERR(recv_one(&s), MP_ECONNREFUSED);
    CHECK(!state(&s)->so_error && !state(&s)->so_error_native_checked);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(udp_error_queries == 1); // Already-reported synchronous errors are not cached.
    udp_pending_error = MP_ENETDOWN;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ENETDOWN, 0);
    CHECK(udp_error_queries == 2 && !udp_pending_error && !state(&s)->so_error);
    nic->close(&s);
}
static void test_getsockopt_error_pending(const char *mode) {
    mod_network_socket_obj_t s = tcp_new(0);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    s.timeout = 20; // SO_ERROR stays nonblocking even on a now-blocking socket.
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(tcp_job && !tcp_live && tcp_finishes == 1 && !tcp_cancels);
    CHECK(state(&s)->phase == TCP_PENDING && state(&s)->connect_token == 71);
    CHECK(!state(&s)->stream_token && !state(&s)->so_error && !state(&s)->so_error_native_checked);
    tcp_ready = true;
    bool success = !strcmp(mode, "success");
    bool after_poll = !strcmp(mode, "failure-after-poll");
    bool before_poll = !strcmp(mode, "failure-before-poll");
    bool allocation = !strncmp(mode, "allocation-", 11);
    mp_int_t length = !strncmp(mode, "failure-length-", 15) ?
        (mp_int_t)strtol(mode + 15, NULL, 10) : -1;
    if (!success) tcp_error = MP_ECONNREFUSED;
    // Neither ready jobs nor failed native jobs may be observed by SO_TYPE or
    // invalid SO_ERROR requests. Validation must precede the sole finish attempt.
    option_forms(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, 0, MP_EOPNOTSUPP);
    option_errno(&s, 0, MPYNN_SOCKET_SO_ERROR, 0, MP_EOPNOTSUPP);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, 0, 0, MP_EOPNOTSUPP);
    option_raises(&s, &nonint_sentinel, (mp_obj_t)MPYNN_SOCKET_SO_ERROR, NULL, HOST_TYPE_ERROR);
    option_raises(&s, (mp_obj_t)MOD_NETWORK_SOL_SOCKET, &nonint_sentinel, NULL, HOST_TYPE_ERROR);
    option_raises(&s, (mp_obj_t)MOD_NETWORK_SOL_SOCKET, (mp_obj_t)MPYNN_SOCKET_SO_ERROR,
        &nonint_sentinel, HOST_TYPE_ERROR);
    const mp_int_t bad_lengths[] = {-1, (mp_int_t)sizeof(mp_int_t) + 1, INTPTR_MAX, INTPTR_MIN};
    for (unsigned i = 0; i < sizeof(bad_lengths)/sizeof(bad_lengths[0]); ++i)
        option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, bad_lengths[i], HOST_VALUE_ERROR);
    CHECK(tcp_job && !tcp_live && tcp_finishes == 1 && !tcp_cancels);
    CHECK(state(&s)->phase == TCP_PENDING && !tcp_error_queries);
    if (success) {
        option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, 0);
        CHECK(state(&s)->phase == TCP_CONNECTED && s.state == MOD_NETWORK_SS_CONNECTED);
        CHECK(tcp_finishes == 2 && !tcp_cancels && !tcp_job && tcp_live);
        CHECK(!state(&s)->connect_token && state(&s)->stream_token == 81);
        peer_is(&s, "192.0.2.1", 9000); // No getpeername prerequisite to promotion.
        option_forms(&s, MPYNN_SOCKET_SO_ERROR, 0);
        CHECK(tcp_finishes == 2 && !tcp_cancels);
    } else {
        if (after_poll) {
            CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_WR | MP_STREAM_POLL_ERR,
                &error) == MP_STREAM_POLL_ERR);
            CHECK(state(&s)->phase == TCP_FAILED && state(&s)->so_error == MP_ECONNREFUSED);
            CHECK(tcp_finishes == 2 && tcp_cancels == 1 && !tcp_job);
        }
        if (allocation) {
            CHECK(!strcmp(mode, "allocation-int") || !strcmp(mode, "allocation-bytes"));
            fail_option_result = true;
            option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR,
                !strcmp(mode, "allocation-int") ? 0 : 1, HOST_MEMORY_ERROR);
            fail_option_result = false;
            CHECK(state(&s)->so_error == MP_ECONNREFUSED);
            CHECK(state(&s)->sticky_error == MP_ECONNREFUSED);
            option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ECONNREFUSED,
                !strcmp(mode, "allocation-int") ? 0 : 1);
        } else option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_ECONNREFUSED, length);
        // Direct refusal, integer/native byte-prefix and pre/post-poll cache paths
        // all consume the report once without destroying the sticky failure.
        CHECK(state(&s)->phase == TCP_FAILED && s.state != MOD_NETWORK_SS_CONNECTED);
        CHECK(tcp_finishes == 2 && tcp_cancels == 1 && !tcp_job && !tcp_live);
        CHECK(!state(&s)->connect_token && !state(&s)->stream_token);
        CHECK(state(&s)->sticky_error == MP_ECONNREFUSED && !state(&s)->so_error);
        CHECK(state(&s)->so_error_native_checked && !tcp_error_queries);
        option_is(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM, -1);
        option_errno(&s, 0, MPYNN_SOCKET_SO_ERROR, 0, MP_EOPNOTSUPP);
        option_forms(&s, MPYNN_SOCKET_SO_ERROR, 0);
        if (before_poll || after_poll) {
            CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_WR | MP_STREAM_POLL_ERR,
                &error) == MP_STREAM_POLL_ERR);
            option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
            CHECK(!tcp_polls); // Cached failure never polls a nonexistent stream.
        }
        peer_raises(&s, MP_ECONNREFUSED);
        ERR(nic->connect(&s, peer, 9000, &error), MP_ECONNREFUSED);
        UERR(nic->send(&s, buffer, 3, &error), MP_ECONNREFUSED);
        UERR(nic->recv(&s, buffer, 3, &error), MP_ECONNREFUSED);
        option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
        CHECK(state(&s)->phase == TCP_FAILED && tcp_finishes == 2 && tcp_cancels == 1);
        CHECK(!tcp_reads && !tcp_writes && !format_calls);
    }
    // connect-start reads the clock once; sticky send/recv each read it once.
    // option_call checks every SO_ERROR/SO_TYPE invocation adds no clock reads.
    CHECK(!events && !delays && tick_calls == (success ? 1u : 3u));
    CHECK(now == 0 && s.timeout == 20);
    nic->close(&s);
    CHECK(tcp_cancels == (success ? 0u : 1u));
    CHECK(tcp_closes == (success ? 1u : 0u));
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, 0, MP_EBADF);
}
static void test_getsockopt_error_native(mp_int_t length) {
    mod_network_socket_obj_t s = tcp_new(0);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    tcp_ready = true; peer_is(&s, "192.0.2.1", 9000);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(tcp_error_queries == 1 && !state(&s)->so_error_native_checked);
    tcp_terminal_error = MP_EPIPE;
    option_is(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM, -1);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, 0, MP_EOPNOTSUPP);
    option_errno(&s, 0, MPYNN_SOCKET_SO_ERROR, 0, MP_EOPNOTSUPP);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR,
        (mp_int_t)sizeof(mp_int_t) + 1, HOST_VALUE_ERROR);
    CHECK(tcp_error_queries == 1 && !state(&s)->so_error_native_checked);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_EPIPE, length);
    CHECK(tcp_error_queries == 2 && state(&s)->so_error_native_checked);
    option_forms(&s, MPYNN_SOCKET_SO_ERROR, 0);
    CHECK(tcp_error_queries == 2 && tcp_terminal_error == MP_EPIPE);
    CHECK(state(&s)->phase == TCP_CONNECTED && s.state == MOD_NETWORK_SS_CONNECTED);
    CHECK(tcp_live && !tcp_closes && !tcp_reads && !tcp_writes && !tcp_polls);
    CHECK(!events && !delays && tcp_finishes == 1);
    nic->close(&s); CHECK(tcp_closes == 1);
}
static void test_getsockopt_error_finish_failure(int code) {
    mod_network_socket_obj_t s = tcp_new(0);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    tcp_error = code;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, code, 1);
    CHECK(state(&s)->phase == TCP_FAILED && state(&s)->sticky_error == code);
    CHECK(state(&s)->so_error_native_checked && !state(&s)->so_error);
    CHECK(tcp_finishes == 2 && tcp_cancels == 1 && !tcp_job && !tcp_live);
    CHECK(!state(&s)->connect_token && !state(&s)->stream_token && !tcp_error_queries);
    option_forms(&s, MPYNN_SOCKET_SO_ERROR, 0);
    ERR(nic->connect(&s, peer, 9000, &error), code);
    peer_raises(&s, code);
    CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_ERR, &error) == MP_STREAM_POLL_ERR);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(tcp_finishes == 2 && tcp_cancels == 1 && !tcp_polls && !events && !delays);
    nic->close(&s); CHECK(tcp_cancels == 1 && !tcp_closes);
}
static void test_getsockopt_error_native_allocation(mp_int_t length) {
    mod_network_socket_obj_t s = tcp_new(0);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    tcp_ready = true;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(state(&s)->phase == TCP_CONNECTED && tcp_finishes == 1);
    tcp_terminal_error = MP_EPIPE;
    fail_option_result = true;
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MPYNN_SOCKET_SO_ERROR, length, HOST_MEMORY_ERROR);
    fail_option_result = false;
    CHECK(state(&s)->so_error == MP_EPIPE && state(&s)->so_error_native_checked);
    CHECK(tcp_error_queries == 2 && !state(&s)->sticky_error);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, MP_EPIPE, length);
    option_forms(&s, MPYNN_SOCKET_SO_ERROR, 0);
    CHECK(tcp_error_queries == 2 && tcp_finishes == 1 && !tcp_cancels);
    CHECK(state(&s)->phase == TCP_CONNECTED && tcp_live && !tcp_closes);
    CHECK(!tcp_reads && !tcp_writes && !tcp_polls && !events && !delays);
    nic->close(&s); CHECK(tcp_closes == 1);
}
static void test_getsockopt_error_stream(const char *mode) {
    mod_network_socket_obj_t s = tcp_new(0);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    tcp_ready = true; peer_is(&s, "192.0.2.1", 9000);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    bool reading = !strcmp(mode, "read"), writing = !strcmp(mode, "write");
    bool poll_failure = !strcmp(mode, "poll-error");
    CHECK(reading || writing || poll_failure || !strcmp(mode, "poll"));
    if (reading) tcp_read_error = MP_EPIPE;
    else if (writing) tcp_write_error = MP_EPIPE;
    else if (poll_failure) tcp_poll_error = MP_ENOTCONN;
    int terminal = reading || writing ? MP_EPIPE : MP_ENOTCONN;
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1); // Query does not perform native IO.
    if (reading) UERR(nic->recv(&s, buffer, 3, &error), terminal);
    else if (writing) UERR(nic->send(&s, buffer, 3, &error), terminal);
    else if (poll_failure) ERR(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_ERR, &error), terminal);
    else {
        tcp_terminal_error = terminal; poll_events = MP_STREAM_POLL_ERR;
        CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_ERR, &error) == MP_STREAM_POLL_ERR);
    }
    option_is(&s, MPYNN_SOCKET_SO_TYPE, MOD_NETWORK_SOCK_STREAM, -1);
    option_errno(&s, MOD_NETWORK_SOL_SOCKET, MOD_NETWORK_SO_BROADCAST, 0, MP_EOPNOTSUPP);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, terminal, 0);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    CHECK(state(&s)->phase == TCP_CONNECTED && s.state == MOD_NETWORK_SS_CONNECTED);
    CHECK(tcp_live && !tcp_closes && !events && !delays && tcp_finishes == 1);
    // The persistent terminal condition remains consumed even if IO sees it again.
    if (reading) UERR(nic->recv(&s, buffer, 3, &error), terminal);
    else if (writing) UERR(nic->send(&s, buffer, 3, &error), terminal);
    else if (poll_failure) ERR(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_ERR, &error), terminal);
    else CHECK(nic->ioctl(&s, MP_STREAM_POLL, MP_STREAM_POLL_ERR, &error) == MP_STREAM_POLL_ERR);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    tcp_read_error = tcp_write_error = tcp_poll_error = tcp_terminal_error = 0;
    CHECK(nic->recv(&s, buffer, 3, &error) == 3);
    CHECK(nic->send(&s, buffer, 3, &error) == 2);
    option_is(&s, MPYNN_SOCKET_SO_ERROR, 0, -1);
    nic->close(&s); CHECK(tcp_closes == 1);
}
static void shutdown_call(mod_network_socket_obj_t *s, mp_int_t how, int code) {
    mod_network_socket_obj_t before = *s;
    udp_state_t private_before = {0};
    bool inspect = s->state != MOD_NETWORK_SS_CLOSED && state(s);
    if (inspect) private_before = *state(s);
    bool native = inspect && how >= 0 && how <= 2 &&
        s->domain == MOD_NETWORK_AF_INET && s->type == MOD_NETWORK_SOCK_STREAM &&
        (s->proto == 0 || s->proto == 6) && private_before.phase == TCP_CONNECTED;
    option_observation_t counters = observe_option();
    unsigned queries = tcp_error_queries, udp_queries = udp_error_queries;
    unsigned conversions = int_conversions, ints = int_results, bytes = bytes_results;
    bool rd_before = tcp_shutdown_rd, wr_before = tcp_shutdown_wr;
    bool live_before = tcp_live, job_before = tcp_job, listener_before = listener_live;
    int terminal_before = tcp_terminal_error, pending_before = udp_pending_error;
    byte data_before[sizeof(buffer)]; memcpy(data_before, buffer, sizeof(buffer));
    nlr_buf_t outer;
    if (nlr_push(&outer) == 0) {
        CHECK(mpynn_socket_shutdown(MP_OBJ_FROM_PTR(s), (mp_obj_t)how) == mp_const_none);
        nlr_pop(); CHECK(code == 0);
    } else CHECK(code != 0 && outer.ret_val == (void *)(intptr_t)code);
    option_observation_t after = observe_option();
    CHECK(after.values[32] == counters.values[32] + (native ? 1u : 0u));
    after.values[32] = counters.values[32]; // This is the sole allowed native call.
    CHECK(!memcmp(&after, &counters, sizeof(counters)));
    CHECK(int_conversions == conversions + (before.state == MOD_NETWORK_SS_CLOSED ? 0u : 1u));
    CHECK(int_results == ints && bytes_results == bytes);
    CHECK(tcp_error_queries == queries && udp_error_queries == udp_queries);
    CHECK(tcp_live == live_before && tcp_job == job_before && listener_live == listener_before);
    CHECK(tcp_terminal_error == terminal_before && udp_pending_error == pending_before);
    CHECK(tcp_shutdown_rd == (rd_before || (native && !code && how != 1)));
    CHECK(tcp_shutdown_wr == (wr_before || (native && !code && how != 0)));
    CHECK(!memcmp(buffer, data_before, sizeof(buffer)));
    CHECK(!memcmp(s, &before, sizeof(before)));
    if (inspect) {
        udp_state_t expected_private = private_before;
        // Only a successful native WR/BOTH shutdown changes the adapter's
        // write-side latch; failed shutdowns leave every private field intact.
        if (native && !code && how != 0) expected_private.write_shutdown = true;
        CHECK(!memcmp(state(s), &expected_private, sizeof(expected_private)));
    }
    CHECK(nlr_top == NULL);
}
static void shutdown_raises(mod_network_socket_obj_t *s, mp_int_t how, int code) {
    CHECK(code != 0); shutdown_call(s, how, code);
}
static void shutdown_is(mod_network_socket_obj_t *s, mp_int_t how) {
    shutdown_call(s, how, 0);
}
static void shutdown_io_is(mod_network_socket_obj_t *s, bool rd, bool wr) {
    mod_network_socket_obj_t before = *s;
    // The fake's nonzero read count models data cached before RD shutdown.
    CHECK(tcp_read_count == 3);
    CHECK(nic->recv(s, buffer, 3, &error) == (rd ? 0u : 3u));
    if (wr) UERR(nic->send(s, buffer, 3, &error), MP_EPIPE);
    else CHECK(nic->send(s, buffer, 3, &error) == 2);
    const unsigned masks[] = {0, MP_STREAM_POLL_RD, MP_STREAM_POLL_WR,
        MP_STREAM_POLL_ERR, MP_STREAM_POLL_HUP, MP_STREAM_POLL_NVAL,
        MP_STREAM_POLL_RD | MP_STREAM_POLL_WR,
        MP_STREAM_POLL_RD | MP_STREAM_POLL_WR | MP_STREAM_POLL_ERR | MP_STREAM_POLL_HUP};
    poll_events = MP_STREAM_POLL_WR; // RD must be ready due to EOF, not native RX.
    for (unsigned i = 0; i < sizeof(masks)/sizeof(masks[0]); ++i) {
        unsigned ready = (rd ? MP_STREAM_POLL_RD : 0) | (wr ? 0 : MP_STREAM_POLL_WR);
        CHECK(nic->ioctl(s, MP_STREAM_POLL, masks[i], &error) == (int)(ready & masks[i]));
    }
    CHECK(!memcmp(s, &before, sizeof(before)));
    CHECK(state(s)->phase == TCP_CONNECTED && tcp_live && !tcp_closes);
}
static void test_shutdown(const char *mode) {
    mod_network_socket_obj_t s = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM, .state=MOD_NETWORK_SS_NEW};
    if (!strcmp(mode, "validation")) {
        shutdown_raises(&s, -1, MP_EINVAL);
        shutdown_raises(&s, 3, MP_EINVAL);
        shutdown_raises(&s, INTPTR_MAX, MP_EINVAL); // No narrowing to a valid mode.
        for (int how = 0; how <= 2; ++how) shutdown_raises(&s, how, MP_ENOTCONN);
        s.type = MOD_NETWORK_SOCK_DGRAM;
        for (int how = 0; how <= 2; ++how) shutdown_raises(&s, how, MP_EOPNOTSUPP);
        s.type = 3; shutdown_raises(&s, 1, MP_EOPNOTSUPP);
        s.type = MOD_NETWORK_SOCK_STREAM; s.proto = 17;
        shutdown_raises(&s, 1, MP_EOPNOTSUPP);
        s.proto = 6; s.domain = 99; shutdown_raises(&s, 1, MP_EAFNOSUPPORT);
        s.state = MOD_NETWORK_SS_CLOSED; s._private = (void *)1;
        for (int how = -1; how <= 3; ++how) shutdown_raises(&s, how, MP_EBADF);
        CHECK(!allocation_count && !opens && !tcp_starts); return;
    }
    if (!strcmp(mode, "udp")) {
        s = socket_new();
        for (int how = 0; how <= 2; ++how) shutdown_raises(&s, how, MP_EOPNOTSUPP);
        CHECK(!opens);
        CHECK(nic->connect(&s, peer, 9000, &error) == 0);
        for (int how = 0; how <= 2; ++how) shutdown_raises(&s, how, MP_EOPNOTSUPP);
        CHECK(connected_io(&s, false) == 3 && connected_io(&s, true) == 3);
        nic->close(&s); return;
    }
    s = tcp_new(0);
    if (!strcmp(mode, "phases")) {
        shutdown_raises(&s, 1, MP_ENOTCONN);
        CHECK(nic->bind(&s, wildcard, 9000, &error) == 0);
        shutdown_raises(&s, 1, MP_ENOTCONN);
        CHECK(nic->listen(&s, 1, &error) == 0);
        shutdown_raises(&s, 1, MP_ENOTCONN);
        nic->close(&s);
        shutdown_raises(&s, 1, MP_EBADF);
        s = tcp_new(0);
        ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
        for (int how = 0; how <= 2; ++how) shutdown_raises(&s, how, MP_ENOTCONN);
        tcp_ready = true; // Shutdown must not promote even a now-ready job.
        shutdown_raises(&s, 1, MP_ENOTCONN);
        CHECK(tcp_job && !tcp_live && !tcp_finishes && !tcp_cancels);
        tcp_error = MP_ECONNREFUSED;
        peer_raises(&s, MP_ECONNREFUSED);
        shutdown_raises(&s, 1, MP_ENOTCONN);
        nic->close(&s); return;
    }
    // Each connected/accepted mode runs in a fresh process, never inherits flags
    // from an earlier half-close. Generic accept initializes family/type/proto.
    mod_network_socket_obj_t child = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM, .proto=6};
    bool accepted = !strncmp(mode, "accepted-", 9);
    CHECK(accepted || !strncmp(mode, "connected-", 10));
    const char *operation = mode + (accepted ? 9 : 10);
    bool errors = !strcmp(operation, "errors");
    bool terminal = !strcmp(operation, "terminal");
    bool combo_rd = !strcmp(operation, "rd-wr");
    bool combo_wr = !strcmp(operation, "wr-rd");
    int how = !strcmp(operation, "rd") || combo_rd ? 0 :
        !strcmp(operation, "wr") || combo_wr ? 1 : 2;
    CHECK(errors || terminal || combo_rd || combo_wr ||
        !strcmp(operation, "rd") || !strcmp(operation, "wr") || !strcmp(operation, "both"));
    nodelay_set(&s, 0, 0); // Explicit setting survives connect or is inherited.
    CHECK(nic->bind(&s, wildcard, 9000, &error) == 0);
    if (accepted) {
        CHECK(nic->listen(&s, 1, &error) == 0); listener_ready = true;
        stream_local_port = 9000;
        byte ip[4]; mp_uint_t port;
        CHECK(nic->accept(&s, &child, ip, &port, &error) == 0);
        CHECK(state(&child)->nodelay_configured && !state(&child)->nodelay);
    } else {
        s.timeout = 20; tcp_ready = true;
        CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    }
    mod_network_socket_obj_t *stream = accepted ? &child : &s;
    CHECK(!tcp_shutdown_rd && !tcp_shutdown_wr && nodelay_calls == 1 && !nodelay_value);
    peer_is(stream, "192.0.2.1", 9000);
    local_is(stream, "198.51.100.7", 9000);
    nodelay_forms(stream, false);
    option_is(stream, MPYNN_SOCKET_SO_ERROR, 0, -1);
    shutdown_raises(stream, -1, MP_EINVAL);
    shutdown_raises(stream, 3, MP_EINVAL);
    shutdown_raises(stream, INTPTR_MIN, MP_EINVAL);
    shutdown_raises(stream, INTPTR_MAX, MP_EINVAL);
    CHECK(!tcp_shutdown_calls);
    if (errors) {
        // A synchronous shutdown failure is neither a terminal adapter report nor
        // an implicit close: every mode forwards once, retaining all native flags.
        for (int round = 0; round < 2; ++round) {
            tcp_shutdown_error = round ? MP_ENOTCONN : MP_EBUSY;
            for (int mode_how = 0; mode_how <= 2; ++mode_how) {
                shutdown_raises(stream, mode_how, tcp_shutdown_error);
                option_is(stream, MPYNN_SOCKET_SO_ERROR, 0, -1);
                shutdown_io_is(stream, false, false);
            }
        }
        tcp_shutdown_error = 0;
        shutdown_is(stream, 1);
        // Failure after one successful half-close must not enable the other half.
        tcp_shutdown_error = MP_ENOTCONN;
        shutdown_raises(stream, 2, MP_ENOTCONN);
        CHECK(!tcp_shutdown_rd && tcp_shutdown_wr && !state(stream)->so_error);
        tcp_shutdown_error = 0;
        shutdown_is(stream, 0);
        CHECK(tcp_shutdown_calls == 9);
    } else if (terminal) {
        tcp_terminal_error = MP_ECONNREFUSED;
        for (int mode_how = 0; mode_how <= 2; ++mode_how)
            shutdown_raises(stream, mode_how, MP_ECONNREFUSED);
        CHECK(!tcp_shutdown_rd && !tcp_shutdown_wr && !state(stream)->so_error);
        // The pre-existing native report remains independently available exactly
        // once; shutdown itself does not cache, consume or replace SO_ERROR.
        option_is(stream, MPYNN_SOCKET_SO_ERROR, MP_ECONNREFUSED, -1);
        option_is(stream, MPYNN_SOCKET_SO_ERROR, 0, -1);
        shutdown_raises(stream, 2, MP_ECONNREFUSED);
        option_is(stream, MPYNN_SOCKET_SO_ERROR, 0, -1);
        CHECK(tcp_shutdown_calls == 4);
    } else {
        // A local write after SHUT_WR/BOTH still raises EPIPE, but that local
        // condition is excluded from SO_ERROR once the adapter's WR latch is set.
        // Exercise both terminal errno values after the first local EPIPE: the
        // native report is queried once, latched, then consumed to zero.
        int injected_terminal = accepted ? MP_ECONNREFUSED : MP_EIO;
        for (int round = 0; round < 2; ++round) {
            shutdown_is(stream, how);
            option_is(stream, MPYNN_SOCKET_SO_ERROR, 0, -1); // Half-close is not an error.
            shutdown_io_is(stream, how != 1, how != 0);
            if (how != 0) {
                unsigned queries_before = tcp_error_queries;
                // With no native terminal condition, SO_ERROR may query the
                // bridge repeatedly; local EPIPE is filtered by write_shutdown.
                option_is(stream, MPYNN_SOCKET_SO_ERROR, 0, -1);
                CHECK(tcp_error_queries == queries_before + 1);
            }
        }
        CHECK(tcp_shutdown_calls == 2);
        if (combo_rd || combo_wr) {
            shutdown_is(stream, how == 0 ? 1 : 0);
            shutdown_io_is(stream, true, true);
            // The write-side EPIPE remains local and does not re-arm SO_ERROR.
            option_is(stream, MPYNN_SOCKET_SO_ERROR, 0, -1);
            shutdown_is(stream, 2); // Both is still forwarded after separate halves.
            shutdown_is(stream, 2);
            CHECK(tcp_shutdown_calls == 5);
        }
        // Inject a genuine native terminal report only after local EPIPE has
        // been observed and queried. It is latched once and consumed once.
        tcp_terminal_error = injected_terminal;
        unsigned queries_before = tcp_error_queries;
        option_is(stream, MPYNN_SOCKET_SO_ERROR, injected_terminal, -1);
        CHECK(tcp_error_queries == queries_before + 1);
        option_is(stream, MPYNN_SOCKET_SO_ERROR, 0, -1);
        CHECK(tcp_error_queries == queries_before + 1);
        CHECK(state(stream)->so_error_native_checked && !state(stream)->so_error);
        tcp_terminal_error = 0;
    }
    peer_is(stream, "192.0.2.1", 9000);
    local_is(stream, "198.51.100.7", 9000);
    nodelay_forms(stream, false);
    CHECK(tcp_live && !tcp_closes && !events && !delays && nodelay_calls == 1);
    if (accepted) {
        // Listener ownership/state/options are independent of the child's halves.
        CHECK(state(&s)->phase == TCP_LISTENING && listener_live);
        nodelay_forms(&s, false); local_is(&s, "0.0.0.0", 9000);
        nic->close(&s); nic->close(&s);
        CHECK(listener_closes == 1 && tcp_live);
        peer_is(stream, "192.0.2.1", 9000);
    }
    nic->close(stream); nic->close(stream);
    shutdown_raises(stream, 1, MP_EBADF);
    CHECK(tcp_closes == 1 && !tcp_live && !tcp_shutdown_rd && !tcp_shutdown_wr);
}
// Directional timeout options are adapter-local configuration: neither setting
// nor querying may open a transport, poll, read the clock, yield, or take errors.
static void timeout_set_raw(mod_network_socket_obj_t *s, mp_uint_t level,
                            mp_uint_t opt, const void *value, mp_uint_t len,
                            int expected_error) {
    mod_network_socket_obj_t socket_before = *s;
    bool inspect = state(s) && s->state != MOD_NETWORK_SS_CLOSED;
    udp_state_t expected = {0};
    if (inspect) expected = *state(s);
    option_observation_t before = observe_option();
    unsigned tcp_queries = tcp_error_queries, udp_queries = udp_error_queries;
    int result = nic->setsockopt(s, level, opt, value, len, &error);
    CHECK(result == (expected_error ? -1 : 0));
    if (expected_error) CHECK(error == expected_error);
    option_observation_t after = observe_option();
    CHECK(!memcmp(&before, &after, sizeof(before)));
    CHECK(tcp_error_queries == tcp_queries && udp_error_queries == udp_queries);
    CHECK(!memcmp(s, &socket_before, sizeof(socket_before)));
    if (inspect) {
        if (!expected_error) {
            mp_int_t ms; memcpy(&ms, value, sizeof(ms));
            if (opt == MOD_NETWORK_SO_SNDTIMEO) {
                expected.send_timeout_set = true;
                expected.send_timeout = ms ? (int32_t)ms : -1;
            } else {
                CHECK(opt == MOD_NETWORK_SO_RCVTIMEO);
                expected.recv_timeout_set = true;
                expected.recv_timeout = ms ? (int32_t)ms : -1;
            }
        }
        CHECK(!memcmp(state(s), &expected, sizeof(expected)));
    }
}
static void timeout_set(mod_network_socket_obj_t *s, bool writing, mp_int_t ms) {
    timeout_set_raw(s, MOD_NETWORK_SOL_SOCKET,
        writing ? MOD_NETWORK_SO_SNDTIMEO : MOD_NETWORK_SO_RCVTIMEO,
        &ms, sizeof(ms), 0);
}
static void test_direction_options(void) {
    const mp_int_t opts[] = {MOD_NETWORK_SO_SNDTIMEO, MOD_NETWORK_SO_RCVTIMEO};
    mod_network_socket_obj_t fresh = {.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_DGRAM, .state=MOD_NETWORK_SS_NEW, .timeout=-1};
    for (unsigned i = 0; i < 2; ++i) {
        fresh.domain = 99;
        option_errno(&fresh, MOD_NETWORK_SOL_SOCKET, opts[i], 0, MP_EAFNOSUPPORT);
        fresh.domain = MOD_NETWORK_AF_INET; fresh.type = 99;
        option_errno(&fresh, MOD_NETWORK_SOL_SOCKET, opts[i], 0, MP_EOPNOTSUPP);
        fresh.type = MOD_NETWORK_SOCK_DGRAM; fresh.proto = 6;
        option_errno(&fresh, MOD_NETWORK_SOL_SOCKET, opts[i], 0, MP_EOPNOTSUPP);
    }
    for (unsigned transport = 0; transport < 2; ++transport) {
        fresh.type = transport ? MOD_NETWORK_SOCK_STREAM : MOD_NETWORK_SOCK_DGRAM;
        fresh.proto = transport ? 6 : 17;
        for (unsigned i = 0; i < 2; ++i) {
            fresh.timeout = -1; option_forms(&fresh, opts[i], 0);
            fresh.timeout = 37; option_forms(&fresh, opts[i], 37);
            fresh.timeout = 0; option_forms(&fresh, opts[i], 0);
        }
        mod_network_socket_obj_t s = transport ? tcp_new(37) : socket_new();
        CHECK(!state(&s)->send_timeout_set && !state(&s)->recv_timeout_set);
        CHECK(nic->settimeout(&s, 37, &error) == 0);
        CHECK(!state(&s)->send_timeout_set && !state(&s)->recv_timeout_set);
        for (unsigned i = 0; i < 2; ++i) {
            mp_int_t opt = opts[i], valid = 41, negative = -1;
            option_forms(&s, opt, 37);
            timeout_set_raw(&s, MOD_NETWORK_SOL_SOCKET, opt, NULL, sizeof(valid), MP_EINVAL);
            timeout_set_raw(&s, MOD_NETWORK_SOL_SOCKET, opt, &valid, 0, MP_EINVAL);
            timeout_set_raw(&s, MOD_NETWORK_SOL_SOCKET, opt, &valid, sizeof(valid)-1, MP_EINVAL);
            timeout_set_raw(&s, MOD_NETWORK_SOL_SOCKET, opt, &valid, sizeof(valid)+1, MP_EINVAL);
            timeout_set_raw(&s, MOD_NETWORK_SOL_SOCKET, opt, &negative, sizeof(negative), MP_EINVAL);
            if (sizeof(mp_int_t) > sizeof(int32_t)) {
                mp_int_t overflow = (mp_int_t)((mp_uint_t)INT32_MAX + 1);
                timeout_set_raw(&s, MOD_NETWORK_SOL_SOCKET, opt, &overflow, sizeof(overflow), MP_EINVAL);
            }
            timeout_set_raw(&s, MPYNN_SOCKET_IPPROTO_TCP, opt, &valid, sizeof(valid), MP_EOPNOTSUPP);
            // Unaligned native integers are valid; wrapper normalization is separate.
            byte unaligned[sizeof(valid)+1]; memcpy(unaligned+1, &valid, sizeof(valid));
            timeout_set_raw(&s, MOD_NETWORK_SOL_SOCKET, opt, unaligned+1, sizeof(valid), 0);
            option_forms(&s, opt, valid);
            timeout_set(&s, i == 0, INT32_MAX); option_forms(&s, opt, INT32_MAX);
            timeout_set(&s, i == 0, 0); option_forms(&s, opt, 0);
            timeout_set(&s, i == 0, 0x01020304); option_forms(&s, opt, 0x01020304);
            fail_option_result = true;
            option_errno(&s, MOD_NETWORK_SOL_SOCKET, opt, 0, HOST_MEMORY_ERROR);
            option_errno(&s, MOD_NETWORK_SOL_SOCKET, opt, 1, HOST_MEMORY_ERROR);
            fail_option_result = false; option_forms(&s, opt, 0x01020304);
            option_errno(&s, 0, opt, 0, MP_EOPNOTSUPP);
            option_errno(&s, MOD_NETWORK_SOL_SOCKET, opt, -1, HOST_VALUE_ERROR);
            option_errno(&s, MOD_NETWORK_SOL_SOCKET, opt, sizeof(mp_int_t)+1, HOST_VALUE_ERROR);
            option_raises(&s, &nonint_sentinel, (mp_obj_t)opt, NULL, HOST_TYPE_ERROR);
            option_raises(&s, (mp_obj_t)MOD_NETWORK_SOL_SOCKET, (mp_obj_t)opt,
                &nonint_sentinel, HOST_TYPE_ERROR);
        }
        CHECK(s.timeout == 37 && !opens && !tcp_starts && !listener_opens);
        ERR(nic->settimeout(&s, (mp_uint_t)INT32_MAX+1, &error), MP_EINVAL);
        CHECK(state(&s)->send_timeout_set && state(&s)->recv_timeout_set && s.timeout == 37);
        for (unsigned i = 0; i < 3; ++i) {
            mp_int_t ms = i == 0 ? 19 : i == 1 ? -1 : 0;
            CHECK(nic->settimeout(&s, (mp_uint_t)ms, &error) == 0);
            CHECK(!state(&s)->send_timeout_set && !state(&s)->recv_timeout_set);
            option_forms(&s, opts[0], ms < 0 ? 0 : ms);
            option_forms(&s, opts[1], ms < 0 ? 0 : ms);
            timeout_set(&s, true, 7); timeout_set(&s, false, 11);
        }
        // Query reports configured values even though nonblocking dominates IO.
        CHECK(s.timeout == 0); option_forms(&s, opts[0], 7); option_forms(&s, opts[1], 11);
        nic->close(&s);
        for (unsigned i = 0; i < 2; ++i) {
            mp_int_t value = 5;
            timeout_set_raw(&s, MOD_NETWORK_SOL_SOCKET, opts[i], &value, sizeof(value), MP_EBADF);
            option_errno(&s, MOD_NETWORK_SOL_SOCKET, opts[i], 0, MP_EBADF);
            option_raises(&s, &nonint_sentinel, (mp_obj_t)opts[i], &nonint_sentinel, MP_EBADF);
        }
    }
}
static mod_network_socket_obj_t *direction_callback_socket;
static bool direction_callback_writing;
static int direction_callback_action;
static void direction_advance_clock(void) {
    event_callback = NULL; now += 20000;
}
static void direction_change_timeout(void) {
    event_callback = NULL;
    if (direction_callback_action == 1) {
        CHECK(nic->settimeout(direction_callback_socket, 0, &error) == 0);
    } else if (direction_callback_action == 2) {
        timeout_set(direction_callback_socket, direction_callback_writing, 1);
    } else timeout_set(direction_callback_socket, direction_callback_writing, 100);
}
static mp_uint_t direction_io(mod_network_socket_obj_t *s, const char *operation) {
    if (!strcmp(operation, "sendto")) return send_one(s);
    if (!strcmp(operation, "recvfrom")) return recv_one(s);
    if (!strcmp(operation, "send")) return nic->send(s, buffer, 3, &error);
    CHECK(!strcmp(operation, "recv")); return nic->recv(s, buffer, 3, &error);
}
static void test_direction_io(bool tcp, const char *operation, const char *mode) {
    static mod_network_socket_obj_t s;
    bool writing = !strncmp(operation, "send", 4);
    s = tcp ? tcp_new(9) : socket_new();
    if (tcp) tcp_ready = true;
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    CHECK(nic->settimeout(&s, 9, &error) == 0);
    timeout_set(&s, true, 2); timeout_set(&s, false, 4);
    option_forms(&s, MOD_NETWORK_SO_SNDTIMEO, 2);
    option_forms(&s, MOD_NETWORK_SO_RCVTIMEO, 4);
    tcp_read_error = tcp_write_error = send_error = recv_error = MP_EAGAIN;
    unsigned budget = writing ? 2 : 4;
    if (!strcmp(mode, "nonblocking")) s.timeout = 0;
    else if (!strcmp(mode, "blocking-timeout")) s.timeout = -1;
    else if (!strcmp(mode, "infinite")) {
        timeout_set(&s, writing, 0); success_after_delay = true;
        event_callback = direction_advance_clock;
    } else if (!strcmp(mode, "inherited")) {
        CHECK(nic->settimeout(&s, 3, &error) == 0); budget = 3;
    } else if (!strcmp(mode, "inherited-callback")) {
        CHECK(nic->settimeout(&s, 3, &error) == 0); budget = 3;
        direction_callback_socket = &s; direction_callback_writing = writing;
        direction_callback_action = 1; event_callback = direction_change_timeout;
    } else if (!strcmp(mode, "reset-blocking")) {
        CHECK(nic->settimeout(&s, (mp_uint_t)-1, &error) == 0);
        success_after_delay = true;
    } else if (!strcmp(mode, "event-close")) close_on_event = &s;
    else if (!strcmp(mode, "interrupt")) interrupt_event = true;
    else if (!strcmp(mode, "errors")) tcp_read_error = tcp_write_error = send_error = recv_error = MP_ENETDOWN;
    else if (!strncmp(mode, "callback-", 9)) {
        direction_callback_socket = &s; direction_callback_writing = writing;
        direction_callback_action = !strcmp(mode+9, "reset") ? 1 : !strcmp(mode+9, "shorter") ? 2 : 0;
        event_callback = direction_change_timeout;
    } else CHECK(!strcmp(mode, "timeout"));
    if (interrupt_event) {
        nlr_buf_t outer;
        if (nlr_push(&outer) == 0) {
            direction_io(&s, operation); nlr_pop(); CHECK(false);
        } else CHECK(outer.ret_val == (void *)123);
        CHECK(events == 1 && !delays && (tcp ? tcp_live : live));
        interrupt_event = false;
    } else if (success_after_delay) {
        CHECK(direction_io(&s, operation) == (tcp && writing ? 2u : 3u));
        CHECK(events == 1 && delays == 1 && now == (!strcmp(mode, "infinite") ? 21000u : 1000u));
    } else if (!strcmp(mode, "event-close")) {
        UERR(direction_io(&s, operation), MP_EBADF);
        CHECK(events == 1 && !delays && !s._private);
    } else if (!strcmp(mode, "errors")) {
        UERR(direction_io(&s, operation), MP_ENETDOWN); CHECK(!events && !delays && !now);
    } else if (!strcmp(mode, "nonblocking")) {
        UERR(direction_io(&s, operation), MP_EAGAIN); CHECK(!events && !delays && !now);
    } else {
        UERR(direction_io(&s, operation), MP_ETIMEDOUT);
        CHECK(now == (uint64_t)budget*1000 && events == budget && delays == budget);
        CHECK((tcp ? (writing ? tcp_writes : tcp_reads) :
            (!strcmp(operation, "sendto") ? sends : writing ? connected_sends : recvs)) == budget);
    }
    int expected_timeout = !strcmp(mode, "nonblocking") || !strcmp(mode, "callback-reset") ||
        !strcmp(mode, "inherited-callback") ? 0 :
        !strcmp(mode, "inherited") ? 3 :
        !strcmp(mode, "reset-blocking") || !strcmp(mode, "blocking-timeout") ? -1 : 9;
    CHECK(s.timeout == expected_timeout && nlr_top == NULL);
    nic->close(&s); nic->close(&s);
    CHECK(tcp ? tcp_closes == 1 : closes == 1);
}
static void test_direction_sendall(const char *mode) {
    static mod_network_socket_obj_t s;
    s = tcp_new(9); tcp_ready = true;
    CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    timeout_set(&s, true, 3); timeout_set(&s, false, 1);
    if (!strcmp(mode, "success")) {
        write_step(0, 2, 1000); write_step(0, 6, 1000); sendall_ok(&s);
        CHECK(tcp_writes == 2 && written_bytes == 8 && now == 2000);
    } else if (!strcmp(mode, "infinite")) {
        timeout_set(&s, true, 0);
        write_step(0, 2, 10000000); write_step(0, 6, 10000000); sendall_ok(&s);
        CHECK(written_bytes == 8 && now == 20000000);
    } else if (!strcmp(mode, "nonblocking")) {
        s.timeout = 0; write_step(MP_EAGAIN, 0, 0); sendall_raises(&s, MP_EAGAIN);
        CHECK(tcp_writes == 1 && !events && !delays);
    } else {
        write_step(0, 2, 1000); write_step(MP_EAGAIN, 0, 0);
        write_step(MP_EAGAIN, 0, 0); write_step(0, 6, 0);
        if (!strncmp(mode, "callback-", 9)) {
            direction_callback_socket = &s; direction_callback_writing = true;
            direction_callback_action = !strcmp(mode+9, "reset") ? 1 : !strcmp(mode+9, "shorter") ? 2 : 0;
            event_callback = direction_change_timeout;
        } else CHECK(!strcmp(mode, "timeout"));
        sendall_raises(&s, MP_ETIMEDOUT);
        CHECK(now == 3000 && written_bytes == 2 && tcp_writes == 3);
    }
    CHECK(s.timeout == (!strcmp(mode, "nonblocking") || !strcmp(mode, "callback-reset") ? 0 : 9));
    nic->close(&s); CHECK(tcp_closes == 1);
}
static void test_direction_accept(const char *mode) {
    static mod_network_socket_obj_t s, child;
    s = tcp_new(9); child = (mod_network_socket_obj_t){.domain=MOD_NETWORK_AF_INET,
        .type=MOD_NETWORK_SOCK_STREAM, .timeout=777};
    timeout_set(&s, true, 1); timeout_set(&s, false, 3);
    CHECK(nic->listen(&s, 1, &error) == 0);
    option_forms(&s, MOD_NETWORK_SO_SNDTIMEO, 1);
    option_forms(&s, MOD_NETWORK_SO_RCVTIMEO, 3);
    timeout_set(&s, true, 1); timeout_set(&s, false, 3);
    byte ip[4]; mp_uint_t port;
    if (!strcmp(mode, "timeout")) {
        ERR(nic->accept(&s, &child, ip, &port, &error), MP_ETIMEDOUT);
        CHECK(now == 3000 && events == 3 && delays == 3 && listener_accepts == 3);
        CHECK(!child._private && listener_live && !tcp_live);
    } else if (!strcmp(mode, "nonblocking")) {
        s.timeout = 0; ERR(nic->accept(&s, &child, ip, &port, &error), MP_EAGAIN);
        CHECK(!events && !delays && listener_accepts == 1 && !child._private);
    } else if (!strcmp(mode, "event-close")) {
        close_on_event = &s;
        ERR(nic->accept(&s, &child, ip, &port, &error), MP_EBADF);
        CHECK(events == 1 && !delays && !s._private && !child._private && !listener_live);
    } else if (!strcmp(mode, "interrupt")) {
        interrupt_event = true; nlr_buf_t outer;
        if (nlr_push(&outer) == 0) {
            nic->accept(&s, &child, ip, &port, &error); nlr_pop(); CHECK(false);
        } else CHECK(outer.ret_val == (void *)123);
        CHECK(events == 1 && !delays && !child._private && listener_live);
        interrupt_event = false;
    } else if (!strcmp(mode, "child") || !strcmp(mode, "infinite")) {
        listener_after_delay = true;
        if (!strcmp(mode, "infinite")) {
            timeout_set(&s, false, 0); event_callback = direction_advance_clock;
        }
        CHECK(nic->accept(&s, &child, ip, &port, &error) == 0);
        CHECK(now == (!strcmp(mode, "infinite") ? 21000u : 1000u) && child.timeout == -1);
        CHECK(!state(&child)->send_timeout_set && !state(&child)->recv_timeout_set);
        option_forms(&child, MOD_NETWORK_SO_SNDTIMEO, 0);
        option_forms(&child, MOD_NETWORK_SO_RCVTIMEO, 0);
        CHECK(s.timeout == 9 && state(&s)->send_timeout_set && state(&s)->recv_timeout_set);
        nic->close(&child);
    } else {
        direction_callback_socket = &s; direction_callback_writing = false;
        direction_callback_action = !strcmp(mode, "callback-reset") ? 1 : 0;
        event_callback = direction_change_timeout;
        ERR(nic->accept(&s, &child, ip, &port, &error), MP_ETIMEDOUT);
        CHECK(now == 3000 && listener_accepts == 3 && !child._private);
    }
    nic->close(&s); CHECK(listener_closes == 1);
}
static void test_direction_udp_sendall(const char *mode) {
    static mod_network_socket_obj_t s;
    s = socket_new(); CHECK(nic->connect(&s, peer, 9000, &error) == 0);
    CHECK(nic->settimeout(&s, 9, &error) == 0);
    timeout_set(&s, true, 3); timeout_set(&s, false, 1);
    send_error = MP_EAGAIN;
    if (!strcmp(mode, "infinite")) {
        timeout_set(&s, true, 0); success_after_delay = true; sendall_ok(&s);
        CHECK(connected_sends == 2 && now == 1000);
    } else if (!strcmp(mode, "nonblocking")) {
        s.timeout = 0; sendall_raises(&s, MP_EAGAIN);
        CHECK(connected_sends == 1 && !events && !delays);
    } else {
        if (!strcmp(mode, "callback-reset")) {
            direction_callback_socket = &s; direction_callback_writing = true;
            direction_callback_action = 1; event_callback = direction_change_timeout;
        } else CHECK(!strcmp(mode, "timeout"));
        sendall_raises(&s, MP_ETIMEDOUT);
        CHECK(now == 3000 && connected_sends == 3 && events == 3 && delays == 3);
    }
    CHECK(s.timeout == (!strcmp(mode, "nonblocking") || !strcmp(mode, "callback-reset") ? 0 : 9));
    nic->close(&s); CHECK(closes == 1);
}
static void test_direction_pending(const char *operation) {
    mod_network_socket_obj_t s = tcp_new(0);
    ERR(nic->connect(&s, peer, 9000, &error), MP_EINPROGRESS);
    CHECK(nic->settimeout(&s, 9, &error) == 0);
    timeout_set(&s, true, 2); timeout_set(&s, false, 4);
    unsigned finishes = tcp_finishes;
    option_forms(&s, MOD_NETWORK_SO_SNDTIMEO, 2);
    option_forms(&s, MOD_NETWORK_SO_RCVTIMEO, 4);
    CHECK(tcp_finishes == finishes && tcp_job); // Pure queries never promote pending TCP.
    bool writing = !strcmp(operation, "send");
    UERR(direction_io(&s, operation), MP_ETIMEDOUT);
    CHECK(now == (uint64_t)(writing ? 2 : 4)*1000);
    CHECK(tcp_cancels == 1 && !tcp_job && !tcp_live && !tcp_reads && !tcp_writes);
    CHECK(s.timeout == 9 && state(&s)->send_timeout_set && state(&s)->recv_timeout_set);
    nic->close(&s);
}
static void test_direction_connect(void) {
    mod_network_socket_obj_t s = tcp_new(3);
    timeout_set(&s, true, 1); timeout_set(&s, false, 2);
    ERR(nic->connect(&s, peer, 9000, &error), MP_ETIMEDOUT);
    CHECK(now == 3000 && tcp_cancels == 1 && !tcp_job && s.timeout == 3);
    option_forms(&s, MOD_NETWORK_SO_SNDTIMEO, 1);
    option_forms(&s, MOD_NETWORK_SO_RCVTIMEO, 2);
    nic->close(&s);
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    if (!strcmp(argv[1], "direction-options")) test_direction_options();
    else if (!strcmp(argv[1], "direction-connect")) test_direction_connect();
    else if (!strncmp(argv[1], "direction-pending-", sizeof("direction-pending-")-1)) test_direction_pending(argv[1]+sizeof("direction-pending-")-1);
    else if (!strncmp(argv[1], "direction-udp-sendall-", sizeof("direction-udp-sendall-")-1)) test_direction_udp_sendall(argv[1]+sizeof("direction-udp-sendall-")-1);
    else if (!strncmp(argv[1], "direction-sendall-", sizeof("direction-sendall-")-1)) test_direction_sendall(argv[1]+sizeof("direction-sendall-")-1);
    else if (!strncmp(argv[1], "direction-accept-", sizeof("direction-accept-")-1)) test_direction_accept(argv[1]+sizeof("direction-accept-")-1);
    else if (!strncmp(argv[1], "direction-io-", sizeof("direction-io-")-1)) {
        char transport[8], operation[16], mode[32];
        CHECK(sscanf(argv[1]+sizeof("direction-io-")-1, "%7[^:]:%15[^:]:%31s", transport, operation, mode) == 3);
        CHECK(!strcmp(transport, "tcp") || !strcmp(transport, "udp"));
        test_direction_io(!strcmp(transport, "tcp"), operation, mode);
    }
    else if (!strcmp(argv[1], "nodelay-validation")) test_nodelay_validation();
    else if (!strcmp(argv[1], "nodelay-live")) test_nodelay_live();
    else if (!strncmp(argv[1], "nodelay-connect-", 16)) test_nodelay_connect(argv[1] + 16);
    else if (!strncmp(argv[1], "nodelay-accept-", 15)) test_nodelay_accept(argv[1] + 15);
    else if (!strncmp(argv[1], "reservation-", 12)) test_tcp_reservation(argv[1] + 12);
    else if (!strncmp(argv[1], "shutdown-", 9)) test_shutdown(argv[1] + 9);
    else if (!strcmp(argv[1], "getsockopt-validation")) test_getsockopt_validation();
    else if (!strcmp(argv[1], "getsockopt-error-defaults")) test_getsockopt_error_defaults();
    else if (!strcmp(argv[1], "getsockopt-error-udp-validation")) test_getsockopt_error_udp_validation();
    else if (!strncmp(argv[1], "getsockopt-error-udp-reconnect-", sizeof("getsockopt-error-udp-reconnect-") - 1)) test_getsockopt_error_udp_reconnect((mp_int_t)strtol(argv[1] + sizeof("getsockopt-error-udp-reconnect-") - 1, NULL, 10));
    else if (!strncmp(argv[1], "getsockopt-error-udp-native-bound-", sizeof("getsockopt-error-udp-native-bound-") - 1)) test_getsockopt_error_udp_native("bound", (mp_int_t)strtol(argv[1] + sizeof("getsockopt-error-udp-native-bound-") - 1, NULL, 10));
    else if (!strncmp(argv[1], "getsockopt-error-udp-native-lazy-", sizeof("getsockopt-error-udp-native-lazy-") - 1)) test_getsockopt_error_udp_native("lazy", (mp_int_t)strtol(argv[1] + sizeof("getsockopt-error-udp-native-lazy-") - 1, NULL, 10));
    else if (!strncmp(argv[1], "getsockopt-error-udp-native-connected-", sizeof("getsockopt-error-udp-native-connected-") - 1)) test_getsockopt_error_udp_native("connected", (mp_int_t)strtol(argv[1] + sizeof("getsockopt-error-udp-native-connected-") - 1, NULL, 10));
    else if (!strncmp(argv[1], "getsockopt-error-udp-allocation-", sizeof("getsockopt-error-udp-allocation-") - 1)) test_getsockopt_error_udp_allocation((mp_int_t)strtol(argv[1] + sizeof("getsockopt-error-udp-allocation-") - 1, NULL, 10));
    else if (!strncmp(argv[1], "getsockopt-error-udp-sync-", sizeof("getsockopt-error-udp-sync-") - 1)) test_getsockopt_error_udp_sync(argv[1] + sizeof("getsockopt-error-udp-sync-") - 1);
    else if (!strncmp(argv[1], "getsockopt-error-finish-failure-", 32)) test_getsockopt_error_finish_failure((int)strtol(argv[1] + 32, NULL, 10));
    else if (!strncmp(argv[1], "getsockopt-error-native-allocation-", 35)) test_getsockopt_error_native_allocation((mp_int_t)strtol(argv[1] + 35, NULL, 10));
    else if (!strncmp(argv[1], "getsockopt-error-native-", 24)) test_getsockopt_error_native((mp_int_t)strtol(argv[1] + 24, NULL, 10));
    else if (!strncmp(argv[1], "getsockopt-error-pending-", 25)) test_getsockopt_error_pending(argv[1] + 25);
    else if (!strncmp(argv[1], "getsockopt-error-stream-", 24)) test_getsockopt_error_stream(argv[1] + 24);
    else if (!strcmp(argv[1], "getsockopt-udp-bound")) test_getsockopt_broadcast(true);
    else if (!strcmp(argv[1], "getsockopt-udp-lazy")) test_getsockopt_broadcast(false);
    else if (!strncmp(argv[1], "getsockopt-tcp-", 15)) test_getsockopt_tcp(argv[1] + 15);
    else if (!strcmp(argv[1], "getsock-fresh")) test_getsock_fresh();
    else if (!strcmp(argv[1], "getsock-accept")) test_getsock_accept();
    else if (!strncmp(argv[1], "getsock-udp-", 12)) test_getsock_udp(argv[1] + 12);
    else if (!strncmp(argv[1], "getsock-tcp-", 12)) test_getsock_tcp(argv[1] + 12);
    else if (!strcmp(argv[1], "getpeer-udp")) test_getpeer_udp();
    else if (!strcmp(argv[1], "getpeer-accept")) test_getpeer_accept();
    else if (!strncmp(argv[1], "getpeer-tcp-", 12)) test_getpeer_tcp(argv[1] + 12);
    else if (!strncmp(argv[1], "sendall-pending-", 16)) test_sendall_pending(argv[1] + 16);
    else if (!strncmp(argv[1], "sendall-udp-", 12)) test_sendall_udp(argv[1] + 12);
    else if (!strncmp(argv[1], "sendall-", 8)) test_sendall(argv[1] + 8);
    else if (!strncmp(argv[1], "listener-idle-", 14)) test_listener_idle(argv[1] + 14);
    else if (!strncmp(argv[1], "listener-phase-", 15)) test_listener_invalid_phase(argv[1] + 15);
    else if (!strncmp(argv[1], "listener-ephemeral-", 19)) test_listener_ephemeral(argv[1] + 19);
    else if (!strncmp(argv[1], "listener-", 9)) test_listener(argv[1] + 9);
    else if (!strncmp(argv[1], "tcp-bound-", 10)) test_tcp_bound(argv[1] + 10);
     else if (!strncmp(argv[1], "tcp-", 4)) test_tcp(argv[1] + 4);
    else if (!strcmp(argv[1], "udp-connect-lazy")) test_udp_connect(false);
    else if (!strcmp(argv[1], "udp-connect-bound")) test_udp_connect(true);
    else if (!strcmp(argv[1], "udp-connect-errors")) test_udp_connect_errors();
    else if (!strcmp(argv[1], "udp-unconnected-recv")) test_udp_unconnected_recv();
    else if (!strcmp(argv[1], "udp-empty")) test_udp_empty();
    else if (!strncmp(argv[1], "udp-send-", 9)) test_udp_io(argv[1] + 9, false);
    else if (!strncmp(argv[1], "udp-recv-", 9)) test_udp_io(argv[1] + 9, true);
    else if (!strcmp(argv[1], "lazy")) test_lazy();
    else if (!strcmp(argv[1], "bind")) test_bind();
    else if (!strcmp(argv[1], "local-bind")) test_local_bind();
    else if (!strcmp(argv[1], "broadcast")) test_broadcast();
    else if (!strcmp(argv[1], "unsupported")) test_unsupported();
    else if (!strcmp(argv[1], "errors")) test_errors();
    else if (!strcmp(argv[1], "timeout-send")) test_timeout(false, false);
    else if (!strcmp(argv[1], "timeout-recv")) test_timeout(true, false);
    else if (!strcmp(argv[1], "deadline-send")) test_timeout(false, true);
    else if (!strcmp(argv[1], "deadline-recv")) test_timeout(true, true);
    else if (!strcmp(argv[1], "retry-send")) test_retry_success(false);
    else if (!strcmp(argv[1], "retry-recv")) test_retry_success(true);
    else if (!strcmp(argv[1], "close-send")) test_event_close(false);
    else if (!strcmp(argv[1], "close-recv")) test_event_close(true);
    else if (!strcmp(argv[1], "poll")) test_poll();
    else CHECK(!"unknown scenario");
    for (unsigned i = 0; i < allocation_count; ++i) free(allocations[i]);
    puts("PASS"); return 0;
}
"""


@unittest.skipUnless(COMPILER.is_file(), "host GCC is not installed")
class SocketUdpPortHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-socket-udp-")

        def cleanup():
            for attempt in range(20):
                try:
                    temporary.cleanup()
                    return
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.1)

        cls.addClassCleanup(cleanup)
        cls.root = Path(temporary.name)
        for name, content in HEADERS.items():
            target = cls.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        harness = cls.root / "harness.c"
        harness.write_text(HARNESS, encoding="utf-8")
        cls.executable = cls.root / "socket-udp-host.exe"
        cls.env = dict(os.environ)
        cls.env["PATH"] = str(COMPILER.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [str(COMPILER), "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-I", str(cls.root),
             # Never put the port on -I: it would shadow the host <setjmp.h>.
             "-iquote", str(SOURCE.parent), str(harness), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host GCC compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, name):
        result = subprocess.run([str(self.executable), name], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_direction_timeout_native_integer_validation_queries_prefixes_and_reset(self):
        self.run_scenario("direction-options")

    def test_direction_timeout_udp_tcp_asymmetric_retry_deadline_reset_close_and_interrupt(self):
        for transport, operations in (("udp", ("send", "recv", "sendto", "recvfrom")),
                                      ("tcp", ("send", "recv"))):
            for operation in operations:
                for mode in ("timeout", "blocking-timeout", "errors", "nonblocking", "infinite",
                             "inherited", "inherited-callback", "reset-blocking",
                             "event-close", "interrupt", "callback-longer", "callback-shorter", "callback-reset"):
                    with self.subTest(transport=transport, operation=operation, mode=mode):
                        self.run_scenario(f"direction-io-{transport}:{operation}:{mode}")

    def test_direction_timeout_sendall_total_send_budget_without_mutating_socket_timeout(self):
        for mode in ("success", "timeout", "infinite", "nonblocking",
                     "callback-longer", "callback-shorter", "callback-reset"):
            with self.subTest(mode=mode):
                self.run_scenario("direction-sendall-" + mode)

    def test_direction_timeout_accept_receive_budget_and_children_start_blocking_without_overrides(self):
        for mode in ("timeout", "nonblocking", "child", "infinite", "event-close", "interrupt",
                     "callback-longer", "callback-reset"):
            with self.subTest(mode=mode):
                self.run_scenario("direction-accept-" + mode)

    def test_direction_timeout_tcp_connect_uses_socket_timeout_not_direction_options(self):
        self.run_scenario("direction-connect")

    def test_direction_timeout_pending_tcp_io_uses_operation_direction_before_promotion(self):
        for operation in ("send", "recv"):
            with self.subTest(operation=operation):
                self.run_scenario("direction-pending-" + operation)

    def test_direction_timeout_connected_udp_sendall_snapshots_send_budget(self):
        for mode in ("timeout", "infinite", "nonblocking", "callback-reset"):
            with self.subTest(mode=mode):
                self.run_scenario("direction-udp-sendall-" + mode)

    def test_nodelay_default_query_validation_and_strict_setter_state(self):
        self.run_scenario("nodelay-validation")

    def test_nodelay_deferred_connect_default_explicit_pending_and_failed_cleanup(self):
        for mode in ("default", "pre0", "pre1", "bound0", "bound1", "pending0", "pending1",
                     "blocking0", "blocking1", "fail0", "fail1"):
            with self.subTest(mode=mode):
                self.run_scenario("nodelay-connect-" + mode)

    def test_nodelay_live_toggle_rolls_back_on_native_error(self):
        self.run_scenario("nodelay-live")

    def test_nodelay_listener_child_default_inheritance_and_failed_cleanup(self):
        for mode in ("default", "inherit0", "inherit1", "fail0", "fail1"):
            with self.subTest(mode=mode):
                self.run_scenario("nodelay-accept-" + mode)

    def test_tcp_explicit_bind_reservation_lifecycle_conflicts_errors_and_reset(self):
        for mode in ("bind", "native", "query-error", "udp", "ephemeral", "capacity",
                     "pending", "connect", "finish-failure", "timeout", "start-error",
                     "listen", "listen-error", "listen-query-error", "accept", "deinit"):
            with self.subTest(mode=mode):
                self.run_scenario("reservation-" + mode)

    def test_getsockopt_validation_conversions_closed_precedence_and_byte_prefixes(self):
        self.run_scenario("getsockopt-validation")

    def test_getsockopt_error_tcp_udp_defaults_without_open_or_allocation_and_closed_precedence(self):
        self.run_scenario("getsockopt-error-defaults")

    def test_getsockopt_error_udp_native_requeries_each_new_error_and_byte_prefixes(self):
        for mode in ("bound", "lazy", "connected"):
            for length in (-1, 0, 1, 2, 4, 8):
                with self.subTest(mode=mode, length=length):
                    self.run_scenario("getsockopt-error-udp-native-" + mode + "-" + str(length))

    def test_getsockopt_error_udp_allocation_failure_retries_cache_before_new_native_error(self):
        for length in (0, 1, 8):
            with self.subTest(length=length):
                self.run_scenario("getsockopt-error-udp-allocation-" + str(length))

    def test_getsockopt_error_udp_reconnect_failure_retains_cache_success_discards_old_peer_error(self):
        for length in (0, 1, 8):
            with self.subTest(length=length):
                self.run_scenario("getsockopt-error-udp-reconnect-" + str(length))

    def test_getsockopt_error_udp_validation_no_query_and_bridge_failure_preserves_state(self):
        self.run_scenario("getsockopt-error-udp-validation")

    def test_getsockopt_error_udp_synchronous_io_errors_are_not_cached(self):
        for mode in ("connected-send", "connected-recv", "sendto", "recvfrom"):
            with self.subTest(mode=mode):
                self.run_scenario("getsockopt-error-udp-sync-" + mode)

    def test_getsockopt_error_pending_one_finish_success_failure_and_poll_cache(self):
        for mode in ("success", "failure", "failure-before-poll", "failure-after-poll"):
            with self.subTest(mode=mode):
                self.run_scenario("getsockopt-error-pending-" + mode)

    def test_getsockopt_error_pending_refusal_byte_prefixes(self):
        for length in (-1, 0, 1, 2, 4, 8):
            with self.subTest(length=length):
                self.run_scenario("getsockopt-error-pending-failure-length-" + str(length))

    def test_getsockopt_error_pending_result_allocation_failure_retains_report(self):
        for mode in ("allocation-int", "allocation-bytes"):
            with self.subTest(mode=mode):
                self.run_scenario("getsockopt-error-pending-" + mode)

    def test_getsockopt_error_native_query_once_and_byte_prefix(self):
        for length in (-1, 0, 1, 2, 4, 8):
            with self.subTest(length=length):
                self.run_scenario("getsockopt-error-native-" + str(length))

    def test_getsockopt_error_cancelled_busy_interrupted_or_capacity_failure_is_terminal(self):
        for code in (16, 4, 24):  # EBUSY, EINTR, EMFILE from native connect-finish.
            with self.subTest(code=code):
                self.run_scenario("getsockopt-error-finish-failure-" + str(code))

    def test_getsockopt_error_native_result_allocation_failure_retains_report(self):
        for length in (0, 1, 8):
            with self.subTest(length=length):
                self.run_scenario("getsockopt-error-native-allocation-" + str(length))

    def test_getsockopt_error_observed_stream_read_write_poll_consumed_without_close(self):
        for mode in ("read", "write", "poll", "poll-error"):
            with self.subTest(mode=mode):
                self.run_scenario("getsockopt-error-stream-" + mode)

    def test_getsockopt_broadcast_default_preopen_revert_bound_and_failed_update(self):
        for mode in ("bound", "lazy"):
            with self.subTest(mode=mode):
                self.run_scenario("getsockopt-udp-" + mode)

    def test_getsockopt_type_fresh_bound_listener_pending_failed_connected_accepted(self):
        for mode in ("listener", "pending", "failed", "connected", "accepted"):
            with self.subTest(mode=mode):
                self.run_scenario("getsockopt-tcp-" + mode)

    def test_shutdown_validation_without_nic_selection_or_allocation(self):
        self.run_scenario("shutdown-validation")

    def test_shutdown_udp_rejected_without_affecting_io(self):
        self.run_scenario("shutdown-udp")

    def test_shutdown_unconnected_listener_pending_failed_and_closed(self):
        self.run_scenario("shutdown-phases")

    def test_shutdown_connected_and_accepted_halves_repeats_and_combined_modes(self):
        for origin in ("connected", "accepted"):
            for mode in ("rd", "wr", "both", "rd-wr", "wr-rd"):
                with self.subTest(origin=origin, mode=mode):
                    self.run_scenario("shutdown-" + origin + "-" + mode)

    def test_shutdown_bridge_busy_and_notconnected_retain_flags_options_and_so_error(self):
        for origin in ("connected", "accepted"):
            with self.subTest(origin=origin):
                self.run_scenario("shutdown-" + origin + "-errors")

    def test_shutdown_preexisting_terminal_failure_does_not_cache_or_consume_so_error(self):
        for origin in ("connected", "accepted"):
            with self.subTest(origin=origin):
                self.run_scenario("shutdown-" + origin + "-terminal")

    def test_getsockname_fresh_closed_and_no_implicit_native_opens(self):
        self.run_scenario("getsock-fresh")

    def test_getsockname_udp_bind_ephemeral_reconnect_native_and_snapshot_errors(self):
        for mode in ("bound", "ephemeral", "lazy"):
            with self.subTest(mode=mode):
                self.run_scenario("getsock-udp-" + mode)

    def test_getsockname_tcp_connected_pending_ready_sticky_and_guard_errors(self):
        for mode in ("connected", "pending", "failed"):
            with self.subTest(mode=mode):
                self.run_scenario("getsock-tcp-" + mode)

    def test_getsockname_tcp_bound_listener_and_accepted_native_local_port(self):
        self.run_scenario("getsock-accept")

    def test_getpeername_udp_reconnect_saved_copy_and_vm_errno(self):
        self.run_scenario("getpeer-udp")

    def test_getpeername_tcp_pending_promotes_once_and_preserves_errors(self):
        for mode in ("promote", "blocking", "failure", "start-error"):
            with self.subTest(mode=mode):
                self.run_scenario("getpeer-tcp-" + mode)

    def test_getpeername_accepted_copy_listener_rejection_and_close(self):
        self.run_scenario("getpeer-accept")

    def test_sendall_partial_writes_share_original_total_deadline(self):
        for mode in ("partial-success", "partial-deadline", "exact-deadline",
                     "backpressure-success", "backpressure-deadline", "callback-expiry"):
            with self.subTest(mode=mode):
                self.run_scenario("sendall-" + mode)

    def test_sendall_empty_zero_progress_infinite_and_nonblocking(self):
        for mode in ("empty", "zero-progress", "infinite", "nonblocking-success",
                     "nonblocking-partial", "nonblocking-eagain"):
            with self.subTest(mode=mode):
                self.run_scenario("sendall-" + mode)

    def test_sendall_callback_close_interrupt_and_reentry_preserve_timeout(self):
        for mode in ("event-close", "interrupt", "reentry"):
            with self.subTest(mode=mode):
                self.run_scenario("sendall-" + mode)

    def test_sendall_callback_settimeout_cannot_change_captured_budget(self):
        for mode in ("longer", "infinite", "nonblocking"):
            with self.subTest(mode=mode):
                self.run_scenario("sendall-settimeout-" + mode)

    def test_sendall_pending_connect_cleanup(self):
        for mode in ("timeout", "interrupt"):
            with self.subTest(mode=mode):
                self.run_scenario("sendall-pending-" + mode)

    def test_sendall_connected_udp_retry_empty_and_errors(self):
        for mode in ("retry", "empty", "unconnected"):
            with self.subTest(mode=mode):
                self.run_scenario("sendall-udp-" + mode)

    def test_tcp_idle_listen_native_ephemeral_assignment_and_all_backlog_limits(self):
        for backlog in (-2147483648, -1, 0, 1, 2, 3, 4, 5, 99, 2147483647):
            with self.subTest(backlog=backlog):
                self.run_scenario("listener-idle-backlog-" + str(backlog))

    def test_tcp_idle_listen_open_and_query_failure_rollback_retry_bind_and_close_once(self):
        for mode in ("open-error", "query-error", "open-close", "query-close", "query-bind"):
            with self.subTest(mode=mode):
                self.run_scenario("listener-idle-" + mode)

    def test_tcp_implicit_listener_accept_default_and_configured_nodelay_inheritance(self):
        for mode in ("success", "nodelay0", "nodelay1"):
            with self.subTest(mode=mode):
                self.run_scenario("listener-idle-" + mode)

    def test_tcp_listen_connected_pending_and_failed_preserves_state_without_native_calls(self):
        for mode in ("connected", "pending", "failed"):
            with self.subTest(mode=mode):
                self.run_scenario("listener-phase-" + mode)

    def test_tcp_listener_bind_accept_lifetime_and_poll(self):
        for mode in ("success", "max-backlog", "retry", "eagain", "error",
                     "timeout", "deadline", "event-close", "interrupt",
                     "child-close", "poll", "deinit"):
            with self.subTest(mode=mode):
                self.run_scenario("listener-" + mode)

    def test_tcp_bind_zero_listen_assigned_port_and_accepted_name_independence(self):
        self.run_scenario("listener-ephemeral-success")

    def test_tcp_listener_local_port_query_failure_closes_and_retries_bind_zero(self):
        self.run_scenario("listener-ephemeral-query-error")

    def test_tcp_listener_irq_errors_propagate_without_listening_or_losing_bind_zero(self):
        for mode in ("open-irq", "query-irq"):
            with self.subTest(mode=mode):
                self.run_scenario("listener-ephemeral-" + mode)

    def test_tcp_client_dispatch_and_lifetime(self):
        for mode in ("blocking", "nonblocking", "timeout", "interrupt", "event-close",
                     "close", "failure", "send-promote", "recv-promote",
                     "pending-io-timeout", "pending-io-close"):
            with self.subTest(mode=mode):
                self.run_scenario("tcp-" + mode)

    def test_tcp_bound_client_start_ports_promotion_failures_and_cleanup(self):
        for binding in ("explicit", "ephemeral"):
            for mode in ("blocking", "nonblocking", "start-error", "timeout", "interrupt",
                         "close", "pending-io-timeout", "pending-io-close"):
                with self.subTest(binding=binding, mode=mode):
                    self.run_scenario("tcp-bound-" + binding + "-" + mode)

    def test_udp_connect_lazy_and_bound_reconnect_and_close(self):
        for mode in ("lazy", "bound"):
            with self.subTest(mode=mode):
                self.run_scenario("udp-connect-" + mode)

    def test_udp_sendto_then_recv_without_connect_for_ntptime(self):
        self.run_scenario("udp-unconnected-recv")

    def test_udp_connect_failure_keeps_socket_open_and_unconnected(self):
        self.run_scenario("udp-connect-errors")

    def test_udp_empty_send_receive_and_zero_capacity(self):
        self.run_scenario("udp-empty")

    def test_udp_connected_io_errors_retry_deadline_and_event_close(self):
        for operation in ("send", "recv"):
            for mode in ("errors", "retry", "timeout", "deadline", "event-close"):
                with self.subTest(operation=operation, mode=mode):
                    self.run_scenario("udp-" + operation + "-" + mode)

    def test_local_address_bind_snapshot_copy_name_rollback_staleness_and_reservations(self):
        self.run_scenario("local-bind")

    def test_broadcast_before_and_after_bind_and_rollback(self):
        self.run_scenario("broadcast")

    def test_lazy_creation_and_idempotent_close(self):
        self.run_scenario("lazy")

    def test_bind_range_wildcard_and_open_failure(self):
        self.run_scenario("bind")

    def test_unsupported_tcp_dns_and_operations(self):
        self.run_scenario("unsupported")

    def test_send_recv_errno_and_nonblocking_eagain(self):
        self.run_scenario("errors")

    def test_finite_timeout(self):
        for operation in ("send", "recv"):
            with self.subTest(operation=operation):
                self.run_scenario("timeout-" + operation)

    def test_deadline_checked_after_delay_before_retry(self):
        for operation in ("send", "recv"):
            with self.subTest(operation=operation):
                self.run_scenario("deadline-" + operation)

    def test_retry_success_before_deadline(self):
        for operation in ("send", "recv"):
            with self.subTest(operation=operation):
                self.run_scenario("retry-" + operation)

    def test_event_close_returns_ebadf_without_stale_access(self):
        for operation in ("send", "recv"):
            with self.subTest(operation=operation):
                self.run_scenario("close-" + operation)

    def test_poll_flags_errors_and_closed_socket(self):
        self.run_scenario("poll")


if __name__ == "__main__":
    unittest.main()
