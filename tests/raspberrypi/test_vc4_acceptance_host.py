"""Exercise the board runner's rejection paths without pretending to run a QPU."""
from pathlib import Path
import ast
import runpy
import sys
import types
from unittest.mock import patch

import pytest

PORT = Path(__file__).resolve().parents[2] / 'ports' / 'raspberrypi'


@pytest.fixture
def runner():
    machine = types.ModuleType('machine')
    ml = types.ModuleType('ml')
    ml.Model = object
    with patch.dict(sys.modules, machine=machine, ml=ml):
        yield runpy.run_path(str(PORT / 'vc4_multitile_acceptance_1024x2048.py'),
                             run_name='acceptance_host')


SUMMARY = b'vc4: FC matvec timing: in=2048 out=1024 dispatches=1 multitile=1\n'
PERF = (
    b'vc4: V3D perf: qpus=12 elapsed_us=109000 completed=1 idle=10 exec=123 tmu_wait=500 scoreboard_wait=0\n'
    b'vc4: V3D perf cache: inst_hit=10 inst_miss=2 uniform_hit=20 uniform_miss=1 tex_quads=100 tex_miss=40\n'
    b'vc4: V3D perf memory: vdw_stall=1 vcd_stall=0 l2_hit=15 l2_miss=30\n'
)


def test_all_fixture_input_rows_are_nonzero_and_distinct(runner):
    x = runner['INPUTS']
    assert len(x) == len(set(x)) == 2048
    assert all(v != 0 for v in x)
    y = [[x[i] + 0.01 * i for i in range(1024)]]
    assert runner['validate_output'](y, x) == 0
    with pytest.raises(RuntimeError, match='mismatch'):
        runner['validate_output']([[0.01 * i for i in range(1024)]], x)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_output_is_rejected(runner, value):
    x = runner['INPUTS']
    y = [[x[i] + 0.01 * i for i in range(1024)]]
    y[0][991] = value
    with pytest.raises(RuntimeError, match='row 991'):
        runner['validate_output'](y, x)


@pytest.mark.parametrize('logs', [
    SUMMARY.replace(b'dispatches=1', b'dispatches=10'),
    b'vc4: FC matvec timing: in=2048 out=1024 dispatches=6\nother multitile=1\n',
    SUMMARY.replace(b'out=1024', b'out=192'),
])
def test_summary_requires_exact_fields_on_same_line(runner, logs):
    with pytest.raises(RuntimeError, match='summary missing'):
        runner['validate_logs'](logs)


def test_complete_counters_and_summary_are_accepted(runner):
    assert runner['validate_logs'](SUMMARY + PERF, True) == (1, 1)
    assert runner['validate_logs'](SUMMARY, False) == (1, 0)


@pytest.mark.parametrize('perf', [b'', PERF.split(b'V3D perf memory:')[0],
                                 PERF.replace(b'exec=123', b'exec=0'),
                                 PERF.replace(b'completed=1', b'completed=0')])
def test_missing_invalid_or_zero_counters_are_rejected(runner, perf):
    with pytest.raises(RuntimeError):
        runner['validate_logs'](SUMMARY + perf, True)


def test_packed_marker_must_be_in_matching_summary(runner):
    with pytest.raises(RuntimeError):
        runner['validate_logs'](SUMMARY + PERF + b'upload packed16=1\n', True, True)
    packed = SUMMARY.replace(b'multitile=1', b'multitile=1 packed16=1')
    assert runner['validate_logs'](packed + PERF, True, True) == (1, 1)


def test_model_is_released_on_shape_error(runner):
    released = []
    model = types.SimpleNamespace(input_shape=((1, 7),), output_shape=((1, 1024),),
                                  deinit=lambda: released.append(True))
    g = runner['run_mode'].__globals__
    g['machine'].vc4 = lambda value: value
    g['Model'] = lambda *args, **kwargs: model
    with pytest.raises(RuntimeError, match='shapes'):
        runner['run_mode'](True)
    assert released == [True]


def test_log_snapshot_is_single_and_preserved_until_explicit_clear(runner):
    machine = runner['read_logs'].__globals__['machine']
    retained = b'complete evidence\n' * 700
    state = {'data': retained}
    calls = []

    def logs(*, clear=False, limit=16384):
        calls.append((clear, limit))
        result = state['data'][:limit]
        if clear:
            state['data'] = state['data'][limit:]
        return result

    machine.logs = logs
    assert runner['read_logs']() == retained
    assert calls == [(False, 16384)]
    assert machine.logs() == retained  # manual inspection after the runner
    assert runner['read_logs'](clear=True) == retained
    assert state['data'] == b''
    assert calls[-1] == (True, 16384)


