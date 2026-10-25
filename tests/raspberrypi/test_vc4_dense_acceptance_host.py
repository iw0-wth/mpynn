"""Standalone dense runner contracts; explicit stubs do not claim QPU execution."""
from pathlib import Path
import hashlib
import json
import runpy
import sys
import types
from unittest.mock import patch

import pytest

PORT = Path(__file__).resolve().parents[2] / 'ports' / 'raspberrypi'
SHA = '347fa1d32843d9d269fcd4691be377170562eb358328ebf001ffa04df918ef74'
SUMMARY = b'FC matvec timing: in=2048 out=1024 dispatches=1 multitile=1 packed16=1\n'
PERF = (b'V3D perf: completed=1 qpus=12 idle=10 exec=123 tmu_wait=500 scoreboard_wait=0\n'
        b'V3D perf cache: inst_hit=10 inst_miss=2 uniform_hit=20 uniform_miss=1 tex_quads=100 tex_miss=40\n'
        b'V3D perf memory: vdw_stall=1 vcd_stall=0 l2_hit=15 l2_miss=30\n')


@pytest.fixture
def runner():
    machine = types.ModuleType('machine')
    ml = types.ModuleType('ml')
    ml.Model = object
    # A deliberately obsolete common module must be irrelevant: no import or
    # auto-execution of it is allowed by the standalone dense runner.
    stale = types.ModuleType('vc4_multitile_acceptance_1024x2048')
    with patch.dict(sys.modules, machine=machine, ml=ml,
                    vc4_multitile_acceptance_1024x2048=stale):
        yield runpy.run_path(str(PORT/'vc4_dense_acceptance.py'), run_name='dense_host')


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 123.0])
def test_reject_invalid_dense_output(runner, bad):
    expected = [1.0]*1024
    actual = [[1.0]*1024]
    actual[0][977] = bad
    with pytest.raises(RuntimeError, match='row 977'):
        runner['validate_output'](actual, expected)
    assert runner['validate_output']([[1.0]*1024], expected) == 0


def test_exact_layout_and_complete_counter_evidence(runner):
    assert runner['validate_logs'](SUMMARY + PERF, True) == 1
    assert runner['validate_logs'](SUMMARY, True, require_counters=False) == 0
    with pytest.raises(RuntimeError, match='layout'):
        runner['validate_logs'](SUMMARY + PERF, False)
    assert runner['validate_logs'](SUMMARY.replace(b'packed16=1', b'packed16=0')+PERF, False) == 1
    with pytest.raises(RuntimeError, match='summary'):
        runner['validate_logs'](SUMMARY.replace(b'dispatches=1', b'dispatches=10')+PERF, True)
    with pytest.raises(RuntimeError, match='counter'):
        runner['validate_logs'](SUMMARY, True)
    with pytest.raises(RuntimeError, match='counter'):
        runner['validate_logs'](SUMMARY+PERF.replace(b'exec=123', b'exec=0'), True)


@pytest.mark.parametrize('phase', ['ok', 'numeric', 'reload'])
def test_standalone_run_restores_switch_without_common_module(runner, phase):
    g = runner['run'].__globals__
    state = {'enabled': False}
    def vc4(value=None):
        if value is not None:
            state['enabled'] = value
        return state['enabled']
    g['machine'].vc4 = vc4
    g['machine'].freq = lambda: 700000000
    g['load_reference'] = lambda: object()
    logs = iter([b'ARM 700 MHz, CORE 250 MHz\n', SUMMARY+PERF, b''])
    g['read_logs'] = lambda **kwargs: next(logs)
    calls = []
    def mode(enabled, ref, timed=True):
        calls.append((enabled, timed))
        vc4(enabled)
        if phase == 'numeric' and enabled:
            raise RuntimeError('numeric failure')
        if phase == 'reload' and not timed:
            raise RuntimeError('reload failure')
        return 10.0
    g['run_mode'] = mode
    if phase == 'ok':
        runner['run']()
        assert calls == [(False, True), (True, True), (True, False)]
    else:
        with pytest.raises(RuntimeError):
            runner['run']()
    assert state['enabled'] is False


