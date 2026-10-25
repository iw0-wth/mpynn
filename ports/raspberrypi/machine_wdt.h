// SPDX-License-Identifier: MIT
#ifndef MPYNN_MACHINE_WDT_H
#define MPYNN_MACHINE_WDT_H
#ifdef __cplusplus
extern "C" {
#endif
enum {
    MPYNN_WDT_OK = 0, MPYNN_WDT_INVALID = -1,
    MPYNN_WDT_BUSY = -2, MPYNN_WDT_UNINITIALIZED = -3,
};
#define MPYNN_WDT_MAX_SECONDS 15
// An unarmed open must pass arm=0, timeout_seconds=0. It performs no MMIO.
// Every hardware operation requires this same stable, non-null owner token.
int mpynn_wdt_init(const void *owner, int id, int timeout_seconds, unsigned arm);
int mpynn_wdt_feed(const void *owner);
int mpynn_wdt_snapshot(const void *owner, unsigned *running, unsigned *seconds_left);
int mpynn_wdt_deinit(const void *owner);
int mpynn_wdt_deinit_all(void);
#ifdef __cplusplus
}
#endif
#endif
