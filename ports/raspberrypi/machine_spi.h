// SPDX-License-Identifier: MIT
#ifndef MPYNN_MACHINE_SPI_H
#define MPYNN_MACHINE_SPI_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#else
#include "py/obj.h"
extern const mp_obj_type_t machine_spi_type;
#endif

enum mpynn_spi_status {
    MPYNN_SPI_OK = 0, MPYNN_SPI_INVALID = -1, MPYNN_SPI_BUSY = -2,
    MPYNN_SPI_UNINITIALIZED = -3, MPYNN_SPI_TIMEOUT = -4,
    MPYNN_SPI_IO = -5, MPYNN_SPI_BOARD = -6
};
/* Only SPI0; fixed SCK11/MOSI10/MISO9. Both CE pads7/8 are reserved too,
 * because CSPIMaster configures all five pads. Transfers use no hardware CS:
 * callers must drive a separate machine.Pin around the entire operation.
 * No entry point raises an MP exception or calls the scheduler. */
int mpynn_spi_init(unsigned baudrate, unsigned polarity, unsigned phase);
int mpynn_spi_check(void);
int mpynn_spi_transfer(size_t length, const uint8_t *src, uint8_t *dest);
int mpynn_spi_deinit(void);
#ifdef __cplusplus
}
#endif
#endif
