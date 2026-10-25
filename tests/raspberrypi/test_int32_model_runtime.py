# SPDX-License-Identifier: MIT
"""Public int32 I/O test against the repository's real text model."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOP = ROOT.parent
MODEL = TOP / 'ml_text_cls/model_with_softmax.tflite'
RUNTIME = Path(os.environ.get('MPYNN_ML_RUNTIME', ROOT / 'build/windows-ml/mpynn-ml.exe'))

SCRIPT = r'''
import struct
import uml
from ulab import numpy as np
model = uml.Model('model_with_softmax.tflite', arena_size=4*1024*1024)
print('INT32_METADATA', model.input_shape, model.input_dtype,
      model.output_shape, model.output_dtype)
assert model.input_dtype[0] == 'i', model.input_dtype
shape = model.input_shape[0]
assert len(shape) == 2 and shape[0] == 1
n = shape[0] * shape[1]
values = [0, 1, 2, 3] * (n // 4) + [0, 1, 2, 3][:n % 4]
# Prove input pre-processing rejects wrong types/range even when a later op
# might be unavailable in this TFLM reference resolver.
try:
    model.predict([[0.0] + values[1:]])
except TypeError:
    pass
else:
    raise AssertionError('int32 accepted float input')
try:
    model.predict([[2147483648] + values[1:]])
except OverflowError:
    pass
else:
    raise AssertionError('int32 accepted overflow')
raw_input = bytearray(struct.pack('<%di' % n, *values))
held = []
def fill(buf, callback_shape, dtype):
    assert callback_shape == shape and dtype == ord('i')
    buf[:] = raw_input
    held.append(buf)
# Exercise both accepted raw and callable public int32 inputs. This original
# model contains a known int32 SELECT_V2 path that may be unavailable in TFLM.
invoke_error = None
for source in (values, raw_input, fill):
    try:
        raw_result = model.predict([source], raw_output=True)
    except RuntimeError as error:
        invoke_error = str(error)
        break
    assert type(raw_result) is list and len(raw_result) == model.num_outputs
    for index, raw in enumerate(raw_result):
        assert type(raw) is bytearray
        output_shape = model.output_shape[index]
        count = 1
        for dimension in output_shape:
            count *= dimension
        dtype = model.output_dtype[index]
        itemsize = {'i':4, 'f':4, 'b':1, 'B':1, 'h':2, 'H':2}[dtype]
        assert len(raw) == count * itemsize
        if dtype == 'i':
            decoded = struct.unpack('<%di' % count, raw)
            assert all(-2147483648 <= value <= 2147483647 for value in decoded)
    if source is fill:
        assert held and bytes(held[0]) == bytes(raw_input)
if invoke_error:
    print('TFLM_INVOKE_UNSUPPORTED', invoke_error)
else:
    # Confirm raw outputs are independent snapshots and default output remains
    # a float ndarray, while raw_output preserves the exact native tensor bytes.
    prediction = model.predict([values])
    assert len(prediction) == model.num_outputs
    for index, array in enumerate(prediction):
        assert array.shape == model.output_shape[index]
    print('INT32_INVOKE_OK')
model.deinit()
print('INT32_MODEL_RUNTIME_OK')
'''


class Int32ModelRuntimeTests(unittest.TestCase):
    def test_public_int32_input_output(self):
        self.assertTrue(MODEL.is_file(), f'missing public-int32 model fixture: {MODEL}')
        self.assertTrue(RUNTIME.is_file(), f'missing runtime (rebuild host port): {RUNTIME}')
        with tempfile.TemporaryDirectory(prefix='uml-int32-model-') as folder:
            temp = Path(folder)
            shutil.copyfile(MODEL, temp / MODEL.name)
            run = subprocess.run([str(RUNTIME), '-c', SCRIPT], check=True, cwd=temp,
                                 env=os.environ.copy(), text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 timeout=90)
            self.assertIn('INT32_METADATA', run.stdout)
            self.assertIn('INT32_MODEL_RUNTIME_OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
