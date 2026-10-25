# SPDX-License-Identifier: MIT
"""Compile the actual DNS C callback with bridge doubles and setjmp-based NLR."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "ports/raspberrypi/dns_port.c"
WINDOWS_GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")
COMPILER = str(WINDOWS_GCC) if WINDOWS_GCC.is_file() else shutil.which("gcc")

HEADERS = {
    "py/runtime.h": r"""
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t mp_uint_t;
typedef void *mp_obj_t;
void mp_event_handle_nowait(void);
""",
    "py/mperrno.h": r"""
#pragma once
#define MP_EIO 5
#define MP_EAGAIN 11
#define MP_ENOMEM 12
#define MP_EBUSY 16
#define MP_EINVAL 22
#define MP_ENETDOWN 100
#define MP_ETIMEDOUT 110
""",
    "py/mphal.h": "#pragma once\nvoid mp_hal_delay_ms(unsigned ms);\n",
    "py/nlr.h": r"""
#pragma once
#include <setjmp.h>
typedef struct nlr_buf_t {
    jmp_buf jb;
    void *ret_val;
    struct nlr_buf_t *prev;
} nlr_buf_t;
static nlr_buf_t *nlr_top;
#define nlr_push(n) (((n)->prev = nlr_top), (nlr_top = (n)), setjmp((n)->jb))
static void nlr_pop(void) { nlr_top = nlr_top->prev; }
static _Noreturn void nlr_jump(void *value) {
    nlr_buf_t *n = nlr_top;
    if (!n) abort();
    nlr_top = n->prev;
    n->ret_val = value;
    longjmp(n->jb, 1);
}
""",
    "extmod/modnetwork.h": r"""
