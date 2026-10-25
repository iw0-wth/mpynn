# SPDX-License-Identifier: MIT
"""Host GCC tests of the real machine_sdcard.c, not a MicroPython VM.

Only the binding is real: mp_obj, argument/buffer parsing, exceptions, VFS and
bridge calls below are deliberately small host doubles.  In particular this
suite does NOT establish real MP negative-block conversion, integer overflow,
truthiness, keyword validation, buffer-protocol or allocator/GC semantics.
Length tests establish unchanged forwarding to the bridge, not bridge range or
sector validation.  No Circle/ARM build, hardware, filesystem or mkfs is used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "ports/raspberrypi/machine_sdcard.c"

RUNTIME = r"""
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>
#include <setjmp.h>
#include <string.h>
typedef uintptr_t mp_obj_t;
typedef intptr_t mp_int_t;
typedef uintptr_t mp_uint_t;
typedef struct _mp_obj_type_t mp_obj_type_t;
typedef struct { const mp_obj_type_t *type; } mp_obj_base_t;
typedef mp_obj_t (*make_new_t)(const mp_obj_type_t *, size_t, size_t, const mp_obj_t *);
struct _mp_obj_type_t { make_new_t make_new; const void *locals; };
typedef struct { void *buf; size_t len; } mp_buffer_info_t;
typedef union { mp_int_t u_int; bool u_bool; } mp_arg_val_t;
typedef struct { unsigned qstr, flags; mp_arg_val_t defval; } mp_arg_t;
typedef struct { uintptr_t key, value; } mp_rom_map_elem_t;
typedef struct { size_t used; mp_obj_t *table; } mp_map_t;
typedef struct { int unused; } mp_print_t;
typedef struct _nlr_buf_t { jmp_buf jump; struct _nlr_buf_t *prev; void *volatile ret_val; } nlr_buf_t;
extern nlr_buf_t *host_nlr;
extern const mp_print_t mp_plat_print;
static inline nlr_buf_t *host_nlr_prepare(nlr_buf_t *frame) {
    frame->prev = host_nlr;
    host_nlr = frame;
    return frame;
}
/* Keep setjmp directly in the caller's controlling expression. */
#define nlr_push(n) setjmp(host_nlr_prepare(n)->jump)
void nlr_pop(void);
#define mp_const_none ((mp_obj_t)2)
#define mp_const_true ((mp_obj_t)4)
#define mp_const_false ((mp_obj_t)6)
#define MP_OBJ_FROM_PTR(p) ((mp_obj_t)(uintptr_t)(p))
#define MP_OBJ_TO_PTR(o) ((void *)(uintptr_t)(o))
#define MP_OBJ_NEW_SMALL_INT(n) ((mp_obj_t)((mp_uint_t)(mp_int_t)(n) * 2u + 1u))
#define MP_OBJ_NEW_QSTR(q) ((mp_obj_t)(((q) << 3) | 2u))
#define MP_ROM_QSTR(q) ((uintptr_t)(q))
#define MP_ROM_PTR(p) ((uintptr_t)(p))
#define MP_ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define MP_ERROR_TEXT(t) (t)
#define MP_ARG_INT 1
#define MP_ARG_BOOL 2
#define MP_ARG_KW_ONLY 4
#define MP_BUFFER_READ 1
#define MP_BUFFER_WRITE 2
#define MP_TYPE_FLAG_NONE 0
enum { MP_QSTR_id = 1, MP_QSTR_readonly, MP_QSTR_readblocks,
       MP_QSTR_writeblocks, MP_QSTR_ioctl, MP_QSTR_SDCard, MP_QSTR__slash_sd };
#define MP_DEFINE_CONST_FUN_OBJ_3(name, fn) \
    const struct { mp_obj_t (*fun)(mp_obj_t, mp_obj_t, mp_obj_t); } name = {fn}
#define MP_DEFINE_CONST_DICT(name, table) \
    const struct { const void *entries; size_t count; } name = {table, MP_ARRAY_SIZE(table)}
#define MP_DEFINE_CONST_OBJ_TYPE(name, qstr, flags, mk, fn, ld, dict) \
    const mp_obj_type_t name = {fn, dict}
