// SPDX-License-Identifier: MIT
#include "py/runtime.h"
#include "py/mperrno.h"
#include "extmod/virtpin.h"
#include "machine_pin.h"
#include "gpio_bridge.h"

typedef struct _machine_pin_obj_t {
    mp_obj_base_t base;
    unsigned char id;
} machine_pin_obj_t;

// Immutable singleton references; mutable state lives only in gpio_bridge.cpp.
#define PIN(n) {{&machine_pin_type}, (n)}
static const machine_pin_obj_t pin_objects[32] = {
    PIN(0), PIN(1), PIN(2), PIN(3), PIN(4), PIN(5), PIN(6), PIN(7),
    PIN(8), PIN(9), PIN(10), PIN(11), PIN(12), PIN(13), PIN(14), PIN(15),
    PIN(16), PIN(17), PIN(18), PIN(19), PIN(20), PIN(21), PIN(22), PIN(23),
    PIN(24), PIN(25), PIN(26), PIN(27), PIN(28), PIN(29), PIN(30), PIN(31)
};
#undef PIN
static const char pin_owner;
static uint16_t pin_irq_generation[32];
static uint32_t pin_irq_pending;
static uint32_t pin_irq_queued;
MP_REGISTER_ROOT_POINTER(mp_obj_t pin_irq_handlers[32]);
#define PIN_IRQ_HANDLERS MP_STATE_PORT(pin_irq_handlers)

static void pin_check(int result) {
    switch (result) {
        case MPYNN_GPIO_OK: return;
        case MPYNN_GPIO_BOARD:
            mp_raise_ValueError(MP_ERROR_TEXT("unsupported board for Pin"));
        case MPYNN_GPIO_RESERVED:
            mp_raise_ValueError(MP_ERROR_TEXT("GPIO reserved for UART console"));
        case MPYNN_GPIO_BUSY:
            mp_raise_OSError(MP_EBUSY);
        case MPYNN_GPIO_UNINITIALIZED:
            mp_raise_ValueError(MP_ERROR_TEXT("Pin is not initialized; specify IN or OUT"));
        default:
            mp_raise_ValueError(MP_ERROR_TEXT("invalid pin or configuration"));
    }
}

void machine_pin_deinit_all(void) {
    for (unsigned id = 0; id < MP_ARRAY_SIZE(pin_objects); ++id) {
        pin_irq_generation[id]++;
        PIN_IRQ_HANDLERS[id] = MP_OBJ_NULL;
    }
    pin_irq_pending = pin_irq_queued = 0;
    mpynn_gpio_release_all(&pin_owner);
}

unsigned machine_pin_get_id(mp_obj_t pin_in) {
    // Normalize an integer or an existing Pin through the normal no-mode
    // constructor. This validates board policy without claiming/configuring.
    mp_obj_t normalized = mp_pin_make_new(&machine_pin_type, 1, 0, &pin_in);
    const machine_pin_obj_t *self = MP_OBJ_TO_PTR(normalized);
    pin_check(mpynn_gpio_validate(self->id));
    return self->id;
}

void machine_pin_hal_configure(unsigned id, int mode, int pull, int value) {
    if (id >= MP_ARRAY_SIZE(pin_objects)) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid BCM pin"));
    }
    pin_check(mpynn_gpio_configure((int)id, &pin_owner, mode, pull, value));
}

int machine_pin_hal_read(unsigned id) {
    if (id >= MP_ARRAY_SIZE(pin_objects)) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid BCM pin"));
    }
    int value;
    pin_check(mpynn_gpio_read((int)id, &pin_owner, &value));
    return value;
}

void machine_pin_hal_write(unsigned id, int value) {
    if (id >= MP_ARRAY_SIZE(pin_objects) || (value != 0 && value != 1)) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid pin value"));
    }
    int result = mpynn_gpio_write((int)id, &pin_owner, value);
    if (result == MPYNN_GPIO_UNINITIALIZED) {
        // HAL users commonly set an output latch before selecting output mode;
        // configure input first so this never steals a foreign claim.
        result = mpynn_gpio_configure((int)id, &pin_owner, MPYNN_GPIO_IN,
            -1, value);
    }
    pin_check(result);
}

