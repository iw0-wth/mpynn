"""Regression checks on linked ELF QSTR consistency, not ARM VM execution."""
import importlib.util
from pathlib import Path
import struct
import subprocess

import pytest

MPYNN = Path(__file__).resolve().parents[2]
PORT = MPYNN/'ports/raspberrypi'
spec = importlib.util.spec_from_file_location('frozen_qstr_check', PORT/'check_frozen_qstr.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.fixture
def fixed_artifacts():
    elf = MPYNN/'build/RPI1B/packed-profile-v4/bin/kernel.elf'
    header = MPYNN/'build/RPI1B/packed-v4-clean/genhdr/qstrdefs.generated.h'
    if not elf.is_file() or not header.is_file():
        pytest.skip('fresh ARM v4 build not present')
    return elf, header


def mutate(elf, address, replacement, destination):
    parsed = checker.Elf32(elf)
    data = bytearray(parsed.data)
    for start, end, offset in parsed.load:
        if start <= address and address+len(replacement) <= end:
            begin = offset+address-start
            data[begin:begin+len(replacement)] = replacement
            destination.write_bytes(data)
            return destination
    raise AssertionError('unmapped patch address')


def test_fixed_final_elf_has_matching_qstr_pools(fixed_artifacts):
    elf, header = fixed_artifacts
    report = checker.verify_frozen_qstr(elf, header)
    assert report['frozen_tables_checked'] > 1
    assert report['hardware_tested'] is False


def test_checker_rejects_wrong_frozen_pool_boundary(fixed_artifacts, tmp_path):
    elf, header = fixed_artifacts
    parsed = checker.Elf32(elf)
    address, size = parsed.symbols['mp_qstr_frozen_const_pool']
    patched = mutate(elf, address+4, struct.pack('<I', parsed.u32(address+4)+1), tmp_path/'bad.elf')
    with pytest.raises(ValueError, match='starts at'):
        checker.verify_frozen_qstr(patched, header)


def test_checker_rejects_out_of_range_frozen_reference(fixed_artifacts, tmp_path):
    elf, header = fixed_artifacts
    parsed = checker.Elf32(elf)
    base, values = parsed.pool('mp_qstr_frozen_const_pool')
    table_name = next(name for name in parsed.symbols if name.startswith('const_qstr_table_data_'))
    table, size = parsed.symbols[table_name]
    patched = mutate(elf, table, struct.pack('<H', base+len(values)), tmp_path/'range.elf')
    with pytest.raises(ValueError, match='out of range'):
        checker.verify_frozen_qstr(patched, header)


def test_checker_does_not_enforce_module_import_semantics(fixed_artifacts, tmp_path):
    elf, header = fixed_artifacts
    parsed = checker.Elf32(elf)
    base, values = parsed.pool('mp_qstr_const_pool')
    table_name = next(name for name in parsed.symbols if name.startswith('const_qstr_table_data_'))
    table, size = parsed.symbols[table_name]
    # A valid but different ID is not an ABI range/pool violation. Semantic
    # imports are tested by executing frozen modules, not a build whitelist.
    patched = mutate(elf, table, struct.pack('<H', base), tmp_path/'valid-id.elf')
    assert checker.verify_frozen_qstr(patched, header)['hardware_tested'] is False


def test_msys_path_override_and_qstr_header_trigger_object_rebuild(fixed_artifacts):
    bash = Path('E:/msys64/usr/bin/bash.exe')
    if not bash.is_file():
        pytest.skip('MSYS unavailable')
    # Pretend only the generated QSTR header changed. Do not touch sources or
    # generated headers while testing the actual make dependency graph.
    directory = 'D:/openmv_aicore/mpynn/build/RPI1B/packed-v4-clean'
    command = (
        'export PATH=/d/anaconda3:/e/arm-none-eabi/bin:/usr/bin:$PATH; '
        'cd /d/openmv_aicore/mpynn/ports/raspberrypi; '
        'make -n -W ' + directory + '/genhdr/qstrdefs.generated.h '
        'BOARD=RPI1B PYTHON=/d/anaconda3/python.exe '
        'BUILD=/d/openmv_aicore/mpynn/build/RPI1B/packed-v4-clean '
        'VC4_MULTI_TILE=1 VC4_PACKED_WEIGHTS=1 VC4_PROFILE_COUNTERS=1 '
        + directory + '/py/qstr.o'
    )
    result = subprocess.run([str(bash), '-lc', command], cwd=PORT,
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CC ../../lib/micropython/py/qstr.c' in result.stdout
    assert '-o '+directory+'/py/qstr.o' in result.stdout


def test_original_bad_v3_is_rejected():
    bad = MPYNN/'build/RPI1B/packed-profile-v3/bin/kernel.elf'
    header = MPYNN/'build/RPI1B/multitile-experiment/genhdr/qstrdefs.generated.h'
    if not bad.is_file() or not header.is_file():
        pytest.skip('original failure artifact unavailable')
    with pytest.raises(ValueError, match='QSTR ABI mismatch'):
        checker.verify_frozen_qstr(bad, header)