@pytest.mark.parametrize('failure', ['shape', 'changed_input'])
def test_model_released_on_error(runner, failure):
    g = runner['run_mode'].__globals__
    g['machine'].vc4 = lambda enabled: enabled
    released = []
    model = types.SimpleNamespace(input_shape=((1, 2048),), output_shape=((1, 1024),),
                                  deinit=lambda: released.append(True))
    if failure == 'shape':
        model.input_shape = ((1, 7),)
    else:
        g['time'] = types.SimpleNamespace(ticks_ms=lambda: 0, ticks_diff=lambda a,b: 1)
        class Array:
            def reshape(self, shape):
                return self
        ulab = types.ModuleType('ulab')
        ulab.numpy = types.SimpleNamespace(array=lambda *a, **k: Array(), float=float)
        calls = []
        def predict(inputs):
            calls.append(True)
            return [[[1.0]*1024]] if len(calls) <= 2 else [[[float('nan')]*1024]]
        model.predict = predict
    g['Model'] = lambda *a, **k: model
    ref = {'inputs':[0.5]*2048, 'expected':[1.0]*1024, 'expected_negated':[-1.0]*1024}
    ulab_modules = ({'ulab': ulab, 'ulab.numpy': ulab.numpy} if failure != 'shape'
                    else {'ulab': types.ModuleType('ulab')})
    with patch.dict(sys.modules, ulab_modules):
        with pytest.raises(RuntimeError):
            runner['run_mode'](True, ref, timed=False)
    assert released == [True]


@pytest.mark.parametrize('packed,build_id', [
    (False, '4f43f9ba45052bd5083b4a316b1ef274c1695479100201456062fb647f8fd639'),
    (True, 'a0b9e46f3987efc4972939f2550aedfa9cdd1b8d9d6950df35046be4eca1a99f')])
def test_detected_image_rejects_wrong_explicit_layout_before_running(runner, packed, build_id):
    g = runner['run'].__globals__
    g['machine'].board_info = lambda: {'build_id': build_id}
    g['load_reference'] = lambda: pytest.fail('wrong layout should fail before model load')
    with pytest.raises(RuntimeError, match='conflicts'):
        runner['run'](require_packed=not packed)


def test_rearm_supplies_fresh_clock_evidence_on_second_run(runner):
    g = runner['run'].__globals__
    state = {'enabled': False, 'reset': 0}
    def switch(value=None):
        if value is not None:
            state['enabled'] = value
        return state['enabled']
    def reset():
        state['reset'] += 1
    g['machine'].vc4 = switch
    g['machine'].freq = lambda: 700000000
    g['machine'].vc4_reset_diagnostics = reset
    g['load_reference'] = lambda: object()
    g['run_mode'] = lambda *a, **kw: 10.0
    clock = b'VC4 diagnostics rearmed: arm_mhz=700 core_mhz=250 packed16=1 profile=1\n'
    for _ in range(2):
        logs = iter([b'', clock + SUMMARY + PERF, b''])
        g['read_logs'] = lambda **kwargs: next(logs)
        runner['run'](require_packed=True)
    assert state == {'enabled': False, 'reset': 2}


def test_snapshot_reader_preserves_bytes_and_legacy_reader_drains(runner):
    machine = runner['read_logs'].__globals__['machine']
    options = []
    def snapshot(**kwargs):
        options.append(kwargs)
        return b'retained log'
    machine.logs = snapshot
    assert runner['read_logs'](clear=False) == b'retained log'
    assert options == [{'clear': False, 'limit': 16384}]
    chunks = iter([b'one', b'two', b''])
    def legacy(*args, **kwargs):
        if kwargs:
            raise TypeError('legacy takes no keywords')
        return next(chunks)
    machine.logs = legacy
    assert runner['read_logs'](clear=False) == b'onetwo'


def test_streamed_model_hash_is_verified(runner, tmp_path):
    model = tmp_path/'model.tflite'
    model.write_bytes(b'fixture-model')
    reference = tmp_path/'reference.json'
    ref = {'schema':1, 'input_depth':2048, 'output_depth':1024,
           'model_sha256':SHA, 'inputs':[0.5]*2048, 'expected':[1.0]*1024,
           'expected_negated':[-1.0]*1024, 'absolute_tolerance':1e-4, 'relative_tolerance':1e-4}
    reference.write_text(json.dumps(ref))
    g = runner['load_reference'].__globals__
    g['MODEL'], g['REFERENCE'] = str(model), str(reference)
    with pytest.raises(RuntimeError, match='copied model SHA256'):
        runner['load_reference']()
    ref['model_sha256'] = hashlib.sha256(b'fixture-model').hexdigest()
    reference.write_text(json.dumps(ref))
    with pytest.raises(RuntimeError, match='reference model SHA256'):
        runner['load_reference']()
