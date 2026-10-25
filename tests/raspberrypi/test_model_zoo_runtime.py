# SPDX-License-Identifier: MIT
"""Real Windows MicroPython smoke for the checked-in TFLM model zoo."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "build/windows-ml/mpynn-ml.exe"
MODELS = ROOT / "lib/models"
TEXT = ROOT.parent / "ml_text_cls/text_cls_tflm.tflite"


class ModelZooRuntimeTests(unittest.TestCase):
    def test_text_and_yolo_reference_models(self):
        self.assertTrue(RUNTIME.is_file())
        script = r'''
from uml import Model
from ulab import numpy as np

text = Model('text_cls_f32_tflm.tflite', arena_size=2 * 1024 * 1024)
tx = np.zeros((1, 50), dtype=np.float)
ty = text.predict([tx])[0]
assert text.input_shape == ((1, 50),) and text.input_dtype == ('f',)
assert ty.shape == (1, 11) and abs(float(ty[0, 0])) < 10
text.deinit()

lc = Model('yolo_lc_192.tflite', arena_size=8 * 1024 * 1024)
lx = np.zeros((1, 192, 192, 3), dtype=np.uint8)
lo = lc.predict([lx])[0]
assert lc.input_shape == ((1, 192, 192, 3),) and lc.input_dtype == ('B',)
assert lo.shape == (1, 12, 12, 30)
lc.deinit()

yolo = Model('yolov8n_192.tflite', arena_size=16 * 1024 * 1024)
yx = np.zeros((1, 192, 192, 3), dtype=np.uint8)
yo = yolo.predict([yx])[0]
assert yolo.input_shape == ((1, 192, 192, 3),) and yolo.input_dtype == ('B',)
assert yo.shape == (1, 5, 756)
yolo.deinit()
print('MODEL_ZOO_RUNTIME_OK')
'''
        with tempfile.TemporaryDirectory(prefix='mpynn-model-zoo-') as cwd:
            cwd_path = Path(cwd)
            for name, source in {
                'text_cls_f32_tflm.tflite': TEXT,
                'yolo_lc_192.tflite': MODELS / 'yolo_lc_192.tflite',
                'yolov8n_192.tflite': MODELS / 'yolov8n_192.tflite',
            }.items():
                self.assertTrue(source.is_file(), source)
                (cwd_path / name).write_bytes(source.read_bytes())
            env = os.environ.copy()
            env['PATH'] = str(Path('E:/msys64/ucrt64/bin')) + os.pathsep + env.get('PATH', '')
            result = subprocess.run([str(RUNTIME), '-c', script], cwd=cwd_path,
                                    env=env, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('MODEL_ZOO_RUNTIME_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
