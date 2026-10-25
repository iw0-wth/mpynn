// SPDX-License-Identifier: MIT
#ifndef MPYNN_RASPBERRYPI_SDCARD_BRIDGE_H
#define MPYNN_RASPBERRYPI_SDCARD_BRIDGE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum mpynn_sd_status {
    MPYNN_SD_OK = 0,
    MPYNN_SD_NOT_READY = 1,
    MPYNN_SD_INVALID = 2,
    MPYNN_SD_RANGE = 3,
    MPYNN_SD_IO = 4,
    MPYNN_SD_BUSY = 5,
    MPYNN_SD_CONTEXT = 6
};

// Kernel-owned, already initialized CEMMCDevice; attach once after Initialize().
void mpynn_sd_attach(void *device, int initialized);
int mpynn_sd_ready(void);
int mpynn_sd_block_count(uint64_t *blocks);
int mpynn_sd_read(uint64_t block, void *buffer, size_t len);
int mpynn_sd_write(uint64_t block, const void *buffer, size_t len);
// No bridge cache; Circle's Write completes its command before returning.
int mpynn_sd_sync(void);

// Sticky last failure plus cumulative transfer counters; reads no SD sectors.
// stage: 0 validation/context, 1 Seek, 2 actual Read/Write. result is meaningful
// only at stage2; no software cache of filesystem data is exposed.
typedef struct {
    uint64_t read_requests, write_requests, read_sectors, write_sectors, failures;
    uint64_t last_block;
    size_t last_length;
    int last_status, last_result;
    unsigned last_writing, last_stage, ready;
} mpynn_sd_diagnostics_t;
int mpynn_sd_diagnostics(mpynn_sd_diagnostics_t *snapshot);

#ifdef __cplusplus
}
#endif

#endif
