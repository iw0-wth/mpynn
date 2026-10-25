# SPDX-License-Identifier: MIT
"""Compile the actual Raspberry Pi mphalport.c against minimal host dependencies.

Run: python -B -m unittest discover -s mpynn/tests/raspberrypi -p test_uart_host.py -v
Only the C module's contracts are tested: no Circle IRQ, UART hardware, ARM ABI,
real MicroPython scheduler/exception delivery, or timing accuracy is validated.
All generated headers, bridge code, executables and diagnostics are temporary.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2] / "ports/raspberrypi/mphalport.c"
GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")
HEADERS = {
    "py/obj.h": """#ifndef TEST_UART_PY_OBJ_H
#define TEST_UART_PY_OBJ_H
#include <stddef.h>
#include <stdint.h>
typedef uintptr_t mp_obj_t;
typedef struct _mp_obj_type_t mp_obj_type_t;
#endif
""",
    "py/runtime.h": """#include <stddef.h>
#include <stdint.h>
typedef uintptr_t mp_uint_t;
#define MP_HANDLE_PENDING_CALLBACKS_AND_EXCEPTIONS 1
void mp_handle_pending(int mode);
void mp_sched_keyboard_interrupt(void);
""",
    "py/mphal.h": """/* Only the entry points consumed by this bridge. */