#define mp_obj_malloc(t, type) ((t *)host_alloc(sizeof(t), type))
void *host_alloc(size_t size, const mp_obj_type_t *type);
void mp_arg_parse_all_kw_array(size_t n, size_t kw, const mp_obj_t *in,
    size_t count, const mp_arg_t *allowed, mp_arg_val_t *out);
_Noreturn void mp_raise_ValueError(const char *message);
_Noreturn void mp_raise_OSError(int error);
mp_uint_t mp_obj_get_uint(mp_obj_t obj);
mp_int_t mp_obj_get_int(mp_obj_t obj);
void mp_get_buffer_raise(mp_obj_t obj, mp_buffer_info_t *info, int flags);
mp_obj_t mp_obj_new_int_from_ull(unsigned long long value);
mp_obj_t mp_obj_new_str(const char *text, size_t len);
void mp_map_init_fixed_table(mp_map_t *map, size_t count, const mp_obj_t *table);
int mp_printf(const mp_print_t *print, const char *format, ...);
void mp_obj_print_exception(const mp_print_t *print, mp_obj_t exception);
"""
HEADERS = {
    "py/runtime.h": RUNTIME,
    "py/obj.h": '#pragma once\n#include "runtime.h"\n',
    "py/objstr.h": '#pragma once\n#include "runtime.h"\n',
    "py/mphal.h": "#pragma once\nint mpynn_irq_is_enabled(void);\n",
    "py/smallint.h": "#pragma once\n#define MP_SMALL_INT_MAX 0x3fffffff\n",
    "py/mperrno.h": """#pragma once
#define MP_EIO 5
#define MP_EBUSY 16
#define MP_ENODEV 19
#define MP_EINVAL 22
#define MP_EROFS 30
#define MP_EFBIG 27
""",
    "extmod/vfs.h": """#pragma once
#include "py/runtime.h"
#define MP_BLOCKDEV_IOCTL_INIT 1
#define MP_BLOCKDEV_IOCTL_DEINIT 2
#define MP_BLOCKDEV_IOCTL_SYNC 3
#define MP_BLOCKDEV_IOCTL_BLOCK_COUNT 4
#define MP_BLOCKDEV_IOCTL_BLOCK_SIZE 5
mp_obj_t mp_vfs_mount(size_t count, const mp_obj_t *args, mp_map_t *kwargs);
mp_obj_t mp_vfs_chdir(mp_obj_t path);
""",
}

HARNESS = r"""
/* Include the production file unchanged to exercise its static bindings. */
#include "machine_sdcard.c"
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); exit(1); } } while (0)
static int irq = 1, ready = 1, status, mount_error, chdir_error;
static unsigned ready_calls, reads, writes, syncs, counts, mounts, chdirs;
static unsigned diagnostics, exceptions, allocations, uint_calls, buffer_calls;
static int buffer_flags, raised_kind, raised_errno;
static uint64_t last_block, block_count = 1024, boxed_count;
static size_t last_len;
static void *last_buffer;
static void *allocated[32];
static unsigned char bytes[1024];
static mp_buffer_info_t buffer = {bytes, sizeof(bytes)};
static mp_obj_t mounted_device;
static const int VALUE_ERROR = 1, OS_ERROR = 2;
nlr_buf_t *host_nlr;
const mp_print_t mp_plat_print = {0};

