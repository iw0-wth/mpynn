// SPDX-License-Identifier: MIT
#include "sdcard_bridge.h"
#include "sdcard_transfer.h"

#include <SDCard/emmc.h>
#include <circle/synchronize.h>
#include <circle/logger.h>
#include <string.h>

namespace {
CEMMCDevice *device;
bool initialized;
bool busy;
mpynn_sd_diagnostics_t diagnostics = {};

void increment(uint64_t &counter) {
    if (counter != UINT64_MAX) ++counter;
}
int failed(uint64_t block, size_t length, bool writing, int status,
           unsigned stage = 0, int result = 0) {
    increment(diagnostics.failures);
    diagnostics.last_block = block;
    diagnostics.last_length = length;
    diagnostics.last_writing = writing;
    diagnostics.last_status = status;
    diagnostics.last_stage = stage;
    diagnostics.last_result = result;
    return status;
}

int enter(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_SD_CONTEXT;
    if (busy) return MPYNN_SD_BUSY;
    if (!initialized || !device) return MPYNN_SD_NOT_READY;
    busy = true;
    return MPYNN_SD_OK;
}

uint64_t capacity_blocks(void) {
    const uint64_t size = device->GetSize();
    if (size == UINT64_MAX || size < MPYNN_SD_SECTOR_SIZE ||
        size % MPYNN_SD_SECTOR_SIZE != 0) return 0;
    return size / MPYNN_SD_SECTOR_SIZE;
}

int transfer(uint64_t block, const void *buffer, size_t len, bool writing) {
    // IRQ calls are rejected before accessing 64-bit task-owned counters.
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_SD_CONTEXT;
    increment(writing ? diagnostics.write_requests : diagnostics.read_requests);
    if (!buffer || !len || len % MPYNN_SD_SECTOR_SIZE)
        return failed(block, len, writing, MPYNN_SD_INVALID);
    const int status = enter();
    if (status != MPYNN_SD_OK) return failed(block, len, writing, status);
    const uint64_t blocks = capacity_blocks();
    if (!blocks) {
        busy = false;
        return failed(block, len, writing, MPYNN_SD_NOT_READY);
    }
    if (!mpynn_sd_transfer_in_range(block, len, blocks)) {
        busy = false;
        return failed(block, len, writing, MPYNN_SD_RANGE);
    }

    alignas(32) unsigned char sector[MPYNN_SD_SECTOR_SIZE];
    const unsigned char *input = static_cast<const unsigned char *>(buffer);
    unsigned char *output = static_cast<unsigned char *>(const_cast<void *>(buffer));
    const size_t count = len / MPYNN_SD_SECTOR_SIZE;
    int result = MPYNN_SD_OK;
    for (size_t i = 0; i < count; ++i) {
        const uint64_t offset = (block + i) * MPYNN_SD_SECTOR_SIZE;
        if (device->Seek(offset) != offset) {
            CLogger::Get()->Write("mpynn-sd", LogError, "Seek failed: sector %lu write=%u",
                (unsigned long)(block + i), writing ? 1u : 0u);
            result = failed(block + i, MPYNN_SD_SECTOR_SIZE, writing, MPYNN_SD_IO, 1);
            break;
        }
        if (writing) memcpy(sector, input + i * MPYNN_SD_SECTOR_SIZE, sizeof(sector));
        const int done = writing ? device->Write(sector, sizeof(sector))
                                 : device->Read(sector, sizeof(sector));
        if (done != static_cast<int>(sizeof(sector))) {
            CLogger::Get()->Write("mpynn-sd", LogError, "IO failed: sector %lu write=%u result=%d expected=512",
                (unsigned long)(block + i), writing ? 1u : 0u, done);
            result = failed(block + i, MPYNN_SD_SECTOR_SIZE, writing, MPYNN_SD_IO, 2, done);
            break;
        }
        increment(writing ? diagnostics.write_sectors : diagnostics.read_sectors);
        if (!writing) memcpy(output + i * MPYNN_SD_SECTOR_SIZE, sector, sizeof(sector));
    }
    busy = false;
    return result;
}
}

extern "C" void mpynn_sd_attach(void *raw, int ok) {
    if (CurrentExecutionLevel() != TASK_LEVEL || busy) return;
    device = ok && raw ? static_cast<CEMMCDevice *>(raw) : nullptr;
    initialized = device != nullptr;
}

extern "C" int mpynn_sd_diagnostics(mpynn_sd_diagnostics_t *snapshot) {
    if (!snapshot) return MPYNN_SD_INVALID;
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_SD_CONTEXT;
    if (busy) return MPYNN_SD_BUSY;
    *snapshot = diagnostics;
    snapshot->ready = initialized && device != nullptr;
    return MPYNN_SD_OK;
}

extern "C" int mpynn_sd_ready(void) {
    return initialized && device != nullptr;
}

extern "C" int mpynn_sd_block_count(uint64_t *blocks) {
    if (!blocks) return MPYNN_SD_INVALID;
    *blocks = 0;
    const int status = enter();
    if (status != MPYNN_SD_OK) return status;
    const uint64_t count = capacity_blocks();
    busy = false;
    if (!count) return MPYNN_SD_NOT_READY;
    *blocks = count;
    return MPYNN_SD_OK;
}

extern "C" int mpynn_sd_read(uint64_t block, void *buffer, size_t len) {
    return transfer(block, buffer, len, false);
}

extern "C" int mpynn_sd_write(uint64_t block, const void *buffer, size_t len) {
    return transfer(block, buffer, len, true);
}

extern "C" int mpynn_sd_sync(void) {
    const int status = enter();
    if (status != MPYNN_SD_OK) return status;
    // CEMMCDevice has no software write cache and Write is synchronous.
    busy = false;
    return MPYNN_SD_OK;
}
