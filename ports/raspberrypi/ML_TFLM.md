# Raspberry Pi 1B ML/TFLM integration

`lib/tflm/libtflm/lib/libtflm-rpi1b-armv6-reference.a` is built separately from
`D:/openmv_aicore/tflite-micro` with the TFLM Makefile target `rpi1b` and custom
`rpi1b_makefile.inc`:

- `-mcpu=arm1176jzf-s -marm -mfpu=vfp -mfloat-abi=hard`
- reference/portable kernels only;
- no CMSIS-NN, CMSIS-DSP, Ethos-U, NPU, or accelerator target;
- `BUILD_TYPE=release`, `KERNELS_OPTIMIZED_FOR_SIZE`.

The Raspberry Pi Makefile links this archive through the active native
`uml_binding.c` + `uml_backend.cpp` pair; `MICROPY_PY_ML_TFLM=1` is enabled.
Python `ml` package files are frozen from `scripts/libraries/ml` through the port
manifest. The C binding owns VFS/GC/callbacks; the no-exception C++ TFLM backend
has no Circle or MicroPython headers. Its standard-library header mode matches
the archive build and avoids the GCC 15 `-ffreestanding` header restriction.
Full ARM linking is verified with real `MicroInterpreter::AllocateTensors()` and
`Invoke()` symbols in the resulting ELF, rather than merely listing an unused
archive in the linker command. ulab is a native C module under `modules/ulab`.

The archive is a code-level ARMv6 build artifact, not proof of model inference on
Pi hardware. Model arena sizing, operator coverage, and real inference still require
board validation.
