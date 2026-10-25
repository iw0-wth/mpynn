// SPDX-License-Identifier: MIT
#include <circle/gpiopin.h>
#if defined(__arm__)
#include <circle/gpiomanager.h>
#include <circle/synchronize.h>
#endif
#include <circle/machineinfo.h>
#include "gpio_bridge.h"
#include "pin_policy.h"

namespace {
#if defined(__arm__)
class ManagedGPIOPin : public CGPIOPin {
public:
    void AttachManager(CGPIOManager *manager) { m_pManager = manager; }
};
#else
class ManagedGPIOPin : public CGPIOPin { };
#endif
// Default constructors perform no MMIO. AssignPin occurs at most once per pad.
ManagedGPIOPin pins[32];
#if defined(__arm__)
CGPIOManager *gpio_manager;
volatile u32 irq_pending;
#endif
struct PinState {
    const void *owner;
    bool assigned;
    bool configured;
    int mode;
    int pull;
    int latch;
    bool irq_rising;
    bool irq_falling;
    bool irq_connected;
};
PinState states[32];

#if defined(__arm__)
void gpio_irq_handler(void *param) {
    unsigned bcm = (unsigned)(uintptr_t)param;
    if (bcm < 32) {
        irq_pending |= (u32)1 << bcm;
    }
}

void disable_irq_raw(unsigned bcm) {
    PinState &state = states[bcm];
    const bool had_rising = state.irq_rising;
    const bool had_falling = state.irq_falling;
    if (had_falling) {
        if (had_rising) {
            pins[bcm].DisableInterrupt2();
        } else {
            pins[bcm].DisableInterrupt();
        }
        state.irq_falling = false;
    }
    if (had_rising) {
        pins[bcm].DisableInterrupt();
        state.irq_rising = false;
    }
    if (state.irq_connected) {
        pins[bcm].DisconnectInterrupt();
        state.irq_connected = false;
    }
}
#endif

enum mpynn_pin_board board_kind() {
    switch (CMachineInfo::Get()->GetMachineModel()) {
        case MachineModelBRelease1MB256: return MPYNN_PIN_BOARD_B_REV1;
        case MachineModelBRelease2MB256:
        case MachineModelBRelease2MB512: return MPYNN_PIN_BOARD_B_REV2;
        default: return MPYNN_PIN_BOARD_UNKNOWN;
    }
}
int check_owner(int bcm, const void *owner) {
    int result = mpynn_gpio_validate(bcm);
    if (result != MPYNN_GPIO_OK) return result;
    if (!owner) return MPYNN_GPIO_INVALID;
    if (!states[bcm].owner) return MPYNN_GPIO_UNINITIALIZED;
    return states[bcm].owner == owner ? MPYNN_GPIO_OK : MPYNN_GPIO_BUSY;
}
}

extern "C" int mpynn_gpio_validate(int bcm) {
    enum mpynn_pin_board board = board_kind();
    if (board == MPYNN_PIN_BOARD_UNKNOWN) return MPYNN_GPIO_BOARD;
    if (mpynn_pin_is_console(bcm)) return MPYNN_GPIO_RESERVED;
    return mpynn_pin_is_allowed(board, bcm) ? MPYNN_GPIO_OK : MPYNN_GPIO_INVALID;
}

extern "C" int mpynn_gpio_claim(int bcm, const void *owner) {
    int result = mpynn_gpio_validate(bcm);
    if (result != MPYNN_GPIO_OK) return result;
    if (!owner) return MPYNN_GPIO_INVALID;
    PinState &state = states[bcm];
    if (state.owner && state.owner != owner) return MPYNN_GPIO_BUSY;
    state.owner = owner;
    // Claiming alone does not touch registers or change a peripheral's mode.
    return MPYNN_GPIO_OK;
}

extern "C" int mpynn_gpio_claim_many(const int *bcms, unsigned count, const void *owner) {
    if (!bcms || !count || count > 32 || !owner) return MPYNN_GPIO_INVALID;
    // This registry is VM-context-only: no IRQ users, scheduler calls or MMIO
    // intervene between the validation and ownership commit passes.
    for (unsigned i = 0; i < count; ++i) {
        int result = mpynn_gpio_validate(bcms[i]);
        if (result != MPYNN_GPIO_OK) return result;
        if (states[bcms[i]].owner && states[bcms[i]].owner != owner) return MPYNN_GPIO_BUSY;
    }
    for (unsigned i = 0; i < count; ++i) states[bcms[i]].owner = owner;
    return MPYNN_GPIO_OK;
}

