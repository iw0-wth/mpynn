// SPDX-License-Identifier: MIT
#ifndef MPYNN_RTC_BRIDGE_H
#define MPYNN_RTC_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Software system clock. Boot initializes it to 2000-01-01 UTC; not persistent.
int mpynn_rtc_get_utc(uint32_t *seconds, unsigned *valid, unsigned *source);
int mpynn_rtc_set_utc(uint32_t seconds);
int mpynn_rtc_boot_software_epoch(uint32_t seconds);
#ifdef __cplusplus
}
#endif
#endif
