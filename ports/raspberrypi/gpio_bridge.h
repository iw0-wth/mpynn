// SPDX-License-Identifier: MIT
#ifndef MPYNN_GPIO_BRIDGE_H
#define MPYNN_GPIO_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

enum mpynn_gpio_error {
    MPYNN_GPIO_OK = 0,
    MPYNN_GPIO_INVALID = -1,
    MPYNN_GPIO_BOARD = -2,
    MPYNN_GPIO_RESERVED = -3,
    MPYNN_GPIO_BUSY = -4,
    MPYNN_GPIO_UNINITIALIZED = -5
};
enum mpynn_gpio_mode { MPYNN_GPIO_KEEP = -1, MPYNN_GPIO_IN = 0, MPYNN_GPIO_OUT = 1 };
enum mpynn_gpio_pull { MPYNN_GPIO_PULL_NONE = 0, MPYNN_GPIO_PULL_UP = 1, MPYNN_GPIO_PULL_DOWN = 2 };

/* VM-context-only resource registry, shared by all future peripheral drivers.
 * owner is a non-NULL, stable identity token (one per peripheral instance).
 * Claims are exclusive except repeated claims by the SAME token. Future I2C,
 * SPI and UART drivers must claim every pad here before hardware configuration,
 * roll back partial claims on error and release only their own pads on deinit.
 * The console pads are permanently reserved outside this registry.
 * No function calls the MP runtime or raises exceptions through C++ frames.
 */
int mpynn_gpio_validate(int bcm);
int mpynn_gpio_claim(int bcm, const void *owner);
/* Preflight every pad, then commit all ownership without MMIO or yielding.
 * Failure preserves every prior claim, including same-owner claims. */
int mpynn_gpio_claim_many(const int *bcms, unsigned count, const void *owner);
int mpynn_gpio_release(int bcm, const void *owner);
/* KEEP preserves existing state. A first configuration requires an explicit mode.
 * value=-1 preserves a claimed latch; the first configuration defaults it to 0.
 * pull=-1 preserves a claimed pull; the first configuration defaults to no pull.
 */
int mpynn_gpio_configure(int bcm, const void *owner, int mode, int pull, int value);
int mpynn_gpio_read(int bcm, const void *owner, int *value);
/* Writes in input mode preload the latch, as specified by machine.Pin. */
int mpynn_gpio_write(int bcm, const void *owner, int value);
void mpynn_gpio_release_all(const void *owner);

/* IRQ manager is owned by the Circle kernel. Pass its CGPIOManager address
 * opaquely so this C ABI remains usable by kernel.cpp without C++ headers. */
void mpynn_gpio_irq_attach_manager(void *manager);
int mpynn_gpio_irq_configure(int bcm, const void *owner, unsigned trigger);
int mpynn_gpio_irq_disable(int bcm, const void *owner);
void mpynn_gpio_irq_poll(void);
/* Atomically transfer IRQ-latched GPIO bits to the VM-side poller. */
uint32_t mpynn_gpio_irq_take_pending(void);
#ifdef __cplusplus
}
#endif
#endif