static void machine_pin_print(const mp_print_t *print, mp_obj_t self_in, mp_print_kind_t kind) {
    const machine_pin_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_printf(print, "Pin(%u)", (unsigned)self->id);
}

static mp_obj_t pin_init_helper(const machine_pin_obj_t *self, size_t n_args,
    const mp_obj_t *pos_args, mp_map_t *kw_args) {
    enum { ARG_mode, ARG_pull, ARG_value };
    static const mp_arg_t allowed_args[] = {
        { MP_QSTR_mode, MP_ARG_OBJ, {.u_obj = mp_const_none} },
        { MP_QSTR_pull, MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_value, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed_args)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed_args), allowed_args, args);
    int mode = MPYNN_GPIO_KEEP;
    if (args[ARG_mode].u_obj != mp_const_none) {
        mp_int_t requested = mp_obj_get_int(args[ARG_mode].u_obj);
        if (requested != MPYNN_GPIO_IN && requested != MPYNN_GPIO_OUT) {
            mp_raise_ValueError(MP_ERROR_TEXT("only Pin.IN and Pin.OUT are supported"));
        }
        mode = requested;
    }
    int pull = -1;
    if (args[ARG_pull].u_obj != MP_OBJ_NULL) {
        if (args[ARG_pull].u_obj == mp_const_none) {
            pull = MPYNN_GPIO_PULL_NONE;
        } else {
            mp_int_t requested = mp_obj_get_int(args[ARG_pull].u_obj);
            if (requested != MPYNN_GPIO_PULL_UP && requested != MPYNN_GPIO_PULL_DOWN) {
                mp_raise_ValueError(MP_ERROR_TEXT("invalid pull"));
            }
            pull = requested;
        }
    }
    int value = args[ARG_value].u_obj == MP_OBJ_NULL ? -1 : mp_obj_is_true(args[ARG_value].u_obj);
    // All MP parsing (including user truth conversion) finishes before C++ runs.
    pin_check(mpynn_gpio_configure(self->id, &pin_owner, mode, pull, value));
    return mp_const_none;
}

mp_obj_t mp_pin_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 1, 3, true);
    const machine_pin_obj_t *self;
    if (mp_obj_is_type(args[0], &machine_pin_type)) {
        self = MP_OBJ_TO_PTR(args[0]);
    } else {
        if (!mp_obj_is_int(args[0])) {
            mp_raise_TypeError(MP_ERROR_TEXT("Pin id must be a BCM integer"));
        }
        mp_int_t id = mp_obj_get_int(args[0]);
        if (id < 0 || (mp_uint_t)id >= MP_ARRAY_SIZE(pin_objects)) {
            mp_raise_ValueError(MP_ERROR_TEXT("invalid BCM pin"));
        }
        self = &pin_objects[id];
    }
    pin_check(mpynn_gpio_validate(self->id));
    if (n_args > 1 || n_kw != 0) {
        mp_map_t kw_args;
        mp_map_init_fixed_table(&kw_args, n_kw, args + n_args);
        pin_init_helper(self, n_args - 1, args + 1, &kw_args);
    }
    // Standard MP no-mode constructor: reference existing state without changing
    // mode/pull/latch or acquiring ownership. First use requires explicit init.
    return MP_OBJ_FROM_PTR(self);
}

static mp_obj_t machine_pin_init(size_t n_args, const mp_obj_t *args, mp_map_t *kw_args) {
    return pin_init_helper(MP_OBJ_TO_PTR(args[0]), n_args - 1, args + 1, kw_args);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(machine_pin_init_obj, 1, machine_pin_init);

static mp_obj_t machine_pin_call(mp_obj_t self_in, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 0, 1, false);
    const machine_pin_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (n_args == 0) {
        int value;
        pin_check(mpynn_gpio_read(self->id, &pin_owner, &value));
        return MP_OBJ_NEW_SMALL_INT(value);
    }
    int value = mp_obj_is_true(args[0]);
    pin_check(mpynn_gpio_write(self->id, &pin_owner, value));
    return mp_const_none;
}

