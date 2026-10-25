// SPDX-License-Identifier: MIT
#ifndef MPYNN_NETWORK_BRIDGE_H
#define MPYNN_NETWORK_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    unsigned initialized;
    unsigned running; // Circle IsRunning: includes DHCP-bound when DHCP is used.
    unsigned dhcp;
    uint8_t ip[4], netmask[4], gateway[4], dns[4];
} mpynn_network_state_t;
// Kernel owns one CNetSubSystem for platform lifetime; never a VM GC object.
void mpynn_network_attach(void *network, int initialized);
// 0 success (including uninitialized); -2 null output; -3 wrong IRQ context.
int mpynn_network_snapshot(mpynn_network_state_t *state);
// Nonnull: copy static IPv4 ip/netmask/gateway/dns (ignore status flags).
// Null: clear old lease and request DHCP asynchronously; poll snapshot.running.
// MUST close all application sockets before changing configuration. This does
// not close/rebuild the transport or invalidate retained Circle pointers.
// No allocation/yield; task-context only. Returns 0 or positive MP errno:
// ENODEV(19) unattached, EBUSY(16) wrong execution level, EINVAL(22) invalid static IP.
int mpynn_network_configure(const mpynn_network_state_t *state);
#ifdef __cplusplus
}
class CNetSubSystem;
// Internal C++ only; task-context callers must not retain this beyond platform life.
CNetSubSystem *mpynn_network_get();
#endif
#endif