extern "C" int mpynn_gpio_configure(int bcm, const void *owner, int mode, int pull, int value) {
    // Validate everything before claiming or touching hardware.
    int result = mpynn_gpio_validate(bcm);
    if (result != MPYNN_GPIO_OK) return result;
    if (!owner || mode < -1 || mode > 1 || pull < -1 || pull > 2 || value < -1 || value > 1) {
        return MPYNN_GPIO_INVALID;
    }
    PinState &state = states[bcm];
    if (state.owner && state.owner != owner) return MPYNN_GPIO_BUSY;
    if (state.irq_connected && (mode != MPYNN_GPIO_KEEP || mode == MPYNN_GPIO_OUT)) {
#if defined(__arm__)
        disable_irq_raw((unsigned)bcm);
#endif
    }
    if (mode == MPYNN_GPIO_KEEP && !state.configured) return MPYNN_GPIO_UNINITIALIZED;
    if (mode == MPYNN_GPIO_KEEP) mode = state.mode;
    if (pull == -1) pull = state.configured ? state.pull : MPYNN_GPIO_PULL_NONE;
    if (value == -1) value = state.configured ? state.latch : 0;
    result = mpynn_gpio_claim(bcm, owner);
    if (result != MPYNN_GPIO_OK) return result;
    CGPIOPin &pin = pins[bcm];
    if (!state.assigned) {
        pin.AssignPin((unsigned)bcm);
        state.assigned = true;
    }
    if (mode == MPYNN_GPIO_IN) {
        pin.SetMode(GPIOModeInput, FALSE);
    }
    pin.SetPullMode(pull == MPYNN_GPIO_PULL_UP ? GPIOPullModeUp :
                    pull == MPYNN_GPIO_PULL_DOWN ? GPIOPullModeDown : GPIOPullModeOff);
    // WriteAll does not require a previous SetMode, unlike instance Write.
    // Set the latch BEFORE enabling output. Never use SetMode(OUT, TRUE):
    // Circle would drive the old latch and then unconditionally write LOW.
    const u32 mask = (u32)1 << bcm;
    CGPIOPin::WriteAll(value ? mask : 0, mask);
    if (mode == MPYNN_GPIO_OUT) {
        pin.SetMode(GPIOModeOutput, FALSE);
    }
    state.mode = mode;
    state.pull = pull;
    state.latch = value;
    state.configured = true;
    return MPYNN_GPIO_OK;
}

extern "C" int mpynn_gpio_read(int bcm, const void *owner, int *value) {
    int result = check_owner(bcm, owner);
    if (result != MPYNN_GPIO_OK) return result;
    if (!value) return MPYNN_GPIO_INVALID;
    if (!states[bcm].configured) return MPYNN_GPIO_UNINITIALIZED;
    // Circle Read() asserts INPUT; ReadAll also samples pads configured as OUT.
    *value = (CGPIOPin::ReadAll() >> bcm) & 1;
    return MPYNN_GPIO_OK;
}

extern "C" int mpynn_gpio_write(int bcm, const void *owner, int value) {
    int result = check_owner(bcm, owner);
    if (result != MPYNN_GPIO_OK) return result;
    if (value != 0 && value != 1) return MPYNN_GPIO_INVALID;
    if (!states[bcm].configured) return MPYNN_GPIO_UNINITIALIZED;
    pins[bcm].Write((unsigned)value);
    states[bcm].latch = value;
    return MPYNN_GPIO_OK;
}

