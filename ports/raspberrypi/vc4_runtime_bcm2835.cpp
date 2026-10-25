// SPDX-License-Identifier: MIT
// Circle platform backend only. VC4 ownership/packing/V3D protocols live in
// lib/vc4-runtime; no Circle types cross its public platform ABI.
#include "vc4_runtime.h"
#include "vc4_circle_platform.h"
#include "circle_bridge.h"
#include "vc4_platform.h"
#include <circle/bcm2835.h>
#include <circle/bcmpropertytags.h>
#include <circle/machineinfo.h>
#include <circle/memory.h>
#include <circle/memio.h>
#include <circle/synchronize.h>
#include <circle/logger.h>
#include <circle/timer.h>
#include <stdint.h>
#include <string.h>

namespace {
CBcmPropertyTags property_tags;

vc4_status_t property(void *, uint32_t tag, void *values, uint32_t bytes) {
    // This backend supports the existing VC4 property payloads (one or three
    // words). CBcmPropertyTags handles the mailbox channel and wire envelope.
    if (values == nullptr || (bytes != 4u && bytes != 12u)) return VC4_STATUS_INVALID_ARGUMENT;
    struct Message {
        uint32_t tag, value_bytes, value_length;
        uint32_t words[3];
    } message = {};
    message.tag = tag;
    message.value_bytes = bytes;
    message.value_length = bytes;
    memcpy(message.words, values, bytes);
    if (!property_tags.GetTag(tag, &message, 12u + bytes, bytes)) return VC4_STATUS_IO_ERROR;
    memcpy(values, message.words, bytes);
    return VC4_STATUS_OK;
}
void *map_bus(void *, uint32_t bus, uint32_t bytes) {
    const uint32_t alias = bus & 0xC0000000u;
    const uint32_t physical = bus & 0x3FFFFFFFu;
    CMachineInfo *info = CMachineInfo::Get();
    const uint64_t total = info ? static_cast<uint64_t>(info->GetRAMSize()) * 1024u * 1024u : 0u;
    if ((alias != 0x40000000u && alias != 0xC0000000u) || physical == 0u ||
        CMemorySystem::Get() == nullptr || total == 0u ||
        static_cast<uint64_t>(physical) + bytes > total) return nullptr;
    // Identity low-RAM mapping is a Circle/BCM2835 backend detail, not a core assumption.
    return reinterpret_cast<void *>(static_cast<uintptr_t>(physical));
}
void unmap_bus(void *, void *, uint32_t, uint32_t) { /* permanent identity mapping */ }
void cache(void *, void *cpu, size_t bytes, vc4_cache_op_t) {
    // Core calls before launch / after observed completion; it owns and separates
    // these lines. Circle ARMv6 exposes clean+invalidate for both transfers.
    CleanAndInvalidateDataCacheRange(static_cast<u32>(reinterpret_cast<uintptr_t>(cpu)),
                                    static_cast<u32>(bytes));
}
void barrier(void *, vc4_barrier_op_t op) {
    switch (op) {
    case VC4_BARRIER_DATA_SYNC: DataSyncBarrier(); break;
    case VC4_BARRIER_DATA_MEMORY: DataMemBarrier(); break;
    case VC4_BARRIER_PERIPHERAL_ENTER: PeripheralEntry(); break;
    case VC4_BARRIER_PERIPHERAL_EXIT: PeripheralExit(); break;
    }
}
uint32_t mmio_read(void *, uintptr_t address) { return read32(address); }
void mmio_write(void *, uintptr_t address, uint32_t value) { write32(address, value); }
uint64_t ticks(void *) { return CTimer::GetClockTicks64(); }
uint32_t clock_rate(void *, uint32_t clock_id) {
    CMachineInfo *info = CMachineInfo::Get();
    return info ? info->GetClockRate(clock_id) : 0u;
}
void wait_hint(void *) { mpynn_platform_poll(); }
void logv(void *, vc4_log_level_t level, const char *format, va_list args) {
    CLogger *logger = CLogger::Get();
    if (logger != nullptr) logger->WriteV("vc4", level == VC4_LOG_ERROR ? LogError : LogNotice,
                                         format, args);
}
}

extern "C" vc4_status_t mpynn_vc4_bind_circle(void) {
    vc4_platform_t platform = {};
    platform.abi_version = VC4_PLATFORM_ABI_VERSION;
    platform.struct_bytes = sizeof(platform);
    platform.v3d_base = ARM_IO_BASE + 0x00C00000u;
    platform.property = property;
    platform.map_bus = map_bus;
    platform.unmap_bus = unmap_bus;
    platform.cache = cache;
    platform.barrier = barrier;
    platform.read32 = mmio_read;
    platform.write32 = mmio_write;
    platform.ticks_us = ticks;
    platform.clock_hz = clock_rate;
    platform.wait_hint = wait_hint;
    platform.logv = logv;
    return vc4_bind_platform(&platform);
}
