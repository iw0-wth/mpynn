"""Same-image CPU-reference vs VC4 A/B benchmark for 128x4096 FP32 FC.

Place vc4_fc_128x4096.tflite and this script on the SD root. The run toggles the
TFLM offload switch, destroys/recreates the model so Prepare observes each mode,
and keeps the board, clocks, input, and arena identical.
"""
import gc
import time
import machine
from ml import Model

MODEL = "/vc4_fc_128x4096.tflite"
INPUTS = [0.25, -0.5, 0.125, 1.0, -0.75, 0.375, 0.625, -0.25] + [0.0] * 4088
OUTPUT_DEPTH = 128
WARMUP = 5
REPEAT = 100
ARENA = 8 * 1024 * 1024


def run_mode(enabled):
    print("setting machine.vc4:", enabled)
    print("machine.vc4 result:", machine.vc4(enabled))
    model = Model(MODEL, arena_size=ARENA)
    if model.input_shape != ((1, 4096),) or model.output_shape != ((1, 128),):
        raise RuntimeError("unexpected FC benchmark model shape")
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
    avg = elapsed / float(REPEAT)
    mmacs = (4096 * OUTPUT_DEPTH * REPEAT) / float(max(1, elapsed)) / 1000.0
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
    print("require runtime log 'first FP32 FC QPU dispatch complete' for QPU proof")
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
