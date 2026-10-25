// SPDX-License-Identifier: MIT
// Included by extmod/modtime.c. All calendar APIs share machine.RTC's clock.
#include "rtc_bridge.h"
#include "py/mperrno.h"
#include "shared/timeutils/timeutils.h"

static uint32_t rtc_unix_seconds(void) {
    uint32_t seconds;
    unsigned calibrated, source;
    if (mpynn_rtc_get_utc(&seconds, &calibrated, &source)) mp_raise_OSError(MP_EIO);
    return seconds; // Boot year-2000 value is readable, even before calibration.
}
static void mp_time_localtime_get(timeutils_struct_time_t *tm) {
    timeutils_seconds_since_1970_to_struct_time(rtc_unix_seconds(), tm);
}
static mp_obj_t mp_time_time_get(void) {
    return mp_obj_new_int_from_uint(rtc_unix_seconds());
}
// Resolution is one second, despite the nanosecond unit of this API.
uint64_t mp_hal_time_ns(void) {
    return (uint64_t)rtc_unix_seconds() * UINT64_C(1000000000);
}
