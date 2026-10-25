// SPDX-License-Identifier: MIT
#include <circle/netdevice.h>
#include <circle/macaddress.h>
#include <circle/synchronize.h>
#include "ethernet_bridge.h"

extern "C" int mpynn_eth_snapshot(uint8_t mac[6], unsigned *link_up, unsigned *speed) {
    if (!mac || !link_up || !speed) return -2;
    if (CurrentExecutionLevel() != TASK_LEVEL) return -3;
    CNetDevice *device = CNetDevice::GetNetDevice(0);
    if (!device || device->GetType() != NetDeviceTypeEthernet) return -1;
    const CMACAddress *address = device->GetMACAddress();
    if (!address) return -1;
    address->CopyTo(mac);
    *link_up = device->IsLinkUp() ? 1u : 0u;
    *speed = (unsigned)device->GetLinkSpeed();
    return 0;
}
