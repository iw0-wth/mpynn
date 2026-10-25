// SPDX-License-Identifier: MIT
#include <circle/spimaster.h>
#include <circle/synchronize.h>
#include <circle/machineinfo.h>
#include <circle/new.h>
#include "machine_spi.h"
#include "gpio_bridge.h"

namespace {
alignas(CSPIMaster) unsigned char storage[sizeof(CSPIMaster)];
CSPIMaster *master;
const unsigned char owner = 0;
const int pads[] = {7, 8, 9, 10, 11};
int gpio_error(int result) {
    if (result == MPYNN_GPIO_BUSY || result == MPYNN_GPIO_RESERVED) return MPYNN_SPI_BUSY;
    if (result == MPYNN_GPIO_BOARD) return MPYNN_SPI_BOARD;
    return MPYNN_SPI_INVALID;
}
}

extern "C" int mpynn_spi_init(unsigned baudrate, unsigned polarity, unsigned phase) {
    // TASK_LEVEL also requires IRQ and FIQ enabled; reject masked contexts before
    // mailbox clock queries, claims, construction and register accesses.
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_SPI_BUSY;
    if (baudrate < 4000 || baudrate > 125000000 || polarity > 1 || phase > 1) return MPYNN_SPI_INVALID;
    if (master) {
        master->SetClock(baudrate);
        master->SetMode(polarity, phase);
        return MPYNN_SPI_OK;
    }
    if (!CMachineInfo::Get()->GetClockRate(CLOCK_ID_CORE)) return MPYNN_SPI_IO;
    int result = mpynn_gpio_claim_many(pads, sizeof(pads) / sizeof(pads[0]), &owner);
    if (result != MPYNN_GPIO_OK) return gpio_error(result);
    // Fixed storage avoids heap allocation/failure and GC-root lifetime issues.
    // Construction performs MMIO, therefore it MUST follow the atomic claim.
    master = new (storage) CSPIMaster(baudrate, polarity, phase, 0);
    if (!master->Initialize()) {
        master->~CSPIMaster();
        master = nullptr;
        mpynn_gpio_release_all(&owner);
        return MPYNN_SPI_IO;
    }
    return MPYNN_SPI_OK;
}
extern "C" int mpynn_spi_check(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_SPI_BUSY;
    return master ? MPYNN_SPI_OK : MPYNN_SPI_UNINITIALIZED;
}
extern "C" int mpynn_spi_transfer(size_t length, const uint8_t *src, uint8_t *dest) {
    int status = mpynn_spi_check();
    if (status) return status;
    if (length > 0xFFFF || (length && !src && !dest)) return MPYNN_SPI_INVALID;
    // Exact in-place full duplex is supported; partial overlap could overwrite
    // not-yet-transmitted bytes. Reject it before entering the controller.
    if (src && dest && src != dest) {
        uintptr_t a = (uintptr_t)src, b = (uintptr_t)dest;
        if ((a < b ? b - a : a - b) < length) return MPYNN_SPI_INVALID;
    }
    if (!length) return MPYNN_SPI_OK;
    int result = master->WriteRead(master->ChipSelectNone, src, dest, (unsigned)length);
    if (result == -SPI_MASTER_TIMEOUT) return MPYNN_SPI_TIMEOUT;
    if (result == -SPI_MASTER_INVALID_ARGUMENT) return MPYNN_SPI_INVALID;
    return result == (int)length ? MPYNN_SPI_OK : MPYNN_SPI_IO;
}
extern "C" int mpynn_spi_deinit(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_SPI_BUSY;
    if (master) {
        master->~CSPIMaster();
        master = nullptr;
        // Destroy the hardware object before releasing its exclusive pads.
        mpynn_gpio_release_all(&owner);
    }
    return MPYNN_SPI_OK;
}
