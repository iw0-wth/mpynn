"""Standalone dense FC board runner; no common benchmark module is imported.

Copy this script, the dense TFLite, and its JSON goldens to SD root. Firmware
with vc4_reset_diagnostics rearms samples per run; older firmware requires a
reboot for fresh samples. Layout auto-detects supplied image IDs or log fields;
run(require_packed=False) explicitly selects the row-major control. This is a
numeric/reload/A-B test, not timeout or thermal stress validation.
"""
import gc
import json
import time
import machine
from ml import Model

SCRIPT_VERSION = 'dense-standalone-3'
MODEL = '/vc4_fc_dense_1024x2048.tflite'
REFERENCE = '/vc4_fc_dense_1024x2048.json'
WARMUP = 8
REPEAT = 30
ARENA = 4 * 1024 * 1024


def load_reference():
    with open(REFERENCE, 'r') as source:
        ref = json.load(source)
    if (ref.get('schema') != 1 or ref.get('input_depth') != 2048 or
            ref.get('output_depth') != 1024 or len(ref.get('inputs', [])) != 2048 or
            len(ref.get('expected', [])) != 1024 or
            len(ref.get('expected_negated', [])) != 1024):
        raise RuntimeError('unexpected dense fixture schema/shape')
    if ref.get('model_sha256') != '347fa1d32843d9d269fcd4691be377170562eb358328ebf001ffa04df918ef74':
        raise RuntimeError('unexpected dense reference model SHA256')
    # Do not trust a changed JSON tolerance to turn bad outputs into a pass.
    if ref.get('absolute_tolerance') != 1e-4 or ref.get('relative_tolerance') != 1e-4:
        raise RuntimeError('unexpected dense reference tolerance')
    print('model:', MODEL, 'reference:', REFERENCE)
    print('reference model SHA256:', ref['model_sha256'])
    # hashlib is optional in this port. When present, stream rather than reading
    # another 8 MB model copy into the GC heap.
    try:
        import hashlib
        import binascii
    except ImportError:
        print('model hash: not checked on board (hashlib unavailable)')
    else:
        sha = hashlib.sha256()
        with open(MODEL, 'rb') as source:
            while True:
                chunk = source.read(4096)
                if not chunk:
                    break
                sha.update(chunk)
        actual = binascii.hexlify(sha.digest()).decode()
        if actual != ref['model_sha256']:
            raise RuntimeError('copied model SHA256 does not match reference')
        print('model hash: verified')
    return ref


def validate_output(output, expected):
    maximum = 0.0
    for row in range(1024):
        target = expected[row]
        magnitude = target if target >= 0 else -target
        if not magnitude < float('inf'):
            raise RuntimeError('invalid reference value at row %d' % row)
        delta = float(output[0][row]) - target
        error = delta if delta >= 0 else -delta
        if not error <= 1e-4 + 1e-4 * magnitude:
            raise RuntimeError('dense mismatch/nonfinite at row %d' % row)
        if error > maximum:
            maximum = error
    return maximum


def run_mode(enabled, ref, timed=True):
    machine.vc4(enabled)
    model = Model(MODEL, arena_size=ARENA)
    try:
        if model.input_shape != ((1, 2048),) or model.output_shape != ((1, 1024),):
            raise RuntimeError('unexpected dense FC model shapes')
        from ulab import numpy as np
        x = np.array(ref['inputs'], dtype=np.float).reshape((1, 2048))
        for _ in range(WARMUP if timed else 1):
            validate_output(model.predict([x])[0], ref['expected'])
        elapsed = 0
        if timed:
            start = time.ticks_ms()
            output = None
            for _ in range(REPEAT):
                output = model.predict([x])[0]
            elapsed = time.ticks_diff(time.ticks_ms(), start)
            if elapsed <= 0:
                raise RuntimeError('invalid benchmark elapsed time')
            error = validate_output(output, ref['expected'])
        else:
            error = validate_output(model.predict([x])[0], ref['expected'])
        x2 = np.array([-v for v in ref['inputs']], dtype=np.float).reshape((1, 2048))
        alternate_error = validate_output(model.predict([x2])[0], ref['expected_negated'])
        print('mode:', 'vc4' if enabled else 'cpu',
              'warmup:', WARMUP if timed else 1, 'repeat:', REPEAT if timed else 0,
              'avg_ms:', elapsed / float(REPEAT) if timed else None,
              'max_error:', error, 'changed_input_error:', alternate_error)
        return elapsed / float(REPEAT) if timed else None
    finally:
        model.deinit()
        gc.collect()


def read_logs(clear=True):
    data = b''
    if hasattr(machine, 'logs'):
        try:
            # New firmware can snapshot the entire retained ring in one call.
            return machine.logs(clear=clear, limit=16384)
        except TypeError:
            # Legacy firmware only has consuming 1024-byte reads. Do not loop
            # with peek on new firmware, since that would repeat the prefix.
            for _ in range(32):
                chunk = machine.logs()
                if not chunk:
                    break
                data += chunk if isinstance(chunk, bytes) else bytes(chunk)
    return data


