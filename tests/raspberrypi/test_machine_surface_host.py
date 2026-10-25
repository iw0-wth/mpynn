# SPDX-License-Identifier: MIT
"""Source/preprocessor contract for the deliberately limited Pi machine surface.

This is not a board-runtime test. The C harness consumes the real configuration,
extra-global macro and upstream registration table, rather than recreating the
module's registrations. It uses stdin and never writes an executable or build
artifact. Pin/RTC implementation behavior is covered by their separate tests.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "ports/raspberrypi"
UPSTREAM = ROOT / "lib/micropython"
DISABLED = ("PWM", "UART")
GUARDED = {
    "I2C": "I2C",
    "SPI": "SPI",
    "SoftI2C": "SOFTI2C",
    "SoftSPI": "SOFTSPI",
    "PWM": "PWM",
    "WDT": "WDT",
    "UART": "UART",
    "SDCard": "SDCARD",
}


def _without_comments(source):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)


def _extra_globals(source):
    """Extract the complete existing multiline definition, including continuations."""
    match = re.search(
        r"^#define MICROPY_PY_MACHINE_EXTRA_GLOBALS[^\n]*(?:\n[^\n]*)*",
        source,
        flags=re.M,
    )
    if match is None:
        raise AssertionError("port must define MICROPY_PY_MACHINE_EXTRA_GLOBALS")
    lines = match.group().splitlines()
    definition = []
    for line in lines:
        definition.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return "\n".join(definition) + "\n"


def _globals_table(source):
    match = re.search(
        r"static const mp_rom_map_elem_t machine_module_globals_table\[\]\s*=\s*\{"
        r".*?^\};",
        source,
        flags=re.M | re.S,
    )
    if match is None:
        raise AssertionError("upstream machine registration table not found")
    return match.group() + "\n"


def _compiler():
    for name in ("gcc", "clang", "cc"):
        executable = shutil.which(name)
        if executable:
            return executable
    gcc = Path("E:/msys64/ucrt64/bin/gcc.exe")
    return str(gcc) if gcc.is_file() else None


class MachineSurfaceHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = _without_comments((PORT / "mpconfigport.h").read_text(encoding="utf-8"))
        cls.port_source = _without_comments((PORT / "modmachine_port.c").read_text(encoding="utf-8"))
        cls.upstream_source = _without_comments((UPSTREAM / "extmod/modmachine.c").read_text(encoding="utf-8"))
        cls.makefile = (PORT / "Makefile").read_text(encoding="utf-8")
        cls.extra = _extra_globals(cls.port_source)
        cls.table = _globals_table(cls.upstream_source)

    def test_port_config_enables_machine_but_not_unimplemented_peripherals(self):
        for name, value in (("MICROPY_PY_MACHINE", "1"), ("MICROPY_PY_MACHINE_SDCARD", "0"), ("MICROPY_PY_MACHINE_WDT", "1"), ("MICROPY_PY_MACHINE_SOFTI2C", "1"), ("MICROPY_PY_MACHINE_SOFTSPI", "1"), ("MICROPY_PY_MACHINE_TIMER", "1")):
            with self.subTest(macro=name):
                definitions = re.findall(r"^\s*#define\s+" + name + r"\s+([^\n]+)$", self.config, re.M)
                self.assertEqual(len(definitions), 1)
                self.assertEqual(definitions[0].strip().strip("() "), value)
        self.assertRegex(self.config, r'(?m)^#define\s+MICROPY_PY_MACHINE_INCLUDEFILE\s+"modmachine_port\.c"\s*$')
        for feature in DISABLED:
            with self.subTest(feature=feature):
                definitions = re.findall(
                    r"^\s*#define\s+MICROPY_PY_MACHINE_" + feature + r"(?:\s+([^\n]*))?$",
                    self.config,
                    re.M,
                )
                for value in definitions:
                    self.assertEqual(value.strip().strip("() "), "0", "peripheral must be absent or explicitly disabled")

    def test_actual_upstream_guards_and_port_extension_contract(self):
        self.assertRegex(self.upstream_source, r"(?m)^#if MICROPY_PY_MACHINE\s*$")
        self.assertRegex(
            self.upstream_source,
            r"#ifdef MICROPY_PY_MACHINE_INCLUDEFILE\s*\n#include MICROPY_PY_MACHINE_INCLUDEFILE\s*\n#endif",
        )
        self.assertIn("MP_REGISTER_EXTENSIBLE_MODULE(MP_QSTR_machine, mp_module_machine);", self.upstream_source)
        for name, feature in GUARDED.items():
            with self.subTest(symbol=name):
                self.assertRegex(
                    self.table,
                    r"#if MICROPY_PY_MACHINE_" + feature + r"\s*\n"
                    r"\s*\{\s*MP_ROM_QSTR\(MP_QSTR_" + name + r"\),\s*MP_ROM_PTR\([^\n]+\}\s*,\s*\n\s*#endif",
                )
        self.assertRegex(
            self.table,
            r"#ifdef MICROPY_PY_MACHINE_EXTRA_GLOBALS\s*\n\s*MICROPY_PY_MACHINE_EXTRA_GLOBALS\s*\n\s*#endif",
        )
        for name, symbol in (("Pin", "machine_pin_type"), ("RTC", "mpynn_rtc_type")):
            with self.subTest(symbol=name):
                self.assertIn("{ MP_ROM_QSTR(MP_QSTR_" + name + "), MP_ROM_PTR(&" + symbol + ") },", self.extra)
        extra_names = set(re.findall(r"MP_ROM_QSTR\(MP_QSTR_(\w+)\)", self.extra))
        self.assertTrue({"Pin", "RTC"}.issubset(extra_names))
        self.assertTrue(set(GUARDED).difference({"Timer"}).isdisjoint(extra_names))
        self.assertIn("Timer", extra_names)

    def test_makefile_uses_upstream_module_and_only_includes_port_fragment(self):
        logical = self.makefile.replace("\\\n", " ")
        assignments = dict(re.findall(r"(?m)^([A-Z_]+)\s*:=\s*([^\n]*)", logical))
        self.assertIn("include $(TOP)/extmod/extmod.mk", logical)
        self.assertIn("extmod/modmachine.c", assignments["SRC_EXTMOD_C"].split())
        self.assertNotIn("modmachine_port.c", assignments["SRC_C"].split())
        self.assertRegex(logical, r"(?m)^SRC_QSTR\s*\+=.*\bmodmachine_port\.c\b")
        self.assertNotRegex(logical, r"(?m)^SRC_(?:C|EXTMOD_C)\s*(?::=|\+=|=)[^\n]*\bmodmachine_port\.c\b")

    def _run_compiler(self, compiler, program, mode):
        env = os.environ.copy()
        env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
        command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", *mode,
                   "-I" + str(PORT), "-I" + str(ROOT / "boards/RPI1B"),
                   "-I" + str(UPSTREAM), "-x", "c", "-"]
        result = subprocess.run(command, input=program, env=env, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, " ".join(command) + "\n" + result.stdout + result.stderr)
        return result.stdout

    def _program(self, enabled=()):
        # Consume every real port directive and upstream py/mpconfig.h default.
        # MinGW lacks POSIX alloca.h; its declarations are irrelevant to this
        # registration-only harness. Remove that one include, not any macros.
        # The real port include guard prevents py/mpconfig.h from rereading it.
        # board_config.h is still included from the real board directory.
        checks = ["#if MICROPY_PY_MACHINE != 1", '#error "machine must be enabled"', "#endif",
                  "#if MICROPY_PY_MACHINE_SDCARD != 0", '#error "SDCard must be disabled"', "#endif"]
        for feature in DISABLED:
            checks += ["#if MICROPY_PY_MACHINE_" + feature,
                       '#error "unsupported peripheral enabled: ' + feature + '"', "#endif"]
        port_config = re.sub(r'(?m)^\s*#include\s+<alloca\.h>\s*$', '', self.config)
        program = port_config + '\n#include "py/mpconfig.h"\n' + "\n".join(checks) + "\n"
        program += '_Static_assert(sizeof(MICROPY_PY_MACHINE_INCLUDEFILE) == sizeof("modmachine_port.c"), "port include file");\n'
        # Positive controls override only after checking the production config.
        for feature in enabled:
            program += "#undef MICROPY_PY_MACHINE_" + feature + "\n#define MICROPY_PY_MACHINE_" + feature + " 1\n"
        names = sorted(set(re.findall(r"MP_QSTR_(\w+)", self.table + self.extra)))
        pointers = sorted(set(re.findall(r"MP_ROM_PTR\(&([A-Za-z_]\w*)\)", self.table + self.extra)))
        program += "typedef struct { const char *key; const void *value; } mp_rom_map_elem_t;\n"
        program += "#define MP_ROM_QSTR(q) #q\n#define MP_ROM_PTR(p) p\n"
        # ABI-only declarations for symbols referenced by the extracted table;
        # these do not supply any registrations or peripheral enable flags.
        program += "extern const char " + ", ".join(pointers) + ";\n"
        self.assertIn("Pin", names)
        self.assertIn("RTC", names)
        program += self.extra + self.table
        program += "_Static_assert(sizeof(machine_module_globals_table) > 0, \"nonempty module\");\n"
        return program

    def test_real_config_and_extracted_registrations_compile_without_executable(self):
        compiler = _compiler()
        if compiler is None:
            self.skipTest("host C compiler unavailable; source contracts still run")
        program = self._program()
        self._run_compiler(compiler, program, ["-fsyntax-only"])
        preprocessed = self._run_compiler(compiler, program, ["-E", "-P"])
        surface = _globals_table(preprocessed)
        self.assertIn('{ "MP_QSTR_Pin", &machine_pin_type }', surface)
        self.assertIn('{ "MP_QSTR_RTC", &mpynn_rtc_type }', surface)
        for name in (*GUARDED, "Timer"):
            if name in ("I2C", "SPI", "WDT", "SoftI2C", "SoftSPI", "Timer"): 
                continue
            with self.subTest(excluded=name):
                self.assertNotIn('"MP_QSTR_' + name + '"', surface)

        # A constant empty/fake table would also pass an exclusion check. Enabling
        # each actual guard must instead reveal precisely its actual registration.
        controls = ("I2C", "SPI", "PWM", "WDT")
        for feature in controls:
            with self.subTest(positive_control=feature):
                enabled = _globals_table(self._run_compiler(compiler, self._program((feature,)), ["-E", "-P"]))
                self.assertIn('"MP_QSTR_' + feature + '"', enabled)
                for other in set(GUARDED).difference({feature, "I2C", "SPI", "WDT", "SoftI2C", "SoftSPI"}):
                    self.assertNotIn('"MP_QSTR_' + other + '"', enabled)
                self.assertIn('"MP_QSTR_Pin"', enabled)
                self.assertIn('"MP_QSTR_RTC"', enabled)


if __name__ == "__main__":
    unittest.main()
