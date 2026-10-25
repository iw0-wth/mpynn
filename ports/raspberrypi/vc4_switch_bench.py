"""Compare the public machine.vc4() switch on the same FP32 FC fixture.

Copy vc4_fc_32x1024.tflite and this script to the SD root. The model must be
re-created after each switch because TFLM uploads persistent weights in Prepare.
"""
import time
import gc
import machine
from ml import Model

MODEL = "/vc4_fc_32x1024.tflite"
INPUTS = [0.25, -0.5, 0.125, 1.0, -0.75, 0.375, 0.625, -0.25] + [0.0] * 1016
WARMUP = 5
REPEAT = 100


def run_mode(enabled):
    print("set machine.vc4:", enabled, "previous:", machine.vc4())
    print("machine.vc4 returned:", machine.vc4(enabled))
    m = Model(MODEL, arena_size=2 * 1024 * 1024)
    import ulab.numpy as np
    x = np.array(INPUTS, dtype=np.float).reshape(m.input_shape[0])
    for _ in range(WARMUP):
        m.predict([x])
    start = time.ticks_ms()
    y = None
    for _ in range(REPEAT):
        y = m.predict([x])[0]
    elapsed = time.ticks_diff(time.ticks_ms(), start)
    expected = [INPUTS[i] + 0.01 * i for i in range(32)]
    err = 0.0
    for i in range(32):
        delta = float(y[0][i]) - expected[i]
        delta = delta if delta >= 0.0 else -delta
        if delta > err:
            err = delta
    print("mode:", "vc4-allowed" if enabled else "cpu-reference",
          "total_ms:", elapsed, "avg_ms:", elapsed / float(REPEAT),
          "max_error:", err)
    if err > 1e-4:
        raise RuntimeError("output mismatch")
    m.deinit()
    del m
    gc.collect()
    return elapsed


def run():
    initial = machine.vc4()
    print("initial machine.vc4:", initial)
    cpu_ms = run_mode(False)
    vc4_ms = run_mode(True)
    print("observed speedup cpu/vc4:", cpu_ms / float(vc4_ms))
    print("VC4 allowed is not proof of QPU use; require runtime dispatch-complete log")
    print("recent runtime logs:")
    try:
        print(machine.logs(clear=False, limit=16384))
    except TypeError:
        for _ in range(16):
            line = machine.logs()
            if not line:
                break
            print(line)


run()
