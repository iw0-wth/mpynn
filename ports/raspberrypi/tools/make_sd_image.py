#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a deterministic, small MBR + FAT16 SD image using only Python stdlib.

No physical devices, mounting, firmware downloads or automatic card expansion.
The supplied kernel/config replace stale boot-directory copies. Optional extra
files are copied to the FAT root; collisions with boot files are rejected.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile

SECTOR = 512
START_LBA = 2048
REQUIRED = ('bootcode.bin', 'start.elf', 'fixup.dat', 'LICENCE.broadcom')


class Node:
    def __init__(self, name, source=None, directory=False):
        self.name, self.source, self.directory = name, source, directory
        self.children = []
        self.data = b''
        self.cluster = 0
        self.count = 0
        self.short = b''


def safe_name(name):
    if (not name or name in ('.', '..') or name[-1] in ' .' or
            any(ord(c) < 32 or c in '\\/:*?"<>|' for c in name) or
            len(name.encode('utf-16le')) // 2 > 255):
        raise ValueError('invalid FAT filename: ' + repr(name))


def regular(path, directory=False):
    if path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)()):
        raise ValueError('linked input/output is not allowed: ' + str(path))
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError('missing/invalid input: ' + str(path))
    for ancestor in path.parents:
        if ancestor.is_symlink() or bool(getattr(ancestor, 'is_junction', lambda: False)()):
            raise ValueError('linked ancestor is not allowed: ' + str(path))


def scan(directory):
    regular(directory, directory=True)
    result = []
    seen = set()
    for p in sorted(directory.iterdir(), key=lambda p: (p.name.casefold(), p.name)):
        safe_name(p.name)
        if p.name.casefold() in seen:
            raise ValueError('case-insensitive filename collision: ' + p.name)
        seen.add(p.name.casefold())
        if p.name in ('.git', '__pycache__', '.pytest_cache'):
            continue
        regular(p, directory=p.is_dir())
        node = Node(p.name, p, p.is_dir())
        if node.directory:
            node.children = scan(p)
        result.append(node)
    return result


def merge(target, added):
    for node in added:
        found = next((n for n in target if n.name.casefold() == node.name.casefold()), None)
        if found is not None:
            if found.directory and node.directory:
                merge(found.children, node.children)
            else:
                raise ValueError('extra file collides with boot content: ' + node.name)
        else:
            target.append(node)
    target.sort(key=lambda n: (n.name.casefold(), n.name))


def walk(nodes, prefix=''):
    for node in nodes:
        name = prefix + node.name
        yield name, node
        if node.directory:
            yield from walk(node.children, name + '/')