static _Noreturn void raise_host(int kind, int error) {
    CHECK(host_nlr != NULL);
    raised_kind = kind;
    raised_errno = error;
    nlr_buf_t *target = host_nlr;
    target->ret_val = (void *)(uintptr_t)kind;
    host_nlr = target->prev;
    longjmp(target->jump, 1);
}
void nlr_pop(void) { CHECK(host_nlr != NULL); host_nlr = host_nlr->prev; }
_Noreturn void mp_raise_ValueError(const char *message) {
    CHECK(strstr(message, "SDCard(0)") != NULL);
    raise_host(VALUE_ERROR, 0);
}
_Noreturn void mp_raise_OSError(int error) { raise_host(OS_ERROR, error); }
#define EXPECT_RAISE(kind, error, expr) do { \
    nlr_buf_t catch; \
    if (nlr_push(&catch) == 0) { (void)(expr); nlr_pop(); CHECK(!"expected exception"); } \
    else { CHECK(raised_kind == (kind)); CHECK(raised_errno == (error)); } \
} while (0)
void *host_alloc(size_t size, const mp_obj_type_t *type) {
    CHECK(allocations < MP_ARRAY_SIZE(allocated));
    mp_obj_base_t *p = calloc(1, size);
    CHECK(p != NULL);
    p->type = type;
    allocated[allocations++] = p;
    return p;
}
mp_int_t mp_obj_get_int(mp_obj_t obj) {
    CHECK(obj & 1u);
    /* Host-only tagged small integers; not an MP representation claim. */
    return ((mp_int_t)(obj - 1u)) / 2;
}
mp_uint_t mp_obj_get_uint(mp_obj_t obj) {
    ++uint_calls;
    mp_int_t value = mp_obj_get_int(obj);
    /* Deliberately refuse to model real MP negative/overflow conversion. */
    CHECK(value >= 0);
    return (mp_uint_t)value;
}
void mp_arg_parse_all_kw_array(size_t n, size_t kw, const mp_obj_t *in,
        size_t count, const mp_arg_t *allowed, mp_arg_val_t *out) {
    CHECK(count == 2);
    CHECK(allowed[0].qstr == MP_QSTR_id && allowed[0].flags == MP_ARG_INT);
    CHECK(allowed[1].qstr == MP_QSTR_readonly);
    CHECK(allowed[1].flags == (MP_ARG_KW_ONLY | MP_ARG_BOOL));
    for (size_t i = 0; i < count; ++i) out[i] = allowed[i].defval;
    /* Only the known-valid call shapes used below are supported. */
    CHECK(n <= 1 && kw <= 1);
    if (n) out[0].u_int = mp_obj_get_int(in[0]);
    if (kw) {
        CHECK(in[n] == MP_OBJ_NEW_QSTR(MP_QSTR_readonly));
        CHECK(in[n + 1] == mp_const_true || in[n + 1] == mp_const_false);
        out[1].u_bool = in[n + 1] == mp_const_true;
    }
}
void mp_get_buffer_raise(mp_obj_t obj, mp_buffer_info_t *info, int flags) {
    CHECK(obj == MP_OBJ_FROM_PTR(&buffer));
    ++buffer_calls;
    buffer_flags = flags;
    *info = buffer;
}
static char mount_path[16];
mp_obj_t mp_obj_new_str(const char *text, size_t len) {
    CHECK(len < sizeof mount_path);
    memcpy(mount_path, text, len);
    mount_path[len] = 0;
    return MP_OBJ_FROM_PTR(mount_path);
}
mp_obj_t mp_obj_new_int_from_ull(unsigned long long value) {
    boxed_count = value;
    return MP_OBJ_FROM_PTR(&boxed_count);
}
void mp_map_init_fixed_table(mp_map_t *map, size_t count, const mp_obj_t *table) {
    map->used = count;
    map->table = (mp_obj_t *)table;
}
int mp_printf(const mp_print_t *print, const char *format, ...) {
    CHECK(print == &mp_plat_print);
    CHECK(strstr(format, "no format attempted") != NULL);
    ++diagnostics;
    return 0;
}
void mp_obj_print_exception(const mp_print_t *print, mp_obj_t exception) {
    CHECK(print == &mp_plat_print && exception == (mp_obj_t)OS_ERROR);
    ++exceptions;
}
int mpynn_irq_is_enabled(void) { return irq; }
int mpynn_sd_ready(void) { ++ready_calls; return ready; }
int mpynn_sd_read(uint64_t block, void *data, size_t len) {
    ++reads; last_block = block; last_buffer = data; last_len = len; return status;
}
int mpynn_sd_write(uint64_t block, const void *data, size_t len) {
    ++writes; last_block = block; last_buffer = (void *)data; last_len = len; return status;
}
int mpynn_sd_sync(void) { ++syncs; return status; }
int mpynn_sd_block_count(uint64_t *out) { ++counts; *out = block_count; return status; }
mp_obj_t mp_vfs_mount(size_t n, const mp_obj_t *args, mp_map_t *kwargs) {
    ++mounts;
    CHECK(n == 2);
    CHECK(strcmp((const char *)MP_OBJ_TO_PTR(args[1]), "/") == 0);
    machine_sdcard_obj_t *device = MP_OBJ_TO_PTR(args[0]);
    CHECK(device->base.type == &machine_sdcard_type && !device->readonly);
    /* Exactly one keyword proves mkfs is absent, not merely false. */
    CHECK(kwargs->used == 1);
    CHECK(kwargs->table[0] == MP_OBJ_NEW_QSTR(MP_QSTR_readonly));
    CHECK(kwargs->table[1] == mp_const_false);
    mounted_device = args[0];
    if (mount_error) mp_raise_OSError(MP_EIO);
    return mp_const_none;
}
mp_obj_t mp_vfs_chdir(mp_obj_t path) {
    ++chdirs;
    CHECK(strcmp((const char *)MP_OBJ_TO_PTR(path), "/") == 0);
    if (chdir_error) mp_raise_OSError(MP_EIO);
    return mp_const_none;
}
static mp_obj_t make_default(void) {
    return sdcard_make_new(&machine_sdcard_type, 0, 0, NULL);
}
static mp_obj_t make_writable(void) {
    mp_obj_t args[] = {MP_OBJ_NEW_QSTR(MP_QSTR_readonly), mp_const_false};
    return sdcard_make_new(&machine_sdcard_type, 0, 1, args);
}
static mp_int_t read_result(mp_obj_t self, unsigned block) {
    return mp_obj_get_int(sdcard_readblocks(self, MP_OBJ_NEW_SMALL_INT(block), MP_OBJ_FROM_PTR(&buffer)));
}
static mp_int_t write_result(mp_obj_t self, unsigned block) {
    return mp_obj_get_int(sdcard_writeblocks(self, MP_OBJ_NEW_SMALL_INT(block), MP_OBJ_FROM_PTR(&buffer)));
}
static mp_obj_t ioctl_result(mp_obj_t self, int cmd) {
    return sdcard_ioctl(self, MP_OBJ_NEW_SMALL_INT(cmd), mp_const_none);
}
static void test_constructor(void) {
    mp_obj_t ro = make_default(), rw = make_writable();
    CHECK(((machine_sdcard_obj_t *)MP_OBJ_TO_PTR(ro))->readonly);
    CHECK(!((machine_sdcard_obj_t *)MP_OBJ_TO_PTR(rw))->readonly);
    block_count = (uint64_t)MP_SMALL_INT_MAX + 1;
    EXPECT_RAISE(OS_ERROR, MP_EFBIG, make_default());
    block_count = 0;
    EXPECT_RAISE(OS_ERROR, MP_EFBIG, make_default());
    block_count = MP_SMALL_INT_MAX;
    mp_obj_t max_card = make_default();
    CHECK(((machine_sdcard_obj_t *)MP_OBJ_TO_PTR(max_card))->readonly);
    block_count = 1024;
    CHECK(write_result(ro, 0) == -MP_EROFS && writes == 0);
    CHECK(write_result(rw, 0) == 0 && writes == 1);
    mp_obj_t id = MP_OBJ_NEW_SMALL_INT(1);
    unsigned before = ready_calls;
    EXPECT_RAISE(VALUE_ERROR, 0, sdcard_make_new(&machine_sdcard_type, 1, 0, &id));
    id = MP_OBJ_NEW_SMALL_INT(-1);
    EXPECT_RAISE(VALUE_ERROR, 0, sdcard_make_new(&machine_sdcard_type, 1, 0, &id));
    CHECK(ready_calls == before && allocations == 3);
    ready = 0;
    EXPECT_RAISE(OS_ERROR, MP_ENODEV, make_default());
    CHECK(allocations == 3);
    irq = 0;
    before = ready_calls;
    EXPECT_RAISE(OS_ERROR, MP_EBUSY, make_default());
    CHECK(ready_calls == before && allocations == 3);
}
static void test_errno(void) {
    const int statuses[] = {MPYNN_SD_OK, MPYNN_SD_NOT_READY, MPYNN_SD_INVALID,
        MPYNN_SD_RANGE, MPYNN_SD_IO, MPYNN_SD_BUSY, MPYNN_SD_CONTEXT, 1234};
    const int errors[] = {0, MP_ENODEV, MP_EINVAL, MP_EINVAL, MP_EIO, MP_EBUSY, MP_EBUSY, MP_EIO};
    mp_obj_t rw = make_writable();
    for (size_t i = 0; i < MP_ARRAY_SIZE(statuses); ++i) {
        status = statuses[i];
        CHECK(read_result(rw, 7) == -errors[i]);
        CHECK(buffer_flags == MP_BUFFER_WRITE && last_block == 7);
        CHECK(write_result(rw, 9) == -errors[i]);
        CHECK(buffer_flags == MP_BUFFER_READ && last_block == 9);
        CHECK(last_buffer == bytes && last_len == sizeof(bytes));
    }
    CHECK(reads == MP_ARRAY_SIZE(statuses) && writes == MP_ARRAY_SIZE(statuses));
    CHECK(uint_calls == reads + writes && buffer_calls == reads + writes);
}
static void test_irq(void) {
    mp_obj_t rw = make_writable(), ro = make_default();
    irq = 0;
    CHECK(read_result(rw, 0) == -MP_EBUSY);
    CHECK(write_result(rw, 0) == -MP_EBUSY);
    CHECK(write_result(ro, 0) == -MP_EROFS); /* readonly wins over IRQ guard */
    unsigned before = ready_calls;
    for (int cmd = 1; cmd <= 6; ++cmd) CHECK(mp_obj_get_int(ioctl_result(rw, cmd)) == -MP_EBUSY);
    CHECK(reads == 0 && writes == 0 && syncs == 0 && counts == 2);
    CHECK(ready_calls == before);
}
static void test_ioctl(void) {
    mp_obj_t ro = make_default();
    CHECK(mp_obj_get_int(ioctl_result(ro, 1)) == 0);
    ready = 0;
    CHECK(mp_obj_get_int(ioctl_result(ro, 1)) == -MP_ENODEV);
    ready = 1;
    const int statuses[] = {MPYNN_SD_OK, MPYNN_SD_NOT_READY, MPYNN_SD_INVALID,
        MPYNN_SD_RANGE, MPYNN_SD_IO, MPYNN_SD_BUSY, MPYNN_SD_CONTEXT, -100};
    const int errors[] = {0, MP_ENODEV, MP_EINVAL, MP_EINVAL, MP_EIO, MP_EBUSY, MP_EBUSY, MP_EIO};
    for (size_t i = 0; i < MP_ARRAY_SIZE(statuses); ++i) {
        status = statuses[i];
        CHECK(mp_obj_get_int(ioctl_result(ro, 2)) == -errors[i]);
        CHECK(mp_obj_get_int(ioctl_result(ro, 3)) == -errors[i]);
        if (errors[i]) { EXPECT_RAISE(OS_ERROR, errors[i], ioctl_result(ro, 4)); }
        else {
            CHECK(mp_obj_get_int(ioctl_result(ro, 4)) == (mp_int_t)block_count);
        }
    }
    CHECK(syncs == 2 * MP_ARRAY_SIZE(statuses));
    CHECK(counts == MP_ARRAY_SIZE(statuses) + 1);
    status = MPYNN_SD_OK;
    block_count = (uint64_t)MP_SMALL_INT_MAX + 1;
    EXPECT_RAISE(OS_ERROR, MP_EFBIG, ioctl_result(ro, 4));
    block_count = 0;
    EXPECT_RAISE(OS_ERROR, MP_EFBIG, ioctl_result(ro, 4));
    block_count = MP_SMALL_INT_MAX;
    CHECK(mp_obj_get_int(ioctl_result(ro, 4)) == MP_SMALL_INT_MAX);
    unsigned old_syncs = syncs, old_counts = counts, old_ready = ready_calls;
    CHECK(mp_obj_get_int(ioctl_result(ro, 5)) == 512);
    CHECK(ioctl_result(ro, 0) == mp_const_none);
    CHECK(ioctl_result(ro, 6) == mp_const_none);
    CHECK(ioctl_result(ro, -1) == mp_const_none);
    CHECK(syncs == old_syncs && counts == old_counts && ready_calls == old_ready);
}
static void test_lengths(void) {
    mp_obj_t rw = make_writable();
    const size_t lengths[] = {0, 1, 511, 512, 513, 1024};
    for (size_t i = 0; i < MP_ARRAY_SIZE(lengths); ++i) {
        buffer.len = lengths[i];
        /* Fake bridge decides validity: this checks forwarding only. */
        status = MPYNN_SD_INVALID;
        CHECK(read_result(rw, 4) == -MP_EINVAL && last_len == lengths[i]);
        CHECK(write_result(rw, 4) == -MP_EINVAL && last_len == lengths[i]);
        CHECK(last_buffer == bytes && last_block == 4);
    }
    CHECK(reads == MP_ARRAY_SIZE(lengths) && writes == MP_ARRAY_SIZE(lengths));
}
static void test_mount(void) {
    ready = 0;
    CHECK(!mpynn_storage_mount());
    CHECK(mounts == 0 && chdirs == 0 && allocations == 0);
    ready = 1;
    CHECK(mpynn_storage_mount());
    CHECK(mounts == 1 && chdirs == 1 && mounted_device != 0 && host_nlr == NULL);
    CHECK(writes == 0 && diagnostics == 0 && exceptions == 0);
    CHECK(write_result(mounted_device, 0) == 0 && writes == 1);
    writes = 0; // fake bridge only: never writes a host/physical disk
    mount_error = 1;
    CHECK(!mpynn_storage_mount());
    CHECK(mounts == 2 && chdirs == 1 && diagnostics == 1 && exceptions == 1);
    CHECK(host_nlr == NULL);
    mount_error = 0;
    chdir_error = 1;
    CHECK(!mpynn_storage_mount());
    CHECK(mounts == 3 && chdirs == 2 && diagnostics == 2 && exceptions == 2);
    chdir_error = 0;
    irq = 0;
    CHECK(!mpynn_storage_mount());
    CHECK(mounts == 3 && chdirs == 2 && diagnostics == 3 && exceptions == 3);
    CHECK(host_nlr == NULL && writes == 0);
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    if (!strcmp(argv[1], "constructor")) test_constructor();
    else if (!strcmp(argv[1], "errno")) test_errno();
    else if (!strcmp(argv[1], "irq")) test_irq();
    else if (!strcmp(argv[1], "ioctl")) test_ioctl();
    else if (!strcmp(argv[1], "lengths")) test_lengths();
    else if (!strcmp(argv[1], "mount")) test_mount();
    else CHECK(!"unknown scenario");
    CHECK(host_nlr == NULL);
    for (unsigned i = 0; i < allocations; ++i) free(allocated[i]);
    puts("PASS");
    return 0;
}
"""


class SDCardBindingHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = next((candidate for candidate in (
            "E:/msys64/ucrt64/bin/gcc.exe", shutil.which("gcc")
        ) if candidate and Path(candidate).is_file()), None)
        if compiler is None:
            raise unittest.SkipTest("host GCC unavailable")
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-sdcard-binding-")
        def cleanup():
            for attempt in range(21):
                try:
                    temporary.cleanup()
                    return
                except PermissionError:
                    if attempt == 20:
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
        cls.executable = cls.root / "sdcard-binding-host.exe"
        cls.env = dict(os.environ)
        cls.env["PATH"] = str(Path(compiler).parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(cls.root),
             # Quote-only search avoids shadowing host <setjmp.h> with the port's.
             "-iquote", str(SOURCE.parent), str(harness), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host GCC compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, name):
        result = subprocess.run([str(self.executable), name], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_constructor_readonly_id_and_absent_device(self):
        self.run_scenario("constructor")

    def test_read_write_negative_errno_mapping(self):
        self.run_scenario("errno")

    def test_masked_irq_prevents_bridge_io(self):
        self.run_scenario("irq")

    def test_ioctl_commands_and_error_forms(self):
        self.run_scenario("ioctl")

    def test_buffer_lengths_forwarded_without_binding_validation(self):
        self.run_scenario("lengths")

    def test_mount_writable_root_without_mkfs_and_failure_fallback(self):
        self.run_scenario("mount")


if __name__ == "__main__":
    unittest.main()
