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
import uml
from ml.preprocessing import Normalization


class Model(uml.Model):
    """Public ML model facade with a reserved backend-selection argument.

    Supported selectors on the Raspberry Pi backend are ``reference`` and
    ``vc4``. ``None``/``auto`` preserve the process-level machine.vc4 switch.
    This keeps ml.Model as the single public API while leaving room for future
    backends without adding any new backend implementation today.
    """
    _BACKENDS = (None, "auto", "reference", "vc4")

    @staticmethod
    def _switch_backend(backend):
        if backend in (None, "auto"):
            return None
        try:
            import machine
        except ImportError:
            if backend == "reference":
                return None
            raise ValueError("VC4 backend is unavailable on this platform")
        if not hasattr(machine, "vc4"):
            if backend == "reference":
                return None
            raise ValueError("VC4 backend control is unavailable")
        previous = machine.vc4()
        machine.vc4(backend == "vc4")
        return (machine, previous)

    @staticmethod
    def _restore_backend(token):
        if token is not None:
            machine, previous = token
            machine.vc4(previous)

    def __init__(self, *args, **kwargs):
        backend = kwargs.pop("backend", None)
        if backend not in self._BACKENDS:
            raise ValueError("backend must be 'auto', 'reference', or 'vc4'")
        postprocess = kwargs.pop("postprocess", None)
        self._backend = "auto" if backend is None else backend
        if postprocess is not None:
            # Native-base methods receive the native subobject. Public callbacks
            # must see this Python Model (including labels/custom attributes).
            native_postprocess = lambda model, inputs, outputs: postprocess(self, inputs, outputs)
        else:
            native_postprocess = None
        backend_token = self._switch_backend(backend)
        try:
            super().__init__(*args, native_postprocess, **kwargs)
        finally:
            self._restore_backend(backend_token)
        try:
            path = args[0].split(".")[0] + ".txt"
            self.labels = [line.rstrip('\n') for line in open(path, "r")]
        except Exception:
            self.labels = None

    @property
    def backend(self):
        """Selected public backend name (auto/reference/vc4)."""
        return self._backend

    def predict(self, args, **kwargs):
        # Tensor and callable inputs do not require the optional image module.
        try:
            import image
        except ImportError:
            image = None
        args = [
            Normalization()(x) if image is not None and isinstance(x, image.Image) else x
            for x in args
        ]
        callback = kwargs.get("callback", None)
        if callback is not None:
            if not callable(callback):
                raise TypeError("callback must be callable")
            kwargs["callback"] = lambda model, inputs, outputs: callback(self, inputs, outputs)
        backend_token = self._switch_backend(self._backend)
        try:
            return super().predict(args, **kwargs)
        finally:
            self._restore_backend(backend_token)
