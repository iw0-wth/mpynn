# SPDX-License-Identifier: MIT
"""Compile actual modsocket getsockopt wrapper, hook and option exports on host."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / "ports/raspberrypi"
GCC = Path("E:/msys64/ucrt64/bin/gcc.exe")


class GetsockoptExportTests(unittest.TestCase):
    def test_actual_var_between_wrapper_hook_method_and_tcp_option_constants(self):
        if not GCC.is_file():
            self.skipTest("host GCC unavailable")
        source = (PORT / "upstream_overrides/micropython/extmod/modsocket.c").read_text()
        start = source.index("#ifdef MICROPY_PORT_SOCKET_GETSOCKOPT\nstatic mp_obj_t socket_getsockopt(")
        wrapper = source[start:source.index("#endif", start) + len("#endif")]
        locals_start = source.index("static const mp_rom_map_elem_t socket_locals_dict_table[]")
        method_start = source.index("    #ifdef MICROPY_PORT_SOCKET_GETSOCKOPT", locals_start)
        method = source[method_start:source.index("    #endif", method_start) + len("    #endif")]
        globals_start = source.index("static const mp_rom_map_elem_t mp_module_socket_globals_table[]")
        constant_start = source.index("    #ifdef MICROPY_PORT_SOCKET_GETSOCKOPT", globals_start)
        constants = source[constant_start:source.index("    #endif", constant_start) + len("    #endif")]
        config = (PORT / "mpconfigport.h").read_text()
        hook = next(line for line in config.splitlines() if line.startswith("#define MICROPY_PORT_SOCKET_GETSOCKOPT "))
        declaration = next(line for line in (PORT / "socket_port.h").read_text().splitlines()
                           if line.startswith("mp_obj_t mpynn_socket_getsockopt("))
        # Compile the actual port constant, not an independently invented fake.
        header = (PORT / "socket_port.h").read_text()
        type_constant = next(line for line in header.splitlines()
                             if line.startswith("#define MPYNN_SOCKET_SO_TYPE "))
        error_constant = next(line for line in header.splitlines()
                              if line.startswith("#define MPYNN_SOCKET_SO_ERROR "))
        tcp_constant = next(line for line in header.splitlines()
                            if line.startswith("#define MPYNN_SOCKET_IPPROTO_TCP "))
        nodelay_constant = next(line for line in header.splitlines()
                                if line.startswith("#define MPYNN_SOCKET_TCP_NODELAY "))
        program = r'''
#include <stddef.h>
#include <stdint.h>
#include <assert.h>
typedef void *mp_obj_t;
typedef struct { int key; uintptr_t value; } mp_rom_map_elem_t;
typedef struct { size_t min_args, max_args; mp_obj_t (*call)(size_t, const mp_obj_t *); } fun_obj_t;
#define MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(name, min, max, fun) const fun_obj_t name = {min, max, fun}
#define MP_ROM_QSTR(q) q
#define MP_ROM_PTR(p) ((uintptr_t)(p))
#define MP_ROM_INT(n) n
enum { MP_QSTR_getsockopt, MP_QSTR_SO_TYPE, MP_QSTR_SO_ERROR, MP_QSTR_IPPROTO_TCP, MP_QSTR_TCP_NODELAY };
static size_t seen_count;
static const mp_obj_t *seen_args;
''' + hook + "\n" + declaration + "\n" + type_constant + "\n" + error_constant + "\n" + tcp_constant + "\n" + nodelay_constant + r'''
mp_obj_t mpynn_socket_getsockopt(size_t n_args, const mp_obj_t *args) {
    seen_count = n_args; seen_args = args; return (mp_obj_t)99;
}
''' + wrapper + "\nstatic const mp_rom_map_elem_t methods[] = {\n" + method + "\n};\nstatic const mp_rom_map_elem_t constants[] = {\n" + constants + r'''
};
int main(void) {
    assert(sizeof(methods) / sizeof(methods[0]) == 1);
    assert(methods[0].key == MP_QSTR_getsockopt);
    const fun_obj_t *method = (const fun_obj_t *)methods[0].value;
    assert(method->min_args == 3 && method->max_args == 4);
    assert(sizeof(constants) / sizeof(constants[0]) == 4);
    unsigned seen_type = 0, seen_error = 0, seen_tcp = 0, seen_nodelay = 0;
    for (size_t i = 0; i < sizeof(constants) / sizeof(constants[0]); ++i) {
        if (constants[i].key == MP_QSTR_SO_TYPE) {
            assert(constants[i].value == 0x1008 && MPYNN_SOCKET_SO_TYPE == 0x1008);
            ++seen_type;
        } else if (constants[i].key == MP_QSTR_SO_ERROR) {
            assert(constants[i].value == 0x1007 && MPYNN_SOCKET_SO_ERROR == 0x1007);
            ++seen_error;
        } else if (constants[i].key == MP_QSTR_IPPROTO_TCP) {
            assert(constants[i].value == 6 && MPYNN_SOCKET_IPPROTO_TCP == 6);
            ++seen_tcp;
        } else {
            assert(constants[i].key == MP_QSTR_TCP_NODELAY);
            assert(constants[i].value == 1 && MPYNN_SOCKET_TCP_NODELAY == 1);
            ++seen_nodelay;
        }
    }
    assert(seen_type == 1 && seen_error == 1 && seen_tcp == 1 && seen_nodelay == 1);
    const uintptr_t options[] = {0x1008, 0x1007, MPYNN_SOCKET_TCP_NODELAY};
    for (size_t option = 0; option < sizeof(options) / sizeof(options[0]); ++option) {
        uintptr_t level = option == 2 ? MPYNN_SOCKET_IPPROTO_TCP : 0x0fff;
        mp_obj_t args[] = {(mp_obj_t)42, (mp_obj_t)level, (mp_obj_t)options[option], (mp_obj_t)1};
        for (size_t count = 3; count <= 4; ++count) {
            assert(method->call(count, args) == (mp_obj_t)99);
            assert(seen_count == count && seen_args == args);
            assert(seen_args[0] == (mp_obj_t)42 && seen_args[1] == (mp_obj_t)level);
            assert(seen_args[2] == (mp_obj_t)options[option]);
            if (count == 4) assert(seen_args[3] == (mp_obj_t)1);
        }
    }
}
'''
        env = os.environ.copy()
        env["PATH"] = str(GCC.parent) + os.pathsep + env.get("PATH", "")
        with tempfile.TemporaryDirectory(prefix="mpynn-getsockopt-export-") as folder:
            root = Path(folder)
            src = root / "test.c"
            exe = root / "test.exe"
            src.write_text(program)
            for command in ([str(GCC), "-std=c11", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], [str(exe)]):
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
