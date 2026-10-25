// SPDX-License-Identifier: MIT
#include <circle/bcmwatchdog.h>
#include <circle/synchronize.h>
#include <circle/new.h>
#include "machine_wdt.h"

namespace {
alignas(CBcmWatchdog) unsigned char storage[sizeof(CBcmWatchdog)];
CBcmWatchdog *watchdog;
const void *owner;
unsigned timeout_seconds;
static_assert(MPYNN_WDT_MAX_SECONDS == CBcmWatchdog::MaxTimeoutSeconds,
    "WDT timeout contract must match Circle");
int check(const void *token) {
    // Includes FIQ-only masking, not merely machine.disable_irq(). Reject before
    // constructing, reading or writing any watchdog hardware.
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_WDT_BUSY;
    if (!token) return MPYNN_WDT_INVALID;
    if (!owner) return MPYNN_WDT_UNINITIALIZED;
    return owner == token ? MPYNN_WDT_OK : MPYNN_WDT_BUSY;
}
int stop() {
    if (watchdog) {
        // Circle's destructor does NOT stop the watchdog. Stop explicitly before
        // destroying it or releasing ownership, including during VM soft reset.
        watchdog->Stop();
        watchdog->~CBcmWatchdog();
        watchdog = nullptr;
    }
    owner = nullptr;
    timeout_seconds = 0;
    return MPYNN_WDT_OK;
}
}
extern "C" int mpynn_wdt_init(const void *token, int id, int seconds, unsigned arm) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_WDT_BUSY;
    if (!token || id != 0 || arm > 1 || (arm ? seconds < 1 || seconds > MPYNN_WDT_MAX_SECONDS : seconds != 0)) {
        return MPYNN_WDT_INVALID;
    }
    if (owner && owner != token) return MPYNN_WDT_BUSY;
    owner = token;
    // Merely obtaining WDT(0) must not arm, rearm or touch the device, even when
    // the singleton was previously explicitly configured.
    if (!arm) return MPYNN_WDT_OK;
    if (!watchdog) watchdog = new (storage) CBcmWatchdog;
    watchdog->Start((unsigned)seconds);
    timeout_seconds = (unsigned)seconds;
    return MPYNN_WDT_OK;
}
extern "C" int mpynn_wdt_feed(const void *token) {
    int status = check(token);
    if (status) return status;
    if (!watchdog || !timeout_seconds) return MPYNN_WDT_UNINITIALIZED;
    // IMPORTANT: Circle Restart() means immediate machine reboot (~150us and
    // never returns), NOT pet/feed. Start(saved timeout) is the rearm operation.
    watchdog->Start(timeout_seconds);
    return MPYNN_WDT_OK;
}
extern "C" int mpynn_wdt_snapshot(const void *token, unsigned *running, unsigned *seconds_left) {
    int status = check(token);
    if (status) return status;
    if (!running || !seconds_left) return MPYNN_WDT_INVALID;
    *running = watchdog ? !!watchdog->IsRunning() : 0;
    *seconds_left = *running ? watchdog->GetTimeLeft() : 0;
    return MPYNN_WDT_OK;
}
extern "C" int mpynn_wdt_deinit(const void *token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_WDT_BUSY;
    if (!token) return MPYNN_WDT_INVALID;
    if (owner && owner != token) return MPYNN_WDT_BUSY;
    return stop();
}
extern "C" int mpynn_wdt_deinit_all(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_WDT_BUSY;
    return stop();
}
