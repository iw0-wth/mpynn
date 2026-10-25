"""CPython-only contract tests for the ml Python wrapper.

Run from the workspace root:
    python -B -m unittest discover -s mpynn/tests/ai_core -p "test_*.py" -v

These explicit uml/ulab/image stubs exercise Python dispatch and preprocessing
math, NOT firmware, real ulab ndarrays, image conversion, TFLM or inference.
No native modules or third-party packages are downloaded or required.
"""

import builtins
from contextlib import contextmanager
import importlib
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import mock_open, patch


ML_CORE = Path(__file__).resolve().parents[2] / "scripts" / "libraries" / "ml" / "ml-core"


class ArrayStub:
    """Small elementwise vector, optionally backed by a caller's tensor buffer."""

    def __init__(self, values, buffer=None, dtype="f"):
        self.values = list(values)
        self.buffer = buffer
        self.dtype = dtype
        self._store()

    def _store(self):
        if self.buffer is not None:
            struct.pack_into("=" + self.dtype * len(self.values), self.buffer, 0, *self.values)

    def tobytes(self):
        return struct.pack("=" + self.dtype * len(self.values), *self.values)

    def _binary(self, other, operation):
        values = other.values if isinstance(other, ArrayStub) else [other] * len(self.values)
        return ArrayStub([operation(a, values[i % len(values)]) for i, a in enumerate(self.values)])

    def __rsub__(self, other):
        return self._binary(other, lambda a, b: b - a)

    def __truediv__(self, other):
        return self._binary(other, lambda a, b: a / b)

    def __rtruediv__(self, other):
        return self._binary(other, lambda a, b: b / a)

    def __imul__(self, other):
        self.values = self._binary(other, lambda a, b: a * b).values
        self._store()
        return self

    def __iadd__(self, other):
        self.values = self._binary(other, lambda a, b: a + b).values
        self._store()
        return self


def make_image_module():
    module = types.ModuleType("image")
    module.GRAYSCALE = 1
    module.RGB565 = 2
    module.BILINEAR = 1
    module.CENTER = 2
    module.SCALE_ASPECT_IGNORE = 4
    module.BLACK_BACKGROUND = 8
    module.created = []

    class ImageStub:
        def __init__(self, width, height, pixfmt, buffer=None, pixels=()):
            self._width = width
            self._height = height
            self.pixfmt = pixfmt
            self.buffer = buffer
            self.pixels = list(pixels)
            self.draw_call = None
            module.created.append(self)

        def width(self):
            return self._width

        def height(self):
            return self._height

        def draw_image(self, source, x, y, **kwargs):
            # Only record the adapter's contract: no resizing/RGB565 emulation.
            self.draw_call = (source, x, y, kwargs)
            self.pixels = source.pixels

        def to_ndarray(self, dtype, buffer=None):
            return ArrayStub(self.pixels, buffer, chr(dtype))

    module.Image = ImageStub
    return module


@contextmanager
def load_ml(image_module=None, machine_module=None):
    """Isolate module state and actively block unavailable native dependencies."""
    saved = {
        name: module for name, module in sys.modules.items()
        if name == "ml" or name.startswith("ml.") or name in ("uml", "ulab", "image", "machine")
    }
    for name in saved:
        del sys.modules[name]

    uml = types.ModuleType("uml")

    class ModelStub:
        def __init__(self, *args):
            self.constructor_args = args
            self.calls = []
            self.callback_buffers = []
            self.result = object()

        def predict(self, args, **kwargs):
            self.calls.append((args, kwargs))
            for item in args:
                if callable(item):
                    buffer = bytearray(4)
                    item(buffer, (1, 1, 1, 1), ord("f"))
                    self.callback_buffers.append(buffer)
                elif not isinstance(item, ArrayStub):
                    raise ValueError("Unsupported input type")
            return self.result

    uml.Model = ModelStub
    ulab = types.ModuleType("ulab")
    ulab.numpy = types.SimpleNamespace(array=ArrayStub)
    sys.modules["uml"] = uml
    if image_module is not None:
        sys.modules["image"] = image_module
        sys.modules["ulab"] = ulab
    if machine_module is not None:
        sys.modules["machine"] = machine_module
    original_import = builtins.__import__
    imports = []

    def guarded_import(name, *args, **kwargs):
        imports.append(name)
        if image_module is None and name in ("image", "ulab"):
            raise ImportError("host test deliberately blocks " + name)
        return original_import(name, *args, **kwargs)

    sys.path.insert(0, str(ML_CORE))
    try:
        with patch("builtins.__import__", side_effect=guarded_import):
            yield importlib.import_module("ml"), imports
    finally:
        sys.path.remove(str(ML_CORE))
        for name in list(sys.modules):
            if name == "ml" or name.startswith("ml.") or name in ("uml", "ulab", "image", "machine"):
                del sys.modules[name]
        sys.modules.update(saved)


