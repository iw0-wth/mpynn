"""Same-image CPU-reference vs VC4 benchmark, multi-dispatch 1024x2048 FC.

Copy vc4_fc_1024x2048.tflite and this script to the SD root. This fixture uses
identity rows plus known bias; each FC spans multiple 12-QPU launches.
"""
import gc
import time
import machine
from ml import Model

MODEL = "/vc4_fc_1024x2048.tflite"
INPUTS = [0.25, -0.5, 0.125, 1.0, -0.75, 0.375, 0.625, -0.25] + [0.0] * 2040
INPUT_DEPTH = 2048
OUTPUT_DEPTH = 1024
WARMUP = 3
REPEAT = 30
ARENA = 4 * 1024 * 1024


def run_mode(enabled):
    print("setting machine.vc4:", enabled)
    print("machine.vc4 result:", machine.vc4(enabled))
    model = Model(MODEL, arena_size=ARENA)
    expected_shape = ((1, INPUT_DEPTH),)
    output_shape = ((1, OUTPUT_DEPTH),)
    if model.input_shape != expected_shape or model.output_shape != output_shape:
        raise RuntimeError("unexpected FC model shapes")
    import ulab.numpy as np
    x = np.array(INPUTS, dtype=np.float).reshape(model.input_shape[0])
    for _ in range(WARMUP):
        model.predict([x])
    start = time.ticks_ms()
    output = None
    for _ in range(REPEAT):
        output = model.predict([x])[0]
    elapsed = time.ticks_diff(time.ticks_ms(), start)
    max_error = 0.0
    for i in range(OUTPUT_DEPTH):
        delta = float(output[0][i]) - (INPUTS[i] + 0.01 * i)
        error = delta if delta >= 0.0 else -delta
        if error > max_error:
            max_error = error
    macs = INPUT_DEPTH * OUTPUT_DEPTH
    avg = elapsed / float(REPEAT)
    mmacs = (macs * REPEAT) / float(max(1, elapsed)) / 1000.0
    print("mode:", "vc4-enabled" if enabled else "cpu-reference",
          "warmup:", WARMUP, "repeat:", REPEAT,
          "total_ms:", elapsed, "avg_ms:", avg,
          "MMAC/s:", mmacs, "max_error:", max_error)
    if max_error > 1e-4:
        raise RuntimeError("benchmark output mismatch")
    model.deinit()
    del model
    gc.collect()
    return avg


def run():
    print("initial machine.vc4:", machine.vc4())
    cpu = run_mode(False)
    vc4 = run_mode(True)
    print("same-image CPU/VC4 speedup:", cpu / vc4)
    print("require dispatch-complete log and inspect dispatch_count/polls")
    if hasattr(machine, "logs"):
        try:
            print(machine.logs(clear=False, limit=16384))
        except TypeError:
            for _ in range(16):
                chunk = machine.logs()
                if not chunk:
                    break
                print(chunk)


run()
