# SPDX-License-Identifier: MIT
"""Read-only board diagnostics after a failed Thonny write; does not retry writes.
Paste via UART/Thonny REPL. Output machine.logs only on explicit invocation.
"""
import sys
import os
import machine


def run():
    print('implementation:', sys.implementation)
    if hasattr(os, 'uname'):
        print('uname:', os.uname())
    else:
        print('uname: unavailable on this firmware')
    if hasattr(machine, 'board_info'):
        print('board/build:', machine.board_info())
    rtc_exported = hasattr(machine, 'RTC')
    storage_exported = hasattr(machine, 'storage_info')
    print('RTC exported:', rtc_exported)
    print('storage_info exported:', storage_exported)
    if not rtc_exported or not storage_exported:
        print('WARNING: running image predates the current mpynn diagnostic build')
    if storage_exported:
        try:
            print('storage before directory reads:', machine.storage_info())
        except Exception as exc:
            print('storage_info', repr(exc))
    card = None
    try:
        if hasattr(machine, 'SDCard'):
            card = machine.SDCard(0, readonly=True)
            print('sd block_count:', card.ioctl(4, 0))
            print('sd block_size:', card.ioctl(5, 0))
            # Read sector zero twice to detect inconsistent block reads. This
            # is strictly read-only and does not inspect/modify filesystem data.
            sector_a = bytearray(512)
            sector_b = bytearray(512)
            ret_a = card.readblocks(0, sector_a)
            ret_b = card.readblocks(0, sector_b)
            print('sector0 read returns:', ret_a, ret_b,
                  'same:', sector_a == sector_b,
                  'mbr_signature:', bytes(sector_a[510:512]))
            if sector_a[510:512] == b'\x55\xaa':
                for index in range(4):
                    off = 446 + index * 16
                    ptype = sector_a[off + 4]
                    start = int.from_bytes(sector_a[off + 8:off + 12], 'little')
                    count = int.from_bytes(sector_a[off + 12:off + 16], 'little')
                    if ptype and count:
                        boot = bytearray(512)
                        ret = card.readblocks(start, boot)
                        print('partition', index, 'type', hex(ptype),
                              'start_lba', start, 'sectors', count,
                              'boot_read', ret, 'bpb_signature',
                              bytes(boot[510:512]), 'bytes_per_sector',
                              int.from_bytes(boot[11:13], 'little'),
                              'sectors_per_cluster', boot[13],
                              'reserved_sectors', int.from_bytes(boot[14:16], 'little'),
                              'fat_count', boot[16], 'root_entries',
                              int.from_bytes(boot[17:19], 'little'),
                              'fat16_size', int.from_bytes(boot[22:24], 'little'),
                              'fat32_size', int.from_bytes(boot[36:40], 'little'),
                              'root_cluster', int.from_bytes(boot[44:48], 'little'))
    except Exception as exc:
        print('sd raw diagnostics:', repr(exc))
    for label, operation in (
        ('cwd', os.getcwd),
        ('mounts', lambda: __import__('vfs').mount()),
        ('root', lambda: os.listdir('/')),
        ('root_ilistdir', lambda: list(os.ilistdir('/'))),
        ('statvfs', lambda: os.statvfs('/')),
    ):
        try:
            print(label, operation())
        except Exception as exc:
            print(label, repr(exc))
    # Compare repeated root traversals and FAT iterator metadata. All operations
    # below are read-only; do not delete/reformat the suspicious entries.
    try:
        for attempt in range(3):
            names = os.listdir('/')
            print('root pass', attempt, 'entries', len(names),
                  'suspect count', sum(1 for name in names
                                       if name == 'USUSUSUS.usu'))
        root_names = os.listdir('/')
        suspect_count = sum(1 for name in root_names if name == 'USUSUSUS.usu')
        print('root entries:', len(root_names), 'suspect duplicate count:', suspect_count)
        print('root unique names:', len(set(root_names)))
        entries = list(os.ilistdir('/'))
        suspect_entries = [entry for entry in entries
                           if entry and entry[0] == 'USUSUSUS.usu']
        print('suspect ilistdir entries (name, type, inode, size):',
              suspect_entries)
        try:
            print('suspect stat mode/size:', os.stat('/USUSUSUS.usu')[0:7])
        except Exception as exc:
            print('suspect stat:', repr(exc))
    except Exception as exc:
        print('root duplicate summary:', repr(exc))
    suspect = '/USUSUSUS.usu'
    try:
        print('suspect stat:', suspect, os.stat(suspect))
    except Exception as exc:
        print('suspect stat:', repr(exc))
    try:
        print('suspect entries:', list(os.ilistdir(suspect)))
    except Exception as exc:
        print('suspect ilistdir:', repr(exc))
    try:
        print('suspect file open:', open(suspect, 'rb').read(32))
    except Exception as exc:
        print('suspect open:', repr(exc))
    if storage_exported:
        try:
            print('storage after directory reads:', machine.storage_info())
        except Exception as exc:
            print('storage_info_after', repr(exc))
    if hasattr(machine, 'logs'):
        for _ in range(8):
            data = machine.logs()
            if not data:
                break
            print(data)
    print('STORAGE_DIAG_DONE_NO_WRITES')


if __name__ == '__main__':
    run()
