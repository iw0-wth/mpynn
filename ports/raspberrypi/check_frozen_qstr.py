#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check linked ARM ELF QSTR pools against the generated header and frozen IDs.

No third-party dependencies. This is a static ABI check, not VM execution.
"""
import argparse
import ast
import json
from pathlib import Path
import re
import struct


class Elf32:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if self.data[:7] != b'\x7fELF\x01\x01\x01':
            raise ValueError('expected ELF32 little endian')
        header = struct.unpack_from('<16sHHIIIIIHHHHHH', self.data)
        shoff, entsize, count = header[6], header[11], header[12]
        if entsize != 40:
            raise ValueError('invalid ELF section entry size')
        sections = [struct.unpack_from('<IIIIIIIIII', self.data, shoff+i*entsize)
                    for i in range(count)]
        self.load = [(s[3], s[3]+s[5], s[4]) for s in sections if s[2]&2 and s[1]!=8]
        self.symbols = {}
        for section in sections:
            if section[1] != 2:
                continue
            table = sections[section[6]]
            strings = self.data[table[4]:table[4]+table[5]]
            for pos in range(section[4], section[4]+section[5], section[9]):
                name, value, size, info, other, index = struct.unpack_from('<IIIBBH', self.data, pos)
                if name and index:
                    label = strings[name:strings.index(b'\0', name)].decode('ascii')
                    self.symbols[label] = (value, size)

    def read(self, address, count):
        for start, end, offset in self.load:
            if start <= address and address+count <= end:
                begin = offset+address-start
                return self.data[begin:begin+count]
        raise ValueError('unmapped ELF address %#x (%u bytes)' % (address, count))

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def string(self, address):
        for start, end, offset in self.load:
            if start <= address < end:
                begin = offset+address-start
                top = offset+end-start
                return self.data[begin:self.data.index(b'\0', begin, top)]
        raise ValueError('unmapped QSTR string address %#x' % address)

    def pool(self, name):
        if name not in self.symbols:
            raise ValueError('missing QSTR pool: '+name)
        address, size = self.symbols[name]
        # ARM32 qstr_pool_t has packed total_prev_len/is_sorted then alloc,len.
        base, count = self.u32(address+4)&0x7fffffff, self.u32(address+12)
        pointer_offset = size-count*4
        if pointer_offset not in (20, 24) or count > 65535:
            raise ValueError('invalid ARM32 QSTR pool layout: '+name)
        strings = [self.string(self.u32(address+pointer_offset+i*4)) for i in range(count)]
        return base, strings


def header_strings(path):
    result = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'QDEF([01])\((MP_QSTR[^,]*),\s*\d+,\s*(\d+),\s*(".*")\)', line)
        if match:
            # Generated literals are ASCII with escaped bytes. latin1 preserves
            # \xNN payloads instead of re-encoding them into UTF-8.
            value = ast.literal_eval(match[4]).encode('latin1')
            if len(value) != int(match[3]):
                raise ValueError('invalid generated QSTR literal: '+match[2])
            result.append((match[1], match[2], value))
    if not result or result[0][1] != 'MP_QSTRnull':
        raise ValueError('invalid generated QSTR header')
    return result


def verify_frozen_qstr(elf_path, qstr_header):
    elf = Elf32(elf_path)
    names = ('mp_qstr_const_pool_static', 'mp_qstr_const_pool', 'mp_qstr_frozen_const_pool')
    pools = [elf.pool(name) for name in names]
    total = 0
    for name, (base, strings) in zip(names, pools):
        if base != total:
            raise ValueError('QSTR ABI mismatch: %s starts at %u, linked preceding pools end at %u'
                             % (name, base, total))
        total += len(strings)
    definitions = header_strings(qstr_header)
    for kind, pool in [('0', pools[0]), ('1', pools[1])]:
        expected = [value for group, name, value in definitions if group == kind]
        if len(expected) != len(pool[1]):
            raise ValueError('QSTR ABI mismatch: generated group '+kind+' count differs from ELF')
        for index, (want, got) in enumerate(zip(expected, pool[1])):
            if want != got:
                raise ValueError('QSTR ABI mismatch at id %u: header %r, ELF %r'
                                 % (pool[0]+index, want, got))
    tables = 0
    for name, (address, size) in elf.symbols.items():
        if name.startswith('const_qstr_table_data_'):
            if size % 2:
                raise ValueError('invalid frozen QSTR table size')
            ids = struct.unpack('<%uH' % (size//2), elf.read(address, size))
            if any(q >= total for q in ids):
                raise ValueError('frozen QSTR reference out of range: '+name)
            tables += 1
    return {'verification': 'linked-qstr-static', 'constant_qstrs': pools[2][0],
            'frozen_qstrs': len(pools[2][1]), 'frozen_tables_checked': tables,
            'hardware_tested': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('qstr_header', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_frozen_qstr(args.elf, args.qstr_header), indent=2))
