// SPDX-License-Identifier: MIT
#include "tcp_stream_bridge.h"
#include "network_bridge.h"
#include "socket_errno_bridge.h"
#include "socket_rx_cache.h"
#include <circle/net/netsubsystem.h>
#include <circle/net/transportlayer.h>
#include <circle/net/netbuffer.h>
#include <circle/net/in.h>
#include <circle/synchronize.h>

namespace {
struct Stream {
    CTransportLayer *transport = nullptr;
    int handle = -1;
    uint32_t generation = 0;
    MpynnSocketRxCache<CNetBuffer> rx;
    bool read_shutdown = false;
    bool write_shutdown = false;
};
Stream streams[4];
Stream *lookup(uint32_t token) {
    Stream &s = streams[token & 3];
    return s.transport && s.generation == (token >> 2) ? &s : nullptr;
}
}
extern "C" int mpynn_tcp_stream_claim(int handle, uint32_t *token) {
    if (!token || handle < 0) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    CNetSubSystem *net = mpynn_network_get();
    if (!net) return MPYNN_NODEV;
    CTransportLayer *transport = net->GetTransportLayer();
    if (!transport) return MPYNN_NODEV;
    for (const Stream &s : streams) {
        if (s.transport == transport && s.handle == handle) return MPYNN_BUSY;
    }
    for (unsigned i=0; i<4; ++i) {
        Stream &s = streams[i];
        if (s.transport || s.generation == (UINT32_MAX >> 2)) continue;
        // Adopt the owner ref transferred by take; do not retain a second ref.
        s.rx.clear();
        s.read_shutdown = false;
        s.write_shutdown = false;
        s.transport = transport;
        s.handle = handle;
        ++s.generation;
        *token = (s.generation << 2) | i;
        return 0;
    }
    return MPYNN_MFILE;
}
extern "C" int mpynn_tcp_stream_discard(int handle) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (handle < 0) return MPYNN_INVAL;
    CNetSubSystem *net = mpynn_network_get();
    if (!net) return MPYNN_NODEV;
    CTransportLayer *transport = net->GetTransportLayer();
    if (!transport) return MPYNN_NODEV;
    for (const Stream &s : streams) {
        if (s.transport == transport && s.handle == handle) return MPYNN_BUSY;
    }
    int result = transport->Disconnect(handle);
    int released = transport->ReleaseConnection(handle);
    return mpynn_socket_error_from_circle(result < 0 ? result : released);
}
extern "C" int mpynn_tcp_stream_local_port(uint32_t token, uint16_t *port) {
    if (!port) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Stream *s = lookup(token);
    if (!s) return MPYNN_BADF;
    *port = s->transport->GetOwnPort(s->handle);
    return 0;
}
extern "C" int mpynn_tcp_stream_get_error(uint32_t token, int *error) {
    if (!error) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Stream *s = lookup(token);
    if (!s) return MPYNN_BADF;
    const int terminal = s->transport->GetTerminalError(s->handle);
    *error = terminal < 0 ? mpynn_socket_error_from_circle(terminal) : 0;
    return 0;
}
extern "C" int mpynn_tcp_stream_set_nodelay(uint32_t token, unsigned enabled) {
    if (enabled > 1) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Stream *s = lookup(token);
    if (!s) return MPYNN_BADF;
    return mpynn_socket_error_from_circle(s->transport->SetOptionNoDelay(enabled != 0, s->handle));
}
extern "C" int mpynn_tcp_stream_shutdown(uint32_t token, unsigned how) {
    if (how > 2) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Stream *s = lookup(token);
    if (!s) return MPYNN_BADF;
    const int result = s->transport->Shutdown(how, s->handle);
    if (result < 0) return mpynn_socket_error_from_circle(result);
    if (how == 0 || how == 2) {
        s->rx.clear();
        s->read_shutdown = true;
    }
    if (how == 1 || how == 2) s->write_shutdown = true;
    return 0;
}
extern "C" int mpynn_tcp_stream_poll(uint32_t token, unsigned requested, unsigned *events) {
    if (!events) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Stream *s = lookup(token);
    if (!s) { *events = MPYNN_TCP_POLL_NVAL; return 0; }
    unsigned result = 0;
    auto status = s->transport->GetStatus(s->handle);
    int terminal = s->transport->GetTerminalError(s->handle);
    if (s->read_shutdown || s->rx.available() || status.bRxReady || s->transport->IsReceiveEOF(s->handle))
        result |= requested & MPYNN_TCP_POLL_RD;
    if (!s->write_shutdown && status.bTxReady && terminal >= 0) result |= requested & MPYNN_TCP_POLL_WR;
    if (status.bException || terminal < 0) result |= MPYNN_TCP_POLL_ERR;
    if (!status.bConnected) result |= MPYNN_TCP_POLL_HUP;
    *events = result;
    return 0;
}
extern "C" int mpynn_tcp_stream_read(uint32_t token, void *buffer, size_t length, size_t *received) {
    if (!received || (!buffer && length)) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Stream *s = lookup(token);
    if (!s) return MPYNN_BADF;
    if (s->read_shutdown || !length) { *received=0; return 0; }
    if (!s->rx.available()) {
        int terminal = s->transport->GetTerminalError(s->handle);
        if (terminal < 0) return mpynn_socket_error_from_circle(terminal);
        if (s->transport->IsReceiveEOF(s->handle)) { *received=0; return 0; }
        CNetBuffer *packet = nullptr;
        int result = s->transport->Receive(&packet, MSG_DONTWAIT, s->handle);
        if (result < 0) { delete packet; return mpynn_socket_error_from_circle(result); }
        if (!packet) {
            int terminal = s->transport->GetTerminalError(s->handle);
            if (terminal < 0) return mpynn_socket_error_from_circle(terminal);
            // No pending data on an established stream is still EAGAIN.
            return MPYNN_AGAIN;
        }
        if (result == 0 || (size_t)result != packet->GetLength() || !s->rx.adopt(packet)) {
            delete packet;
            return MPYNN_IO;
        }
    }
    *received = s->rx.read(buffer, length);
    return 0;
}
extern "C" int mpynn_tcp_stream_write(uint32_t token, const void *buffer, size_t length, size_t *sent) {
    if (!sent || (!buffer && length)) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Stream *s = lookup(token);
    if (!s) return MPYNN_BADF;
    if (s->write_shutdown) return MPYNN_PIPE;
    if (!length) { *sent=0; return 0; }
    int terminal = s->transport->GetTerminalError(s->handle);
    if (terminal < 0) return mpynn_socket_error_from_circle(terminal);
    if (!s->transport->GetStatus(s->handle).bTxReady) return MPYNN_AGAIN;
    size_t count = s->transport->GetMSS(s->handle);
    if (!count) return MPYNN_NOTCONN;
    if (count > length) count = length;
    // One MSS per attempt bounds queued bytes and preserves partial-send results.
    CNetBuffer *packet = new CNetBuffer(CNetBuffer::TCPSend, count, buffer);
    int result = s->transport->Send(packet, MSG_DONTWAIT, s->handle);
    if (result < 0) { delete packet; return mpynn_socket_error_from_circle(result); }
    if ((size_t)result > count || result == 0) return MPYNN_IO;
    *sent = result;
    return 0;
}
extern "C" int mpynn_tcp_stream_close(uint32_t token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Stream *s = lookup(token);
    if (!s) return MPYNN_BADF;
    s->rx.clear();
    int result = s->transport->Disconnect(s->handle);
    int released = s->transport->ReleaseConnection(s->handle);
    if (result >= 0) result = released;
    s->transport = nullptr;
    s->handle = -1;
    return mpynn_socket_error_from_circle(result);
}
extern "C" int mpynn_tcp_stream_close_all(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    int first_error=0;
    for (unsigned i=0; i<4; ++i) {
        if (!streams[i].transport) continue;
        int error=mpynn_tcp_stream_close((streams[i].generation << 2) | i);
        if (!first_error) first_error=error;
    }
    return first_error;
}