void mpynn_console_reset(void);
void mpynn_poll_io(void);
void mpynn_event_poll(void);
int mp_hal_stdin_rx_chr(void);
uintptr_t mp_hal_stdio_poll(uintptr_t flags);
mp_uint_t mp_hal_stdout_tx_strn(const char *text, size_t size);
extern volatile unsigned mpynn_console_rx_dropped;
""",
    "py/stream.h": "#define MP_STREAM_POLL_RD (0x0001)\n#define MP_STREAM_POLL_WR (0x0004)\n",
    "shared/runtime/interrupt_char.h": "extern int mp_interrupt_char;\n",
}

BRIDGE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "py/runtime.h"
#include "py/mphal.h"
#include "py/stream.h"
#include "circle_bridge.h"
#include "machine_timer.h"
#include "machine_pin.h"
#include "audio_file.h"

#define CHECK(expr) do { if (!(expr)) { \
    fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #expr); \
    exit(1); \
} } while (0)

int mp_interrupt_char = 3;
static unsigned char input[4096], output[4096];
static size_t input_size, input_pos, output_size;
static size_t requests[256], write_count, write_limit;
static size_t script[16], script_size;
static unsigned irq_count, platform_count, pending_count, irq_at_pending;
static unsigned timer_poll_count, pin_poll_count, audio_poll_count;
static int pending_mode;

int mpynn_console_read(void) {
    return input_pos < input_size ? input[input_pos++] : -1;
}
size_t mpynn_console_write(const char *data, size_t length) {
    CHECK(write_count < sizeof(requests) / sizeof(requests[0]));
    requests[write_count] = length;
    size_t n = write_count < script_size ? script[write_count] : length;
    ++write_count;
    if (n > write_limit) n = write_limit;
    if (n > length) n = length;
    CHECK(output_size + n <= sizeof(output));
    memcpy(output + output_size, data, n);
    output_size += n;
    return n;
}
void mpynn_platform_poll(void) { ++platform_count; }
/* Deferred dependency hooks are counted, never IRQ/callback execution fakes. */
void mpynn_timer_poll(void) { ++timer_poll_count; }
void machine_pin_irq_poll(void) { ++pin_poll_count; }
void audio_file_poll(void) { ++audio_poll_count; }
uint64_t mpynn_ticks_us64(void) { static uint64_t tick; return ++tick; }
void mp_sched_keyboard_interrupt(void) { ++irq_count; }
void mp_handle_pending(int mode) {
    ++pending_count;
    pending_mode = mode;
    irq_at_pending = irq_count;
}
static void reset(void) {
    /* Production reset is used only for isolation, never to inject ring state. */
    mpynn_console_reset();
    mpynn_console_rx_dropped = 0;
    input_size = input_pos = output_size = write_count = script_size = 0;
    irq_count = platform_count = pending_count = irq_at_pending = 0;
    timer_poll_count = pin_poll_count = audio_poll_count = 0;
    pending_mode = -1;
    write_limit = sizeof(output);
    mp_interrupt_char = 3;
}
static void feed(unsigned char value) {
    CHECK(input_size < sizeof(input));
    input[input_size++] = value;
}
static void full_ring_ctrl_c(void) {
    for (unsigned i = 0; i < 255; ++i) feed((unsigned char)(32 + i % 90));
    for (unsigned i = 0; i < 8; ++i) mpynn_poll_io();
    CHECK(input_pos == 255);
    CHECK(mpynn_console_rx_dropped == 0);
    feed('x'); feed(3); feed('y');
    mpynn_poll_io();
    CHECK(input_pos == input_size);
    CHECK(irq_count == 1);
    CHECK(mpynn_console_rx_dropped == 2);
    CHECK(pending_count == 0);
    for (unsigned i = 0; i < 255; ++i)
        CHECK(mp_hal_stdin_rx_chr() == (int)(32 + i % 90));
    CHECK(mp_hal_stdio_poll(MP_STREAM_POLL_RD) == 0);
}
static void normal_order(void) {
    /* More than two ring lengths, including NUL/high bytes and index wrap. */
    mp_interrupt_char = -1;
    for (unsigned round = 0; round < 4; ++round) {
        for (unsigned i = 0; i < 200; ++i) feed((unsigned char)(round * 200 + i));
        for (unsigned i = 0; i < 7; ++i) mpynn_poll_io();
        for (unsigned i = 0; i < 200; ++i)
            CHECK(mp_hal_stdin_rx_chr() == (int)(unsigned char)(round * 200 + i));
        CHECK(mp_hal_stdio_poll(MP_STREAM_POLL_RD) == 0);
    }
    CHECK(irq_count == 0);
    CHECK(mpynn_console_rx_dropped == 0);
}
static void poll_flags(void) {
    const uintptr_t rd = MP_STREAM_POLL_RD, wr = MP_STREAM_POLL_WR;
    CHECK(mp_hal_stdio_poll(0) == 0);
    CHECK(mp_hal_stdio_poll(rd) == 0);
    CHECK(mp_hal_stdio_poll(wr) == wr);
    CHECK(mp_hal_stdio_poll(rd | wr | 0x80) == wr);
    feed('Q');
    CHECK(mp_hal_stdio_poll(rd | wr | 0x80) == (rd | wr));
    CHECK(mp_hal_stdio_poll(rd) == rd);
    CHECK(mp_hal_stdio_poll(wr) == wr);
    CHECK(mp_hal_stdio_poll(0x80) == 0);
    CHECK(platform_count == 0 && pending_count == 0);
    CHECK(mp_hal_stdin_rx_chr() == 'Q');
    CHECK(mp_hal_stdio_poll(rd | wr) == wr);
}
static void stdout_chunks(void) {
    char text[150];
    for (unsigned i = 0; i < sizeof(text); ++i) text[i] = (char)i;
    feed(3);
    CHECK(mp_hal_stdout_tx_strn(text, sizeof(text)) == sizeof(text));
    CHECK(write_count == 3);
    CHECK(requests[0] == 64 && requests[1] == 64 && requests[2] == 22);
    CHECK(output_size == sizeof(text) && memcmp(output, text, sizeof(text)) == 0);
    CHECK(platform_count == 3 && irq_count == 1 && pending_count == 0);
    CHECK(mp_hal_stdout_tx_strn(text, 0) == 0);
    CHECK(write_count == 3 && platform_count == 3);
}
static void stdout_partial(void) {
    char text[150];
    memset(text, 0, sizeof(text));
    for (unsigned i = 0; i < sizeof(text); ++i) text[i] = (char)(i + 1);
    write_limit = 13;
    CHECK(mp_hal_stdout_tx_strn(text, sizeof(text)) == sizeof(text));
    CHECK(write_count == 12 && platform_count == 12 && pending_count == 0);
    for (unsigned i = 0; i < write_count; ++i) {
        size_t remaining = sizeof(text) - i * 13;
        CHECK(requests[i] == (remaining > 64 ? 64 : remaining));
    }
    CHECK(output_size == sizeof(text) && memcmp(output, text, sizeof(text)) == 0);
}
static void stdout_zero(void) {
    const char *text = "abcdefghijklmnopqrstuvwxyz";
    script[0] = 7; script[1] = 3; script[2] = 0; script_size = 3;
    CHECK(mp_hal_stdout_tx_strn(text, 26) == 10);
    CHECK(write_count == 3);
    CHECK(requests[0] == 26 && requests[1] == 19 && requests[2] == 16);
    CHECK(output_size == 10 && memcmp(output, text, 10) == 0);
    CHECK(platform_count == 2 && pending_count == 0);
}
static void vm_pending(void) {
    feed(3); feed('A');
    mpynn_poll_io();
    CHECK(irq_count == 1 && platform_count == 1 && pending_count == 0);
    feed(3);
    mpynn_event_poll();
    CHECK(platform_count == 2 && pending_count == 1);
    CHECK(irq_at_pending == 2);
    CHECK(pending_mode == MP_HANDLE_PENDING_CALLBACKS_AND_EXCEPTIONS);
    CHECK(mp_hal_stdin_rx_chr() == 'A');
    CHECK(platform_count == 3 && pending_count == 2);
    CHECK(pending_mode == MP_HANDLE_PENDING_CALLBACKS_AND_EXCEPTIONS);
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    reset();
    if (!strcmp(argv[1], "full_ring_ctrl_c")) full_ring_ctrl_c();
    else if (!strcmp(argv[1], "normal_order")) normal_order();
    else if (!strcmp(argv[1], "poll_flags")) poll_flags();
    else if (!strcmp(argv[1], "stdout_chunks")) stdout_chunks();
    else if (!strcmp(argv[1], "stdout_partial")) stdout_partial();
    else if (!strcmp(argv[1], "stdout_zero")) stdout_zero();
    else if (!strcmp(argv[1], "vm_pending")) vm_pending();
    else CHECK(0);
    /* Every task poll services each deferred dependency once. stdio_poll
       alone only inspects UART input and must not call these hooks. */
    CHECK(timer_poll_count == platform_count);
    CHECK(pin_poll_count == platform_count);
    CHECK(audio_poll_count == platform_count);
    puts("PASS");
    return 0;
}
'''


class UartHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GCC.is_file():
            raise unittest.SkipTest(f"host C compiler not found: {GCC}")
        cls.temp = tempfile.TemporaryDirectory(prefix="mpynn-uart-host-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        for name, content in HEADERS.items():
            header = cls.root / name
            header.parent.mkdir(parents=True, exist_ok=True)
            header.write_text(content, encoding="utf-8")
        bridge = cls.root / "bridge.c"
        bridge.write_text(BRIDGE, encoding="utf-8")
        cls.executable = cls.root / "uart-host.exe"
        cls.environment = dict(os.environ)
        cls.environment["PATH"] = str(GCC.parent) + os.pathsep + os.environ.get("PATH", "")
        # Compile the unmodified production file directly, as its own translation
        # unit. Its real circle_bridge.h supplies the bridge function prototypes.
        cls.run_process("compile", [str(GCC), "-std=c11", "-Wall", "-Wextra", "-Werror",
                                   "-I", str(cls.root), "-I", str(SOURCE.parent),
                                   "-I", str(SOURCE.parents[2] / "modules/audio"),
                                   str(SOURCE), str(bridge), "-o", str(cls.executable)])

    @classmethod
    def run_process(cls, name, command):
        # Files avoid pipe dependencies and retain both streams until cleanup;
        # include their contents in any failure so unittest preserves diagnostics.
        stdout_path = cls.root / (name + ".stdout.txt")
        stderr_path = cls.root / (name + ".stderr.txt")
        timeout = None
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            try:
                result = subprocess.run(command, cwd=cls.root, env=cls.environment,
                                        stdout=stdout, stderr=stderr, timeout=30, check=False)
            except subprocess.TimeoutExpired as exc:
                timeout = exc
        out = stdout_path.read_text(encoding="utf-8", errors="replace")
        err = stderr_path.read_text(encoding="utf-8", errors="replace")
        diagnostics = f"command: {command!r}\nstdout:\n{out}\nstderr:\n{err}"
        if timeout is not None:
            raise AssertionError(f"host process timed out\n{diagnostics}") from timeout
        if result.returncode != 0:
            raise AssertionError(f"host process returned {result.returncode}\n{diagnostics}")
        return out

    def run_case(self, name):
        self.assertEqual(self.run_process(name, [str(self.executable), name]).strip(), "PASS")

    def test_full_ring_still_consumes_ctrl_c(self):
        self.run_case("full_ring_ctrl_c")

    def test_normal_character_order_and_wrap(self):
        self.run_case("normal_order")

    def test_stdio_poll_masks_requested_flags(self):
        self.run_case("poll_flags")

    def test_stdout_chunks_and_polls_without_pending(self):
        self.run_case("stdout_chunks")

    def test_stdout_partial_writes_preserve_order(self):
        self.run_case("stdout_partial")

    def test_stdout_stops_on_zero_write(self):
        self.run_case("stdout_zero")

    def test_event_and_stdin_trigger_vm_pending(self):
        self.run_case("vm_pending")


if __name__ == "__main__":
    unittest.main()
