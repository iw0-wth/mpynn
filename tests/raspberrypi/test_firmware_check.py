# SPDX-License-Identifier: MIT
"""Host-only unit tests for the ELF layout checker; no hardware simulation."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

CHECKER = Path(__file__).resolve().parents[2] / "ports/raspberrypi/check_firmware.py"
spec = importlib.util.spec_from_file_location("firmware_check", CHECKER)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def fixture(entry=0x8000, machine=40, bss_end=0x9000, flags=0x5000400):
    names = b"\0.init\0.bss\0.shstrtab\0.strtab\0.symtab\0"
    symbols = b"\0_start\0main\0mpynn_vm_run\0mp_init\0gc_collect\0mpynn_setjmp\0mpynn_longjmp\0"
    data = bytearray(0x100)
    data[0x80:0x84] = b"BOOT"
    name_off = len(data)
    data.extend(names)
    str_off = len(data)
    data.extend(symbols)
    sym_off = len(data)
    data.extend(bytes(16))
    for symbol in (b"_start", b"main", b"mpynn_vm_run", b"mp_init", b"gc_collect", b"mpynn_setjmp", b"mpynn_longjmp"):
        data.extend(struct.pack("<IIIBBH", symbols.index(symbol), 0x8000, 0, 0x12, 0, 1))
    sym_size = len(data) - sym_off
    shoff = len(data)
    sections = [
        (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        (names.index(b".init"), 1, 6, 0x8000, 0x80, 4, 0, 0, 4, 0),
        (names.index(b".bss"), 8, 3, 0x8008, 0x88, bss_end - 0x8008, 0, 0, 8, 0),
        (names.index(b".shstrtab"), 3, 0, 0, name_off, len(names), 0, 0, 1, 0),
        (names.index(b".strtab"), 3, 0, 0, str_off, len(symbols), 0, 0, 1, 0),
        (names.index(b".symtab"), 2, 0, 0, sym_off, sym_size, 4, 1, 4, 16),
    ]
    for section in sections:
        data.extend(struct.pack("<IIIIIIIIII", *section))
    struct.pack_into("<16sHHIIIIIHHHHHH", data, 0,
                     b"\x7fELF\x01\x01\x01" + bytes(9), 2, machine, 1, entry,
                     0, shoff, flags, 52, 0, 0, 40, len(sections), 3)
    return data


class FirmwareCheckTests(unittest.TestCase):
    def run_check(self, data, image=b"BOOT"):
        with tempfile.TemporaryDirectory() as folder:
            elf, img = Path(folder)/"kernel.elf", Path(folder)/"kernel.img"
            elf.write_bytes(data)
            img.write_bytes(image)
            return checker.verify(elf, img)

    def test_valid_layout_is_static_only(self):
        result = self.run_check(fixture())
        self.assertEqual(result["image_bytes"], 4)
        self.assertFalse(result["hardware_tested"])

    def test_wrong_entry_rejected(self):
        with self.assertRaisesRegex(ValueError, "entry"):
            self.run_check(fixture(entry=0x10000))

    def test_wrong_architecture_rejected(self):
        with self.assertRaisesRegex(ValueError, "ARM"):
            self.run_check(fixture(machine=183))

    def test_soft_float_rejected(self):
        with self.assertRaisesRegex(ValueError, "hard-float"):
            self.run_check(fixture(flags=0x5000200))

    def test_bss_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError, "reserved memory"):
            self.run_check(fixture(bss_end=0x208004))

    def test_truncated_image_rejected(self):
        with self.assertRaisesRegex(ValueError, "size"):
            self.run_check(fixture(), image=b"BO")


if __name__ == "__main__":
    unittest.main()
