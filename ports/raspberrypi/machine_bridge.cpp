// SPDX-License-Identifier: MIT
#include <circle/bcmpropertytags.h>
#include <circle/machineinfo.h>
#include <circle/startup.h>
#include "machine_bridge.h"

extern "C" int mpynn_machine_serial(uint8_t serial[8]) {
    CBcmPropertyTags tags;
    TPropertyTagSerial tag = {};
    if (!tags.GetTag(PROPTAG_GET_BOARD_SERIAL, &tag, sizeof(tag))) return -1;
    // Stable big-endian representation of the board's 64-bit firmware serial.
    for (unsigned i = 0; i < 4; ++i) {
        serial[i] = (uint8_t)(tag.Serial[1] >> (24 - 8 * i));
        serial[i + 4] = (uint8_t)(tag.Serial[0] >> (24 - 8 * i));
    }
    return 0;
}
extern "C" uint32_t mpynn_machine_frequency(void) {
    // Circle's generic helper asserts if both queries fail for CLOCK_ID_ARM.
    // Preserve a recoverable error for the Python layer instead of halting.
    CBcmPropertyTags tags;
    TPropertyTagClockRate tag = {};
    tag.nClockId = CLOCK_ID_ARM;
    if (tags.GetTag(PROPTAG_GET_CLOCK_RATE_MEASURED, &tag, sizeof(tag), 4) && tag.nRate) {
        return tag.nRate;
    }
    tag = {};
    tag.nClockId = CLOCK_ID_ARM;
    if (tags.GetTag(PROPTAG_GET_CLOCK_RATE, &tag, sizeof(tag), 4) && tag.nRate) {
        return tag.nRate;
    }
    return 0;
}
extern "C" uint32_t mpynn_machine_revision(void) {
    return CMachineInfo::Get()->GetRevisionRaw();
}
extern "C" uint32_t mpynn_machine_ram_mb(void) {
    return CMachineInfo::Get()->GetRAMSize();
}
extern "C" const char *mpynn_machine_name(void) {
    return CMachineInfo::Get()->GetMachineName();
}
extern "C" void mpynn_machine_reset(void) {
    reboot();
    for (;;) {}
}
