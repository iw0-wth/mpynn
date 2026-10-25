# Native MicroPython host ML runtime (Windows)

This is an isolated host-only build configuration. It uses the upstream
`lib/micropython/ports/windows/Makefile` without modifying that port or project
library sources. It builds all 33 upstream ulab C translation units, the native
file-image/PNG module, WAV audio module, and Raspberry Pi UML binding/backend.
The backend is compiled as C++ and linked against the real host TFLM archive;
there is no fake backend in the interpreter.

## Build

Run from the checkout root in PowerShell (the `bash -lc` command sets the full
UCRT64/native DLL path). Use the requested Python executable only:

```powershell
$script = "cd /d/openmv_aicore/mpynn/lib/micropython/ports/windows && export PATH=/e/msys64/ucrt64/bin:/e/msys64/usr/bin:`$PATH && make BUILD=../../../../build/host-tests/ml-runtime VARIANT_DIR=../../../../tests/host_ml_variant FROZEN_MANIFEST= PROG=ml-runtime.exe USER_C_MODULES=../../../../tests/host_ml_usermod PYTHON=/d/anaconda3/python.exe"
& 'E:\msys64\usr\bin\bash.exe' -lc $script
```

`PROG=ml-runtime.exe` is intentional: GCC creates a `.exe` on Windows, while the
upstream strip rule uses the `PROG` name verbatim. To test the generated runtime:

```powershell
& 'D:\anaconda3\python.exe' -m pytest -q mpynn/tests/raspberrypi/test_ml_native_runtime.py -s
```

The integration test uses the real `tflite-micro` hello-world float/int8 model
fixtures, actual Python `ml.Model`, and the real image/audio/ulab native modules.
The final successful runtime was 1,352,704 bytes with SHA-256
`D8B25D4556A6A727B13BDE6E5DE52AFDACB128093382F1B25781A73CA0828FBB`.
It copies only the required Python library modules and model/image/audio fixtures
to a temporary working directory for the interpreter. No Python implementation
of a native module is used.

## TFLM ABI note

The host TFLM archive was built with `TF_LITE_STATIC_MEMORY`,
`TF_LITE_DISABLE_X86_NEON`, `KERNELS_OPTIMIZED_FOR_SIZE`, and
`TF_LITE_STRIP_ERROR_STRINGS`. These defines must be present when compiling
`uml_backend.cpp`; in particular, `TF_LITE_STATIC_MEMORY` changes TFLM tensor
layout. If the makefile flags change, force a rebuild of
`build/host-tests/ml-runtime/ports/raspberrypi/uml_backend.o` before relinking.
The successful archive is
`build/host-tests/uml_backend/genrel/linux_x86_64_release_gcc/lib/libtensorflow-microlite.a`.
