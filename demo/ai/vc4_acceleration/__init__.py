# SPDX-License-Identifier: MIT
"""Ready-to-run dense feature scoring demo: CPU vs real VC4 dispatch.

Import is inert. Copy this package with model.tflite and reference.json to SD,
then call run(). No development test files or desktop packages are imported.
"""

_MODEL_SHA256 = '347fa1d32843d9d269fcd4691be377170562eb358328ebf001ffa04df918ef74'
_INPUTS = 2048
_OUTPUTS = 1024
_TOLERANCE = 1e-4


def _directory():
    return __file__.replace('\\', '/').rsplit('/', 1)[0]


def _load(directory):
    import json
    with open(directory + '/reference.json', 'r') as stream:
        ref = json.load(stream)
    if (ref.get('schema') != 1 or ref.get('input_depth') != _INPUTS or
            ref.get('output_depth') != _OUTPUTS or
            ref.get('model_sha256') != _MODEL_SHA256 or
            len(ref.get('inputs', ())) != _INPUTS or
            len(ref.get('expected', ())) != _OUTPUTS or
            len(ref.get('expected_negated', ())) != _OUTPUTS):
        raise ValueError('Unexpected demo model/reference; copy the complete demo directory')
    return ref


def _error(output, expected):
    if tuple(output.shape) != (1, _OUTPUTS):
        raise ValueError('Unexpected scoring output shape')
    maximum = 0.0
    for row in range(_OUTPUTS):
        target = float(expected[row])
        value = float(output[0, row])
        if not abs(target) < float('inf'):
            raise ValueError('Nonfinite demo reference')
        delta = abs(value - target)
        # NaN also fails this comparison. Tolerance is fixed by the program.
        if not delta <= _TOLERANCE + _TOLERANCE * abs(target):
            raise ValueError('Score mismatch/nonfinite at output %d' % row)
        if delta > maximum:
            maximum = delta
    return maximum


def _mode(path, ref, backend, warmup, repeat, arena_size):
    import gc
    import time
    import machine
    from ml import Model
    from ulab import numpy as np
    model = None
    previous = machine.vc4()
    try:
        # Match vc4_dense_acceptance.py: select once before Prepare, then keep
        # auto mode for the entire group instead of toggling on every predict.
        machine.vc4(backend == 'vc4')
        model = Model(path, arena_size=arena_size)
        if (model.input_shape != ((1, _INPUTS),) or
                model.output_shape != ((1, _OUTPUTS),) or
                model.input_dtype != ('f',) or model.output_dtype != ('f',)):
            raise ValueError('Demo requires the supplied FP32 dense model')
        x = np.array(ref['inputs'], dtype=np.float).reshape((1, _INPUTS))
        for _ in range(warmup):
            _error(model.predict([x])[0], ref['expected'])
        # Same whole-loop millisecond timing as the original dense acceptance.
        # Upload/Prepare, warmup, validation and printing remain outside timing.
        start = time.ticks_ms()
        last = None
        for _ in range(repeat):
            last = model.predict([x])[0]
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed <= 0:
            raise RuntimeError('Timer resolution/range insufficient; increase repeat')
        error = _error(last, ref['expected'])
        preview = [float(last[0, row]) for row in range(8)]
        x2 = np.array([-value for value in ref['inputs']], dtype=np.float).reshape((1, _INPUTS))
        changed = model.predict([x2])[0]
        changed_error = _error(changed, ref['expected_negated'])
        result = {'backend': backend, 'avg_ms': elapsed / float(repeat),
                  'max_error': error, 'changed_input_error': changed_error,
                  'scores': preview}
        print(backend, 'avg_ms:', result['avg_ms'], 'max_error:', error,
              'changed_input_error:', changed_error)
        print('first 8 scores:', preview)
        return result
    finally:
        try:
            if model is not None:
                model.deinit()
        finally:
            try:
                machine.vc4(previous)
            finally:
                gc.collect()


def _fields(line):
    result = {}
    for word in line.split():
        if b'=' in word:
            key, value = word.split(b'=', 1)
            result[key] = value
    return result


