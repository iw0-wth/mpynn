"""1024x2048 multi-tile board smoke/A-B; not a timeout/recovery test.

Use the identity-row FC fixture. All input columns are nonzero and distinct.
Counter-enabled firmware is checked when its perf samples are present; call
run(require_counters=True) after importing to require hardware counter evidence.
Reboot before testing, since firmware bounds its diagnostic samples.
"""
import gc
import time
import machine
from ml import Model

MODEL = "/vc4_fc_1024x2048.tflite"
INPUT_DEPTH = 2048
OUTPUT_DEPTH = 1024
INPUTS = [(((i * 37) % 2048) - 1024 + 0.5) / 1024 for i in range(INPUT_DEPTH)]
# Exclude the runtime's first eight logged samples from steady-state timing.
WARMUP = 8
REPEAT = 30
ARENA = 4 * 1024 * 1024


def validate_output(output, inputs):
    max_error = 0.0
    for i in range(OUTPUT_DEPTH):
        value = float(output[0][i])
        delta = value - (inputs[i] + 0.01 * i)
        error = delta if delta >= 0.0 else -delta
        # This comparison rejects NaN and infinities as well as large errors.
        if not error <= 1e-4:
            raise RuntimeError("output mismatch/nonfinite at row %d" % i)
        if error > max_error:
            max_error = error
    return max_error


def run_mode(enabled):
    machine.vc4(enabled)
    model = Model(MODEL, arena_size=ARENA)
    try:
        if model.input_shape != ((1, INPUT_DEPTH),) or model.output_shape != ((1, OUTPUT_DEPTH),):
            raise RuntimeError("unexpected FC model shapes")
        import ulab.numpy as np
        x = np.array(INPUTS, dtype=np.float).reshape(model.input_shape[0])
        for _ in range(WARMUP):
            validate_output(model.predict([x])[0], INPUTS)
        start = time.ticks_ms()
        output = None
        for _ in range(REPEAT):
            output = model.predict([x])[0]
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        max_error = validate_output(output, INPUTS)
        if elapsed <= 0:
            raise RuntimeError("invalid benchmark elapsed time")
        # Change every column on the same prepared model to detect stale input.
        alternate = [-v for v in INPUTS]
        x2 = np.array(alternate, dtype=np.float).reshape(model.input_shape[0])
        alternate_error = validate_output(model.predict([x2])[0], alternate)
        print("mode:", "vc4" if enabled else "cpu",
              "warmup:", WARMUP, "repeat:", REPEAT,
              "avg_ms:", elapsed / float(REPEAT),
              "max_error:", max_error, "changed_input_error:", alternate_error)
        return elapsed / float(REPEAT)
    finally:
        model.deinit()
        gc.collect()


def read_logs(clear=False):
    data = b""
    if hasattr(machine, "logs"):
        try:
            return machine.logs(clear=clear, limit=16384)
        except TypeError:
            # Legacy firmware only supports consuming reads.
            for _ in range(32):
                chunk = machine.logs()
                if not chunk:
                    break
                data += chunk if isinstance(chunk, bytes) else bytes(chunk)
    return data


def fields(line):
    result = {}
    for token in line.split():
        if b"=" in token:
            key, value = token.split(b"=", 1)
            result[key] = value
    return result


def validate_logs(logs, require_counters=False, require_packed=False):
    summaries = [fields(line) for line in logs.split(b'\n')
                 if b"FC matvec timing:" in line]
    expected = {b"in": b"2048", b"out": b"1024", b"dispatches": b"1", b"multitile": b"1"}
    if require_packed:
        expected[b"packed16"] = b"1"
    matching = [row for row in summaries
                if all(row.get(key) == value for key, value in expected.items())]
    if not matching:
        raise RuntimeError("fresh 1024x2048 dispatches=1 multitile=1 summary missing; reboot and rerun")
    perf = []
    sample = None
    for line in logs.split(b'\n'):
        if b"V3D perf: " in line:
            sample = fields(line)
        elif b"V3D perf cache: " in line and sample is not None:
            sample.update(fields(line))
        elif b"V3D perf memory: " in line and sample is not None:
            sample.update(fields(line))
            perf.append(sample)
            sample = None
    if require_counters or b"V3D perf:" in logs:
        required = (b"idle", b"exec", b"tmu_wait", b"scoreboard_wait",
                    b"inst_hit", b"inst_miss", b"uniform_hit", b"uniform_miss",
                    b"tex_quads", b"tex_miss", b"vdw_stall", b"vcd_stall", b"l2_hit", b"l2_miss")
        if not perf:
            raise RuntimeError("complete performance counter samples missing")
        for sample in perf:
            if sample.get(b"completed") != b"1" or sample.get(b"qpus") != b"12":
                raise RuntimeError("incomplete or unexpected counter dispatch")
            if not all(key in sample for key in required):
                raise RuntimeError("counter sample fields missing")
            values = [int(sample[key]) for key in required]
            if int(sample[b"exec"]) == 0 or not any(values):
                raise RuntimeError("zero exec counter; do not interpret this as measured utilization")
    return len(matching), len(perf)


def run(require_counters=False, require_packed=False):
    previous = machine.vc4()
    boot_logs = read_logs(clear=True)  # remove stale dispatch summaries before this run
    try:
        freq = machine.freq()
        print("machine.freq:", freq)
        if freq not in (700000000, (700000000, 250000000)):
            raise RuntimeError("expected ARM 700 MHz")
        if hasattr(machine, 'vc4_reset_diagnostics'):
            machine.vc4_reset_diagnostics()
        cpu_ms = run_mode(False)
        vc4_ms = run_mode(True)
        logs = read_logs()
        print("same-image speedup:", cpu_ms / vc4_ms)
        print(boot_logs)
        print(logs)
        rearmed_clock = any(fields(line).get(b'arm_mhz') == b'700' and
                             fields(line).get(b'core_mhz') == b'250'
                             for line in logs.split(b'\n') if b'VC4 diagnostics rearmed:' in line)
        if b"ARM 700 MHz, CORE 250 MHz" not in boot_logs + logs and not rearmed_clock:
            raise RuntimeError("700/250 MHz clock evidence missing; reboot and rerun")
        summaries, samples = validate_logs(logs, require_counters, require_packed)
        print("fresh summaries:", summaries, "complete counter samples:", samples)
        print("MULTITILE SMOKE: all rows, changed input and one-dispatch logs passed")
        print("Timeout/recovery, dense weights and thermal stress remain separate tests")
    finally:
        machine.vc4(previous)


if __name__ == "__main__":
    run()
