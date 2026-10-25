# Native ML runtime evidence

## ARM firmware

### Pi1B RAM policy

The Pi1B ARM port no longer hardcodes a 16 MiB GC heap. After Circle initializes
SD/USB/network devices, `kernel.cpp` queries `CMemorySystem::Get()->GetHeapFreeSpace`
for the measured low-memory region, reserves 32 MiB for Circle's future network,
USB and filesystem allocations, and gives the remainder to MicroPython GC. It
requires at least 16 MiB for GC. This uses the ARM-memory size reported by the
Pi property tag, so a 512 MiB board with a normal GPU split can expose hundreds
of MiB without pretending that all physical RAM is safe for the VM. TFLM model
bytes and tensor arenas are then allocated from this GC heap; the native backend
still bounds each arena to 1 KiB..64 MiB.

The Windows validation port uses a separate 256 MiB host GC heap and does not
change Pi memory policy. At boot the Pi logger now prints measured Circle low free,
selected GC heap and reserve in MiB; this is the authoritative board-specific
number to record, because GPU split and Circle device allocations vary.

User board measurement: `Circle low free 438 MiB, MicroPython GC 406 MiB, reserve
32 MiB`. Thus 438 MiB is the measured post-Circle low-memory pool, 406 MiB is the
actual GC heap, and 32 MiB is the deliberate Circle reserve. The remaining part of
the nominal 512 MiB is GPU split, kernel/page/coherent memory and Circle allocations;
it is not lost MicroPython heap. Code-level optimization is not currently needed
for the verified models. A further conservative optimization is lowering the
reserve to 16 MiB after long USB/network/SD stress, which would expose about 422
MiB GC on this exact boot. The largest improvement comes from reducing the Pi
`gpu_mem` split in `config.txt` (subject to Circle/USB/display requirements), then
rechecking this log; the firmware must not assume the nominal 512 MiB.

The Pi1B ARM image is built with the native `uml`, `ulab`, file `image`, and file
`audio` modules. The linker contains:

- `uml_module`
- `ulab_user_cmodule`
- `image_file_module`
- `audio_module`
- `uml_backend_invoke`
- `tflite::MicroInterpreter::AllocateTensors()`
- `tflite::MicroInterpreter::Invoke()`

The latest completed build after reset-fencing and TFLM libc cleanup is 1,386,712
bytes and passes the static ARMv6 hard-float layout checker. The ELF still contains
all four native modules and TFLM AllocateTensors/Invoke.

## Host TFLM

The independently built host reference archive is:

```text
mpynn/build/host-tests/uml_backend/genrel/linux_x86_64_release_gcc/lib/libtensorflow-microlite.a
```

Size: 2,168,122 bytes.

SHA-256:

```text
7DE74318DB72D0ED5DB11C94C4D4768DBF20C3A1C2BB4B9234241B7C4DD43778
```

A native host harness has run `hello_world_float.tflite` and checked sine outputs
for multiple inputs. The harness also checks state/arena alignment, malformed model
rejection, small-arena rejection, idempotent destroy, tensor metadata and invalid
indices. The persisted harness now passes all these checks, including truncated, zeroed,
and schema-valid-but-empty-subgraph models. It lives in
`tests/raspberrypi/uml_backend_runtime_test.cpp` and is built/run by
`test_uml_backend_runtime.py`. An independently repeated run passed in 21.63s.
The generated report is `build/host-tests/uml_backend/uml_backend_runtime_report.json`.
It records compiler flags, model/archive SHA-256 hashes and native-host verification
scope. This does not execute Raspberry Pi hardware.

## Python/native contract tests

All project `tests/...` paths in this historical report now refer to workspace
`tests/`, sibling to mpynn (`../../../tests/` relative to this document).
Board smoke/VC4 benchmark scripts also live there; normal user examples are in
`mpynn/demo/`. The test move does not change the old report's hardware scope.

- `tests/test_uml_binding_host.py`: native C binding ARM syntax and host lifetime,
  conversion, callback, NLR and output-copy tests.
- `tests/raspberrypi/test_ml_wrapper.py`: public Python `ml.Model` forwards
  `arena_size`, maps callbacks back to the outer Python object, and rejects invalid
  callbacks.
- `tests/raspberrypi/test_ulab_native.py`: all 33 ulab C sources, 70-file hash
  provenance and ARMv6 strict syntax.
- `tests/raspberrypi/test_image_file_*.py`: actual PNG/BMP/PNM codecs, processing,
  ownership, bounds and ARM syntax; one device-only test is skipped.
- `tests/raspberrypi/test_audio_file_*.py`: WAV/PCM fixtures and API contracts.

Host/static tests are not board execution. The Pi1B acceptance script remains the
final check for SD/VFS model loading, native ulab, image file processing, audio file
polling and actual model inference.
