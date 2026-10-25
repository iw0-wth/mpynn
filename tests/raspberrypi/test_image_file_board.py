# SPDX-License-Identifier: MIT
"""Run on Raspberry Pi MicroPython; uses /sd for a tiny real file fixture.

Requires the native image/ulab modules. Host discovery skips device checks.
"""
import sys


def run():
    import image
    from ulab import numpy as np

    assert not hasattr(image, '__file__'), 'image must be a native built-in module'
    path = '/sd/image_file_acceptance.pgm'
    try:
        with open(path, 'wb') as file:
            file.write(b'P5\n2 2\n255\n\x00\x40\x80\xff')
        loaded = image.Image(path)
        assert loaded.width() == 2 and loaded.height() == 2
        assert loaded.format() == image.GRAYSCALE
        assert loaded.get_pixel(1, 1) == 255
        loaded.set_pixel(0, 0, 32)
        assert loaded.get_pixel(0, 0) == 32
        copied = loaded.copy(roi=(1, 0, 1, 2))
        assert copied.width() == 1 and copied.get_pixel(0, 1) == 255
        resized = loaded.resize(1, 1)
        assert resized.width() == 1 and resized.height() == 1

        original = bytearray([10, 20])
        owned = image.Image(2, 1, image.GRAYSCALE, buffer=original)
        original[:] = b''
        assert owned.get_pixel(0, 0) == 10
        target = bytearray(8)
        array = owned.to_ndarray(ord('f'), buffer=target)
        assert array.shape == (1, 2) and array.tolist() == [[10.0, 20.0]]
        assert np.frombuffer(target, dtype=np.float).tolist() == [10.0, 20.0]
        array += 1
        assert np.frombuffer(target, dtype=np.float).tolist() == [10.0, 20.0]
        target[:] = b''
        assert array.tolist() == [[11.0, 21.0]]

        color = image.Image(2, 1, image.RGB565)
        color.set_pixel(0, 0, (255, 0, 0))
        color.set_pixel(1, 0, (0, 255, 0))
        assert color.get_pixel(0, 0) == (255, 0, 0)
        assert color.to_ndarray('B').shape == (1, 2, 3)
        gray = color.to_grayscale(copy=True)
        assert gray.format() == image.GRAYSCALE
        assert color.format() == image.RGB565
        destination = image.Image(4, 4, image.GRAYSCALE)
        destination.draw_image(gray, 0, 0, roi=(0, 0, 2, 1),
                               hint=image.BILINEAR | image.CENTER |
                               image.SCALE_ASPECT_IGNORE | image.BLACK_BACKGROUND)
        assert destination.get_pixel(0, 0) == gray.get_pixel(0, 0)
        print('native file image pixel/tensor acceptance passed')
    finally:
        import os
        try:
            os.remove(path)
        except OSError:
            pass


if sys.implementation.name == 'micropython':
    run()
else:
    import unittest

    @unittest.skip('requires Raspberry Pi firmware with native image and an SD card')
    class ImageFileBoardAcceptance(unittest.TestCase):
        def test_native_file_image_pipeline(self):
            run()
