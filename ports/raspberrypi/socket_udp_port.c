// SPDX-License-Identifier: MIT
// UDP and TCP adapter for the standard non-LWIP MicroPython socket module.
#include "py/runtime.h"
#include "py/mperrno.h"
#include "py/mphal.h"
#include "py/stream.h"
#include "extmod/modnetwork.h"
#include "shared/netutils/netutils.h"
#include "udp_bridge.h"
#include "network_bridge.h"
#include "tcp_connect_bridge.h"
#include "tcp_stream_bridge.h"
#include "tcp_listener_bridge.h"
#include "py/nlr.h"
#include "circle_bridge.h"
#include "socket_port.h"
// Exported sendall declaration also allows focused host runtime harnesses.
mp_obj_t mpynn_socket_sendall(mp_obj_t self_in, mp_obj_t buffer_in);
#include <string.h>

enum { TCP_IDLE, TCP_BOUND, TCP_LISTENING, TCP_PENDING, TCP_CONNECTED, TCP_FAILED };
typedef struct {
    uint32_t token;
    bool opened;
    bool connected;
    bool broadcast;
    bool nodelay;
    bool nodelay_configured;
    bool write_shutdown;
    bool send_timeout_set;
    bool recv_timeout_set;
    int32_t send_timeout;
    int32_t recv_timeout;
    unsigned kind;
    uint32_t connect_token;
    uint32_t stream_token;
    uint32_t listener_token;
    uint16_t local_port;
    uint8_t bind_ip[4];
    uint32_t bind_reservation;
    uint8_t peer_ip[4];
    uint16_t peer_port;
    unsigned phase;
    int sticky_error;
    int so_error;
    bool so_error_native_checked;
} udp_state_t;
// Adapter-owned TCP namespace, independent of UDP and native handle lifetime.
// Integer owners avoid rooting socket/GC pointers. Generations survive VM reset
// so a stale close cannot release a replacement socket's reservation.
#define TCP_BIND_SLOTS 16u
#define TCP_BIND_MAX_GENERATION (UINT32_MAX >> 4)
typedef struct { uint16_t port; uint32_t generation; } tcp_bind_slot_t;
static tcp_bind_slot_t tcp_bind_slots[TCP_BIND_SLOTS];
static int tcp_bind_reserve(uint16_t port, uint32_t *token) {
    unsigned in_use;
    int result = mpynn_tcp_port_in_use(port, &in_use);
    if (result) return result;
    if (in_use) return MP_EADDRINUSE;
    unsigned free_slot = TCP_BIND_SLOTS;
    for (unsigned i = 0; i < TCP_BIND_SLOTS; ++i) {
        if (tcp_bind_slots[i].port == port) return MP_EADDRINUSE;
        if (!tcp_bind_slots[i].port &&
            tcp_bind_slots[i].generation < TCP_BIND_MAX_GENERATION &&
            free_slot == TCP_BIND_SLOTS) free_slot = i;
    }
    if (free_slot == TCP_BIND_SLOTS) return MP_EMFILE;
    tcp_bind_slot_t *slot = &tcp_bind_slots[free_slot];
    ++slot->generation;
    slot->port = port;
    *token = (slot->generation << 4) | free_slot;
    return 0;
}
static void tcp_bind_release(uint32_t token) {
    if (!token) return;
    tcp_bind_slot_t *slot = &tcp_bind_slots[token & (TCP_BIND_SLOTS - 1)];
    if (slot->generation == (token >> 4)) slot->port = 0;
}
static int fail(int code, int *error) { *error = code; return -1; }
static udp_state_t *state(mod_network_socket_obj_t *s) { return s->_private; }
static void record_so_error(udp_state_t *p, int error) {
    // EPIPE after local SHUT_WR is not a native terminal condition; it must not
    // suppress a later peer RST/timeout report through SO_ERROR.
    if (!p || error == MP_EAGAIN || error == MP_EBUSY || error == MP_EINTR ||
        (error == MP_EPIPE && p->write_shutdown)) return;
    // A persistent native terminal condition is reported once through SO_ERROR;
    // repeated read/write/poll attempts must not re-arm the consumed result.
    if (p->so_error_native_checked) return;
    if (!p->so_error) p->so_error = error;
    p->so_error_native_checked = true;
}
static int ensure_open(mod_network_socket_obj_t *s, uint16_t port, int *error) {
    udp_state_t *p = state(s);
    if (!p || s->state == MOD_NETWORK_SS_CLOSED) return fail(MP_EBADF, error);
    if (p->kind != MOD_NETWORK_SOCK_DGRAM) return fail(MP_EOPNOTSUPP, error);
    if (p->opened) return 0;
    int result = mpynn_udp_open_bound(port, &p->token);
    if (result) return fail(result, error);
    if (p->broadcast) {
        result = mpynn_udp_broadcast(p->token, 1);
        if (result) {
            (void)mpynn_udp_close(p->token);
            return fail(result, error);
        }
    }
    p->opened = true;
    return 0;
}
static int udp_socket(mod_network_socket_obj_t *s, int *error) {
    // Standard socket_select_nic can be reached again after close clears nic.
    // Never allocate new transport state for a logically closed socket.
    if (s->state == MOD_NETWORK_SS_CLOSED) return fail(MP_EBADF, error);
    if (s->domain != MOD_NETWORK_AF_INET) return fail(MP_EAFNOSUPPORT, error);
    if (!((s->type == MOD_NETWORK_SOCK_DGRAM && (s->proto == 0 || s->proto == 17)) ||
          (s->type == MOD_NETWORK_SOCK_STREAM && (s->proto == 0 || s->proto == 6))))
        return fail(MP_EOPNOTSUPP, error);
    s->_private = m_new0(udp_state_t, 1);
    state(s)->kind = s->type;
    // Circle historically sends sub-MSS data without a Nagle gate.
    state(s)->nodelay = s->type == MOD_NETWORK_SOCK_STREAM;
    return 0;
}
static void udp_close(mod_network_socket_obj_t *s) {
    udp_state_t *p = state(s);
    if (p && p->kind == MOD_NETWORK_SOCK_STREAM) {
        if (p->phase == TCP_PENDING) (void)mpynn_tcp_connect_cancel(p->connect_token);
        if (p->phase == TCP_CONNECTED) (void)mpynn_tcp_stream_close(p->stream_token);
        if (p->phase == TCP_LISTENING) (void)mpynn_tcp_listener_close(p->listener_token);
        tcp_bind_release(p->bind_reservation);
        p->bind_reservation = 0;
        p->phase = TCP_IDLE;
    }
    if (p && p->opened) {
        // If called with IRQs masked, keep the token for close_all on VM reset.
        (void)mpynn_udp_close(p->token);
        p->opened = false;
    }
    s->_private = NULL;
    s->state = MOD_NETWORK_SS_CLOSED;
}
static int udp_bind(mod_network_socket_obj_t *s, byte *ip, mp_uint_t port, int *error) {
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return fail(MP_EBADF, error);
    if (port > 65535) return fail(MP_EINVAL, error);
    uint8_t local_ip[4] = {0};
    if (ip[0] || ip[1] || ip[2] || ip[3]) {
        mpynn_network_state_t network;
        int snapshot = mpynn_network_snapshot(&network);
        if (snapshot) return fail(MP_EBUSY, error);
        if (!network.initialized || !network.running) return fail(MP_ENOTCONN, error);
        if (memcmp(ip, network.ip, sizeof(local_ip)) != 0) return fail(MP_EINVAL, error);
        memcpy(local_ip, ip, sizeof(local_ip));
    }
    if (state(s)->kind == MOD_NETWORK_SOCK_STREAM) {
        if (state(s)->phase != TCP_IDLE) return fail(MP_EINVAL, error);
        // Reserve explicit ports now, without opening a native connection.
        // Zero remains unreserved: connect/listen choose an ephemeral port later.
        if (port) {
            int result = tcp_bind_reserve((uint16_t)port, &state(s)->bind_reservation);
            if (result) return fail(result, error);
        }
        // Defer native passive opens until listen supplies the backlog.
        state(s)->local_port = (uint16_t)port;
        memcpy(state(s)->bind_ip, local_ip, sizeof(local_ip));
        state(s)->phase = TCP_BOUND;
        s->bound = true;
        return 0;
    }
    if (state(s)->opened) return fail(MP_EINVAL, error);
    if (ensure_open(s, (uint16_t)port, error)) return -1;
    if (local_ip[0] || local_ip[1] || local_ip[2] || local_ip[3]) {
        int result = mpynn_udp_bind_local(state(s)->token, local_ip);
        if (result) {
            (void)mpynn_udp_close(state(s)->token);
            state(s)->opened = false;
            return fail(result, error);
        }
        memcpy(state(s)->bind_ip, local_ip, sizeof(local_ip));
    }
    s->bound = true;
    return 0;
}
static int udp_timeout(mod_network_socket_obj_t *s, mp_uint_t ms, int *error) {
    if (ms != (mp_uint_t)-1 && ms > INT32_MAX) return fail(MP_EINVAL, error);
    s->timeout = ms == (mp_uint_t)-1 ? -1 : (int32_t)ms;
    if (state(s)) {
        state(s)->send_timeout_set = false;
        state(s)->recv_timeout_set = false;
    }
    return 0;
}
static int32_t socket_io_timeout(mod_network_socket_obj_t *s, bool writing) {
    // Nonblocking is a socket mode and takes precedence over direction limits.
    if (s->timeout == 0) return 0;
    udp_state_t *p = state(s);
    if (p && writing && p->send_timeout_set) return p->send_timeout;
    if (p && !writing && p->recv_timeout_set) return p->recv_timeout;
    return s->timeout;
}
// Retry in C, after returning from the Circle C++ bridge. Pending Python
// exceptions (Ctrl-C) must never unwind a live Circle C++ stack frame.
static bool retry(mod_network_socket_obj_t *s, uint64_t start, int code, int *error, int32_t timeout) {
    if (code != MP_EAGAIN) { *error = code; return false; }
    if (timeout == 0) { *error = MP_EAGAIN; return false; }
    if (timeout > 0 && mpynn_ticks_us64() - start >= (uint64_t)timeout * 1000) {
        *error = MP_ETIMEDOUT; return false;
    }
    mp_event_handle_nowait();
    // A scheduled Python callback may close this socket while servicing events.
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) {
        *error = MP_EBADF; return false;
    }
    mp_hal_delay_ms(1);
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) {
        *error = MP_EBADF; return false;
    }
    // Do not attempt another IO after yielding has exhausted the total deadline.
    if (timeout > 0 && mpynn_ticks_us64() - start >= (uint64_t)timeout * 1000) {
        *error = MP_ETIMEDOUT; return false;
    }
    return true;
}
static mp_uint_t udp_sendto(mod_network_socket_obj_t *s, const byte *buf, mp_uint_t len,
                           byte *ip, mp_uint_t port, int *error) {
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return (mp_uint_t)fail(MP_EBADF, error);
    if (state(s)->kind != MOD_NETWORK_SOCK_DGRAM) return (mp_uint_t)fail(MP_EOPNOTSUPP, error);
    if (!port || port > 65535) return (mp_uint_t)fail(MP_EINVAL, error);
    const int32_t timeout = socket_io_timeout(s, true);
    if (ensure_open(s, 0, error)) return (mp_uint_t)-1;
    uint64_t start = mpynn_ticks_us64();
    for (;;) {
        int result = mpynn_udp_sendto(state(s)->token, buf, len, ip, port);
        if (!result) return len;
        if (!retry(s, start, result, error, timeout)) return (mp_uint_t)-1;
        if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return (mp_uint_t)fail(MP_EBADF, error);
    }
}
static mp_uint_t udp_recvfrom(mod_network_socket_obj_t *s, byte *buf, mp_uint_t len,
                             byte *ip, mp_uint_t *port, int *error) {
    const int32_t timeout = socket_io_timeout(s, false);
    if (ensure_open(s, 0, error)) return (mp_uint_t)-1;
    uint64_t start = mpynn_ticks_us64();
    for (;;) {
        size_t received; uint16_t peer_port;
        int result = mpynn_udp_recvfrom(state(s)->token, buf, len, &received, ip, &peer_port);
        if (!result) { *port = peer_port; return received; }
        if (!retry(s, start, result, error, timeout)) return (mp_uint_t)-1;
        if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return (mp_uint_t)fail(MP_EBADF, error);
    }
}
static int tcp_finish(mod_network_socket_obj_t *s);
static int udp_ioctl(mod_network_socket_obj_t *s, mp_uint_t request, mp_uint_t arg, int *error) {
    if (request != MP_STREAM_POLL) return fail(MP_EINVAL, error);
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return MP_STREAM_POLL_NVAL;
    if (state(s)->kind == MOD_NETWORK_SOCK_STREAM) {
        bool pending = state(s)->phase == TCP_PENDING;
        if (state(s)->phase == TCP_IDLE || state(s)->phase == TCP_BOUND) return 0;
        if (state(s)->phase == TCP_LISTENING) {
            unsigned ready;
            int result = mpynn_tcp_listener_poll(state(s)->listener_token, &ready);
            if (result) return MP_STREAM_POLL_ERR;
            return ready ? (arg & MP_STREAM_POLL_RD) : 0;
        }
        int result = tcp_finish(s);
        if (result == MP_EAGAIN) return 0;
        if (result) { record_so_error(state(s), result); return MP_STREAM_POLL_ERR; }
        // Completion must wake a writer even before the next native status update.
        if (pending) return arg & MP_STREAM_POLL_WR;
        unsigned events;
        result = mpynn_tcp_stream_poll(state(s)->stream_token, arg, &events);
        if (result) { record_so_error(state(s), result); return fail(result, error); }
        return events;
    }
    if (ensure_open(s, 0, error)) return -1;
    unsigned events;
    int result = mpynn_udp_poll(state(s)->token, arg, &events);
    if (result) return fail(result, error);
    return events;
}
#include "dns_port.h"
// Every bridge call below is nonblocking. Only retry() runs VM events/yields.
static void tcp_abort_pending(mod_network_socket_obj_t *s, int code) {
    udp_state_t *p = state(s);
    if (p && s->state != MOD_NETWORK_SS_CLOSED && p->phase == TCP_PENDING) {
        (void)mpynn_tcp_connect_cancel(p->connect_token);
        p->connect_token = 0;
        p->phase = TCP_FAILED;
        p->sticky_error = code;
        // Once a job is aborted this error is terminal, even if the original
        // cause was a context/resource error. Never report failed completion as 0.
        p->so_error = code;
        p->so_error_native_checked = true;
    }
}
static int tcp_finish(mod_network_socket_obj_t *s) {
    udp_state_t *p = state(s);
    if (!p || s->state == MOD_NETWORK_SS_CLOSED) return MP_EBADF;
    if (p->phase == TCP_FAILED) return p->sticky_error;
    if (p->phase == TCP_CONNECTED) return 0;
    if (p->phase != TCP_PENDING) return MP_ENOTCONN;
    int result = mpynn_tcp_connect_finish(p->connect_token, &p->stream_token);
    if (!result) {
        p->connect_token = 0;
        if (p->nodelay_configured) {
            result = mpynn_tcp_stream_set_nodelay(p->stream_token, p->nodelay);
            if (result) {
                (void)mpynn_tcp_stream_close(p->stream_token);
                p->stream_token = 0;
                p->phase = TCP_FAILED;
                p->sticky_error = p->so_error = result;
                p->so_error_native_checked = true;
                return result;
            }
        }
        p->phase = TCP_CONNECTED;
        s->state = MOD_NETWORK_SS_CONNECTED;
    } else if (result != MP_EAGAIN) {
        // finish failure leaves the job owned by us, including stream-slot exhaustion.
        tcp_abort_pending(s, result);
    }
    return result;
}
mp_obj_t mpynn_socket_getsockname(mp_obj_t self) {
    mod_network_socket_obj_t *s = MP_OBJ_TO_PTR(self);
    if (s->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    udp_state_t *p = state(s);
    uint8_t ip[4] = {0};
    uint16_t port = 0;
    bool connected = false;
    if (p) {
        int result = 0;
        if (p->kind == MOD_NETWORK_SOCK_DGRAM) {
            // Inspect only: a fresh socket must not acquire a native handle.
            if (p->opened) result = mpynn_udp_local_port(p->token, &port);
            if (!p->connected) memcpy(ip, p->bind_ip, sizeof(ip));
            connected = p->connected;
        } else if (p->kind == MOD_NETWORK_SOCK_STREAM) {
            if (p->phase == TCP_BOUND || p->phase == TCP_LISTENING) {
                port = p->local_port;
                memcpy(ip, p->bind_ip, sizeof(ip));
            } else if (p->phase != TCP_IDLE) {
                // One nonblocking finish attempt. EAGAIN means no stream handle
                // exists yet, so there is no local endpoint to report.
                result = tcp_finish(s);
                if (result == MP_EAGAIN) result = MP_ENOTCONN;
                if (!result) {
                    // Accepted children query their own stream, not the parent
                    // listener's saved bind port or the remote peer port.
                    result = mpynn_tcp_stream_local_port(p->stream_token, &port);
                    connected = true;
                }
            }
        } else {
            result = MP_EOPNOTSUPP;
        }
        if (result) mp_raise_OSError(result);
    }
    if (connected) {
        mpynn_network_state_t network;
        if (mpynn_network_snapshot(&network)) mp_raise_OSError(MP_EBUSY);
        if (!network.initialized || !network.running) mp_raise_OSError(MP_ENOTCONN);
        memcpy(ip, network.ip, sizeof(ip));
    }
    // Native/context errors precede the sole address-tuple formatting allocation.
    return netutils_format_inet_addr(ip, port, NETUTILS_BIG);
}
mp_obj_t mpynn_socket_getsockopt(size_t n_args, const mp_obj_t *args) {
    mod_network_socket_obj_t *s = MP_OBJ_TO_PTR(args[0]);
    if (s->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    mp_int_t level = mp_obj_get_int(args[1]);
    mp_int_t opt = mp_obj_get_int(args[2]);
    mp_int_t length = n_args == 4 ? mp_obj_get_int(args[3]) : 0;
    if (length < 0 || (mp_uint_t)length > sizeof(mp_int_t))
        mp_raise_ValueError(MP_ERROR_TEXT("option buffer size must be 0..sizeof(int)"));
    if (s->domain != MOD_NETWORK_AF_INET) mp_raise_OSError(MP_EAFNOSUPPORT);
    if (!((s->type == MOD_NETWORK_SOCK_DGRAM && (s->proto == 0 || s->proto == 17)) ||
          (s->type == MOD_NETWORK_SOCK_STREAM && (s->proto == 0 || s->proto == 6))))
        mp_raise_OSError(MP_EOPNOTSUPP);
    mp_int_t value;
    if (level == MPYNN_SOCKET_IPPROTO_TCP && opt == MPYNN_SOCKET_TCP_NODELAY) {
        if (s->type != MOD_NETWORK_SOCK_STREAM) mp_raise_OSError(MP_EOPNOTSUPP);
        value = state(s) ? state(s)->nodelay : 1;
        if (length) return mp_obj_new_bytes((const byte *)&value, (size_t)length);
        return mp_obj_new_int(value);
    }
    if (level != MOD_NETWORK_SOL_SOCKET) mp_raise_OSError(MP_EOPNOTSUPP);
    if (opt == MPYNN_SOCKET_SO_TYPE) {
        value = s->type;
    } else if (opt == MOD_NETWORK_SO_SNDTIMEO || opt == MOD_NETWORK_SO_RCVTIMEO) {
        udp_state_t *p = state(s);
        // Inspect configured direction limits, not the nonblocking mode override.
        int32_t milliseconds = s->timeout;
        if (p && opt == MOD_NETWORK_SO_SNDTIMEO && p->send_timeout_set)
            milliseconds = p->send_timeout;
        if (p && opt == MOD_NETWORK_SO_RCVTIMEO && p->recv_timeout_set)
            milliseconds = p->recv_timeout;
        value = milliseconds < 0 ? 0 : milliseconds;
    } else if (opt == MPYNN_SOCKET_SO_ERROR) {
        udp_state_t *p = state(s);
        if (s->type == MOD_NETWORK_SOCK_DGRAM) {
            value = p ? p->so_error : 0;
            if (p && p->opened && value == 0) {
                int pending = 0;
                int status = mpynn_udp_take_error(p->token, &pending);
                if (status) mp_raise_OSError(status);
                value = pending;
                // Native error has been consumed, so retain it in GC-rooted
                // adapter state until the result object is successfully built.
                p->so_error = pending;
            }
            mp_obj_t result = length ? mp_obj_new_bytes((const byte *)&value, (size_t)length)
                                     : mp_obj_new_int(value);
            if (p) p->so_error = 0;
            return result;
        }
        if (p && p->phase == TCP_PENDING) {
            // One native nonblocking completion check; no VM event or delay.
            // A completed refusal must not be mistaken for SO_ERROR == 0 simply
            // because poll/getpeername has not yet promoted the Python state.
            (void)tcp_finish(s);
        }
        value = p ? p->so_error : 0;
        if (p && p->phase == TCP_CONNECTED && !p->so_error_native_checked) {
            int terminal = 0;
            int result = mpynn_tcp_stream_get_error(p->stream_token, &terminal);
            if (result) mp_raise_OSError(result);
            if (terminal != 0) {
                p->so_error_native_checked = true;
                if (!value) value = terminal;
                p->so_error = value;
            }
        }
        // Construct first: a failed bytes allocation must not lose the errno.
        mp_obj_t result = length ? mp_obj_new_bytes((const byte *)&value, (size_t)length)
                                 : mp_obj_new_int(value);
        // Connect failure remains sticky for connect/send/recv. SO_ERROR merely
        // consumes its report and never makes a failed socket usable again.
        if (p) p->so_error = 0;
        return result;
    } else if (opt == MOD_NETWORK_SO_BROADCAST && s->type == MOD_NETWORK_SOCK_DGRAM) {
        // This cache changes only after a successful native set, or before native
        // open (ensure_open applies it). Fresh socket default is false.
        value = state(s) && state(s)->broadcast ? 1 : 0;
    } else {
        mp_raise_OSError(MP_EOPNOTSUPP);
    }
    // Queries do not select a NIC or wait; SO_ERROR may finish a native job.
    // Other option queries leave connection state untouched.
    if (length) return mp_obj_new_bytes((const byte *)&value, (size_t)length);
    return mp_obj_new_int(value);
}

mp_obj_t mpynn_socket_shutdown(mp_obj_t self, mp_obj_t how_in) {
    mod_network_socket_obj_t *s = MP_OBJ_TO_PTR(self);
    if (s->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    mp_int_t how = mp_obj_get_int(how_in);
    if (how < 0 || how > 2) mp_raise_OSError(MP_EINVAL);
    if (s->domain != MOD_NETWORK_AF_INET) mp_raise_OSError(MP_EAFNOSUPPORT);
    if (s->type != MOD_NETWORK_SOCK_STREAM || (s->proto != 0 && s->proto != 6))
        mp_raise_OSError(MP_EOPNOTSUPP);
    udp_state_t *p = state(s);
    // Shutdown never selects a NIC or promotes/cancels a pending connect. The
    // stream keeps its owner reference until close(), including after both halves
    // stop. Native WR shutdown queues FIN after accepted writes; RD drops RX only.
    if (!p || p->phase != TCP_CONNECTED) mp_raise_OSError(MP_ENOTCONN);
    int result = mpynn_tcp_stream_shutdown(p->stream_token, (unsigned)how);
    if (result) mp_raise_OSError(result);
    if (how == 1 || how == 2) p->write_shutdown = true;
    return mp_const_none;
}
mp_obj_t mpynn_socket_getpeername(mp_obj_t self) {
    mod_network_socket_obj_t *s = MP_OBJ_TO_PTR(self);
    if (s->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    if (!state(s)) mp_raise_OSError(MP_ENOTCONN);
    if (state(s)->kind == MOD_NETWORK_SOCK_STREAM) {
        // Query completion once, without running VM events or waiting for IO.
        int result = tcp_finish(s);
        if (result) mp_raise_OSError(result == MP_EAGAIN ? MP_ENOTCONN : result);
    } else if (!state(s)->connected) {
        mp_raise_OSError(MP_ENOTCONN);
    }
    return netutils_format_inet_addr(state(s)->peer_ip, state(s)->peer_port, NETUTILS_BIG);
}
static bool tcp_retry(mod_network_socket_obj_t *s, uint64_t start, int code, int *error, int32_t timeout) {
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        bool again = retry(s, start, code, error, timeout);
        nlr_pop();
        if (!again && *error == MP_ETIMEDOUT) tcp_abort_pending(s, *error);
        return again;
    }
    // An exception from a VM event must not strand an in-flight connect job.
    // Reacquire state: the event may already have closed this socket.
    tcp_abort_pending(s, MP_EINTR);
    nlr_jump(nlr.ret_val);
}
static int tcp_local_bind_current(udp_state_t *p) {
    if (!p || !(p->bind_ip[0] | p->bind_ip[1] | p->bind_ip[2] | p->bind_ip[3])) return 0;
    mpynn_network_state_t network;
    int result = mpynn_network_snapshot(&network);
    if (result) return MP_EBUSY;
    if (!network.initialized || !network.running) return MP_ENOTCONN;
    if (memcmp(p->bind_ip, network.ip, sizeof(p->bind_ip)) != 0) return MP_EINVAL;
    return 0;
}
static int socket_connect(mod_network_socket_obj_t *s, byte *ip, mp_uint_t port, int *error) {
    udp_state_t *p = state(s);
    if (!p || s->state == MOD_NETWORK_SS_CLOSED) return fail(MP_EBADF, error);
    if (p->kind == MOD_NETWORK_SOCK_DGRAM) {
        // Reject narrowing; native connect validates the IPv4 peer and zero port.
        if (port > 65535) return fail(MP_EINVAL, error);
        if (ensure_open(s, 0, error)) return -1;
        int result = mpynn_udp_connect(p->token, ip, (uint16_t)port);
        if (result) return fail(result, error);
        // Reconnect is supported; a failure leaves the previous connection intact.
        memcpy(p->peer_ip, ip, sizeof(p->peer_ip));
        p->peer_port = (uint16_t)port;
        // Native SetPeer drops old-peer errors; mirror that for an errno cached
        // after a failed Python allocation. Reconnect failure leaves it intact.
        p->so_error = 0;
        p->connected = true;
        s->state = MOD_NETWORK_SS_CONNECTED;
        return 0;
    }
    if (p->kind != MOD_NETWORK_SOCK_STREAM) return fail(MP_EOPNOTSUPP, error);
    if (p->phase == TCP_LISTENING) return fail(MP_EOPNOTSUPP, error);
    if (p->phase == TCP_CONNECTED) return fail(MP_EISCONN, error);
    if (p->phase == TCP_PENDING) {
        int result = tcp_finish(s);
        if (result == MP_EAGAIN) return fail(MP_EALREADY, error);
        return fail(result ? result : MP_EISCONN, error);
    }
    if (p->phase == TCP_FAILED) return fail(p->sticky_error, error);
    int local_bind_error = tcp_local_bind_current(p);
    if (local_bind_error) return fail(local_bind_error, error);
    if (!port || port > 65535) return fail(MP_EINVAL, error);
    const int32_t timeout = s->timeout;
    uint64_t start = mpynn_ticks_us64();
    int result = p->phase == TCP_BOUND
        ? mpynn_tcp_connect_start_bound(ip, (unsigned)port, p->local_port, &p->connect_token)
        : mpynn_tcp_connect_start(ip, (unsigned)port, &p->connect_token);
    if (result) return fail(result, error);
    // Retain the endpoint while pending; never retain the caller's IP pointer.
    memcpy(p->peer_ip, ip, sizeof(p->peer_ip));
    p->peer_port = (uint16_t)port;
    p->phase = TCP_PENDING;
    if (timeout == 0) return fail(MP_EINPROGRESS, error);
    for (;;) {
        result = tcp_finish(s);
        if (!result) return 0;
        if (!tcp_retry(s, start, result, error, timeout)) return -1;
    }
}
static int socket_listen(mod_network_socket_obj_t *s, mp_int_t backlog, int *error) {
    udp_state_t *p = state(s);
    if (!p || s->state == MOD_NETWORK_SS_CLOSED) return fail(MP_EBADF, error);
    if (p->kind != MOD_NETWORK_SOCK_STREAM) return fail(MP_EOPNOTSUPP, error);
    // Unbound TCP sockets implicitly request a wildcard ephemeral port. Keep
    // IDLE on failure so retry or an explicit bind remains possible.
    if (p->phase != TCP_BOUND && p->phase != TCP_IDLE) return fail(MP_EINVAL, error);
    int local_bind_error = tcp_local_bind_current(p);
    if (local_bind_error) return fail(local_bind_error, error);
    // Circle retains at most four candidates; zero/negative requests mean one.
    if (backlog <= 0) backlog = 1;
    if (backlog > 4) backlog = 4;
    int result = mpynn_tcp_listener_open(p->local_port, (unsigned)backlog, &p->listener_token);
    if (result) return fail(result, error);
    uint16_t assigned_port;
    result = mpynn_tcp_listener_local_port(p->listener_token, &assigned_port);
    if (result) {
        (void)mpynn_tcp_listener_close(p->listener_token);
        return fail(result, error);
    }
    p->local_port = assigned_port;
    p->phase = TCP_LISTENING;
    s->bound = true;
    s->state = MOD_NETWORK_SS_LISTENING;
    return 0;
}
static void accept_discard(mod_network_socket_obj_t *other) {
    udp_state_t *p = state(other);
    other->_private = NULL;
    if (p) m_del(udp_state_t, p, 1);
}
static int socket_accept(mod_network_socket_obj_t *s, mod_network_socket_obj_t *other,
                         byte *ip, mp_uint_t *port, int *error) {
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return fail(MP_EBADF, error);
    if (state(s)->kind != MOD_NETWORK_SOCK_STREAM) return fail(MP_EOPNOTSUPP, error);
    if (state(s)->phase != TCP_LISTENING) return fail(MP_EINVAL, error);
    // Allocate/root all child state before the bridge transfers native ownership.
    // Nothing below success may allocate or run VM events.
    other->_private = m_new0(udp_state_t, 1);
    state(other)->kind = MOD_NETWORK_SOCK_STREAM;
    const int32_t timeout = socket_io_timeout(s, false);
    uint64_t start = mpynn_ticks_us64();
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        for (;;) {
            uint16_t peer_port;
            int result = mpynn_tcp_listener_accept(state(s)->listener_token,
                &state(other)->stream_token, ip, &peer_port);
            if (!result) {
                state(other)->nodelay = state(s)->nodelay;
                state(other)->nodelay_configured = state(s)->nodelay_configured;
                if (state(other)->nodelay_configured) {
                    result = mpynn_tcp_stream_set_nodelay(state(other)->stream_token,
                        state(other)->nodelay);
                    if (result) {
                        (void)mpynn_tcp_stream_close(state(other)->stream_token);
                        nlr_pop();
                        accept_discard(other);
                        return fail(result, error);
                    }
                }
                memcpy(state(other)->peer_ip, ip, sizeof(state(other)->peer_ip));
                state(other)->peer_port = peer_port;
                state(other)->phase = TCP_CONNECTED;
                other->state = MOD_NETWORK_SS_CONNECTED;
                other->timeout = -1; // Standard modsocket accepted-socket default.
                *port = peer_port;
                nlr_pop();
                return 0;
            }
            if (!retry(s, start, result, error, timeout)) {
                nlr_pop();
                accept_discard(other);
                return -1;
            }
            // retry may close/collect the parent; reacquire it on every call.
        }
    }
    accept_discard(other);
    nlr_jump(nlr.ret_val);
}
static mp_uint_t tcp_io(mod_network_socket_obj_t *s, void *buf, mp_uint_t len,
                        bool writing, int *error) {
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return (mp_uint_t)fail(MP_EBADF, error);
    if (state(s)->kind != MOD_NETWORK_SOCK_STREAM) return (mp_uint_t)fail(MP_EOPNOTSUPP, error);
    const int32_t timeout = socket_io_timeout(s, writing);
    uint64_t start = mpynn_ticks_us64();
    for (;;) {
        int result = tcp_finish(s);
        if (!result) {
            size_t count;
            uint32_t token = state(s)->stream_token;
            result = writing ? mpynn_tcp_stream_write(token, buf, len, &count)
                             : mpynn_tcp_stream_read(token, buf, len, &count);
            if (!result) return (mp_uint_t)count;
            record_so_error(state(s), result);
        }
        if (!tcp_retry(s, start, result, error, timeout)) return (mp_uint_t)-1;
        // Do not retain private-state pointers across retry's Python events.
    }
}
static mp_uint_t socket_send(mod_network_socket_obj_t *s, const byte *buf, mp_uint_t len, int *error) {
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return (mp_uint_t)fail(MP_EBADF, error);
    if (state(s)->kind != MOD_NETWORK_SOCK_DGRAM) return tcp_io(s, (void *)buf, len, true, error);
    if (!state(s)->connected) return (mp_uint_t)fail(MP_ENOTCONN, error);
    const int32_t timeout = socket_io_timeout(s, true);
    uint64_t start = mpynn_ticks_us64();
    for (;;) {
        // Even an empty send must emit a datagram, not merely return zero.
        int result = mpynn_udp_send(state(s)->token, buf, len);
        if (!result) return len;
        if (!retry(s, start, result, error, timeout)) return (mp_uint_t)-1;
        // retry may close/collect the socket; reacquire state for each bridge call.
    }
}
static mp_uint_t socket_recv(mod_network_socket_obj_t *s, byte *buf, mp_uint_t len, int *error) {
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) return (mp_uint_t)fail(MP_EBADF, error);
    if (state(s)->kind != MOD_NETWORK_SOCK_DGRAM) return tcp_io(s, buf, len, false, error);
    // UDP recv is also valid after bind/sendto without connect (upstream ntptime).
    // Native active-peer filtering remains in effect only when a peer is set.
    // recv(0) is immediate and does not consume a packet; recvfrom(0) does.
    if (!len) return 0;
    byte ip[4]; mp_uint_t port;
    // The native socket's peer filter applies; the caller does not need its address.
    return udp_recvfrom(s, buf, len, ip, &port, error);
}
mp_obj_t mpynn_socket_sendall(mp_obj_t self_in, mp_obj_t buffer_in) {
    mod_network_socket_obj_t *s = MP_OBJ_TO_PTR(self_in);
    if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    if (state(s)->kind == MOD_NETWORK_SOCK_DGRAM && !state(s)->connected)
        mp_raise_OSError(MP_ENOTCONN);
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(buffer_in, &buffer, MP_BUFFER_READ);
    const int32_t timeout = socket_io_timeout(s, true);
    const uint64_t start = mpynn_ticks_us64();
    size_t offset = 0;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        while (offset < buffer.len) {
            if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
            if (timeout > 0 && mpynn_ticks_us64() - start >= (uint64_t)timeout * 1000) {
                tcp_abort_pending(s, MP_ETIMEDOUT);
                mp_raise_OSError(MP_ETIMEDOUT);
            }
            size_t count = 0;
            int result;
            if (state(s)->kind == MOD_NETWORK_SOCK_STREAM) {
                result = tcp_finish(s);
                if (!result) result = mpynn_tcp_stream_write(state(s)->stream_token,
                    (const byte *)buffer.buf + offset, buffer.len - offset, &count);
            } else {
                result = mpynn_udp_send(state(s)->token,
                    (const byte *)buffer.buf + offset, buffer.len - offset);
                if (!result) count = buffer.len - offset;
            }
            if (result && result != MP_EAGAIN) mp_raise_OSError(result);
            if (!result) {
                if (!count) mp_raise_OSError(MP_EPIPE);
                if (count > buffer.len - offset) mp_raise_OSError(MP_EIO);
                offset += count;
                if (offset == buffer.len) break;
            }
            if (timeout == 0) mp_raise_OSError(MP_EAGAIN);
            // Bridge IO is nonblocking. This is the sole VM-event/yield site;
            // re-acquire private state and check the original deadline above.
            mp_event_handle_nowait();
            if (!state(s) || s->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
            if (result == MP_EAGAIN) mp_hal_delay_ms(1);
        }
        nlr_pop();
        return mp_const_none;
    }
    // Retain established sockets, but do not strand a pending native connect
    // after timeout/Ctrl-C. No private pointer survives event processing.
    tcp_abort_pending(s, MP_EINTR);
    nlr_jump(nlr.ret_val);
}

static int no_option(mod_network_socket_obj_t *s, mp_uint_t level, mp_uint_t opt,
                     const void *value, mp_uint_t len, int *error) {
    udp_state_t *p = state(s);
    if (!p || s->state == MOD_NETWORK_SS_CLOSED) return fail(MP_EBADF, error);
    if (level == MOD_NETWORK_SOL_SOCKET &&
        (opt == MOD_NETWORK_SO_SNDTIMEO || opt == MOD_NETWORK_SO_RCVTIMEO)) {
        if (!value || len != sizeof(mp_int_t)) return fail(MP_EINVAL, error);
        mp_int_t milliseconds;
        memcpy(&milliseconds, value, sizeof(milliseconds));
        if (milliseconds < 0 || milliseconds > INT32_MAX) return fail(MP_EINVAL, error);
        if (opt == MOD_NETWORK_SO_SNDTIMEO) {
            p->send_timeout = milliseconds ? (int32_t)milliseconds : -1;
            p->send_timeout_set = true;
        } else {
            p->recv_timeout = milliseconds ? (int32_t)milliseconds : -1;
            p->recv_timeout_set = true;
        }
        return 0;
    }
    if (level == MPYNN_SOCKET_IPPROTO_TCP && opt == MPYNN_SOCKET_TCP_NODELAY) {
        if (p->kind != MOD_NETWORK_SOCK_STREAM) return fail(MP_EOPNOTSUPP, error);
        if (!value || len != sizeof(mp_int_t)) return fail(MP_EINVAL, error);
        mp_int_t number;
        memcpy(&number, value, sizeof(number));
        bool enabled = number != 0;
        if (p->phase == TCP_CONNECTED) {
            int result = mpynn_tcp_stream_set_nodelay(p->stream_token, enabled);
            if (result) return fail(result, error);
        }
        p->nodelay = enabled;
        p->nodelay_configured = true;
        return 0;
    }
    if (p->kind != MOD_NETWORK_SOCK_DGRAM) return fail(MP_EOPNOTSUPP, error);
    if (level != MOD_NETWORK_SOL_SOCKET || opt != MOD_NETWORK_SO_BROADCAST)
        return fail(MP_EOPNOTSUPP, error);
    if (!value || len != sizeof(mp_int_t)) return fail(MP_EINVAL, error);
    mp_int_t number;
    memcpy(&number, value, sizeof(number)); // Python buffer may be unaligned
    bool enabled = number != 0;
    if (p->opened) {
        int result = mpynn_udp_broadcast(p->token, enabled);
        if (result) return fail(result, error);
    }
    p->broadcast = enabled;
    return 0;
}
static void udp_deinit(void) {
    (void)mpynn_tcp_connect_cancel_all();
    (void)mpynn_tcp_listener_close_all();
    (void)mpynn_tcp_stream_close_all();
    (void)mpynn_udp_close_all();
    for (unsigned i = 0; i < TCP_BIND_SLOTS; ++i) tcp_bind_slots[i].port = 0;
}
const mod_network_nic_protocol_t mpynn_udp_nic_protocol = {
    .gethostbyname=mpynn_gethostbyname, .deinit=udp_deinit, .socket=udp_socket, .close=udp_close,
    .bind=udp_bind, .listen=socket_listen, .accept=socket_accept, .connect=socket_connect,
    .send=socket_send, .recv=socket_recv, .sendto=udp_sendto, .recvfrom=udp_recvfrom,
    .setsockopt=no_option, .settimeout=udp_timeout, .ioctl=udp_ioctl,
};
_Static_assert(MPYNN_UDP_POLL_RD == MP_STREAM_POLL_RD && MPYNN_UDP_POLL_WR == MP_STREAM_POLL_WR &&
    MPYNN_UDP_POLL_ERR == MP_STREAM_POLL_ERR && MPYNN_UDP_POLL_HUP == MP_STREAM_POLL_HUP &&
    MPYNN_UDP_POLL_NVAL == MP_STREAM_POLL_NVAL, "poll ABI");
_Static_assert(MPYNN_TCP_POLL_RD == MP_STREAM_POLL_RD && MPYNN_TCP_POLL_WR == MP_STREAM_POLL_WR &&
    MPYNN_TCP_POLL_ERR == MP_STREAM_POLL_ERR && MPYNN_TCP_POLL_HUP == MP_STREAM_POLL_HUP &&
    MPYNN_TCP_POLL_NVAL == MP_STREAM_POLL_NVAL, "TCP poll ABI");
