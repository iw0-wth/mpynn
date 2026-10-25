#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the Pi 1 Circle ELF layout without third-party Python packages.

This is a static build check, NOT evidence of successful hardware execution.
"""
import argparse
import json
from pathlib import Path
import struct


def verify(elf_path, image_path):
    data = Path(elf_path).read_bytes()
    if data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("expected a 32-bit little-endian ELF")
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
    _, kind, machine, _, entry, _, shoff, flags, _, _, _, shentsize, shnum, shstrndx = header
    if (kind, machine, entry) != (2, 40, 0x8000):
        raise ValueError(f"expected ARM executable entry 0x8000, got {kind}/{machine}/{entry:#x}")
    if not flags & 0x400 or flags & 0x200:
        raise ValueError("expected hard-float EABI, not soft-float")
    if shentsize != 40 or not 0 < shstrndx < shnum:
        raise ValueError("invalid section header table")
    sections = [struct.unpack_from("<IIIIIIIIII", data, shoff + i * shentsize) for i in range(shnum)]
    strings = sections[shstrndx]
    names = data[strings[4]:strings[4] + strings[5]]

    def string_at(blob, offset):
        return blob[offset:blob.index(b"\0", offset)].decode("ascii")

    allocated = []
    symbols = {}
    undefined = []
    for section in sections:
        name, stype, sflags, addr, offset, size, link, _, _, entsize = section
        section_name = string_at(names, name)
        if sflags & 2 and size:
            allocated.append({"name": section_name, "address": addr, "size": size})
            if addr < 0x8000 or addr + size > 0x208000:
                raise ValueError(f"{section_name} overlaps reserved memory: {addr:#x}+{size:#x}")
        if stype == 2:
            table = sections[link]
            symnames = data[table[4]:table[4] + table[5]]
            for pos in range(offset, offset + size, entsize):
                nm, value, _, info, _, shndx = struct.unpack_from("<IIIBBH", data, pos)
                if not nm:
                    continue
                symbol = string_at(symnames, nm)
                if shndx:
                    symbols[symbol] = value
                elif info >> 4 != 2:  # ignore undefined weak hooks
                    undefined.append(symbol)
    if undefined:
        raise ValueError(f"unresolved non-weak symbols: {undefined}")
    required = ("_start", "main", "mpynn_vm_run", "mp_init", "gc_collect", "mpynn_setjmp", "mpynn_longjmp")
    for symbol in required:
        if symbol not in symbols:
            raise ValueError(f"missing required symbol: {symbol}")
    for prefix in ("omv_protocol", "omv_csi", "py_csi", "framebuffer_init"):
        if any(symbol.startswith(prefix) for symbol in symbols):
            raise ValueError(f"unexpected OpenMV hardware/protocol symbol: {prefix}")
    image_size = Path(image_path).stat().st_size
    file_sections = [s for s in sections if s[2] & 2 and s[1] != 8 and s[5]]
    image_start = min(s[3] for s in file_sections)
    image_end = max(s[3] + s[5] for s in file_sections)
    if image_size != image_end - image_start:
        raise ValueError("binary image size does not match the ELF load span")
    return {"verification": "static-only", "entry": entry, "hard_float": True,
            "image_bytes": image_size, "allocated_end": max(s["address"] + s["size"] for s in allocated),
            "reserved_stack_start": 0x208000, "sections": allocated,
            "required_symbols": {s: symbols[s] for s in required}, "hardware_tested": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elf", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args.elf, args.image)
    text = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
