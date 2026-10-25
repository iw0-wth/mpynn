# SPDX-License-Identifier: MIT
# WARNING: this test writes to the boot SD. Use a backed-up disposable card.
# Exclusive creation prevents overwriting an existing user file.
import os
import vfs

mounts = vfs.mount()
assert any(path == '/' for _, path in mounts)
print('Root entries:', os.listdir('/'))
with open('/config.txt', 'r') as f:
    config = f.read()
assert 'kernel=kernel.img' in config
# The boot SD is deliberately writable, like MCU internal flash.
with open('/__mpynn_vfs_smoke__.txt', 'x') as f:
    f.write('mpynn vfs smoke\n')
os.sync()
assert '__mpynn_vfs_smoke__.txt' in os.listdir('/')
with open('/__mpynn_vfs_smoke__.txt', 'r') as f:
    assert f.read() == 'mpynn vfs smoke\n'
os.remove('/__mpynn_vfs_smoke__.txt')
os.sync()
print('MPYNN_BOOT_VFS_READ_WRITE_SMOKE_PASS')
# Repeat after machine.soft_reset(). Also test a card with invalid FAT: startup
# must report the failure and return to REPL, never call mkfs automatically.
# Hot removal while powered is not supported/tested; do not remove a mounted card.
