// SPDX-License-Identifier: MIT
#include "network_bridge.h"
#include "socket_errno_bridge.h"
#include <circle/net/netsubsystem.h>
#include <circle/synchronize.h>
#include <string.h>

namespace {
CNetSubSystem *network;
uint32_t address(const uint8_t *p) {
    return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | p[3];
}
bool unicast(uint32_t ip) {
    return (ip >> 24) != 0 && (ip >> 24) != 127 && (ip >> 24) < 224;
}
bool valid_static(const mpynn_network_state_t &state) {
    const uint32_t ip = address(state.ip), mask = address(state.netmask);
    const uint32_t hosts = ~mask, gateway = address(state.gateway), dns = address(state.dns);
    if (!unicast(ip) || !mask || (hosts & (hosts + 1))) return false;
    // /31 point-to-point and /32 host interfaces do not have reserved host bits.
    if (hosts > 1 && (!(ip & hosts) || (ip & hosts) == hosts)) return false;
    if (gateway && (!unicast(gateway) || (ip & mask) != (gateway & mask)
                    || (hosts > 1 && (!(gateway & hosts) || (gateway & hosts) == hosts)))) return false;
    return !dns || unicast(dns);
}
}
extern "C" int mpynn_network_configure(const mpynn_network_state_t *state) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!network) return MPYNN_NODEV;
    // Reject invalid tuples before cancelling any lease or mutating live state.
    if (state && !valid_static(*state)) return MPYNN_INVAL;
    // Never Yield: RequestMode prevents a suspended DHCP exchange from writing
    // over this tuple when the worker next resumes. Caller pointers are copied.
    if (state) network->Configure(state->ip, state->netmask, state->gateway, state->dns);
    else network->Configure();
    return 0;
}
CNetSubSystem *mpynn_network_get() {
    return CurrentExecutionLevel() == TASK_LEVEL ? network : nullptr;
}
extern "C" void mpynn_network_attach(void *value, int initialized) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return;
    network = initialized ? static_cast<CNetSubSystem *>(value) : nullptr;
}
extern "C" int mpynn_network_snapshot(mpynn_network_state_t *state) {
    if (!state) return -2;
    if (CurrentExecutionLevel() != TASK_LEVEL) return -3;
    // No Yield here: network tasks cannot change a configuration halfway through
    // this snapshot. No caller retains any Circle or GC-owned pointer.
    mpynn_network_state_t result = {};
    if (network) {
        result.initialized = 1;
        result.running = network->IsRunning() ? 1u : 0u;
        CNetConfig *config = network->GetConfig();
        result.dhcp = config->IsDHCPUsed() ? 1u : 0u;
        config->GetIPAddress()->CopyTo(result.ip);
        memcpy(result.netmask, config->GetNetMask(), sizeof(result.netmask));
        config->GetDefaultGateway()->CopyTo(result.gateway);
        config->GetDNSServer()->CopyTo(result.dns);
    }
    *state = result;
    return 0;
}
