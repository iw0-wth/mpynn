# Raspberry Pi 1B ML restoration status

## Current native integration

- `uml_binding.c` registers `uml.Model` and is in the active C source list.
- `uml_backend.cpp` is the pure C ABI wrapper around reference TFLM. It is compiled
  independently of Circle and MicroPython headers, with C++11, no exceptions and
  no RTTI, and links `libtflm-rpi1b-armv6-reference.a`.
- `MICROPY_PY_ML`, `MICROPY_PY_ML_TFLM` and `MICROPY_PY_ULAB` are enabled.
- The standard `ml` Python package remains frozen. The wrapper forwards
  `arena_size` to the native constructor.
- ulab 6.12.0 snapshot `d161443` is native C code under `modules/ulab/code`, matching
  OpenMV's module layout, not a frozen Python package. Four-dimensional arrays,
  numpy/scipy upstream defaults and complex support are enabled.

## ML contract

`uml.Model(path_or_buffer, postprocess=None, arena_size=2097152)` loads a VFS file
or copies model bytes into GC-owned aligned storage. The arena is bounded to
1KiB..64MiB; the Pi1B GC heap remains 16MiB, so larger requests fail naturally.

`predict(inputs, callback=None)` accepts a list/tuple of ulab arrays or callable
inputs. Callable inputs are invoked as `__call__(bytearray, shape, dtype)` where
`dtype` is an integer typecode (for example `ord('f')`). Their bytearrays own their
memory and are copied back to tensor storage after the call. Retaining the
bytearray therefore does not retain a dangling arena pointer. Array inputs support
strides and float/quantized conversion. Outputs are independent float ulab arrays,
including dequantization. A callback receives `(model, inputs, outputs)` and its
return value becomes the prediction result. Constructor postprocessing is used
when no explicit callback is supplied. Busy-state guards reject recursive predict,
deinit or native reinitialization during callbacks; cleanup is exception-safe.

## Verification boundary

- Real full C binding strict ARM syntax and bounded real-function host tests pass;
  these include buffer ownership, NLR cleanup, stream failures, stride conversion,
  quantization and output copies. These tests use a bounded backend harness and
  are not proof of TFLM inference.
- All 33 actual ulab C sources passed strict ARM1176 VFP hard-float syntax checks;
  all 70 copied upstream files match their recorded SHA-256 provenance.
- Full Pi1B firmware link passes, latest image 1,387,208 bytes; static layout
  validation passes. The ELF contains `uml_module`, `ulab_user_cmodule`,
  `image_file_module`, `audio_module`, `uml_backend_invoke`, real TFLM
  AllocateTensors and Invoke.
- Pi1B GC heap now uses measured Circle low-memory space after platform
  initialization, reserves 32 MiB for Circle networking/USB/SD work, and requires
  at least 16 MiB for MicroPython. This replaces the old fixed 16 MiB heap so the
  512 MiB board can use its available ARM RAM for larger model bytes and arenas.
- Latest image SHA-256: `626528d7649305cf159b4c64d3a28052e36a04ac680420879d61dc67d393132e`.
- Real host TFLM backend execution passes hello_world_float sine inference and the
  malformed/alignment/small-arena/destroy harness. Real Windows MicroPython
  integration passes float and int8 prediction, callback identity, callable input,
  output/bytearray lifetime after GC, PNG normalization, 4D ulab and WAV audio.
- No Pi hardware execution is claimed by any host/static result.

The earlier prototype's claimed exception/schema blocker was misdiagnosed:
GCC 15 rejects hosted standard library headers when compiled as `-ffreestanding`.
The TFLM translation unit now uses the same standard-header mode as the standalone
library while retaining no exceptions/RTTI and complete isolation from Circle
headers. No generated schema stripping or exception runtime is needed.

## VFS image/audio subset

The native `image` module loads PNG (OpenMV LodePNG), uncompressed BMP24/BMP32
and PNM P1..P6 files. Pixel access, ROI crop/draw, resize, grayscale and ulab tensor
conversion are implemented. Images and ndarrays own their buffers; the ML
Normalization callable explicitly commits converted tensor bytes after arithmetic.
JPEG is explicitly unsupported; it raises `NotImplementedError` rather than
returning fake pixels. All four image C files pass strict ARM syntax tests; ten
actual-codec/core/binding host tests pass and the device-only test is skipped.

The native `audio` module provides WAV PCM16 little-endian and explicit raw PCM
file sources with `init`, `start_streaming`, `stop_streaming`, `deinit`, `poll`.
The VM poll and reset hooks are wired; callbacks never run in hardware IRQs.
The first audio tests only checked Python fixtures/contracts, so native parser,
callback and lifecycle host tests are still required before claiming runtime support.

Camera capture, IDE preview, sensor drivers and accelerated kernels remain absent.
The user selected WAV/PCM file input first, not USB/I2S/ADC capture. Live audio
hardware requires an explicit later backend and device validation.

## Remaining verification

Real host TFLM inference and the complete malformed/alignment/arena/destroy
harness pass. A real Windows MicroPython runtime (1,352,704 bytes) now executes
native ulab 4D, PNG VFS image conversion/Normalization, float and int8 Model
prediction, outer-Python callback identity/labels, callable bytearray input,
output lifetime after deinit/GC, WAV callbacks/EOF/reinit, and MicroSpeech import
and constants. Its runtime integration test passes. Native audio C regression is
7 passed, and the final ARM build passes after reset fencing and minimal libc glue.
Board acceptance remains a separate hardware step.
