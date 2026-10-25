# SPDX-License-Identifier: MIT
"""Integration checks executed by the real Windows MicroPython runtime."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT.parent / "tflite-micro/tensorflow/lite/micro/examples"
RUNTIME = Path(os.environ.get(
    "MPYNN_ML_RUNTIME",
    ROOT / "build/windows-ml/mpynn-ml.exe",
))


class NativeRuntimeTests(unittest.TestCase):
    def test_ulab_image_and_audio_are_native_runtime_modules(self):
        self.assertTrue(RUNTIME.is_file(), f"missing real runtime: {RUNTIME}")
        script = r'''
import sys
import struct
sys.path.extend(("modules", "modules/ml-core"))
import ulab
import image
import audio
import uml
from ml.model import Model
from ml.preprocessing import Normalization
from ml.apps import MicroSpeech
assert MicroSpeech._SAMPLES_PER_STEP == 160
assert MicroSpeech._SLICE_SIZE == 40
assert uml.Model.__name__ == "Model"
assert issubclass(Model, uml.Model)
from ulab import numpy as np
assert ulab.__name__ == "ulab"
assert image.__name__ == "image"
assert audio.__name__ == "audio"
a = np.array([1, 2, 3, 4], dtype=np.float)
b = a.reshape((2, 2))
c = b + b
assert c.shape == (2, 2), c.shape
assert c[0, 0] == 2
assert c[0, 0] + c[0, 1] + c[1, 0] + c[1, 1] == 20
four_d = np.array(list(range(16)), dtype=np.float).reshape((1, 2, 2, 4))
assert four_d.shape == (1, 2, 2, 4)
assert four_d[0, 1, 1, 3] == 15
# A real native image object owns converted ndarray data.
im = image.Image(2, 2, pixformat=image.GRAYSCALE)
im.set_pixel(0, 0, 10)
im.set_pixel(1, 0, 20)
im.set_pixel(0, 1, 30)
im.set_pixel(1, 1, 40)
pixels = im.to_ndarray('f')
assert pixels.shape == (2, 2), pixels.shape
assert pixels[1, 1] == 40
im.set_pixel(1, 1, 99)
assert pixels[1, 1] == 40
# PNG VFS decoder -> native image -> ml Normalization -> real model callable.
source_image = image.Image('red.png')
assert source_image.width() == 1 and source_image.height() == 1
normalizer = Normalization()(source_image)
model = Model("hello_world_float.tflite", arena_size=65536)
assert model.input_shape == ((1, 1),), model.input_shape
assert model.input_dtype == ('f',), model.input_dtype
assert model.output_shape == ((1, 1),), model.output_shape
x = np.array([0.0], dtype=np.float).reshape((1, 1))
seen = []
def postprocess(public_model, inputs, outputs):
    seen.append(public_model)
    assert public_model is model
    assert public_model.labels is not None, public_model.labels
    assert public_model.labels[0].startswith('zero') and public_model.labels[1].startswith('one'), public_model.labels
    return outputs
result = model.predict([x], callback=postprocess)
assert seen == [model]
assert len(result) == 1 and result[0].shape == (1, 1)
assert abs(result[0][0, 0] - 0.0264) < 0.02, result
held_output = result[0]
model.deinit()
del model
import gc
gc.collect()
assert held_output[0, 0] == result[0][0, 0]
# Callable input gets an owned scratch bytearray, not arena-backed memory.
raw = []
def fill(buf, shape, dtype):
    assert len(buf) == 4
    assert shape == (1, 1)
    assert dtype == ord('f')
    raw.append(buf)
    struct.pack_into('<f', buf, 0, 0.25)
call_model = Model('hello_world_float.tflite', arena_size=65536)
normalized = bytearray(4)
normalizer(normalized, (1, 1, 1, 1), ord('f'))
assert abs(struct.unpack('<f', normalized)[0] - 0.299) < 0.04
call_result = call_model.predict([fill])
assert call_result[0].shape == (1, 1)
call_model.deinit()
del call_model
import gc
gc.collect()
assert len(raw[0]) == 4
raw[0][0] = 0
assert raw[0][0] == 0
# Real quantized fixture exercises input quantization and output dequantization.
qmodel = Model('hello_world_int8.tflite', arena_size=65536)
assert qmodel.input_dtype == ('b',), qmodel.input_dtype
qinput = np.array([0], dtype=np.int8).reshape((1, 1))
qoutput = qmodel.predict([qinput])
assert qoutput[0].shape == (1, 1)
assert abs(qoutput[0][0, 0]) < 0.1, qoutput
qmodel.deinit()
# VFS WAV input, streaming callbacks, retained-buffer ownership, EOF/reinit.
wav_path = "host-runtime.wav"
samples = struct.pack("<4h", -3, -1, 2, 4)
with open(wav_path, "wb") as f:
    f.write(b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVE")
    f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16))
    f.write(b"data" + struct.pack("<I", len(samples)) + samples)
received = []
audio.init(source=wav_path, samples=3)
audio.start_streaming(lambda buf: received.append(buf))
for _ in range(5):
    audio.poll()
assert [bytes(chunk) for chunk in received] == [samples[:6], samples[6:]], received
assert audio.eof()
assert bytes(received[0]) == samples[:6]
audio.deinit()
audio.init(source=wav_path, samples=2)
audio.start_streaming(lambda buf: received.append(bytes(buf)))
audio.poll()
audio.stop_streaming()
audio.deinit()
print("NATIVE_RUNTIME_OK")
'''
        hello_float = MODEL_DIR / "hello_world/models/hello_world_float.tflite"
        hello_int8 = MODEL_DIR / "hello_world/models/hello_world_int8.tflite"
        self.assertTrue(hello_float.is_file(), f"missing real TFLite fixture: {hello_float}")
        with tempfile.TemporaryDirectory(prefix="mpynn-native-runtime-") as cwd:
            cwd_path = Path(cwd)
            (cwd_path / "modules").mkdir()
            (cwd_path / "modules/ml-core").mkdir(parents=True)
            (cwd_path / "modules/ml-core/ml").mkdir()
            package_init = ROOT / "scripts/libraries/ml/ml-core/ml/__init__.py"
            (cwd_path / "modules/ml-core/ml/__init__.py").write_bytes(package_init.read_bytes())
            for module in ("model.py", "preprocessing.py", "apps.py"):
                source = ROOT / "scripts/libraries/ml/ml-core/ml" / module
                (cwd_path / "modules/ml-core/ml" / module).write_bytes(source.read_bytes())
            (cwd_path / "hello_world_float.tflite").write_bytes(hello_float.read_bytes())
            import struct
            import zlib
            def png_chunk(tag, payload):
                return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff)
            png = (b"\x89PNG\r\n\x1a\n" +
                   png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
                   png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) +
                   png_chunk(b"IEND", b""))
            (cwd_path / "red.png").write_bytes(png)
            (cwd_path / "hello_world_float.txt").write_text("zero\none\n", encoding="ascii")
            if hello_int8.is_file():
                (cwd_path / "hello_world_int8.tflite").write_bytes(hello_int8.read_bytes())
            env = os.environ.copy()
            env["PATH"] = str(Path("E:/msys64/ucrt64/bin")) + os.pathsep + env.get("PATH", "")
            result = subprocess.run(
                [str(RUNTIME), "-c", script], cwd=cwd_path, env=env,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("NATIVE_RUNTIME_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
