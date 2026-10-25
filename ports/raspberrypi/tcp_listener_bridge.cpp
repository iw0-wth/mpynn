// SPDX-License-Identifier: MIT
#include "tcp_listener_bridge.h"
#include "tcp_stream_bridge.h"
#include "network_bridge.h"
#include "socket_errno_bridge.h"
#include <circle/net/netsubsystem.h>
#include <circle/net/transportlayer.h>
#include <circle/net/ipaddress.h>
#include <circle/net/in.h>
#include <circle/synchronize.h>

namespace {
constexpr unsigned slot_count = 2;
constexpr uint32_t max_generation = UINT32_MAX >> 1;
struct Listener {
    CTransportLayer *transport = nullptr;
    uint32_t generation = 0;
    uint16_t port = 0;
    unsigned backlog = 0;
    int candidates[4] = {-1, -1, -1, -1};
};
Listener listeners[slot_count];
Listener *lookup(uint32_t token) {
    Listener &s = listeners[token & 1];
    return s.transport && s.generation == (token >> 1) ? &s : nullptr;
}
int dispose(Listener &s, unsigned i) {
    int handle = s.candidates[i];
    if (handle < 0) return 0;
    int result = s.transport->Disconnect(handle);
    int released = s.transport->ReleaseConnection(handle);
    s.candidates[i] = -1;
    return mpynn_socket_error_from_circle(result < 0 ? result : released);
}
int refill(Listener &s, unsigned i) {
    int handle = s.transport->Listen(s.port, IPPROTO_TCP);
    if (handle < 0) return mpynn_socket_error_from_circle(handle);
    // No yield between Listen and retain (nor anywhere in this bridge). Circle
    // Accept returns status/peer, NOT a new handle: this is the eventual stream.
    int result = s.transport->RetainConnection(handle);
    if (result < 0) {
        // A failed retain acquired no owner reference. Do not release one.
        s.transport->Disconnect(handle);
        return mpynn_socket_error_from_circle(result);
    }
    if (!s.port) {
        // First candidate chooses a native ephemeral port. All remaining
        // backlog/refill candidates must listen at exactly that same port.
        uint16_t assigned = s.transport->GetOwnPort(handle);
        if (!assigned) {
            s.transport->Disconnect(handle);
            s.transport->ReleaseConnection(handle);
            return MPYNN_IO;
        }
        s.port = assigned;
    }
    s.candidates[i] = handle;
    return 0;
}
int maintain(Listener &s) {
    int first_error = 0;
    for (unsigned i = 0; i < s.backlog; ++i) {
        if (s.candidates[i] >= 0) {
            int terminal = s.transport->GetTerminalError(s.candidates[i]);
            if (terminal < 0) {
                if (!first_error) first_error = mpynn_socket_error_from_circle(terminal);
                dispose(s, i); // Release even when Disconnect fails on CLOSED.
            }
        }
        if (s.candidates[i] < 0) {
            int error = refill(s, i);
            if (!first_error) first_error = error;
        }
    }
    return first_error;
}
int available(Listener &s) {
    CNetSubSystem *net = mpynn_network_get();
    return net && net->IsRunning() && net->GetTransportLayer() == s.transport
        ? 0 : MPYNN_NODEV;
}
}

extern "C" int mpynn_tcp_listener_open(uint16_t port, unsigned backlog, uint32_t *token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!token || backlog < 1 || backlog > 4) return MPYNN_INVAL;
    for (const Listener &s : listeners)
        if (port && s.transport && s.port == port) return MPYNN_ADDRINUSE;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) return MPYNN_NODEV;
    CTransportLayer *transport = net->GetTransportLayer();
    if (!transport) return MPYNN_NODEV;
    // New listeners cannot share an explicit TCP port with another native owner.
    // Refill does not repeat this check: backlog candidates intentionally share
    // this listener's port, including after an accepted stream is transferred.
    if (port && transport->IsPortInUse(port, IPPROTO_TCP)) return MPYNN_ADDRINUSE;
    for (unsigned i = 0; i < slot_count; ++i) {
        Listener &s = listeners[i];
        if (s.transport || s.generation == max_generation) continue;
        ++s.generation;
        s.transport = transport;
        s.port = port;
        s.backlog = backlog;
        for (unsigned j = 0; j < backlog; ++j) {
            int error = refill(s, j);
            if (error) {
                for (unsigned k = 0; k < backlog; ++k) dispose(s, k);
                s.transport = nullptr;
                return error;
            }
        }
        *token = (s.generation << 1) | i;
        return 0;
    }
    return MPYNN_MFILE;
}

extern "C" int mpynn_tcp_listener_local_port(uint32_t token, uint16_t *port) {
    if (!port) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Listener *s = lookup(token);
    if (!s) return MPYNN_BADF;
    *port = s->port;
    return 0;
}

extern "C" int mpynn_tcp_listener_poll(uint32_t token, unsigned *ready) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!ready) return MPYNN_INVAL;
    Listener *s = lookup(token);
    if (!s) return MPYNN_BADF;
    int error = available(*s);
    if (error) return error;
    error = maintain(*s);
    for (unsigned i = 0; i < s->backlog; ++i) {
        if (s->candidates[i] >= 0 && s->transport->IsAcceptReady(s->candidates[i])) {
            *ready = 1;
            return 0;
        }
    }
    if (error) return error;
    *ready = 0;
    return 0;
}

extern "C" int mpynn_tcp_listener_accept(uint32_t token, uint32_t *stream_token,
                                          uint8_t ip[4], uint16_t *port) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!stream_token || !ip || !port) return MPYNN_INVAL;
    Listener *s = lookup(token);
    if (!s) return MPYNN_BADF;
    int error = available(*s);
    if (error) return error;
    error = maintain(*s);
    for (unsigned i = 0; i < s->backlog; ++i) {
        int handle = s->candidates[i];
        // Never invoke potentially blocking Accept on LISTEN or a half-open SYN.
        if (handle < 0 || !s->transport->IsAcceptReady(handle)) continue;
        CIPAddress peer;
        uint16_t peer_port;
        int result = s->transport->Accept(&peer, &peer_port, handle);
        if (result < 0) {
            dispose(*s, i);
            refill(*s, i);
            return mpynn_socket_error_from_circle(result);
        }
        uint32_t stream;
        result = mpynn_tcp_stream_claim(handle, &stream);
        if (result) return result; // The original retained candidate stays ours.
        s->candidates[i] = -1; // Transfer precisely one existing owner reference.
        *stream_token = stream;
        const uint8_t *address = peer.Get();
        for (unsigned j = 0; j < 4; ++j) ip[j] = address[j];
        *port = peer_port;
        // Allocation failure must not erase a successfully accepted connection.
        // Leave a vacancy for the next poll/accept to retry.
        refill(*s, i);
        return 0;
    }
    return error ? error : MPYNN_AGAIN;
}

extern "C" int mpynn_tcp_listener_close(uint32_t token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Listener *s = lookup(token);
    if (!s) return MPYNN_BADF;
    int first_error = 0;
    for (unsigned i = 0; i < s->backlog; ++i) {
        int error = dispose(*s, i);
        if (!first_error) first_error = error;
    }
    s->transport = nullptr; // Preserve generation; never resurrect stale tokens.
    return first_error;
}
extern "C" int mpynn_tcp_listener_close_all(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    int first_error = 0;
    for (unsigned i = 0; i < slot_count; ++i) {
        if (!listeners[i].transport) continue;
        int error = mpynn_tcp_listener_close((listeners[i].generation << 1) | i);
        if (!first_error) first_error = error;
    }
    return first_error;
}
