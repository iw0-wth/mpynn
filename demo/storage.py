# SPDX-License-Identifier: MIT
"""独立 SD 文件演示；write=True 才写盘。绝不格式化或覆盖已有文件。

from demo import storage
storage.inspect()
storage.roundtrip(write=True)  # 已备份 SD 卡后执行；读回并删除自己创建的文件
storage.prepare(write=True)    # 留下文件用于冷启动验证
# 完全断电、重新上电后再调用：
storage.verify_after_reboot()  # 只读，不自动删除
storage.cleanup(confirm=True) # 核对内容后删除演示文件
"""
PATH = '/__mpynn_demo_persist__.bin'
PAYLOAD = b'mpynn SD persistence demo\x00\xff\r\n' + bytes(range(256)) * 4


def inspect():
    import machine
    import os
    print('Board/build:', machine.board_info())
    print('Storage:', machine.storage_info())
    print('Root:', os.listdir('/'))
    print('statvfs:', os.statvfs('/'))


def _readback():
    with open(PATH, 'rb') as file:
        observed = file.read(len(PAYLOAD) + 1)
    if observed != PAYLOAD:
        raise ValueError('Demo file is incomplete or has unexpected contents; do not delete automatically')
    return len(observed)


def _failure(stage, exc):
    import machine
    print('STORAGE_DEMO_FAILED:', stage, repr(exc))
    try:
        print('Storage failure snapshot:', machine.storage_info())
    except Exception as diagnostic_error:
        print('Snapshot unavailable:', repr(diagnostic_error))
    if hasattr(machine, 'logs'):
        try:
            for _ in range(8):
                data = machine.logs()
                if not data:
                    break
                print(data)
        except Exception as log_error:
            print('Logs unavailable:', repr(log_error))
    # No write retry, delete, sync or formatting after a failure.


def prepare(write=False):
    import os
    if write is not True:
        raise ValueError('Pass write=True explicitly after backing up the SD card')
    stage = 'exclusive create'
    try:
        with open(PATH, 'xb') as file:
            stage = 'write'
            count = file.write(PAYLOAD)
            if count != len(PAYLOAD):
                raise OSError('partial file write')
            stage = 'flush'
            file.flush()
            stage = 'close'
        stage = 'sync'
        os.sync()
        stage = 'readback'
        size = _readback()
        print('SD_WRITE_READBACK_OK:', PATH, size)
        print('Now power off safely, then cold boot and call verify_after_reboot().')
    except BaseException as exc:
        _failure(stage, exc)
        raise


def verify_after_reboot():
    size = _readback()
    print('SD_FILE_CONTENT_OK:', PATH, size)
    print('Counts as power-persistence PASS only if you actually cold-booted before this call.')


def cleanup(confirm=False):
    import os
    if confirm is not True:
        raise ValueError('Pass confirm=True explicitly to delete the verified demo file')
    _readback()  # Never remove an unknown or incomplete file.
    os.remove(PATH)
    os.sync()
    print('SD_DEMO_FILE_REMOVED')


def roundtrip(write=False):
    prepare(write=write)
    cleanup(confirm=True)
    print('SD_ROUNDTRIP_OK (does not prove cold-boot persistence)')


if __name__ == '__main__':
    print(__doc__)
