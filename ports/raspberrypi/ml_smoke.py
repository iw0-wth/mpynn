# SPDX-License-Identifier: MIT
# Board acceptance: copy hello_world_float.tflite from the TFLM examples to /sd/model.tflite.
# Run: exec(open('ml_smoke.py').read()) then check_model('/sd/model.tflite').
import gc
import struct
import uml
from ulab import numpy as np
from ml import Model


def check_model(path):
    model = Model(path)
    assert model.input_shape == ((1, 1),)
    assert model.input_dtype == ('f',)
    inputs = [np.array([[0.5]], dtype=np.float)]
    outputs = model.predict(inputs)
    assert len(outputs) == 1 and outputs[0].shape == (1, 1)
    first = float(outputs[0][0, 0])
    saved_scratch = []

    def fill(buffer, shape, dtype):
        assert isinstance(buffer, bytearray)
        assert shape == (1, 1) and dtype == ord('f')
        saved_scratch.append(buffer)
        buffer[:] = struct.pack('<f', 0.5)
        gc.collect()

    calls = []

    def callback(actual_model, actual_inputs, actual_outputs):
        assert actual_inputs[0] is fill
        assert actual_model.input_shape == model.input_shape
        calls.append(actual_outputs)
        return actual_outputs

    result = model.predict([fill], callback=callback)
    assert len(calls) == 1 and abs(float(result[0][0, 0]) - first) < 1e-6
    model.deinit()
    gc.collect()
    assert struct.unpack('<f', saved_scratch[0])[0] == 0.5
    assert abs(float(outputs[0][0, 0]) - first) < 1e-6
    try:
        model.predict(inputs)
    except RuntimeError:
        pass
    else:
        raise AssertionError('deinitialized model accepted inference')
    print('uml/model/ulab callable + callback + GC ownership: PASS')
    return True
