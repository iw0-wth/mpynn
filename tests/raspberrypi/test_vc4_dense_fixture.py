"""Verify dense model schema/data and the independent oracle on a small fixture."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

PORT = Path(__file__).resolve().parents[2] / 'ports' / 'raspberrypi'


def test_dense_reference_matches_serial_dot_over_serialized_float32(tmp_path):
    sys.path.insert(0, str(PORT))
    try:
        from make_vc4_dense_fixture import make_dense
        from make_vc4_fc_fixture import schema
        model_path, ref_path = tmp_path/'dense.tflite', tmp_path/'dense.json'
        make_dense(model_path, ref_path, rows=32, cols=17)
        blob = model_path.read_bytes()
        root = schema.Model.GetRootAsModel(blob, 0)
        assert root.Version() == 3
        op = root.Subgraphs(0).Operators(0)
        assert op.BuiltinOptionsType() == schema.BuiltinOptions.FullyConnectedOptions
        weights = np.frombuffer(root.Buffers(1).DataAsNumpy().tobytes(), dtype='<f4').reshape(32,17)
        bias = np.frombuffer(root.Buffers(2).DataAsNumpy().tobytes(), dtype='<f4')
        assert np.all(weights != 0) and np.any(weights < 0) and np.any(weights > 0)
        assert len(set(map(tuple, weights))) == 32
        ref = json.loads(ref_path.read_text())
        assert ref['model_sha256'] == hashlib.sha256(blob).hexdigest()
        for negative, key in [(False, 'expected'), (True, 'expected_negated')]:
            x = [-v for v in ref['inputs']] if negative else ref['inputs']
            for row in range(32):
                actual = sum(float(weights[row,col])*x[col] for col in range(17)) + float(bias[row])
                assert actual == ref[key][row]
        make_dense(model_path, ref_path, rows=32, cols=17)
        assert model_path.read_bytes() == blob
    finally:
        sys.path.remove(str(PORT))