class ImageFreeModelTests(unittest.TestCase):
    def test_import_does_not_attempt_image_or_ulab(self):
        with load_ml() as (ml, imports):
            preprocessing = importlib.import_module("ml.preprocessing")
            self.assertTrue(issubclass(ml.Model, sys.modules["uml"].Model))
            self.assertIs(ml.Normalization, preprocessing.Normalization)
            self.assertNotIn("image", imports)
            self.assertNotIn("ulab", imports)

    def test_ndarray_inputs_and_prediction_options_are_forwarded(self):
        with load_ml() as (ml, _):
            model = ml.Model(b"model bytes")
            tensors = [ArrayStub([1, 2]), ArrayStub([3, 4])]
            callback = lambda model, inputs, outputs: outputs
            self.assertIs(model.predict(tensors, callback=callback), model.result)
            args, kwargs = model.calls[-1]
            self.assertIs(args[0], tensors[0])
            self.assertIs(args[1], tensors[1])
            self.assertTrue(callable(kwargs["callback"]))
            self.assertIs(kwargs["callback"](model, tensors, model.result), model.result)
            self.assertEqual(tensors[0].values, [1, 2])

    def test_callable_receives_writable_tensor_buffer(self):
        with load_ml() as (ml, _):
            model = ml.Model(b"model bytes")
            calls = []

            def fill_tensor(buffer, shape, dtype):
                calls.append((shape, dtype))
                struct.pack_into("=f", buffer, 0, 0.75)

            self.assertIs(model.predict([fill_tensor]), model.result)
            self.assertIs(model.calls[0][0][0], fill_tensor)
            self.assertEqual(calls, [((1, 1, 1, 1), ord("f"))])
            self.assertEqual(struct.unpack("=f", model.callback_buffers[0]), (0.75,))

    def test_constructor_postprocess_and_labels_are_preserved(self):
        with load_ml() as (ml, _):
            callback = lambda *args: args
            with patch("builtins.open", mock_open(read_data="first\nsecond\n")) as opened:
                model = ml.Model("network.tflite", postprocess=callback)
            self.assertEqual(model.constructor_args[0], "network.tflite")
            self.assertTrue(callable(model.constructor_args[1]))
            marker = object()
            self.assertEqual(model.constructor_args[1](None, [], marker), (model, [], marker))
            self.assertEqual(model.labels, ["first", "second"])
            opened.assert_called_once_with("network.txt", "r")
            self.assertIsNone(ml.Model(b"model bytes").labels)

    def test_backend_reference_switches_off_then_restores_at_create_and_invoke(self):
        machine = types.ModuleType("machine")
        state = {"enabled": True}
        calls = []

        def vc4(value=None):
            if value is None:
                return state["enabled"]
            state["enabled"] = bool(value)
            calls.append(state["enabled"])
            return state["enabled"]

        machine.vc4 = vc4
        with load_ml(machine_module=machine) as (ml, _):
            model = ml.Model(b"model bytes", backend="reference")
            self.assertTrue(state["enabled"])  # restore process setting after create
            model.predict([ArrayStub([1, 2])])
            self.assertTrue(state["enabled"])  # restore after every invocation
            self.assertEqual(calls, [False, True, False, True])
            self.assertEqual(model.backend, "reference")

    def test_backend_reference_works_when_machine_module_is_absent(self):
        with load_ml() as (ml, imports):
            model = ml.Model(b"model bytes", backend="reference")
            self.assertIs(model.predict([ArrayStub([1, 2])]), model.result)
            self.assertEqual(model.backend, "reference")
            self.assertIn("machine", imports)

    def test_backend_vc4_switches_on_then_restores_at_create_and_invoke(self):
        machine = types.ModuleType("machine")
        state = {"enabled": False}
        calls = []

        def vc4(value=None):
            if value is None:
                return state["enabled"]
            state["enabled"] = bool(value)
            calls.append(state["enabled"])
            return state["enabled"]

        machine.vc4 = vc4
        with load_ml(machine_module=machine) as (ml, _):
            model = ml.Model(b"model bytes", backend="vc4")
            self.assertFalse(state["enabled"])
            model.predict([ArrayStub([1, 2])])
            self.assertFalse(state["enabled"])
            self.assertEqual(calls, [True, False, True, False])
            self.assertEqual(model.backend, "vc4")

    def test_backend_switch_restores_when_native_constructor_raises(self):
        machine = types.ModuleType("machine")
        state = {"enabled": True}
        calls = []

        def vc4(value=None):
            if value is None:
                return state["enabled"]
            state["enabled"] = bool(value)
            calls.append(state["enabled"])
            return state["enabled"]

        machine.vc4 = vc4
        with load_ml(machine_module=machine) as (ml, _):
            native_type = sys.modules["uml"].Model

            def fail_init(self, *args):
                raise RuntimeError("native allocation failure")

            native_type.__init__ = fail_init
            with self.assertRaisesRegex(RuntimeError, "native allocation failure"):
                ml.Model(b"model bytes", backend="reference")
            self.assertTrue(state["enabled"])
            self.assertEqual(calls, [False, True])

    def test_backend_switch_restores_when_native_predict_raises(self):
        machine = types.ModuleType("machine")
        state = {"enabled": True}
        calls = []

        def vc4(value=None):
            if value is None:
                return state["enabled"]
            state["enabled"] = bool(value)
            calls.append(state["enabled"])
            return state["enabled"]

        machine.vc4 = vc4
        with load_ml(machine_module=machine) as (ml, _):
            model = ml.Model(b"model bytes", backend="reference")
            native_type = sys.modules["uml"].Model

            def fail_predict(self, *args, **kwargs):
                raise RuntimeError("native invoke failure")

            native_type.predict = fail_predict
            with self.assertRaisesRegex(RuntimeError, "native invoke failure"):
                model.predict([ArrayStub([1, 2])])
            self.assertTrue(state["enabled"])
            self.assertEqual(calls, [False, True, False, True])

    def test_backend_auto_preserves_global_switch(self):
        machine = types.ModuleType("machine")
        machine.vc4 = lambda *args: self.fail("auto must not change global switch")
        with load_ml(machine_module=machine) as (ml, _):
            model = ml.Model(b"model bytes")
            model.predict([ArrayStub([1, 2])])
            self.assertEqual(model.backend, "auto")

    def test_vc4_backend_reports_unavailable_on_host(self):
        with load_ml() as (ml, _):
            with self.assertRaisesRegex(ValueError, "VC4 backend is unavailable"):
                ml.Model(b"model bytes", backend="vc4")

    def test_vc4_backend_requires_machine_switch_api(self):
        machine = types.ModuleType("machine")
        with load_ml(machine_module=machine) as (ml, _):
            with self.assertRaisesRegex(ValueError, "VC4 backend control is unavailable"):
                ml.Model(b"model bytes", backend="vc4")

    def test_reference_backend_works_without_machine_vc4_api(self):
        machine = types.ModuleType("machine")
        with load_ml(machine_module=machine) as (ml, _):
            model = ml.Model(b"model bytes", backend="reference")
            self.assertIs(model.predict([ArrayStub([1, 2])]), model.result)

    def test_unsupported_backend_is_rejected(self):
        with load_ml() as (ml, _):
            with self.assertRaisesRegex(ValueError, "backend must be"):
                ml.Model(b"model bytes", backend="stai")

    def test_unsupported_inputs_still_reach_backend_validation(self):
        with load_ml() as (ml, _):
            with self.assertRaisesRegex(ValueError, "Unsupported input type"):
                ml.Model(b"model bytes").predict([object()])

    def test_optional_image_binding_reports_missing_dependency(self):
        with load_ml() as (ml, _):
            normalization = ml.Normalization()
            with self.assertRaisesRegex(ImportError, "Normalization requires the optional image module"):
                normalization(object())

    def test_optional_image_callback_reports_missing_dependency(self):
        with load_ml() as (ml, _):
            with self.assertRaisesRegex(ImportError, "Normalization requires the optional image module"):
                ml.Model(b"model bytes").predict([ml.Normalization()])


