# SPDX-License-Identifier: MIT
"""Exercise the public Python ML wrapper with a deliberately native-like base.

This is wrapper contract evidence, not proof of TFLM or ulab execution.
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / 'scripts/libraries/ml/ml-core/ml/model.py'


class NativeLikeModel:
    def __init__(self, path, postprocess=None, **kwargs):
        self.native_args = (path, kwargs)
        self.native_postprocess = postprocess

    def predict(self, inputs, callback=None):
        callback = callback or self.native_postprocess
        # Native built-in base calls do not receive the outer Python instance.
        native_subobject = object()
        output = ['native-output']
        return callback(native_subobject, inputs, output) if callback else output


class ModelWrapperTests(unittest.TestCase):
    def load(self):
        uml = types.ModuleType('uml')
        uml.Model = NativeLikeModel
        ml = types.ModuleType('ml')
        ml.__path__ = []
        preprocessing = types.ModuleType('ml.preprocessing')
        preprocessing.Normalization = lambda: None
        spec = importlib.util.spec_from_file_location('_test_ml_model', MODEL)
        module = importlib.util.module_from_spec(spec)
        modules = {'uml': uml, 'ml': ml, 'ml.preprocessing': preprocessing}
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(module)
        return module.Model

    def test_constructor_kwargs_and_callback_see_public_model(self):
        Model = self.load()
        calls = []
        def postprocess(model, inputs, outputs):
            calls.append((model, inputs, outputs))
            return model.labels
        model = Model('/not-a-real-model.tflite', postprocess=postprocess, arena_size=4096)
        model.labels = ['public-label']
        self.assertEqual(model.native_args, ('/not-a-real-model.tflite', {'arena_size': 4096}))
        self.assertEqual(model.predict([1]), ['public-label'])
        self.assertIs(calls[0][0], model)
        explicit = []
        self.assertEqual(model.predict([2], callback=lambda m, i, o: explicit.append(m) or 7), 7)
        self.assertIs(explicit[0], model)
        self.assertEqual(len(calls), 1)

    def test_invalid_callback_rejected_before_native(self):
        model = self.load()('/not-a-real-model.tflite')
        with self.assertRaisesRegex(TypeError, 'callback must be callable'):
            model.predict([1], callback=42)
        self.assertEqual(model.predict([1]), ['native-output'])


if __name__ == '__main__':
    unittest.main()
