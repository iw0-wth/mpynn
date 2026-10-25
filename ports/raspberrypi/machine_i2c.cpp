// SPDX-License-Identifier: MIT
#include <circle/i2cmaster.h>
#include <circle/new.h>
#include <circle/synchronize.h>
#include "gpio_bridge.h"
#include "machine_i2c.h"

static_assert(I2C_MASTER_TRANSFER_TIMEOUT_US == MPYNN_I2C_TIMEOUT_US,
    "Python timeout must match bounded Circle override");
namespace {
alignas(CI2CMaster) unsigned char master_storage[sizeof(CI2CMaster)];
CI2CMaster *master;
const void *active_owner;
bool busy;
bool pending_close;

int context() {
    return CurrentExecutionLevel() == TASK_LEVEL ? 0 : MPYNN_I2C_CONTEXT;
}
void close_master() {
    // Destroy hardware while pads are STILL exclusively owned.
    if (master) master->~CI2CMaster();
    master = nullptr;
    if (active_owner) {
        (void)mpynn_gpio_release(3, active_owner);
        (void)mpynn_gpio_release(2, active_owner);
    }
    active_owner = nullptr;
    pending_close = false;
}
int enter(const void *owner) {
    int status = context();
    if (status) return status;
    if (busy) return MPYNN_I2C_BUSY;
    if (pending_close) close_master();
    if (!owner || !master || active_owner != owner) return MPYNN_I2C_NOT_READY;
    return 0;
}
int claim_error(int status) {
    if (status == MPYNN_GPIO_BUSY) return MPYNN_I2C_BUSY;
    // BCM2/3 are unavailable on Pi1 Model B rev1; never silently use BCM0/1.
    return MPYNN_I2C_BOARD;
}
int transfer_result(int result, size_t expected) {
    if (result >= 0) {
        // A short or impossible success must not expose uninitialised bytes or
        // claim a complete transfer. Hardware reports exact counts on success.
        return (size_t)result == expected ? result : MPYNN_I2C_IO;
    }
    switch (-result) {
        case I2C_MASTER_ERROR_NACK: return MPYNN_I2C_NACK;
        case I2C_MASTER_ERROR_CLKT:
        case I2C_MASTER_TIMEOUT: return MPYNN_I2C_TIMEOUT;
        case I2C_MASTER_BUS_BUSY: return MPYNN_I2C_BUSY;
        case I2C_MASTER_INALID_PARM: return MPYNN_I2C_INVALID;
        default: return MPYNN_I2C_IO;
    }
}
bool valid(unsigned addr, const void *buf, size_t len) {
    return addr < 128 && len <= MPYNN_I2C_MAX_TRANSFER && (!len || buf);
}
}

extern "C" int mpynn_i2c_init(const void *owner, unsigned freq, unsigned timeout_us) {
    int status = context();
    if (status) return status;
    if (!owner || (freq != 100000 && freq != 400000) || timeout_us != MPYNN_I2C_TIMEOUT_US)
        return MPYNN_I2C_INVALID;
    if (busy) return MPYNN_I2C_BUSY;
    if (pending_close) close_master();
    if (active_owner) {
        if (active_owner != owner) return MPYNN_I2C_BUSY;
        master->SetClock(freq);
        return 0;
    }
    status = mpynn_gpio_claim(2, owner);
    if (status) return claim_error(status);
    status = mpynn_gpio_claim(3, owner);
    if (status) {
        (void)mpynn_gpio_release(2, owner);
        return claim_error(status);
    }
    active_owner = owner;
    // Constructor configures the mux; both pad claims MUST precede it.
    master = new (master_storage) CI2CMaster(1, freq == 400000, 0);
    if (!master->Initialize()) {
        close_master();
        return MPYNN_I2C_IO;
    }
    return 0;
}

extern "C" int mpynn_i2c_deinit(const void *owner, int defer) {
    int status = context();
    if (status || busy) {
        // GC can run inside an IRQ-masked critical section. Never touch MMIO
        // there, but retain enough native state to reclaim pads in task context.
        if (defer && owner && active_owner == owner) {
            pending_close = true;
            return 0;
        }
        return status ? status : MPYNN_I2C_BUSY;
    }
    // A deferred finaliser belongs to the active owner. An unrelated I2C
    // object's deinit must never tear down another object's controller.
    if (owner && active_owner == owner) {
        close_master();
    }
    return 0;
}
extern "C" int mpynn_i2c_deinit_all(void) {
    int status = context();
    if (status) return status;
    if (busy) return MPYNN_I2C_BUSY;
    close_master();
    return 0;
}
extern "C" int mpynn_i2c_read(const void *owner, unsigned addr, void *buf, size_t len) {
    int status = enter(owner);
    if (status) return status;
    if (!valid(addr, buf, len)) return MPYNN_I2C_INVALID;
    if (!len) return 0; // Circle Read rejects zero length; do not assert.
    busy = true;
    const int result = master->Read((u8)addr, buf, (unsigned)len);
    busy = false;
    return transfer_result(result, len);
}
extern "C" int mpynn_i2c_write(const void *owner, unsigned addr, const void *buf, size_t len) {
    int status = enter(owner);
    if (status) return status;
    if (!valid(addr, buf, len)) return MPYNN_I2C_INVALID;
    busy = true;
    // Zero-length writes are supported by the override (address-only scan).
    const int result = master->Write((u8)addr, buf, (unsigned)len);
    busy = false;
    return transfer_result(result, len);
}
extern "C" int mpynn_i2c_write_read(const void *owner, unsigned addr,
    const void *prefix, size_t prefix_len, void *buf, size_t len) {
    int status = enter(owner);
    if (status) return status;
    if (!valid(addr, buf, len) || !prefix || !prefix_len || prefix_len > 16)
        return MPYNN_I2C_INVALID;
    if (!len) return 0;
    busy = true;
    const int result = master->WriteReadRepeatedStart((u8)addr, prefix,
        (unsigned)prefix_len, buf, (unsigned)len);
    busy = false;
    return transfer_result(result, len);
}