@pytest.mark.parametrize('never_empty', [False, True])
def test_log_reader_legacy_fallback_is_bounded(runner, never_empty):
    machine = runner['read_logs'].__globals__['machine']
    chunks = iter([b'one', bytearray(b'two'), b''])
    calls = []

    def logs(*args, **kwargs):
        calls.append(kwargs)
        if kwargs:
            raise TypeError('legacy takes no keywords')
        return b'x' if never_empty else next(chunks)

    machine.logs = logs
    assert runner['read_logs']() == (b'x' * 32 if never_empty else b'onetwo')
    assert calls == [{'clear': False, 'limit': 16384}] + [{}] * (32 if never_empty else 3)


def test_run_clears_old_evidence_and_retains_fresh_logs(runner):
    g = runner['run'].__globals__
    stale = SUMMARY.replace(b'dispatches=1', b'dispatches=10')
    fresh = SUMMARY + PERF
    state = {'enabled': False, 'data': b'ARM 700 MHz, CORE 250 MHz\n' + stale}
    calls = []

    def vc4(value=None):
        if value is not None:
            state['enabled'] = value
        return state['enabled']

    def logs(*, clear=False, limit=16384):
        calls.append((clear, limit))
        result = state['data'][:limit]
        if clear:
            state['data'] = state['data'][limit:]
        return result

    def mode(enabled):
        if enabled:
            assert state['data'] == b''
            state['data'] = fresh
        return 10.0

    g['machine'].vc4 = vc4
    g['machine'].freq = lambda: 700000000
    g['machine'].logs = logs
    g['run_mode'] = mode
    runner['run'](require_counters=True)
    assert calls == [(True, 16384), (False, 16384)]
    assert g['machine'].logs() == fresh
    assert state['enabled'] is False


LOG_TAILS = [
    ('vc4_ab_switch_bench_128x4096.py', 16),
    ('vc4_ab_switch_bench_1024x2048.py', 16),
    ('vc4_ab_switch_bench_192x2048.py', 16),
    ('vc4_hw_smoke.py', 8),
    ('vc4_hw_smoke_32x1024.py', 16),
    ('vc4_switch_bench.py', 16),
]


@pytest.mark.parametrize('filename,bound', LOG_TAILS)
@pytest.mark.parametrize('firmware', ['snapshot', 'legacy', 'legacy_never_empty'])
def test_standalone_log_tail_retains_snapshot_or_bounds_legacy(filename, bound, firmware):
    # Execute the real log-reading statement without simulating model inference.
    path = PORT / filename
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    tails = [node for node in ast.walk(tree) if isinstance(node, ast.Try)
             and any(isinstance(handler.type, ast.Name) and handler.type.id == 'TypeError'
                     for handler in node.handlers)]
    assert len(tails) == 1
    statement = ast.Module(body=tails, type_ignores=[])
    evidence = b'complete evidence\n' * 700
    state = {'data': evidence, 'reads': 0}
    calls, printed = [], []

    def logs(*args, **kwargs):
        calls.append(kwargs)
        if firmware == 'snapshot':
            clear = kwargs.get('clear', False)
            limit = kwargs.get('limit', 16384)
        else:
            if kwargs:
                raise TypeError('legacy takes no keywords')
            state['reads'] += 1
            if firmware == 'legacy_never_empty':
                return b'x'
            clear, limit = True, 1024
        result = state['data'][:limit]
        if clear:
            state['data'] = state['data'][limit:]
        return result

    machine = types.SimpleNamespace(logs=logs)
    exec(compile(statement, str(path), 'exec'), {'machine': machine, 'print': printed.append})
    assert calls[0] == {'clear': False, 'limit': 16384}
    if firmware == 'snapshot':
        assert calls == [{'clear': False, 'limit': 16384}]
        assert printed == [evidence]
        assert machine.logs() == evidence
    elif firmware == 'legacy_never_empty':
        assert state['reads'] == bound
        assert printed == [b'x'] * bound
    else:
        assert b''.join(printed) == evidence[:bound * 1024]
        assert 1 <= state['reads'] <= bound
