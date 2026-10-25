// SPDX-License-Identifier: MIT
#ifndef MPYNN_RASPBERRYPI_ETHERNET_BRIDGE_H
#define MPYNN_RASPBERRYPI_ETHERNET_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Diagnostic-only Ethernet frame layer. There is no IP, socket or IDE protocol.
// 0: success (link may be down); -1: no net device; -2: bad output;
// -3: not task context / interrupts masked. Speed queries may use USB control IO.
int mpynn_eth_snapshot(uint8_t mac[6], unsigned *link_up, unsigned *speed);
#ifdef __cplusplus
}
#endif
#endif
