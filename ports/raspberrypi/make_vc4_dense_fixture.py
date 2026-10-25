"""Generate deterministic dense signed FC and independent float64 goldens.
Run with D:/anaconda3/python.exe; no TensorFlow package required.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from make_vc4_fc_fixture import make_model


def make_dense(output, reference, rows=1024, cols=2048):
    if cols < 1 or rows < 1 or rows % 16:
        raise ValueError('rows must be a positive multiple of 16, cols positive')
    # Integer hash: no dependence on a particular NumPy RNG version. Magnitudes
    # are 1..8 / 64 and every entry is nonzero; signs and row fingerprints vary.
    index = np.arange(rows * cols, dtype=np.uint32)
    value = index + np.uint32(0x9e3779b9)
    value = (value ^ (value >> 16)) * np.uint32(0x85ebca6b)
    value = (value ^ (value >> 13)) * np.uint32(0xc2b2ae35)
    value ^= value >> 16
    magnitude = ((value >> 1) % 8 + 1).astype(np.float64) / 64
    weights = (magnitude * np.where(value & 1, 1.0, -1.0)).reshape(rows, cols)
    bias = ((np.arange(rows) % 17).astype(np.float64) - 8) / 128
    x = (((np.arange(cols, dtype=np.int64) * 37) % cols) - cols / 2 + 0.5) / cols
    x = x.astype(np.float32).astype(np.float64)
    # Each product is exact in binary64; this oracle is independent of both
    # the scalar reference accumulation order and the packed address traversal.
    dot = (weights * x[None, :]).sum(axis=1, dtype=np.float64)
    make_model(Path(output), cols, rows, weights_data=weights.ravel(), bias_data=bias)
    result = {
        'schema': 1, 'input_depth': cols, 'output_depth': rows,
        'model_sha256': hashlib.sha256(Path(output).read_bytes()).hexdigest(),
        'inputs': x.tolist(), 'expected': (dot + bias).tolist(),
        'expected_negated': (-dot + bias).tolist(),
        'absolute_tolerance': 1e-4, 'relative_tolerance': 1e-4,
        'oracle': 'binary64 dot over exact signed dyadic FP32 weights/input/bias',
    }
    Path(reference).write_text(json.dumps(result, separators=(',', ':')) + '\n', encoding='utf-8')
    print('reference', reference, 'model_sha256', result['model_sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--rows', type=int, default=1024)
    parser.add_argument('--cols', type=int, default=2048)
    args = parser.parse_args()
    make_dense(args.output, args.reference, args.rows, args.cols)
