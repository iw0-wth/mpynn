"""Same-image A/B benchmark for exactly one 12-QPU 192x2048 dispatch."""
import gc
import time
import machine
from ml import Model

MODEL = "/vc4_fc_192x2048.tflite"
INPUTS = [0.25, -0.5, 0.125, 1.0, -0.75, 0.375, 0.625, -0.25] + [0.0] * 2040
REPEAT = 30
WARMUP = 3


def run_mode(enabled):
    print("setting machine.vc4:", enabled)
    print("machine.vc4 result:", machine.vc4(enabled))
    model = Model(MODEL, arena_size=4 * 1024 * 1024)
    import ulab.numpy as np
    x = np.array(INPUTS, dtype=np.float).reshape(model.input_shape[0])
    for _ in range(WARMUP):
        model.predict([x])
    start = time.ticks_ms()
    out = None
    for _ in range(REPEAT):
        out = model.predict([x])[0]
    elapsed = time.ticks_diff(time.ticks_ms(), start)
    max_error = 0.0
    for i in range(192):
        delta = float(out[0][i]) - (INPUTS[i] + 0.01 * i)
        error = delta if delta >= 0.0 else -delta
        if error > max_error:
            max_error = error
    avg = elapsed / float(REPEAT)
    print("mode:", "vc4" if enabled else "cpu",
          "total_ms:", elapsed, "avg_ms:", avg,
          "max_error:", max_error)
    if max_error > 1e-4:
        raise RuntimeError("output mismatch")
    model.deinit()
    del model
    gc.collect()
    return avg


def run():
    cpu = run_mode(False)
    vc4 = run_mode(True)
    print("single-dispatch cpu/vc4 speedup:", cpu / vc4)
    if hasattr(machine, "logs"):
        try:
            print(machine.logs(clear=False, limit=16384))
        except TypeError:
            for _ in range(16):
                line = machine.logs()
                if not line:
                    break
                print(line)


run()