extern "C" int mpynn_gpio_release(int bcm, const void *owner) {
    int result = mpynn_gpio_validate(bcm);
    if (result != MPYNN_GPIO_OK) return result;
    if (!owner) return MPYNN_GPIO_INVALID;
    PinState &state = states[bcm];
    if (!state.owner) return MPYNN_GPIO_OK; // Never touch an unclaimed pin.
    if (state.owner != owner) return MPYNN_GPIO_BUSY;
    if (!state.assigned) {
        pins[bcm].AssignPin((unsigned)bcm);
        state.assigned = true;
    }
#if defined(__arm__)
    disable_irq_raw((unsigned)bcm);
    irq_pending &= ~((u32)1 << bcm);
#endif
    pins[bcm].SetMode(GPIOModeInput, FALSE);
    pins[bcm].SetPullMode(GPIOPullModeOff);
    state.owner = 0;
    state.configured = false;
    state.mode = MPYNN_GPIO_IN;
    state.pull = MPYNN_GPIO_PULL_NONE;
    state.latch = 0;
    return MPYNN_GPIO_OK;
}

extern "C" void mpynn_gpio_release_all(const void *owner) {
    if (!owner) return;
    for (int bcm = 0; bcm < 32; ++bcm) {
        if (states[bcm].owner == owner) {
            (void)mpynn_gpio_release(bcm, owner);
        }
    }
}

extern "C" void mpynn_gpio_irq_attach_manager(void *manager) {
    // Kernel owns the manager for the complete Circle lifetime. No MMIO is
    // performed here; this only supplies the manager used by ConnectInterrupt.
#if defined(__arm__)
    gpio_manager = static_cast<CGPIOManager *>(manager);
    for (unsigned bcm = 0; bcm < 32; ++bcm) {
        pins[bcm].AttachManager(gpio_manager);
    }
#else
    (void)manager;
#endif
}

#if defined(__arm__)
extern "C" int mpynn_gpio_irq_configure(int bcm, const void *owner, unsigned trigger) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_GPIO_BUSY;
    if (bcm < 0 || bcm >= 32 || !owner || !gpio_manager ||
        (trigger & ~(1u | 2u)) != 0 || (trigger & 3u) == 0) {
        return MPYNN_GPIO_INVALID;
    }
    int result = check_owner(bcm, owner);
    if (result != MPYNN_GPIO_OK) return result;
    PinState &state = states[bcm];
    if (!state.configured || state.mode != MPYNN_GPIO_IN) return MPYNN_GPIO_UNINITIALIZED;
    // Replace an existing edge setup atomically from the VM's perspective.
    disable_irq_raw((unsigned)bcm);
    pins[bcm].ConnectInterrupt(gpio_irq_handler, (void *)(uintptr_t)bcm, TRUE);
    state.irq_connected = true;
    if (trigger & 1u) {
        pins[bcm].EnableInterrupt(GPIOInterruptOnRisingEdge);
        state.irq_rising = true;
    }
    if (trigger & 2u) {
        if (trigger & 1u) {
            pins[bcm].EnableInterrupt2(GPIOInterruptOnFallingEdge);
        } else {
            pins[bcm].EnableInterrupt(GPIOInterruptOnFallingEdge);
        }
        state.irq_falling = true;
    }
    return MPYNN_GPIO_OK;
}

extern "C" int mpynn_gpio_irq_disable(int bcm, const void *owner) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_GPIO_BUSY;
    if (bcm < 0 || bcm >= 32 || !owner) return MPYNN_GPIO_INVALID;
    int result = mpynn_gpio_validate(bcm);
    if (result != MPYNN_GPIO_OK) return result;
    if (states[bcm].owner && states[bcm].owner != owner) return MPYNN_GPIO_BUSY;
    disable_irq_raw((unsigned)bcm);
    irq_pending &= ~((u32)1 << bcm);
    return MPYNN_GPIO_OK;
}

extern "C" uint32_t mpynn_gpio_irq_take_pending(void) {
    EnterCritical(IRQ_LEVEL);
    u32 pending = irq_pending;
    irq_pending = 0;
    LeaveCritical();
    return pending;
}

extern "C" void mpynn_gpio_irq_poll(void) {
    // Kept as a C ABI hook for the VM poll path. The VM-side Pin bridge takes
    // pending bits and invokes Python only in task context.
}
#else
extern "C" int mpynn_gpio_irq_configure(int, const void *, unsigned) {
    return MPYNN_GPIO_INVALID;
}
extern "C" int mpynn_gpio_irq_disable(int, const void *) {
    return MPYNN_GPIO_OK;
}
extern "C" uint32_t mpynn_gpio_irq_take_pending(void) {
    return 0;
}
extern "C" void mpynn_gpio_irq_poll(void) { }
#endif