def fields(line):
    result = {}
    for token in line.split():
        if b'=' in token:
            key, value = token.split(b'=', 1)
            result[key] = value
    return result


def validate_logs(logs, require_packed, require_counters=True):
    expected = {b'in': b'2048', b'out': b'1024', b'dispatches': b'1', b'multitile': b'1'}
    if require_packed is not None:
        expected[b'packed16'] = b'1' if require_packed else b'0'
    summaries = [fields(line) for line in logs.split(b'\n') if b'FC matvec timing:' in line]
    matching = [row for row in summaries if all(row.get(k) == v for k, v in expected.items())]
    if not matching or any(row.get(b'packed16') not in (b'0', b'1') for row in matching):
        raise RuntimeError('fresh dense FC summary missing or wrong layout; rearm diagnostics or reboot')
    layouts = set(row[b'packed16'] for row in matching)
    if len(layouts) != 1:
        raise RuntimeError('mixed layout evidence')
    print('observed packed16:', int(matching[0][b'packed16']))
    samples = []
    sample = None
    for line in logs.split(b'\n'):
        if b'V3D perf: ' in line:
            sample = fields(line)
        elif b'V3D perf cache: ' in line and sample is not None:
            sample.update(fields(line))
        elif b'V3D perf memory: ' in line and sample is not None:
            sample.update(fields(line))
            samples.append(sample)
            sample = None
    required = (b'idle', b'exec', b'tmu_wait', b'scoreboard_wait', b'inst_hit', b'inst_miss',
                b'uniform_hit', b'uniform_miss', b'tex_quads', b'tex_miss', b'vdw_stall',
                b'vcd_stall', b'l2_hit', b'l2_miss')
    if not samples and require_counters:
        raise RuntimeError('hardware counter samples missing; reboot with profile image')
    for sample in samples:
        if sample.get(b'completed') != b'1' or sample.get(b'qpus') != b'12':
            raise RuntimeError('incomplete/unexpected counter dispatch')
        if not all(key in sample for key in required):
            raise RuntimeError('counter sample fields missing')
        if any(int(sample[key]) < 0 for key in required) or int(sample[b'exec']) == 0:
            raise RuntimeError('invalid counter values')
    return len(samples)


def run(require_packed=None, require_counters=True):
    board = machine.board_info() if hasattr(machine, 'board_info') else {}
    # These are the same-code profile images already supplied for this test.
    known_layouts = {
        '4f43f9ba45052bd5083b4a316b1ef274c1695479100201456062fb647f8fd639': False,
        'a0b9e46f3987efc4972939f2550aedfa9cdd1b8d9d6950df35046be4eca1a99f': True,
    }
    detected = known_layouts.get(board.get('build_id'))
    if require_packed is None:
        require_packed = detected
    elif detected is not None and bool(require_packed) != detected:
        raise RuntimeError('requested layout conflicts with this image; row-major requires False')
    print('SCRIPT_VERSION:', SCRIPT_VERSION, 'expected packed16:',
          'auto from log' if require_packed is None else require_packed)
    print('board:', board)
    ref = load_reference()
    previous = machine.vc4()
    boot_logs = read_logs()
    # New firmware can rearm bounded samples without reboot. Old firmware can
    # run this compatibility script after reboot but cannot regenerate samples.
    if hasattr(machine, 'vc4_reset_diagnostics'):
        machine.vc4_reset_diagnostics()
        print('VC4 diagnostic samples: rearmed')
    else:
        print('VC4 diagnostic samples: old firmware, first run after reboot required')
    printed_logs = False
    try:
        frequency = machine.freq()
        print('machine.freq:', frequency)
        if frequency != 700000000:
            raise RuntimeError('expected ARM 700 MHz')
        cpu = run_mode(False, ref)
        vc4 = run_mode(True, ref)
        logs = read_logs(clear=False)
        print('same-image speedup:', cpu / vc4)
        print(boot_logs)
        print(logs)
        printed_logs = True
        rearmed_clock = any(
            fields(line).get(b'arm_mhz') == b'700' and
            fields(line).get(b'core_mhz') == b'250'
            for line in logs.split(b'\n') if b'VC4 diagnostics rearmed:' in line)
        if b'ARM 700 MHz, CORE 250 MHz' not in boot_logs + logs and not rearmed_clock:
            raise RuntimeError('700/250 MHz clock evidence missing; reboot and rerun')
        samples = validate_logs(logs, require_packed, require_counters)
        # These modes have destroyed their model; allocate/prepare another one.
        run_mode(True, ref, timed=False)
        print('complete counter samples:', samples)
        print('DENSE PASS: both inputs, all outputs, layout and model reload')
        if not require_counters and not samples:
            print('Performance counters disabled by request (production firmware)')
        print('Timeout/deferred-free fault injection and thermal stress were not tested')
    finally:
        try:
            # Preserve new-firmware logs for manual inspection after success.
            # If prediction failed before printing, expose the retained evidence.
            if not printed_logs:
                remaining_logs = read_logs(clear=False)
                if remaining_logs:
                    print(remaining_logs)
        finally:
            machine.vc4(previous)


if __name__ == '__main__':
    run()