static mp_obj_t machine_pin_value(size_t n_args, const mp_obj_t *args) {
    return machine_pin_call(args[0], n_args - 1, 0, args + 1);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(machine_pin_value_obj, 1, 2, machine_pin_value);

static mp_obj_t machine_pin_on(mp_obj_t self_in) {
    const machine_pin_obj_t *self = MP_OBJ_TO_PTR(self_in);
    pin_check(mpynn_gpio_write(self->id, &pin_owner, 1));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(machine_pin_on_obj, machine_pin_on);

static mp_obj_t machine_pin_off(mp_obj_t self_in) {
    const machine_pin_obj_t *self = MP_OBJ_TO_PTR(self_in);
    pin_check(mpynn_gpio_write(self->id, &pin_owner, 0));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(machine_pin_off_obj, machine_pin_off);

static mp_obj_t machine_pin_deinit(mp_obj_t self_in) {
    const machine_pin_obj_t *self = MP_OBJ_TO_PTR(self_in);
    pin_irq_generation[self->id]++;
    PIN_IRQ_HANDLERS[self->id] = MP_OBJ_NULL;
    pin_check(mpynn_gpio_irq_disable(self->id, &pin_owner));
    pin_check(mpynn_gpio_release(self->id, &pin_owner));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(machine_pin_deinit_obj, machine_pin_deinit);

static mp_obj_t pin_irq_trampoline(mp_obj_t token_obj) {
    mp_uint_t token = mp_obj_get_int(token_obj);
    unsigned id = token & 31u;
    unsigned generation = token >> 5;
    if (id >= MP_ARRAY_SIZE(pin_objects)) return mp_const_none;
    pin_irq_queued &= ~((uint32_t)1 << id);
    if (pin_irq_generation[id] != generation) return mp_const_none;
    mp_obj_t handler = PIN_IRQ_HANDLERS[id];
    if (handler != MP_OBJ_NULL && handler != mp_const_none) {
        mp_call_function_1_protected(handler, MP_OBJ_FROM_PTR(&pin_objects[id]));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(pin_irq_trampoline_obj, pin_irq_trampoline);

void machine_pin_irq_poll(void) {
    pin_irq_pending |= mpynn_gpio_irq_take_pending();
    for (unsigned id = 0; id < MP_ARRAY_SIZE(pin_objects); ++id) {
        uint32_t mask = (uint32_t)1 << id;
        if (!(pin_irq_pending & mask) || (pin_irq_queued & mask)) continue;
        mp_obj_t handler = PIN_IRQ_HANDLERS[id];
        if (handler == MP_OBJ_NULL || handler == mp_const_none) {
            pin_irq_pending &= ~mask;
            continue;
        }
        mp_uint_t token = ((mp_uint_t)pin_irq_generation[id] << 5) | id;
        if (mp_sched_schedule(MP_OBJ_FROM_PTR(&pin_irq_trampoline_obj), MP_OBJ_NEW_SMALL_INT(token))) {
            pin_irq_pending &= ~mask;
            pin_irq_queued |= mask;
        }
    }
}

static mp_obj_t machine_pin_irq(size_t n_args, const mp_obj_t *args, mp_map_t *kw_args) {
    enum { ARG_handler, ARG_trigger, ARG_hard };
    static const mp_arg_t allowed_args[] = {
        { MP_QSTR_handler, MP_ARG_OBJ, {.u_obj = mp_const_none} },
        { MP_QSTR_trigger, MP_ARG_INT, {.u_int = 3} },
        { MP_QSTR_hard, MP_ARG_BOOL, {.u_bool = false} },
    };
    mp_arg_val_t parsed[MP_ARRAY_SIZE(allowed_args)];
    mp_arg_parse_all(n_args - 1, args + 1, kw_args, MP_ARRAY_SIZE(allowed_args), allowed_args, parsed);
    const machine_pin_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    if (parsed[ARG_hard].u_bool) {
        mp_raise_ValueError(MP_ERROR_TEXT("hard IRQs are not supported"));
    }
    unsigned trigger = (unsigned)parsed[ARG_trigger].u_int;
    if ((trigger & ~3u) != 0 || trigger == 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid IRQ trigger"));
    }
    mp_obj_t handler = parsed[ARG_handler].u_obj;
    if (handler != mp_const_none && !mp_obj_is_callable(handler)) {
        mp_raise_TypeError(MP_ERROR_TEXT("handler must be callable or None"));
    }
    // Invalidate every callback token before changing native wiring or roots.
    pin_irq_generation[self->id]++;
    PIN_IRQ_HANDLERS[self->id] = MP_OBJ_NULL;
    pin_irq_pending &= ~((uint32_t)1 << self->id);
    pin_irq_queued &= ~((uint32_t)1 << self->id);
    pin_check(mpynn_gpio_irq_disable(self->id, &pin_owner));
    if (handler == mp_const_none) return mp_const_none;
    pin_check(mpynn_gpio_irq_configure(self->id, &pin_owner, trigger));
    PIN_IRQ_HANDLERS[self->id] = handler;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(machine_pin_irq_obj, 1, machine_pin_irq);

static mp_uint_t machine_pin_ioctl(mp_obj_t self_in, mp_uint_t request, uintptr_t arg, int *errcode) {
    const machine_pin_obj_t *self = MP_OBJ_TO_PTR(self_in);
    int value = 0;
    switch (request) {
        case MP_PIN_READ:
            pin_check(mpynn_gpio_read(self->id, &pin_owner, &value));
            return value;
        case MP_PIN_WRITE:
            pin_check(mpynn_gpio_write(self->id, &pin_owner, arg != 0));
            return 0;
        case MP_PIN_INPUT:
        case MP_PIN_OUTPUT:
            pin_check(mpynn_gpio_configure(self->id, &pin_owner,
                request == MP_PIN_INPUT ? MPYNN_GPIO_IN : MPYNN_GPIO_OUT, -1, -1));
            return 0;
        default:
            if (errcode) *errcode = MP_EINVAL;
            return (mp_uint_t)-1;
    }
}
static const mp_pin_p_t machine_pin_protocol = { .ioctl = machine_pin_ioctl };
static const mp_rom_map_elem_t machine_pin_locals_dict_table[] = {
    { MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&machine_pin_init_obj) },
    { MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&machine_pin_deinit_obj) },
    { MP_ROM_QSTR(MP_QSTR_value), MP_ROM_PTR(&machine_pin_value_obj) },
    { MP_ROM_QSTR(MP_QSTR_on), MP_ROM_PTR(&machine_pin_on_obj) },
    { MP_ROM_QSTR(MP_QSTR_off), MP_ROM_PTR(&machine_pin_off_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq), MP_ROM_PTR(&machine_pin_irq_obj) },
    { MP_ROM_QSTR(MP_QSTR_IN), MP_ROM_INT(MPYNN_GPIO_IN) },
    { MP_ROM_QSTR(MP_QSTR_OUT), MP_ROM_INT(MPYNN_GPIO_OUT) },
    { MP_ROM_QSTR(MP_QSTR_PULL_UP), MP_ROM_INT(MPYNN_GPIO_PULL_UP) },
    { MP_ROM_QSTR(MP_QSTR_PULL_DOWN), MP_ROM_INT(MPYNN_GPIO_PULL_DOWN) },
    { MP_ROM_QSTR(MP_QSTR_IRQ_RISING), MP_ROM_INT(1) },
    { MP_ROM_QSTR(MP_QSTR_IRQ_FALLING), MP_ROM_INT(2) },
};
static MP_DEFINE_CONST_DICT(machine_pin_locals_dict, machine_pin_locals_dict_table);
MP_DEFINE_CONST_OBJ_TYPE(
    machine_pin_type,
    MP_QSTR_Pin,
    MP_TYPE_FLAG_NONE,
    print, machine_pin_print,
    make_new, mp_pin_make_new,
    call, machine_pin_call,
    protocol, &machine_pin_protocol,
    locals_dict, &machine_pin_locals_dict
    );