#pragma once
#include "py/runtime.h"
typedef struct {
    int (*gethostbyname)(mp_obj_t, const char *, mp_uint_t, uint8_t *);
} mod_network_nic_protocol_t;
""",
}

HARNESS = r"""
#include "dns_port.c"
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)
static const mod_network_nic_protocol_t protocol = { .gethostbyname = mpynn_gethostbyname };
static const char name[] = {'e', 'x', '.', 'o', 'r', 'g'};
static const uint8_t address[4] = {192, 0, 2, 42};
static uint8_t output[4] = {9, 8, 7, 6};
static const uint8_t original[4] = {9, 8, 7, 6};
static uint64_t now, start_cost, event_cost, delay_cost = 1000;
static unsigned starts, finishes, cancels, events, delays, pending;
static int live, start_error, finish_error, interrupt_event, interrupt_delay;
static int exception;
uint64_t mpynn_ticks_us64(void) { return now; }
int mpynn_dns_start(const char *value, size_t len, uint32_t *token) {
    ++starts;
    CHECK(value == name && len == sizeof(name));
    now += start_cost;
    if (start_error) return start_error;
    CHECK(!live); live = 1; *token = 0x12345678;
    return 0;
}
int mpynn_dns_finish(uint32_t token, uint8_t ip[4]) {
    CHECK(live && token == 0x12345678);
    ++finishes;
    CHECK(finishes < 6000);
    if (finishes <= pending) return MP_EAGAIN;
    live = 0;  // Completed errors are consumed too.
    if (finish_error) return finish_error;
    memcpy(ip, address, 4);
    return 0;
}
int mpynn_dns_cancel(uint32_t token) {
    CHECK(live && token == 0x12345678);
    ++cancels; live = 0;
    return 0;
}
void mp_event_handle_nowait(void) {
    CHECK(live); ++events; now += event_cost;
    if (interrupt_event) nlr_jump(&exception);
}
void mp_hal_delay_ms(unsigned ms) {
    CHECK(live && ms == 1); ++delays; now += delay_cost;
    if (interrupt_delay) nlr_jump(&exception);
}
static int resolve(void) {
    return protocol.gethostbyname((mp_obj_t)&protocol, name, sizeof(name), output);
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    const char *mode = argv[1];
    int expected = 0;
    unsigned expected_finishes = 1, expected_events = 0, expected_delays = 0;
    if (!strcmp(mode, "success")) { }
    else if (!strcmp(mode, "retry-success")) {
        pending = 3; expected_finishes = 4; expected_events = expected_delays = 3;
    } else if (!strcmp(mode, "before-deadline")) {
        pending = 1; delay_cost = 4999999;
        expected_finishes = 2; expected_events = expected_delays = 1;
    } else if (!strcmp(mode, "error")) {
        finish_error = expected = MP_EIO;
    } else if (!strcmp(mode, "retry-error")) {
        pending = 1; finish_error = expected = MP_ENETDOWN;
        expected_finishes = 2; expected_events = expected_delays = 1;
    } else if (!strcmp(mode, "start-error")) {
        start_error = expected = MP_EBUSY; expected_finishes = 0;
    } else if (!strcmp(mode, "start-eagain")) {
        start_error = expected = MP_EAGAIN; expected_finishes = 0;
    } else if (!strcmp(mode, "timeout")) {
        pending = 6000; expected = MP_ETIMEDOUT;
        expected_finishes = expected_events = expected_delays = 5000;
    } else if (!strcmp(mode, "late-success")) {
        pending = 1; delay_cost = 5000000; expected = MP_ETIMEDOUT;
        expected_events = expected_delays = 1;
    } else if (!strcmp(mode, "event-deadline")) {
        pending = 1; event_cost = 5000000; expected = MP_ETIMEDOUT;
        expected_events = expected_delays = 1;
    } else if (!strcmp(mode, "total-budget")) {
        start_cost = 4999000; pending = 1; expected = MP_ETIMEDOUT;
        expected_events = expected_delays = 1;
    } else if (!strcmp(mode, "start-deadline")) {
        start_cost = 5000000; expected = MP_ETIMEDOUT; expected_finishes = 0;
    } else if (!strcmp(mode, "wraparound")) {
        now = UINT64_MAX - 1000; pending = 2;
        expected_finishes = 3; expected_events = expected_delays = 2;
    } else if (!strcmp(mode, "interrupt-event") || !strcmp(mode, "interrupt-delay")) {
        pending = 1;
        interrupt_event = !strcmp(mode, "interrupt-event");
        interrupt_delay = !interrupt_event;
        nlr_buf_t outer;
        if (nlr_push(&outer) == 0) {
            (void)resolve();
            CHECK(!"exception was swallowed");
        } else {
            CHECK(outer.ret_val == &exception);
        }
        CHECK(starts == 1 && finishes == 1 && cancels == 1 && !live);
        CHECK(events == 1 && delays == (unsigned)interrupt_delay);
        CHECK(memcmp(output, original, 4) == 0 && nlr_top == NULL);
        puts("PASS"); return 0;
    } else CHECK(!"unknown scenario");
    CHECK(resolve() == expected);
    CHECK(starts == 1 && finishes == expected_finishes);
    CHECK(events == expected_events && delays == expected_delays);
    CHECK(cancels == (unsigned)(expected == MP_ETIMEDOUT));
    CHECK(!live && nlr_top == NULL);
    CHECK(memcmp(output, expected ? original : address, 4) == 0);
    puts("PASS"); return 0;
}
"""


@unittest.skipUnless(COMPILER, "host GCC is not installed")
class DnsPortHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-dns-port-")

        def cleanup():
            for attempt in range(20):
                try:
                    temporary.cleanup()
                    return
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.1)

        cls.addClassCleanup(cleanup)
        cls.root = Path(temporary.name)
        for name, content in HEADERS.items():
            target = cls.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        harness = cls.root / "harness.c"
        harness.write_text(HARNESS, encoding="utf-8")
        cls.executable = cls.root / "dns-port-host.exe"
        cls.env = dict(os.environ)
        cls.env["PATH"] = str(Path(COMPILER).parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [COMPILER, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-I", str(cls.root),
             # The port's setjmp.h must not shadow the host C runtime header.
             "-iquote", str(SOURCE.parent), str(harness), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host GCC compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, mode):
        result = subprocess.run([str(self.executable), mode], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_success_and_callback_signature(self):
        for mode in ("success", "retry-success", "before-deadline", "wraparound"):
            with self.subTest(mode=mode):
                self.run_scenario(mode)

    def test_errors_consumed_and_output_preserved(self):
        for mode in ("error", "retry-error", "start-error", "start-eagain"):
            with self.subTest(mode=mode):
                self.run_scenario(mode)

    def test_total_deadline_cancels_without_late_success(self):
        for mode in ("timeout", "late-success", "event-deadline", "total-budget", "start-deadline"):
            with self.subTest(mode=mode):
                self.run_scenario(mode)

    def test_ctrl_c_cancels_and_rethrows_original_exception(self):
        for mode in ("interrupt-event", "interrupt-delay"):
            with self.subTest(mode=mode):
                self.run_scenario(mode)


if __name__ == "__main__":
    unittest.main()
