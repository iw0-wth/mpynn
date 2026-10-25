# SPDX-License-Identifier: MIT
"""Compile actual modsocket shutdown wrapper and export entries with a host ABI."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / "ports/raspberrypi"
GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")


class ShutdownExportTests(unittest.TestCase):
    def test_actual_wrapper_method_and_constants_dispatch(self):
        if not GCC.is_file():
            self.skipTest("host GCC unavailable")
        source = (PORT / "upstream_overrides/micropython/extmod/modsocket.c").read_text()
        start = source.index("#ifdef MICROPY_PORT_SOCKET_SHUTDOWN\nstatic mp_obj_t socket_shutdown(")
        wrapper = source[start:source.index("static const mp_rom_map_elem_t socket_locals_dict_table[]", start)]
        method_start = source.index("    #ifdef MICROPY_PORT_SOCKET_SHUTDOWN", start + len(wrapper))
        method = source[method_start:source.index("    #endif", method_start) + len("    #endif")]
        constant_start = source.index("    #ifdef MICROPY_PORT_SOCKET_SHUTDOWN", source.index("static const mp_rom_map_elem_t mp_module_socket_globals_table[]"))
        constants = source[constant_start:source.index("    #endif", constant_start) + len("    #endif")]
        config = (PORT / "mpconfigport.h").read_text()
        hook = next(line for line in config.splitlines() if line.startswith("#define MICROPY_PORT_SOCKET_SHUTDOWN "))
        declaration = next(line for line in (PORT / "socket_port.h").read_text().splitlines() if line.startswith("mp_obj_t mpynn_socket_shutdown("))
        program = r'''
#include <stdint.h>
#include <assert.h>
typedef void *mp_obj_t;
typedef struct { int key; uintptr_t value; } mp_rom_map_elem_t;
typedef struct { mp_obj_t (*call)(mp_obj_t, mp_obj_t); } fun_obj_t;
#define MP_DEFINE_CONST_FUN_OBJ_2(name, fun) const fun_obj_t name = {fun}
#define MP_ROM_QSTR(q) q
#define MP_ROM_PTR(p) ((uintptr_t)(p))
#define MP_ROM_INT(n) n
enum { MP_QSTR_shutdown, MP_QSTR_SHUT_RD, MP_QSTR_SHUT_WR, MP_QSTR_SHUT_RDWR };
static mp_obj_t seen_self, seen_how;
''' + hook + "\n" + declaration + r'''
mp_obj_t mpynn_socket_shutdown(mp_obj_t self, mp_obj_t how) {
    seen_self = self; seen_how = how; return (mp_obj_t)99;
}
''' + wrapper + "\nstatic const mp_rom_map_elem_t methods[] = {\n" + method + "\n};\nstatic const mp_rom_map_elem_t constants[] = {\n" + constants + r'''
};
int main(void) {
    assert(sizeof(methods) / sizeof(methods[0]) == 1);
    assert(methods[0].key == MP_QSTR_shutdown);
    const fun_obj_t *method = (const fun_obj_t *)methods[0].value;
    assert(sizeof(constants) / sizeof(constants[0]) == 3);
    for (int how = 0; how < 3; ++how) {
        assert(constants[how].key == MP_QSTR_SHUT_RD + how);
        assert(constants[how].value == (uintptr_t)how);
        assert(method->call((mp_obj_t)42, (mp_obj_t)(uintptr_t)how) == (mp_obj_t)99);
        assert(seen_self == (mp_obj_t)42 && seen_how == (mp_obj_t)(uintptr_t)how);
    }
}
'''
        env = os.environ.copy()
        env["PATH"] = str(GCC.parent) + os.pathsep + env.get("PATH", "")
        with tempfile.TemporaryDirectory(prefix="mpynn-shutdown-export-") as folder:
            root = Path(folder)
            src = root / "test.c"
            exe = root / "test.exe"
            src.write_text(program)
            for command in ([str(GCC), "-std=c11", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], [str(exe)]):
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