def _last_marker(data):
    markers = [line for line in data.split(b'\n') if b'VC4 diagnostics rearmed:' in line]
    return markers[-1] if markers else None


def _anchor(machine, previous_marker):
    # Retain old evidence; never use clear=True or a consuming legacy fallback.
    marker = _last_marker(machine.logs(clear=False, limit=16384))
    if marker is None or marker == previous_marker:
        raise RuntimeError('Fresh diagnostic rearm marker missing; check current firmware/log level')
    if _fields(marker).get(b'packed16') != b'1':
        raise RuntimeError('This demonstration requires packed16 firmware')
    return marker


def _dispatch_evidence(logs, marker):
    position = logs.rfind(marker)
    if position < 0:
        raise RuntimeError('Current session marker overwritten; cannot confirm fresh VC4 evidence')
    current = logs[position + len(marker):]
    summaries = [line for line in current.split(b'\n') if b'FC matvec timing:' in line]
    expected = {b'in': b'2048', b'out': b'1024', b'dispatches': b'1',
                b'multitile': b'1', b'packed16': b'1'}
    matching = [line for line in summaries
                if all(_fields(line).get(key) == value for key, value in expected.items())]
    completed = b'first FP32 FC QPU dispatch complete:' in current
    if not matching or not completed:
        raise RuntimeError('VC4 execution not confirmed: CPU fallback or missing fresh dispatch logs')
    # Show one useful completion summary, not all eight counter samples.
    print('GPU evidence:', matching[0])
    return {'confirmed': True, 'summary': matching[0]}


def run(warmup=8, repeat=30, arena_size=4 * 1024 * 1024, directory=None):
    """Compare the bundled dense model and verify fresh QPU execution.

    No filesystem writes/network operations. Preserve logs and the caller's VC4
    switch. The two model instances are destroyed sequentially to bound memory.
    """
    if not isinstance(warmup, int) or warmup < 0:
        raise ValueError('warmup must be a nonnegative integer')
    if not isinstance(repeat, int) or not 1 <= repeat <= 1000:
        raise ValueError('repeat must be 1..1000')
    if not isinstance(arena_size, int) or arena_size < 1024:
        raise ValueError('arena_size must be at least 1024')
    import machine
    for name in ('vc4', 'logs', 'vc4_reset_diagnostics'):
        if not hasattr(machine, name):
            raise RuntimeError('Current VC4 firmware with retained diagnostics is required')
    location = _directory() if directory is None else directory.rstrip('/')
    ref = _load(location)
    previous = machine.vc4()
    try:
        print('VC4 acceleration demo: dense feature scorer, 2048 -> 1024 FP32')
        if hasattr(machine, 'board_info'):
            print('board:', machine.board_info())
        if hasattr(machine, 'freq'):
            print('ARM Hz:', machine.freq())
        print('model:', location + '/model.tflite')
        print('warmup:', warmup, 'repeat:', repeat,
              '(whole-loop predict timing; backend selected once; load/upload excluded)')
        cpu = _mode(location + '/model.tflite', ref, 'reference', warmup, repeat, arena_size)
        # Rearm after CPU mode, before GPU Prepare. Anchor the retained session,
        # so old successful runs cannot masquerade as this execution's proof.
        previous_marker = _last_marker(machine.logs(clear=False, limit=16384))
        machine.vc4_reset_diagnostics()
        marker = _anchor(machine, previous_marker)
        gpu = _mode(location + '/model.tflite', ref, 'vc4', warmup, repeat, arena_size)
        logs = machine.logs(clear=False, limit=16384)
        evidence = _dispatch_evidence(logs, marker)
        speedup = cpu['avg_ms'] / gpu['avg_ms']
        print('CPU / VC4 speedup: %.3fx' % speedup)
        if speedup > 1.0:
            print('VC4 acceleration observed; both inputs and all 1024 scores match.')
        else:
            print('QPU execution confirmed, but no speedup observed on this run.')
        print('Logs retained: machine.logs()')
        return {'cpu': cpu, 'vc4': gpu, 'speedup': speedup, 'gpu_evidence': evidence}
    finally:
        machine.vc4(previous)
