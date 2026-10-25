// SPDX-License-Identifier: MIT
#include "rtc_bridge.h"
#include "tls_random_bridge.h"
#include <stdint.h>

// Strong provider overrides tls_clock.c's unavailable default. A user-set time
// is accepted as asserted UTC, not as a cryptographically authenticated source.
int mpynn_tls_get_utc(time_t *unix_seconds) {
    uint32_t seconds;
    unsigned calibrated, source;
    if (!unix_seconds || mpynn_rtc_get_utc(&seconds, &calibrated, &source) != 0 ||
        !calibrated || source == 0 || seconds > INT32_MAX) {
        return 0;
    }
    *unix_seconds = (time_t)seconds;
    return 1;
}
