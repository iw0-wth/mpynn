"""BCM2835 VC4 smoke test for the 32x1024 FP32 FC fixture."""
import gc
import time
from ml import Model

MODEL_PATH = "/vc4_fc_32x1024.tflite"
INPUTS = [0.25, -0.5, 0.125, 1.0, -0.75, 0.375, 0.625, -0.25] + [0.0] * 1016
OUTPUT_DEPTH = 32


def run():
    print("VC4 32x1024 validation start; capture the full serial log")
    model = Model(MODEL_PATH, arena_size=2 * 1024 * 1024)
    print("input_shape:", model.input_shape, "dtype:", model.input_dtype)
    print("output_shape:", model.output_shape, "dtype:", model.output_dtype)
    if model.input_dtype != ("f",):
        raise RuntimeError("test model input must be FP32")
    if len(model.input_shape) != 1 or model.input_shape[0][-1] != len(INPUTS):
        raise RuntimeError("test model input shape does not match INPUTS")
    import ulab.numpy as np
    tensor = np.array(INPUTS, dtype=np.float).reshape(model.input_shape[0])
    first = model.predict([tensor])[0]
    start = time.ticks_ms()
    repeats = 20
    for _ in range(repeats):
        result = model.predict([tensor])[0]
    elapsed = time.ticks_diff(time.ticks_ms(), start)
    if result.shape != first.shape:
        raise RuntimeError("output shape changed during repeated inference")
    expected = [INPUTS[i] + 0.01 * i for i in range(OUTPUT_DEPTH)]
    max_error = 0.0
    for i in range(OUTPUT_DEPTH):
        delta = float(result[0][i]) - expected[i]
        error = delta if delta >= 0.0 else -delta
        if error > max_error:
            max_error = error
    print("repeated FP32 FC inferences:", repeats, "elapsed_ms:", elapsed)
    print("max_cpu_reference_error:", max_error)
    print("sample output:", result)
    if max_error > 1e-4:
        raise RuntimeError("FP32 FC output differs from CPU reference")
    model.deinit()
    del model
    gc.collect()
    print("model teardown/reload cycle")
    model = Model(MODEL_PATH, arena_size=2 * 1024 * 1024)
    again = model.predict([tensor])[0]
    print("reload output:", again)
    model.deinit()
    try:
        import machine
        if hasattr(machine, "logs"):
            print("recent Circle/runtime logs:")
            try:
                print(machine.logs(clear=False, limit=16384))
            except TypeError:
                for _ in range(16):
                    line = machine.logs()
                    if not line:
                        break
                    print(line)
    except Exception as exc:
        print("could not read recent logs:", repr(exc))
    print("VC4 32x1024 smoke complete")


run()
