"""BCM2835 VC4 hardware validation checklist runner.

This script deliberately does not claim acceleration unless runtime probe,
FP32 matvec, and CPU comparison all pass. The model file must contain an FP32
FullyConnected whose output depth is a multiple of 16 and whose operation size
meets vc4_should_offload_fp32's clock-scaled crossover.
"""

import gc
import time

from ml import Model

# The onboard SD is mounted as the root VFS (`/`), not at `/sd`.
MODEL_PATH = "/vc4_fc_fp32.tflite"
INPUTS = [0.25, -0.5, 0.125, 1.0, -0.75, 0.375, 0.625, -0.25] + [0.0] * 1016


def run():
    print("VC4 validation start; capture the full serial log")
    print("Expected boot lines include measured ARM/CORE clocks and QPU-enable probe")
    model = Model(MODEL_PATH, arena_size=2 * 1024 * 1024)
    print("input_shape:", model.input_shape, "dtype:", model.input_dtype)
    print("output_shape:", model.output_shape, "dtype:", model.output_dtype)
    if model.input_dtype != ("f",):
        raise RuntimeError("test model input must be FP32")
    if len(model.input_shape) != 1 or model.input_shape[0][-1] != len(INPUTS):
        raise RuntimeError("test model input shape does not match INPUTS")

    # NumPy is part of the RPI1B MicroPython module set. This path exercises the
    # public model wrapper; the board runtime logs the QPU probe separately.
    import ulab.numpy as np
    tensor = np.array(INPUTS, dtype=np.float).reshape(model.input_shape[0])

    # Warm up once, then repeat. A success here proves inference, not by itself
    # proof of QPU use; require the serial log to show the successful probe and
    # the test model's FC MAC count to exceed the measured-clock dispatch gate.
    first = model.predict([tensor])[0]
    start = time.ticks_ms()
    repeats = 20
    for _ in range(repeats):
        result = model.predict([tensor])[0]
    elapsed = time.ticks_diff(time.ticks_ms(), start)
    if result.shape != first.shape:
        raise RuntimeError("output shape changed during repeated inference")
    expected = [INPUTS[i] + 0.01 * i for i in range(16)]
    max_error = 0.0
    for i in range(16):
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
                for _ in range(8):
                    line = machine.logs()
                    if not line:
                        break
                    print(line)
    except Exception as exc:
        print("could not read recent logs:", repr(exc))
    print("VC4 smoke complete; compare outputs with CPU reference on host")


run()
