// SPDX-License-Identifier: MIT
#include "py/runtime.h"
#include "py/builtin.h"
#include "py/lexer.h"
#include "py/gc.h"
#include "py/stackctrl.h"
#include "py/mperrno.h"
#include "py/mphal.h"
#include "shared/runtime/gchelper.h"
#include "shared/runtime/pyexec.h"
#include "shared/runtime/interrupt_char.h"
#include "circle_bridge.h"
#include "machine_pin.h"
#include "machine_spi.h"
#include "machine_i2c.h"
#include "machine_wdt.h"
#include "machine_timer.h"
#include "machine_sdcard.h"
#include "udp_bridge.h"
#include "tcp_connect_bridge.h"
#include "tcp_stream_bridge.h"
#include "tcp_listener_bridge.h"
#include "dns_bridge.h"
#include "py/objlist.h"
#include "extmod/modnetwork.h"
#include "../../modules/audio/audio_file.h"

void mpynn_console_reset(void);
void mpynn_vm_run(void *heap, size_t heap_size) {
    mp_stack_ctrl_init();
    mp_stack_set_limit(MPYNN_STACK_LIMIT);
    for (;;) {
        gc_init(heap, (char *)heap + heap_size);
        mp_init();
        audio_file_init0();
        // modnetwork owns a rooted NIC list; reinitialize it on every VM reset.
        mod_network_init();
        mpynn_console_reset();
        mp_hal_set_interrupt_char(-1);
        if (mpynn_storage_mount()) {
            mp_obj_list_append(mp_sys_path, mp_obj_new_str("/", 1));
            mp_obj_list_append(mp_sys_path, mp_obj_new_str("/lib", 4));
            // Do not auto-run user scripts in raw REPL (tool-controlled session).
            if (pyexec_mode_kind == PYEXEC_MODE_FRIENDLY_REPL) {
                int result = pyexec_file_if_exists("/boot.py");
                if (result & PYEXEC_FORCED_EXIT) goto soft_reset;
                if (result == PYEXEC_NORMAL_EXIT && pyexec_mode_kind == PYEXEC_MODE_FRIENDLY_REPL) {
                    result = pyexec_file_if_exists("/main.py");
                    if (result & PYEXEC_FORCED_EXIT) goto soft_reset;
                }
            }
        }
        for (;;) {
            if (pyexec_mode_kind == PYEXEC_MODE_RAW_REPL) {
                if (pyexec_raw_repl()) break;
            } else {
                if (pyexec_friendly_repl()) break;
            }
        }
soft_reset:
        mp_hal_set_interrupt_char(-1);
        // A user may request soft reset while holding an IRQ mask. Restore the
        // platform before finalisers/REPL, or UART/timers can remain disabled.
        mpynn_irq_restore(0);
        // Fence file-audio native state before finalizers and GC sweep. This
        // prevents a finalizer from reopening a stream against swept roots.
        audio_file_reset_begin();
        // Stop a user-armed watchdog before potentially slow finalisers/network
        // teardown and before mp_deinit. WDT does not claim or release GPIO pads.
        (void)mpynn_wdt_deinit_all();
        (void)mpynn_timer_deinit_all();
        audio_file_deinit();
        gc_sweep_all();
        // A finalizer may have masked IRQs while rearming a native peripheral.
        // Restore again before any cleanup that can touch hardware or scheduling.
        mpynn_irq_restore(0);
        // Close Circle-owned UDP handles after VM finalisers, with IRQs enabled.
        // This does not dereference the swept GC heap or reset DHCP/platform state.
        int udp_error = mpynn_udp_close_all();
        if (udp_error) mp_printf(&mp_plat_print, "UDP cleanup error: %d\n", udp_error);
        int dns_error = mpynn_dns_cancel_all();
        if (dns_error) mp_printf(&mp_plat_print, "DNS cleanup error: %d\n", dns_error);
        int tcp_error = mpynn_tcp_connect_cancel_all();
        if (tcp_error) mp_printf(&mp_plat_print, "TCP connect cleanup error: %d\n", tcp_error);
        int listener_error = mpynn_tcp_listener_close_all();
        if (listener_error) mp_printf(&mp_plat_print, "TCP listener cleanup error: %d\n", listener_error);
        int stream_error = mpynn_tcp_stream_close_all();
        if (stream_error) mp_printf(&mp_plat_print, "TCP stream cleanup error: %d\n", stream_error);
        mpynn_storage_sync();
        (void)mpynn_spi_deinit();
        int i2c_error = mpynn_i2c_deinit_all();
        if (i2c_error) mp_printf(&mp_plat_print, "I2C cleanup error: %d\n", i2c_error);
        int wdt_error = mpynn_wdt_deinit_all();
        if (wdt_error) mp_printf(&mp_plat_print, "WDT cleanup error: %d\n", wdt_error);
        machine_pin_deinit_all();
        mp_deinit();
        mp_hal_stdout_tx_str("MPY: soft reboot\r\n");
    }
}
void gc_collect(void) {
    gc_collect_start();
    gc_helper_collect_regs_and_stack();
    gc_collect_end();
}
void nlr_jump_fail(void *value) {
    (void)value;
    mp_hal_stdout_tx_str("FATAL: uncaught NLR\r\n");
    mpynn_platform_halt();
}
