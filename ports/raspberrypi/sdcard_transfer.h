// SPDX-License-Identifier: MIT
#ifndef MPYNN_RASPBERRYPI_SDCARD_TRANSFER_H
#define MPYNN_RASPBERRYPI_SDCARD_TRANSFER_H

#include <stddef.h>
#include <stdint.h>
#include <limits.h>

#define MPYNN_SD_SECTOR_SIZE 512u

// Validate the entire transfer before the first I/O; Circle takes a u32 block number.
static inline int mpynn_sd_transfer_in_range(uint64_t block, size_t len,
                                              uint64_t blocks) {
    const uint64_t count = len / MPYNN_SD_SECTOR_SIZE;
    return len != 0 && len % MPYNN_SD_SECTOR_SIZE == 0 &&
           block <= UINT32_MAX && count <= (uint64_t)UINT32_MAX - block + 1 &&
           block < blocks && count <= blocks - block &&
           block <= UINT64_MAX / MPYNN_SD_SECTOR_SIZE &&
           count - 1 <= UINT64_MAX / MPYNN_SD_SECTOR_SIZE - block;
}

#endif
