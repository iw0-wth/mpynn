# SPDX-License-Identifier: MIT
"""Run on the Raspberry Pi MicroPython REPL with exec(open(...).read()).

This acceptance test imports the native built-in ulab module. CPython discovery
skips it; there is deliberately no NumPy fallback or Python implementation.
"""
import sys


def run():
    import ulab
    from ulab import numpy as np
    from ulab import scipy

    assert ulab.__version__ == '6.12.0-4D-c', ulab.__version__
    assert not hasattr(ulab, '__file__'), 'ulab must be a native built-in module'
    assert hasattr(scipy, 'linalg') and hasattr(scipy, 'signal')
    assert hasattr(np, 'fft') and hasattr(np, 'linalg') and hasattr(np, 'random')

    array = np.array([1, 2, 3, 4], dtype=np.float)
    assert type(array) is np.ndarray
    assert (array + 2).tolist() == [3.0, 4.0, 5.0, 6.0]
    assert (array * 2 - 1).tolist() == [1.0, 3.0, 5.0, 7.0]
    assert (array / 2).tolist() == [0.5, 1.0, 1.5, 2.0]
    array += 1
    assert array.tolist() == [2.0, 3.0, 4.0, 5.0]
    assert np.max(array) == 5.0 and np.min(array) == 2.0
    assert np.argmax(array) == 3
    assert np.roll(array, 1).tolist() == [5.0, 2.0, 3.0, 4.0]

    buffer = bytearray([1, 2, 3, 4])
    view = np.frombuffer(buffer, dtype=np.uint8)
    assert view.tolist() == [1, 2, 3, 4]
    # frombuffer must preserve the upstream zero-copy buffer contract.
    buffer[1] = 9
    assert view[1] == 9
    view[2] = 8
    assert buffer[2] == 8

    tensor = np.zeros((1, 2, 2, 1), dtype=np.float)
    assert tensor.shape == (1, 2, 2, 1) and tensor.ndim == 4
    tensor[0, 1, 1, 0] = 7
    assert np.max(tensor) == 7.0
    matrix = tensor.reshape((2, 2))
    assert matrix.shape == (2, 2)
    assert matrix.tolist() == [[0.0, 0.0], [0.0, 7.0]]
    assert matrix[:, 1].tolist() == [0.0, 7.0]
    assert np.max(matrix, axis=0).tolist() == [0.0, 7.0]
    print('native ulab', ulab.__version__, 'array/tensor acceptance passed')


if sys.implementation.name == 'micropython':
    run()
else:
    import unittest

    @unittest.skip('requires the Raspberry Pi MicroPython firmware and native ulab')
    class UlabBoardAcceptance(unittest.TestCase):
        def test_native_arrays(self):
            run()
