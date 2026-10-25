# Copyright (C) 2024 OpenMV, LLC.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the
#    distribution.
# 3. Any redistribution, use, or modification in source or binary form
#    is done solely for personal benefit and not for any commercial
#    purpose or for monetary gain. For commercial licensing options,
#    please contact openmv@openmv.io
#
# THIS SOFTWARE IS PROVIDED BY THE LICENSOR AND COPYRIGHT OWNER "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE LICENSOR OR COPYRIGHT
# OWNER BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
# OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
class Normalization:
    """Optional image-to-tensor adapter for Model.predict callable inputs."""

    def __init__(
        self,
        scale=(0.0, 1.0),
        mean=(0.0, 0.0, 0.0),
        stdev=(1.0, 1.0, 1.0),
        roi=None,
    ):
        self.scale = scale
        self.mean = mean
        self.stdev = stdev
        self.roi = roi
        self._image = None

    def __call__(self, *args):
        try:
            import image
        except ImportError:
            raise ImportError("Normalization requires the optional image module")

        if len(args) == 1:
            img = args[0]
            if not isinstance(img, image.Image):
                raise ValueError("Expected an image input")
            if self.roi is None:
                self.roi = (0, 0, img.width(), img.height())
            n = Normalization(self.scale, self.mean, self.stdev, self.roi)
            n._image = img
            return n

        buffer, shape, dtype = args
        if self._image is None:
            raise ValueError("Bind an image with Normalization()(img) before preprocessing")

        # Create an image using the input tensor as buffer.
        if len(shape) != 4:
            raise ValueError("Expected input tensor with shape: (1, H, W, C)")
        b, h, w, c = shape
        if b != 1:
            raise ValueError("Expected batches to be 1")
        if c != 1 and c != 3:
            raise ValueError("Expected channels to be 1 or 3")

        # Own the staging image independently of the callable's bytearray.
        # This also permits single-channel int8/uint8 tensors without aliasing.
        pixfmt = image.GRAYSCALE if c == 1 else image.RGB565
        img = image.Image(w, h, pixfmt)

        # Copy and scale (if needed) the input image to the input buffer.
        hints = image.BILINEAR | image.CENTER | image.SCALE_ASPECT_IGNORE | image.BLACK_BACKGROUND
        img.draw_image(self._image, 0, 0, roi=self.roi, hint=hints)

        # Native file images return an owned ndarray, not a borrowed arena view.
        array = img.to_ndarray(dtype)

        # Normalize the input tensor.
        if dtype == ord('f'):
            fscale = (self.scale[1] - self.scale[0]) / 255.0
            fadd = self.scale[0]

            def grayscale(x):
                return (x[0] * 0.299) + (x[1] * 0.587) + (x[2] * 0.114)

            if c == 1:
                fadd = (fadd - grayscale(self.mean)) / grayscale(self.stdev)
                fscale = fscale / grayscale(self.stdev)
            else:
                from ulab import numpy as np

                fadd = (fadd - np.array(self.mean)) / np.array(self.stdev)
                fscale = fscale / np.array(self.stdev)

            # Apply normalization in-place (must be done in two steps for ulab).
            array *= fscale
            array += fadd

        # Explicitly commit after normalization. No ndarray/Image object may
        # outlive or alias the callable input storage owned by the UML binding.
        payload = array.tobytes()
        if len(payload) != len(buffer):
            raise ValueError("Converted image tensor byte size mismatch")
        # MicroPython bytearray slice assignment is not implemented on every
        # port (notably the Raspberry Pi build). A writable memoryview keeps
        # this byte-oriented and avoids one Python-level loop per pixel.
        try:
            memoryview(buffer)[:] = payload
        except (TypeError, ValueError):
            for i in range(len(payload)):
                buffer[i] = payload[i]
