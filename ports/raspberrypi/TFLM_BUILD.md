# Pi1B TFLM standalone build

The archive was built from `D:/openmv_aicore/tflite-micro` with the Makefile target
`rpi1b`, `TARGET_ARCH=armv6`, release and reference kernels:

```text
make -f tensorflow/lite/micro/tools/make/Makefile \
  TARGET=rpi1b TARGET_ARCH=armv6 BUILD_TYPE=release \
  OPTIMIZE_KERNELS_FOR=KERNELS_OPTIMIZED_FOR_SIZE
```

The custom target is `tensorflow/lite/micro/tools/make/targets/rpi1b_makefile.inc`.
It uses ARM1176JZF-S ARM state, hard-float VFP and no CMSIS-NN/CMSIS-DSP/Ethos-U.
The resulting archive is:

```text
mpynn/lib/tflm/libtflm/lib/libtflm-rpi1b-armv6-reference.a
```

Dependencies used by the Makefile:

- FlatBuffers `v23.5.26`: https://github.com/google/flatbuffers/archive/v23.5.26.zip
- KissFFT `v130`: https://github.com/mborgerding/kissfft/archive/refs/tags/v130.zip
- Gemmlowp `719139ce755a0f31cbf1c37f7f98adcc7fc9f425`: https://github.com/google/gemmlowp/archive/719139ce755a0f31cbf1c37f7f98adcc7fc9f425.zip
- RUY `d37128311b445e758136b8602d1bbd2a755e115d`: https://github.com/google/ruy/archive/d37128311b445e758136b8602d1bbd2a755e115d.zip
- Pigweed `47268dff45019863e20438ca3746c6c62df6ef09`: https://pigweed.googlesource.com/pigweed/pigweed/+/47268dff45019863e20438ca3746c6c62df6ef09?format=zip

The archive is now linked through the active `uml_binding.c`/`uml_backend.cpp`
implementation. The TFLM C++ translation unit uses its own include/flag set, without
Circle headers or `-ffreestanding`, while retaining `-fno-exceptions` and
`-fno-rtti`. This corrects the GCC 15 standard-header compile failure in the first
prototype; it does not require an exception runtime or generated-schema edits.