def short_names(nodes):
    used = set()
    for node in nodes:
        # Always emit a long-name entry, preserving case and Unicode. Its short
        # alias remains legal for early boot firmware's case-insensitive lookup.
        base, dot, ext = node.name.rpartition('.')
        if not dot or not base:
            base, ext = node.name, ''
        clean = lambda s: ''.join(c for c in s.upper() if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$~!#%&-{}()@`\'')
        base, ext = clean(base) or 'FILE', clean(ext)[:3]
        alias = base[:8].ljust(8) + ext.ljust(3)
        number = 1
        while alias in used:
            tail = '~' + str(number)
            alias = (base[:8-len(tail)] + tail).ljust(8) + ext.ljust(3)
            number += 1
        node.short = alias.encode('ascii')
        used.add(alias)
        if node.directory:
            short_names(node.children)


def checksum(short):
    value = 0
    for b in short:
        value = (((value & 1) << 7) + (value >> 1) + b) & 255
    return value


def lfn(node):
    units = list(struct.unpack('<%uH' % (len(node.name.encode('utf-16le'))//2),
                               node.name.encode('utf-16le')))
    # A name of exactly 13*n code units fills the last slot without terminator.
    if len(units) % 13:
        units.append(0)
        units += [0xffff] * ((-len(units)) % 13)
    result = bytearray()
    count = len(units)//13
    for index in range(count, 0, -1):
        entry = bytearray(32)
        entry[0] = index | (0x40 if index == count else 0)
        entry[11:14] = bytes((0x0f, 0, checksum(node.short)))
        chunk = units[(index-1)*13:index*13]
        for offset, values in ((1, chunk[:5]), (14, chunk[5:11]), (28, chunk[11:])):
            struct.pack_into('<%uH' % len(values), entry, offset, *values)
        result += entry
    return result


def entry(short, directory, cluster, size):
    data = bytearray(32)
    data[:11] = short
    data[11] = 0x10 if directory else 0x20
    # Fixed 1980-01-01 00:00, independent of locale, wall clock and source mtimes.
    for offset in (16, 18, 24):
        struct.pack_into('<H', data, offset, 0x21)
    struct.pack_into('<H', data, 26, cluster)
    struct.pack_into('<I', data, 28, size)
    return data


def directory_data(nodes, own=0, parent=0, root=False):
    data = bytearray()
    if not root:
        data += entry(b'.          ', True, own, 0)
        data += entry(b'..         ', True, parent, 0)
    for node in nodes:
        data += lfn(node)
        data += entry(node.short, node.directory, node.cluster,
                      0 if node.directory else len(node.data))
    data += bytes(32)  # directory terminator
    return data


def geometry(mib):
    if not 16 <= mib <= 2048:
        raise ValueError('partition-mib must be 16..2048 (small FAT16 volume)')
    total = mib * 1024 * 1024 // SECTOR
    for spc in (8, 16, 32, 64, 128, 4, 2, 1):
        fatsz = 1
        for _ in range(32):
            clusters = (total - 1 - 32 - 2*fatsz)//spc
            needed = ((clusters+2)*2 + SECTOR-1)//SECTOR
            if needed <= fatsz:
                if 4085 <= clusters <= 65524:
                    return total, spc, fatsz, clusters
                break
            fatsz = needed
    raise ValueError('partition cannot be represented as FAT16')


def build(boot_dir, kernel, config, output, partition_mib=128, extra_dir=None, report=None, demo_dir=None):
    boot_dir, kernel, config, output = map(lambda p: Path(p).absolute(),
                                          (boot_dir, kernel, config, output))
    if output.suffix.lower() != '.img':
        raise ValueError('output must be a regular .img file, not a device')
    if output.exists():
        regular(output)
    for path in (kernel, config):
        regular(path)
    nodes = scan(boot_dir)
    for required in REQUIRED:
        match = [n for n in nodes if n.name.casefold() == required.casefold()]
        if len(match) != 1 or match[0].directory:
            raise ValueError('boot directory requires ' + required)
    nodes = [n for n in nodes if n.name.casefold() not in ('kernel.img', 'config.txt')]
    nodes += [Node('kernel.img', kernel), Node('config.txt', config)]
    extras = Path(extra_dir).absolute() if extra_dir is not None else None
    demos = Path(demo_dir).absolute() if demo_dir is not None else None
    if demos is not None:
        demo_node = Node('demo', demos, True)
        demo_node.children = scan(demos)
        merge(nodes, [demo_node])
    if extras is not None:
        merge(nodes, scan(extras))
    nodes.sort(key=lambda n: (n.name.casefold(), n.name))
    # Do not overwrite or create outputs within an input tree. Reject device
    # aliases/symlinked paths and collisions before publishing anything.
    inputs = [boot_dir, kernel, config] + ([extras] if extras else []) + ([demos] if demos else [])
    resolved_output = output.resolve()
    for p in inputs:
        resolved_input = p.resolve()
        if resolved_output == resolved_input or (p.is_dir() and resolved_output.is_relative_to(resolved_input)):
            raise ValueError('output would overwrite input content')
    report_path = Path(report).absolute() if report is not None else output.with_suffix('.json')
    for p in inputs + [output]:
        resolved_input = p.resolve()
        if report_path.resolve() == resolved_input or (p.is_dir() and report_path.resolve().is_relative_to(resolved_input)):
            raise ValueError('report would overwrite input/image')
    if report_path.suffix.lower() != '.json':
        raise ValueError('report must be a regular .json file, not a device')
    if report_path.exists():
        regular(report_path)
    for candidate in (output.parent, report_path.parent):
        # Walk even currently missing parent paths to reject linked ancestors
        # before allocating/publishing the image.
        for ancestor in (candidate, *candidate.parents):
            if ancestor.is_symlink() or bool(getattr(ancestor, 'is_junction', lambda: False)()):
                raise ValueError('linked output ancestor is not allowed: ' + str(ancestor))
    total, spc, fatsz, clusters = geometry(partition_mib)
    cluster_bytes = spc * SECTOR
    short_names(nodes)
    # Validate lengths before reading model/file payloads into host memory.
    file_size = sum(n.source.stat().st_size for _, n in walk(nodes) if not n.directory)
    if file_size > clusters*cluster_bytes:
        raise ValueError('input files exceed FAT16 partition capacity')
    for _, n in walk(nodes):
        if not n.directory:
            if n.source.stat().st_size > 0xffffffff:
                raise ValueError('FAT file is too large')
            n.data = n.source.read_bytes()
    next_cluster = 2
    for _, n in walk(nodes):
        size = len(directory_data(n.children, 0, 0)) if n.directory else len(n.data)
        n.count = (size + cluster_bytes-1)//cluster_bytes
        n.cluster = next_cluster if n.count else 0
        next_cluster += n.count
    if next_cluster-2 > clusters:
        raise ValueError('input files/directories exceed FAT16 partition capacity')
    root = directory_data(nodes, root=True)
    if len(root) > 512*32:
        raise ValueError('too many FAT16 root directory entries')
    fat = bytearray(fatsz * SECTOR)
    struct.pack_into('<HH', fat, 0, 0xfff8, 0xffff)
    for _, n in walk(nodes):
        for i in range(n.count):
            cluster = n.cluster+i
            struct.pack_into('<H', fat, cluster*2, cluster+1 if i+1<n.count else 0xffff)
    mbr = bytearray(SECTOR)
    mbr[440:444] = bytes.fromhex('4d50594e')
    # One active, LBA FAT16 partition. Saturated CHS is informational only.
    struct.pack_into('<B3sB3sII', mbr, 446, 0x80, b'\xfe\xff\xff', 0x0e,
                     b'\xfe\xff\xff', START_LBA, total)
    mbr[510:512] = b'\x55\xaa'
    bpb = bytearray(SECTOR)
    bpb[:3], bpb[3:11] = b'\xeb\x3c\x90', b'MPYNN   '
    struct.pack_into('<HBHBHHBHHHII', bpb, 11, SECTOR, spc, 1, 2, 512,
                     total if total < 65536 else 0, 0xf8, fatsz, 63, 255,
                     START_LBA, total if total >= 65536 else 0)
    bpb[36], bpb[38] = 0x80, 0x29
    struct.pack_into('<I', bpb, 39, 0x4e4e5950)
    bpb[43:54], bpb[54:62], bpb[510:512] = b'MPYNN      ', b'FAT16   ', b'\x55\xaa'
    data_lba = START_LBA + 1 + 2*fatsz + 32
    output.parent.mkdir(parents=True, exist_ok=True)
    regular(output.parent, directory=True)
    fd, tmp_name = tempfile.mkstemp(prefix=output.stem+'-', suffix='.tmp', dir=output.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w+b') as image:
            image.truncate((START_LBA + total)*SECTOR)
            image.seek(0); image.write(mbr)
            image.seek(START_LBA*SECTOR); image.write(bpb)
            image.seek((START_LBA+1)*SECTOR); image.write(fat); image.write(fat)
            image.write(root)
            def write_nodes(children, parent=0):
                for n in children:
                    if n.count:
                        payload = directory_data(n.children,n.cluster,parent) if n.directory else n.data
                        image.seek((data_lba+(n.cluster-2)*spc)*SECTOR)
                        image.write(payload)
                    if n.directory:
                        write_nodes(n.children,n.cluster)
            write_nodes(nodes)
            image.flush(); os.fsync(image.fileno())
        digest = hashlib.sha256()
        with tmp.open('rb') as image:
            for block in iter(lambda: image.read(1024*1024), b''):
                digest.update(block)
        result = {'schema': 1, 'image_bytes': tmp.stat().st_size, 'sha256': digest.hexdigest(),
                  'partition': {'type': 'FAT16 LBA', 'start_lba': START_LBA,
                                'sectors': total, 'mib': partition_mib,
                                'cluster_bytes': cluster_bytes, 'data_clusters': clusters,
                                'free_bytes': (clusters-(next_cluster-2))*cluster_bytes},
                  'files': [{'path':name,'bytes':len(n.data),
                             'sha256':hashlib.sha256(n.data).hexdigest()}
                            for name,n in walk(nodes) if not n.directory],
                  'physical_card_written': False, 'hardware_tested': False}
        # Atomic image publication; incomplete builds never replace an old image.
        os.replace(tmp, output)
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_fd, report_tmp_name = tempfile.mkstemp(prefix=report_path.stem+'-', suffix='.tmp', dir=report_path.parent)
        report_tmp = Path(report_tmp_name)
        try:
            # Replace the directory entry rather than writing through a possible
            # pre-existing hard link to an input file.
            with os.fdopen(report_fd, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(result,indent=2)+'\n')
                stream.flush(); os.fsync(stream.fileno())
            os.replace(report_tmp, report_path)
        finally:
            if report_tmp.exists():
                report_tmp.unlink()  # exact mkstemp file from this call
        return result
    finally:
        if tmp.exists():
            # Exact temporary path created by mkstemp in this call only.
            tmp.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-dir', required=True, type=Path)
    parser.add_argument('--kernel', type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-inputs', action='store_true')
    parser.add_argument('--partition-mib', type=int, default=128)
    parser.add_argument('--extra-dir', type=Path)
    parser.add_argument('--demo-dir', type=Path, help='copy this folder as /demo, without running it')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.check_inputs:
        regular(args.boot_dir, directory=True)
        regular(args.config)
        for name in REQUIRED:
            regular(args.boot_dir/name)
        print('SD boot firmware/config inputs available')
        raise SystemExit(0)
    if args.kernel is None or args.output is None:
        parser.error('--kernel and --output are required when creating an image')
    result = build(args.boot_dir,args.kernel,args.config,args.output,args.partition_mib,args.extra_dir,args.report,args.demo_dir)
    print('SD image:',args.output, '| partition:',args.partition_mib,'MiB FAT16')
    print('SHA256:',result['sha256'],'| free bytes:',result['partition']['free_bytes'])
