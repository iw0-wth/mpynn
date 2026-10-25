# SPDX-License-Identifier: MIT
"""Explicit inference/timing with a user's model and ulab ndarray inputs.

Importing this module does not load a model, change switches, or read logs.
VC4 selection permits offload; supported operators and runtime dispatch gates
still decide whether the QPU is used. See README.md for REPL examples.
"""


def _arguments(inputs, warmup, repeat, arena_size, backend):
    if backend not in ('reference', 'vc4'):
        raise ValueError("backend must be 'reference' or 'vc4'")
    if not isinstance(warmup, int) or warmup < 0:
        raise ValueError('warmup must be a nonnegative integer')
    if not isinstance(repeat, int) or repeat < 1:
        raise ValueError('repeat must be a positive integer')
    if not isinstance(arena_size, int) or arena_size < 1:
        raise ValueError('arena_size must be a positive integer')
    tensors = list(inputs) if isinstance(inputs, (list, tuple)) else [inputs]
    if not tensors or any(not hasattr(x, 'shape') or not hasattr(x, 'dtype') for x in tensors):
        raise TypeError('inputs must be an ndarray or a list/tuple of ndarrays')
    return tensors


def _rearm(machine, rearm):
    if rearm:
        if not hasattr(machine, 'vc4_reset_diagnostics'):
            raise ValueError('diagnostic rearm unavailable; update firmware or use rearm=False')
        machine.vc4_reset_diagnostics()
        print('VC4 diagnostic samples rearmed (retained logs are not cleared).')


def snapshot(limit=16384):
    """Print and return one non-consuming retained log snapshot, when supported."""
    import machine
    if not isinstance(limit, int) or not 1 <= limit <= 16384:
        raise ValueError('limit must be 1..16384')
    if not hasattr(machine, 'logs'):
        print('Retained runtime log snapshot unavailable on this firmware.')
        return None
    try:
        data = machine.logs(clear=False, limit=limit)
    except TypeError:
        # Legacy no-argument logs() consumes data. Never use that fallback here.
        print('Non-consuming log snapshot unavailable; update firmware to retain evidence.')
        return None
    print('Retained runtime logs (may include earlier runs):')
    print(data)
    return data


def _execute(model_path, tensors, backend, arena_size, warmup, repeat):
    import gc
    import time
    import machine
    from ml import Model

    switch = getattr(machine, 'vc4', None)
    if switch is None and backend == 'vc4':
        raise ValueError('VC4 backend control unavailable on this firmware')
    previous = switch() if switch is not None else None
    model = None
    try:
        # Select before Prepare as well as Invoke. Each call constructs its own
        # model so persistent weights follow the requested backend.
        if switch is not None:
            switch(backend == 'vc4')
        model = Model(model_path, arena_size=arena_size, backend=backend)
        print('model:', model_path, 'backend:', backend)
        print('input:', model.input_shape, model.input_dtype)
        print('output:', model.output_shape, model.output_dtype)
        if len(tensors) != len(model.input_shape):
            raise ValueError('number of input ndarrays does not match model')
        for tensor, shape in zip(tensors, model.input_shape):
            if tuple(tensor.shape) != tuple(shape):
                raise ValueError('input ndarray shape does not match model')
        for _ in range(warmup):
            model.predict(tensors)
        start = time.ticks_us()
        outputs = None
        for _ in range(repeat):
            outputs = model.predict(tensors)
        elapsed_us = time.ticks_diff(time.ticks_us(), start)
        # Native predict returns owned ndarrays; they remain usable after deinit.
        result = {'backend': backend, 'outputs': outputs, 'warmup': warmup,
                  'repeat': repeat, 'total_us': elapsed_us,
                  'avg_us': elapsed_us / float(repeat)}
        print('warmup:', warmup, 'repeat:', repeat,
              'total_us:', elapsed_us, 'avg_us:', result['avg_us'])
        print('outputs:', outputs)
        return result
    finally:
        try:
            if model is not None:
                model.deinit()
        finally:
            try:
                if switch is not None:
                    switch(previous)
            finally:
                gc.collect()


def run(model_path, inputs, backend='vc4', arena_size=2 * 1024 * 1024,
        warmup=1, repeat=5, diagnostics=True, rearm=False):
    """Return owned outputs and predict-only timings; always restore machine.vc4.

    inputs is an ulab ndarray, or one ndarray per input in a list/tuple. Shapes
    and dtypes must match the model. rearm=True explicitly rearms bounded VC4
    diagnostic samples before loading; diagnostics=True snapshots logs once.
    """
    import machine
    tensors = _arguments(inputs, warmup, repeat, arena_size, backend)
    _rearm(machine, rearm)
    try:
        return _execute(model_path, tensors, backend, arena_size, warmup, repeat)
    finally:
        if diagnostics:
            snapshot()


def compare(model_path, inputs, arena_size=2 * 1024 * 1024,
            warmup=1, repeat=5, diagnostics=True, rearm=False):
    """Run reference then VC4 with the same ndarrays, returning both results.

    Outputs are displayed for the user's comparison; there is no fixed golden
    or automatic accuracy verdict. Logs are snapshotted once after both runs.
    """
    import machine
    tensors = _arguments(inputs, warmup, repeat, arena_size, 'reference')
    _rearm(machine, rearm)
    try:
        reference = _execute(model_path, tensors, 'reference', arena_size, warmup, repeat)
        accelerated = _execute(model_path, tensors, 'vc4', arena_size, warmup, repeat)
        vc4_us = accelerated['total_us']
        speedup = reference['total_us'] / float(vc4_us) if vc4_us > 0 else None
        print('observed reference/vc4 time ratio:', speedup)
        print('VC4 allowed does not prove QPU dispatch; inspect runtime logs.')
        return {'reference': reference, 'vc4': accelerated, 'speedup': speedup}
    finally:
        if diagnostics:
            snapshot()
