# SPDX-License-Identifier: MIT
"""Explicit ML/file-media demo for the mpynn Pi1B image.

Copy this module to /demo together with a model/image/WAV file on the SD card.
It never captures a camera frame, previews to an IDE, writes a file, or starts
network traffic implicitly.
"""
import gc
import struct
import uml
from ulab import numpy as np
from ml import Model
from ml.preprocessing import Normalization


def infer(model_path, value=0.0, arena_size=65536):
    """Run a scalar float model and return its owned float output."""
    model = Model(model_path, arena_size=arena_size)
    inputs = [np.array([[value]], dtype=np.float)]
    outputs = model.predict(inputs)
    result = float(outputs[0][0, 0])
    model.deinit()
    gc.collect()
    return result


def infer_callable(model_path, value=0.0, arena_size=65536):
    """Exercise the callable bytearray input contract."""
    retained = []

    def fill(buffer, shape, dtype):
        if shape != (1, 1) or dtype != ord("f") or len(buffer) != 4:
            raise ValueError("unexpected model input contract")
        retained.append(buffer)
        struct.pack_into("<f", buffer, 0, value)

    model = Model(model_path, arena_size=arena_size)
    outputs = model.predict([fill])
    model.deinit()
    gc.collect()
    if len(retained[0]) != 4:
        raise RuntimeError("callable buffer did not remain owned")
    return float(outputs[0][0, 0])


def image_tensor(image_path, model_path, arena_size=65536):
    """Load a PNG/BMP/PNM file from VFS and preprocess it into a model input."""
    import image
    source = image.Image(image_path)
    normalizer = Normalization()(source)
    model = Model(model_path, arena_size=arena_size)

    def fill(buffer, shape, dtype):
        normalizer(buffer, shape, dtype)

    outputs = model.predict([fill])
    model.deinit()
    gc.collect()
    return outputs


def stream_wav(wav_path, samples=320):
    """Read WAV PCM16 from VFS and return exact callback chunks."""
    import audio
    chunks = []
    audio.init(source=wav_path, format="wav", channels=1, frequency=16000, samples=samples)
    audio.start_streaming(lambda buf: chunks.append(bytes(buf)))
    while audio.is_streaming():
        audio.poll()
    audio.deinit()
    return chunks
