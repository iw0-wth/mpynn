"""Controlled same-board A/B benchmark for 128x4096 FP32 FC."""
import time
from ml import Model

MODEL_PATH = "/vc4_fc_128x4096.tflite"
INPUTS = [0.25, -0.5, 0.125, 1.0, -0.75, 0.375, 0.625, -0.25] + [0.0] * 4088
OUTPUT_DEPTH = 128
WARMUP = 5
REPEAT = 100


def run():
    m = Model(MODEL_PATH, arena_size=8 * 1024 * 1024)
    import ulab.numpy as np
    x = np.array(INPUTS, dtype=np.float).reshape(m.input_shape[0])
    for _ in range(WARMUP):
        m.predict([x])
    t0 = time.ticks_ms()
    out = None
    for _ in range(REPEAT):
        out = m.predict([x])[0]
    elapsed = time.ticks_diff(time.ticks_ms(), t0)
    expected = [INPUTS[i] + 0.01 * i for i in range(OUTPUT_DEPTH)]
    max_error = 0.0
    for i in range(OUTPUT_DEPTH):
        delta = float(out[0][i]) - expected[i]
        error = delta if delta >= 0.0 else -delta
        if error > max_error:
            max_error = error
    print("model:", MODEL_PATH)
    print("shape:", m.input_shape, m.output_shape)
    print("warmup:", WARMUP, "repeat:", REPEAT)
    print("total_ms:", elapsed, "avg_ms:", elapsed / float(REPEAT))
    print("macs:", 4096 * OUTPUT_DEPTH,
          "mmac_per_s:", (4096 * OUTPUT_DEPTH * REPEAT) / float(max(1, elapsed)) / 1000.0)
    print("max_cpu_reference_error:", max_error)
    if max_error > 1e-4:
        raise RuntimeError("benchmark output mismatch")
    m.deinit()


run()
