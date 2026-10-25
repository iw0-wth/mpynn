// SPDX-License-Identifier: MIT
#include "udp_bridge.h"
#include "network_bridge.h"
#include <circle/net/netsubsystem.h>
#include <circle/net/transportlayer.h>
#include <circle/net/netbuffer.h>
#include <circle/net/in.h>
#include <circle/synchronize.h>
#include "socket_errno_bridge.h"
#include <string.h>

namespace {
constexpr unsigned slots = 8;
struct Entry { CTransportLayer *transport = nullptr; int handle = -1; uint32_t generation = 0; bool connected = false; };
Entry table[slots];
Entry *lookup(uint32_t token) {
    Entry &entry = table[token & (slots-1)];
    return entry.transport && (token >> 3) == entry.generation ? &entry : nullptr;
}
}
extern "C" int mpynn_udp_open(uint32_t *token) {
    return mpynn_udp_open_bound(0, token);
}
extern "C" int mpynn_udp_open_bound(uint16_t local_port, uint32_t *token) {
    if (!token) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) return MPYNN_NODEV;
    // Circle Bind only checks conflicts for ephemeral allocation. Reserve the
    // kernel DHCP client port even between lease renewals; it is not VM-owned.
    if (local_port == 68) return MPYNN_ADDRINUSE;
    if (local_port) {
        for (const Entry &existing : table) {
            if (existing.transport && existing.transport->GetOwnPort(existing.handle) == local_port)
                return MPYNN_ADDRINUSE;
        }
    }
    for (unsigned i = 0; i < slots; ++i) {
        Entry &entry = table[i];
        // Do not wrap a generation and make an ancient token valid again.
        if (entry.transport || entry.generation == (UINT32_MAX >> 3)) continue;
        CTransportLayer *transport = net->GetTransportLayer();
        int handle = transport->Bind(local_port, IPPROTO_UDP);
        if (handle < 0) return mpynn_socket_error_from_circle(handle);
        entry.handle = handle;
        entry.connected = false;
        entry.transport = transport;
        ++entry.generation;
        *token = (entry.generation << 3) | i;
        return 0;
    }
    return MPYNN_MFILE;
}
extern "C" int mpynn_udp_bind_local(uint32_t token, const uint8_t ip[4]) {
    if (!ip) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    CIPAddress address(ip);
    return mpynn_socket_error_from_circle(
        entry->transport->SetUDPLocalAddress(address, entry->handle));
}
extern "C" int mpynn_udp_local_port(uint32_t token, uint16_t *port) {
    if (!port) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    *port = entry->transport->GetOwnPort(entry->handle);
    return 0;
}
extern "C" int mpynn_udp_take_error(uint32_t token, int *error) {
    if (!error) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    *error = mpynn_socket_error_from_circle(entry->transport->TakeUDPError(entry->handle));
    return 0;
}
extern "C" int mpynn_udp_poll(uint32_t token, unsigned requested, unsigned *events) {
    if (!events) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) { *events = MPYNN_UDP_POLL_NVAL; return 0; }
    auto status = entry->transport->GetStatus(entry->handle);
    unsigned result = 0;
    // Pending UDP errors also make RX ready in Circle; recv reports the error.
    if (status.bRxReady) result |= requested & MPYNN_UDP_POLL_RD;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) result |= MPYNN_UDP_POLL_ERR;
    else if (status.bTxReady) result |= requested & MPYNN_UDP_POLL_WR;
    if (!status.bConnected) result |= MPYNN_UDP_POLL_HUP;
    if (status.bException) result |= MPYNN_UDP_POLL_ERR;
    *events = result;
    return 0;
}
extern "C" int mpynn_udp_broadcast(uint32_t token, int enabled) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    return mpynn_socket_error_from_circle(
        entry->transport->SetOptionBroadcast(enabled != 0, entry->handle));
}
extern "C" int mpynn_udp_connect(uint32_t token, const uint8_t ip[4], uint16_t port) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    if (!ip || !port || ip[0] == 0) return MPYNN_INVAL;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) return MPYNN_NOTCONN;
    CIPAddress peer(ip);
    int result = entry->transport->SetUDPPeer(peer, port, entry->handle);
    if (result < 0) return mpynn_socket_error_from_circle(result);
    entry->connected = true;
    return 0;
}
extern "C" int mpynn_udp_send(uint32_t token, const void *data, size_t length) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    if (!entry->connected) return MPYNN_NOTCONN;
    if ((length && !data) || length > entry->transport->GetMSS(entry->handle)) return MPYNN_INVAL;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) return MPYNN_NOTCONN;
    CNetBuffer *packet = new CNetBuffer(CNetBuffer::UDPSend, length, data);
    int result = entry->transport->Send(packet, MSG_DONTWAIT, entry->handle);
    if (result < 0) {
        delete packet;
        return mpynn_socket_error_from_circle(result);
    }
    return (size_t)result == length ? 0 : MPYNN_IO;
}
extern "C" int mpynn_udp_close(uint32_t token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    int result = entry->transport->Disconnect(entry->handle);
    entry->transport = nullptr;
    entry->handle = -1;
    return mpynn_socket_error_from_circle(result);
}
extern "C" int mpynn_udp_close_all(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    int first_error = 0;
    for (unsigned i = 0; i < slots; ++i) {
        if (!table[i].transport) continue;
        int error = mpynn_udp_close((table[i].generation << 3) | i);
        if (!first_error) first_error = error;
    }
    return first_error;
}
extern "C" int mpynn_udp_sendto(uint32_t token, const void *data, size_t length,
                                 const uint8_t ip[4], uint16_t port) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    if ((length && !data) || !ip || !port) return MPYNN_INVAL;
    if (length > entry->transport->GetMSS(entry->handle)) return MPYNN_INVAL;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) return MPYNN_NOTCONN;
    CNetBuffer *packet = new CNetBuffer(CNetBuffer::UDPSend, length, data);
    CIPAddress destination(ip);
    int result = entry->transport->SendTo(packet, MSG_DONTWAIT, destination, port, entry->handle);
    if (result < 0) {
        delete packet;
        return mpynn_socket_error_from_circle(result);
    }
    // On success Circle owns packet, including on an unexpected short result.
    return (size_t)result == length ? 0 : MPYNN_IO;
}
extern "C" int mpynn_udp_recvfrom(uint32_t token, void *data, size_t capacity,
                                   size_t *received, uint8_t ip[4], uint16_t *port) {
    if (!received || !ip || !port || (capacity && !data)) return MPYNN_INVAL;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Entry *entry = lookup(token);
    if (!entry) return MPYNN_BADF;
    CNetBuffer *packet = nullptr;
    CIPAddress source;
    uint16_t source_port = 0;
    int result = entry->transport->ReceiveFrom(&packet, MSG_DONTWAIT, &source, &source_port, entry->handle);
    if (result < 0) { delete packet; return mpynn_socket_error_from_circle(result); }
    if (!packet) return MPYNN_AGAIN; // zero with no packet is not EOF
    size_t count = packet->GetLength();
    if (count > capacity) count = capacity;
    if (count) memcpy(data, packet->GetPtr(), count);
    source.CopyTo(ip);
    *port = source_port;
    *received = count;
    delete packet; // UDP truncation discards just this datagram's tail
    return 0;
}
