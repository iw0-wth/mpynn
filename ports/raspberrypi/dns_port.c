// SPDX-License-Identifier: MIT
#include "py/runtime.h"
#include "py/mperrno.h"
#include "py/mphal.h"
#include "py/nlr.h"
#include "dns_port.h"
#include "dns_bridge.h"
#include "circle_bridge.h"

int mpynn_gethostbyname(mp_obj_t nic, const char *name, mp_uint_t len, uint8_t *out) {
    (void)nic;
    const uint64_t start = mpynn_ticks_us64();
    uint32_t token;
    int result = mpynn_dns_start(name, len, &token);
    if (result) {
        return result;
    }

    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        for (;;) {
            if (mpynn_ticks_us64() - start >= UINT64_C(5000000)) {
                (void)mpynn_dns_cancel(token);
                nlr_pop();
                return MP_ETIMEDOUT;
            }
            result = mpynn_dns_finish(token, out);
            if (result != MP_EAGAIN) {
                // Success and completed errors both consume the bridge job.
                nlr_pop();
                return result;
            }
            // Run Python pending events only after the C++ bridge has returned.
            mp_event_handle_nowait();
            mp_hal_delay_ms(1);
        }
    }
    (void)mpynn_dns_cancel(token);
    nlr_jump(nlr.ret_val);
}
