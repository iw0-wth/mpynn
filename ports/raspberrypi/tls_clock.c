// SPDX-License-Identifier: MIT
#include <stdint.h>
#include <string.h>
#include "mbedtls/platform_time.h"
#include "mbedtls/platform_util.h"
#include "shared/timeutils/timeutils.h"
#include "circle_bridge.h"
#include "tls_random_bridge.h"

// Conservative common range for MicroPython's default 32-bit timeutils and
// signed 32-bit time_t. Reject unsupported timestamps rather than wrapping.
static int supported_utc(time_t seconds) {
    return seconds >= (time_t)0 && (uint64_t)seconds <= INT32_MAX;
}

__attribute__((weak)) int mpynn_tls_get_utc(time_t *unix_seconds) {
    (void)unix_seconds;
    return 0; // No RTC/explicitly established UTC in the default port.
}

time_t mpynn_tls_time(time_t *timer) {
    time_t result = (time_t)-1;
    time_t candidate = (time_t)-1;
    if (mpynn_tls_get_utc(&candidate) == 1 && supported_utc(candidate)) {
        result = candidate;
    }
    if (timer != NULL) {
        *timer = result;
    }
    return result;
}

int mpynn_tls_time_is_valid(void) {
    return mpynn_tls_time(NULL) != (time_t)-1;
}

mbedtls_ms_time_t mbedtls_ms_time(void) {
    // This is monotonic time for protocol deadlines, never a UTC source.
    return (mbedtls_ms_time_t)(mpynn_ticks_us64() / 1000);
}

struct tm *mbedtls_platform_gmtime_r(const mbedtls_time_t *timer,
    struct tm *result) {
    if (timer == NULL || result == NULL || !supported_utc(*timer)) {
        return NULL;
    }
    timeutils_struct_time_t utc;
    timeutils_seconds_since_1970_to_struct_time((timeutils_timestamp_t)*timer, &utc);
    memset(result, 0, sizeof(*result));
    result->tm_year = utc.tm_year - 1900;
    result->tm_mon = utc.tm_mon - 1;
    result->tm_mday = utc.tm_mday;
    result->tm_hour = utc.tm_hour;
    result->tm_min = utc.tm_min;
    result->tm_sec = utc.tm_sec;
    result->tm_wday = (utc.tm_wday + 1) % 7; // MP Monday=0, libc Sunday=0.
    result->tm_yday = utc.tm_yday - 1;
    result->tm_isdst = 0;
    return result;
}