class OptionalImageTests(unittest.TestCase):
    def setUp(self):
        self.image = make_image_module()

    def test_raw_image_still_gets_automatic_normalization(self):
        with load_ml(self.image) as (ml, _):
            source = self.image.Image(1, 1, self.image.GRAYSCALE, pixels=[255])
            model = ml.Model(b"model bytes")
            model.predict([source])
            wrapped = model.calls[0][0][0]
            self.assertIsInstance(wrapped, ml.Normalization)
            self.assertIs(wrapped._image, source)
            self.assertEqual(wrapped.roi, (0, 0, 1, 1))
            self.assertAlmostEqual(struct.unpack("=f", model.callback_buffers[0])[0], 1.0)

    def test_tensor_and_callable_not_wrapped_when_image_available(self):
        with load_ml(self.image) as (ml, _):
            tensor = ArrayStub([2])
            calls = []
            callback = lambda *args: calls.append(args)
            model = ml.Model(b"model bytes")
            model.predict([tensor, callback])
            self.assertIs(model.calls[0][0][0], tensor)
            self.assertIs(model.calls[0][0][1], callback)
            self.assertEqual(len(calls), 1)

    def test_explicit_grayscale_normalization_and_roi(self):
        with load_ml(self.image) as (ml, _):
            source = self.image.Image(8, 6, self.image.GRAYSCALE, pixels=[255])
            normalize = ml.Normalization(scale=(-1, 1), mean=(0.5,) * 3, stdev=(0.5,) * 3,
                                         roi=(2, 1, 3, 4))(source)
            buffer = bytearray(4)
            normalize(buffer, (1, 1, 1, 1), ord("f"))
            target = self.image.created[-1]
            self.assertIsNone(target.buffer)  # staging image must not alias the caller buffer
            self.assertEqual(target.draw_call, (source, 0, 0, {"roi": (2, 1, 3, 4), "hint": 15}))
            self.assertAlmostEqual(struct.unpack("=f", buffer)[0], 1.0)

    def test_rgb_float_normalization_math(self):
        with load_ml(self.image) as (ml, _):
            source = self.image.Image(1, 1, self.image.RGB565, pixels=[0, 128, 255])
            normalize = ml.Normalization(mean=(0.1, 0.2, 0.3), stdev=(1, 2, 4))(source)
            buffer = bytearray(12)
            normalize(buffer, (1, 1, 1, 3), ord("f"))
            expected = (-0.1, (128 / 255 - 0.2) / 2, (1 - 0.3) / 4)
            for actual, value in zip(struct.unpack("=fff", buffer), expected):
                self.assertAlmostEqual(actual, value, places=6)
            self.assertIsNone(self.image.created[-1].buffer)  # independently owned staging

    def test_integer_tensor_is_not_float_normalized(self):
        with load_ml(self.image) as (ml, _):
            source = self.image.Image(1, 1, self.image.GRAYSCALE, pixels=[128])
            normalize = ml.Normalization(scale=(-1, 1))(source)
            buffer = bytearray(1)
            normalize(buffer, (1, 1, 1, 1), ord("B"))
            self.assertEqual(buffer, bytearray([128]))

    def test_bound_normalization_stays_callable(self):
        with load_ml(self.image) as (ml, _):
            source = self.image.Image(1, 1, self.image.GRAYSCALE, pixels=[255])
            normalize = ml.Normalization()(source)
            model = ml.Model(b"model bytes")
            model.predict([normalize])
            self.assertIs(model.calls[0][0][0], normalize)

    def test_invalid_image_and_unbound_callback_have_clear_errors(self):
        with load_ml(self.image) as (ml, _):
            with self.assertRaisesRegex(ValueError, "Expected an image input"):
                ml.Normalization()(object())
            with self.assertRaisesRegex(ValueError, "Bind an image"):
                ml.Normalization()(bytearray(4), (1, 1, 1, 1), ord("f"))

    def test_existing_tensor_shape_validation_is_preserved(self):
        with load_ml(self.image) as (ml, _):
            source = self.image.Image(1, 1, self.image.GRAYSCALE, pixels=[0])
            normalize = ml.Normalization()(source)
            for shape, message in [((1, 1, 1), "Expected input tensor"),
                                   ((2, 1, 1, 1), "Expected batches"),
                                   ((1, 1, 1, 2), "Expected channels")]:
                with self.subTest(shape=shape):
                    with self.assertRaisesRegex(ValueError, message):
                        normalize(bytearray(4), shape, ord("f"))


if __name__ == "__main__":
    unittest.main()
