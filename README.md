# mpynn — MicroPython Neural Network

English | [简体中文](README.zh-CN.md)

Project home: [GitHub](https://github.com/iw0-wth/mpynn) · [Gitee mirror](https://gitee.com/wth_iw0/mpynn)

**mpynn (MicroPython Neural Network) is a MicroPython firmware project specialized for AI inference and computation.**
It takes OpenMV's project organization and ML API design as its starting point, retains `ml.Model` as the public
entry point, and uses the standard MicroPython core, the TFLM inference engine, and replaceable hardware backends,
focusing on neural networks, tensor computation, and device applications.

mpynn also retains **the ability to serve as a foundation for further ports of OpenMV features**: it keeps the
relevant source code, project organization, and extensible board/module boundaries to support later integration
of image processing, capture, display, or other OpenMV capabilities for target hardware. Its AI specialization
is reflected in the choices made for the default firmware; these capabilities require actual porting and
validation before they can be enabled, and full OpenMV compatibility is not currently available on every port.

The current primary target is **Raspberry Pi 1 Model B / BCM2835 / VideoCore IV**: Circle provides bare-metal
platform services, MicroPython provides interaction, scripting, and the filesystem, TFLM executes models, and
VC4 accelerates eligible FP32 fully connected layers. The Windows port provides host validation using the real
MicroPython/native ML stack. Other boards can be added through board-level entry points; existing legacy board
directories do not indicate completed mpynn support.

**Future ports will focus on MCUs with NPUs and SoCs with sufficient compute capacity and memory.** New ports
will adapt to the available inference engine, NPU/GPU/CPU backends, tensor memory, and data paths, reusing the
public Python API and model lifecycle where possible. RPI1B/VC4 is the current implementation target; it does
not limit the project's long-term scope to Raspberry Pi or any single type of accelerator.

## Origins and Version Baseline

The project's OpenMV baseline comes from `D:/openmv_aicore/openmv-master` in the workspace, corresponding to:

- Upstream repository: [openmv/openmv](https://github.com/openmv/openmv).
- Upstream commit: [`222310c96500a7f6d63a37ae90e02db8dbbe35f7`](https://github.com/openmv/openmv/commit/222310c96500a7f6d63a37ae90e02db8dbbe35f7).
- Identification: the Git commit identifier in the original source ZIP, checked file by file against that
  commit's Git tree/blobs. All 4,488 upstream files in the local `openmv-master` directory also match, with
  no missing files or content differences. Neither the archive name `master` nor `SDK_VERSION=1.7.3` is an
  adequate substitute for the exact version.

This identifies **the source version of the OpenMV project**, not the versions of all current dependencies.
mpynn has switched to the standard MicroPython v1.29.0 core and pins other dependencies independently through
[.gitmodules](.gitmodules). The original OpenMV branding, camera product descriptions, and full feature list
do not constitute a feature commitment for mpynn.

## Project Scope and Execution Structure

mpynn targets inference applications in which users supply models and data: tensors, image files, audio files,
networking, and board-level I/O can be combined. Cameras and IDE previews are not prerequisites for running ML.

```text
Python application
    ml.Model / preprocessing / callbacks
        native uml.Model + ulab
            TFLM MicroInterpreter + standard operator resolver
                CPU kernels
                TFLM-VC4 FP32 FullyConnected -> vc4-runtime
                                                platform C callbacks
                                                    Circle adapter on RPI1B
```

Responsibilities of each layer:

| Layer | Current implementation and responsibilities |
| --- | --- |
| Python API | Retains `ml.Model`; handles labels, preprocessing, callbacks, and backend selection |
| Native bindings | `uml.Model` loads models, manages the arena, converts tensors, and returns independent ulab arrays |
| Inference engine | One TFLM archive, standard operator registration, and CPU or VC4 selection according to support conditions |
| VC4 runtime | Resident weights, packed16, multi-tile, QPU submission, caching, timeouts, and diagnostic state |
| Platform adaptation | Circle manages startup, memory/IRQs, SD, USB networking, and cooperative scheduling; connects to the runtime through a C interface |

[vc4-runtime](lib/vc4-runtime/README.md) and its included TFLM-VC4 integration files were written for mpynn and
can also be used by other BCM VC4 projects. The runtime itself does not depend on Circle or MicroPython;
other bare-metal frameworks can implement the same platform interface. BCM2835 is the current implementation
and hardware-tested baseline. Other SoCs require hardware protocol checks and validation.

## Changes from OpenMV: Removed, Retained, and Replaced

Here, “removed” primarily refers to **source selection and feature configuration in the current RPI1B firmware**.
Legacy ports, vendor SDKs, drivers, and examples retained in the repository have not necessarily been deleted,
but their presence does not automatically include them in the Pi firmware. These assets are also retained to
support further ports of OpenMV features on top of mpynn. Future ports can restore and adapt the relevant
modules as needed, without making the camera/IDE path a mandatory dependency of the AI core.

| Component | Current treatment on RPI1B |
| --- | --- |
| OpenMV camera sensor/CSI, sensor detection, and capture | Not compiled in; no stub that fabricates camera data |
| Camera framebuffer, snapshots/streaming, and IDE image preview | Not compiled in |
| OpenMV IDE transport, debugging/RPC protocols, and camera control path | Not compiled in; uses standard MicroPython raw/friendly REPL |
| LCD/display and camera-board-specific clock/GPIO/USB startup conventions | Not dependencies of the Pi port |
| Legacy boards and HALs such as STM32, Alif, and i.MX RT | Source retained for reference; not selected by the current Pi build |
| CMSIS-NN/DSP, Ethos-U, and ST/Alif-specific acceleration paths | Not used by the current Pi ML path |
| Full OpenMV image analysis library | Not imported wholesale as the native image module; replaced by an independent file-image subset |
| MicroPython | Uses the standard v1.29.0 core, with platform differences in the port and controlled adaptation layers |
| OpenMV ML Python package and `ml.Model` design | Retained and connected to the new native bindings/TFLM backend, with the camera dependency removed |
| ulab | Retains native C tensor computation, configured to support four-dimensional ndarrays |
| TFLM | Retains the standard model/schema/interpreter and operator APIs, with FP32 FC specialization |
| Python libraries such as requests / ntptime | Uses standard micropython-lib packages through manifests |
| AprilTag and other disabled submodules | Retains the original OpenMV pointers; this does not indicate that they are enabled on Pi |

See [OPENMV_CUTS.md](ports/raspberrypi/OPENMV_CUTS.md) for a detailed comparison. That document and interim
status files include historical snapshots; the port source, configuration, and this README define the current
feature selection.

## Currently Retained Runtime Capabilities

- **Language and interaction**: standard MicroPython VM/GC, compiler, raw/friendly REPL, Ctrl-C, soft reset,
  scheduler, JSON, select, floating-point and integer computation, and f-strings/t-strings enabled by configuration.
- **Storage**: FAT/VFS through Circle SDHOST/EMMC, with the boot card mounted at `/` and `boot.py` and
  `main.py` loaded from it. The same boot card is not exposed again as a separate `machine.SDCard` mount device.
- **Networking**: USB LAN9512 Ethernet, IPv4/DHCP/static configuration, UDP/TCP, DNS A, timeouts/poll,
  endpoint queries, and some socket options; mbedTLS through standard `tls`/`ssl`, and standard requests.
- **Board interfaces**: Pin, Pin IRQs deferred to the VM, hardware I2C/SPI, SoftI2C/SoftSPI, Timer, WDT,
  software RTC/time, and memory/board diagnostics. UART0 serves the REPL; general-purpose UART/PWM classes
  are not yet enabled.
- **ML**: frozen `ml` package, native `uml.Model`, and ulab; supports model files or bytes, ndarray/callable
  inputs, postprocess callbacks, quantized input conversion, and output dequantization. VC4 currently
  accelerates only eligible FP32 FC operations; quantized and other operators use their corresponding CPU implementations.
- **File media**: native `image` supports decoding PNG, uncompressed BMP, and PNM, pixel access,
  cropping/resizing/grayscale, limited drawing, and ndarray conversion. Native `audio` supports WAV PCM16/raw
  PCM files and VM callbacks. JPEG, the full OpenMV image API, cameras, and live microphone capture are not yet integrated.

These describe the scope currently integrated in the code; they do not mean that every API has complete
hardware test coverage. IPv6, full POSIX/CPython socket compatibility, threads, and native emitters are among
the features not currently enabled.

## RPI1B and VC4 Specialization

### Board and Runtime

- The first board is the Pi 1 Model B R2 / 512 MiB, with BCM2835, ARM1176JZF-S, AArch32, and VFPv2
  hard-float. The baseline configuration is fixed at **ARM 700 MHz / CORE 250 MHz**.
- The [RPI1B board entry point](ports/raspberrypi/boards/RPI1B/README.md) selects the board configuration
  before entering the shared port build. Future boards provide their own selection files and entry points,
  rather than adding more hardcoded branches to the shared Makefile.
- Circle owns startup, the MMU, IRQs, the platform heap, and scheduling. GC allocates from the measured
  available low-memory region, reserving 32 MiB for Circle networking/USB/SD work and requiring at least 16 MiB for GC.
- The ARM port's NLR/GC register save covers VFP callee-saved registers. Python callbacks run in the VM
  context, not in hardware IRQ handlers.

### Inference and Weight Layout

- TFLM retains the standard `Register_FULLY_CONNECTED()`; `CO_PROCESSOR=vc4` replaces the FC source file
  with the same name. It does not link two complete TFLM archives or change the model schema.
- Prepare allocates and uploads resident GPU weights. The original model remains row-major for CPU fallback.
- **multi-tile** lets each QPU loop over multiple 16-row tiles. For 1024x2048 / 12 QPUs, submissions drop
  from 6 to 1, workspace from 103056 to 13296 bytes, and uniforms from 98496 to 384 bytes. This change alone
  yields limited performance improvement; weight memory access remains the main bottleneck.
- **packed16** changes the GPU weight layout to `[tile][k][lane]`, so the 16 lanes for the same k read
  64 contiguous bytes, reducing TMU/cache waits. It does not change the number of weight bytes or modify the source model.
- CPU float fallback uses four accumulators with ARM VFP hard-float; bias and fused activation are handled
  on ARM. Prepare failures can fall back; timeout/I/O errors after submission do not silently rerun on the CPU.
- On timeout, resources that may still be in use by the QPU are retained and reclaimed through deferred-free
  once completion is confirmed.

The current production configuration is:

```text
VC4_ENABLE=1
VC4_MULTI_TILE=1
VC4_PACKED_WEIGHTS=1
VC4_PROFILE_COUNTERS=1
VC4_POLL_STRIDE=256
VC4_WAIT_SLEEP_US=10
```

See the [VC4 runtime README](lib/vc4-runtime/README.md) for the full algorithm, ABI, development history,
counters, and TFLM lifecycle description.

### Logging and Build Consistency

```python
import machine
machine.logs()                       # Retain the snapshot by default; it can be read repeatedly
machine.logs(clear=True)             # Explicitly consume the current logs
machine.vc4_reset_diagnostics()      # Restart diagnostic sampling before the next inference
```

The log ring allocates 16 KiB and retains up to 16383 bytes, overwriting the oldest content when full.
VC4 samples only the first 8 dispatches in each diagnostic session; reading logs does not trigger new
sampling. Log snapshots and restarting diagnostic sampling are separate mechanisms.

Windows builds normalize `BUILD` path representations between MSYS/native GCC, explicitly depend on generated
QSTR headers, and check the final ELF's string pool, frozen reference ranges, and memory layout when generating
the image. This is a general consistency check; it does not hardcode the expected import name of any Python
package. The build ID identifies source/configuration, while the image SHA-256 identifies the binary.
Neither substitutes for the other, and neither constitutes hardware acceptance.

## Public ML API

```python
import ml
from ulab import numpy as np

model = ml.Model('/model.tflite', backend='auto', arena_size=2 * 1024 * 1024)
try:
    # This shape is only an example; match model.input_shape / input_dtype in actual use.
    x = np.array([0.0], dtype=np.float).reshape((1, 1))
    outputs = model.predict([x])
    print(outputs)
finally:
    model.deinit()
```

`backend` accepts `auto`, `reference`, or `vc4`. `auto` preserves the current platform switches,
`reference` uses the CPU path, and `vc4` allows VC4 to be attempted. Selecting `vc4` does not guarantee
that every operator runs on the GPU. Verify actual eligibility, completion logs, and CPU/VC4 comparisons.
The application determines model shapes, data types, and arena size.

## Dependencies and Pinned Commits

[.gitmodules](.gitmodules) retains OpenMV's submodule path organization. The commits below are gitlinks
in the main repository, not floating versions that follow remote branches.

| Path | Repository | Pinned commit |
| --- | --- | --- |
| `lib/micropython` | [micropython](https://github.com/micropython/micropython) | `0fd6c573ea815774668bbb16b8e197c8822368b2` |
| `lib/tinyusb` | [tinyusb](https://github.com/hathach/tinyusb) | `aa0fc2e08f1c2dd6f026a431e8989357fbb4c5bf` |
| `modules/ulab` | [micropython-ulab](https://github.com/v923z/micropython-ulab) | `d161443327173bcf94c2616cb5de37e290af71ca` |
| `lib/tflm/libtflm` | [libtflm-mpynn](https://gitee.com/wth_iw0/libtflm-mpynn) | `9008e63d0acb5a3c739a46af85636e837c6835b2` |
| `lib/vc4-runtime` | [vc4-runtime](https://github.com/iw0-wth/vc4-runtime) | `284d73c2876fc53f53009b1e14bd1f4306419f06` |
| `lib/circle` | [circle](https://gitee.com/wth_iw0/circle) | `7a81e1b480fe7d19fc1fc695b89bff0a0848f44b` |
| `lib/apriltag` | [OpenMV apriltag](https://github.com/openmv/apriltag) | `636b9ba14ba8485c9fc09590cd4ef53f11427966` |
| `tools/alif` | [alif-security-toolkit](https://github.com/micropython/alif-security-toolkit) | `63698efe8567eed115fe620d5e5de75f460310d7` |
| `scripts/libraries/microdot` | [microdot](https://github.com/miguelgrinberg/microdot) | `b241dfce270883e5018f0b8ec8f5821ea4fe156e` |

The last three entries are inherited from OpenMV and are not dependencies of the current RPI1B port.
The tinyusb pointer is also retained in the project; Circle implements the current RPI1B USB host/LAN9512
support, so TinyUSB is not automatically used. Nested libraries copied inside MicroPython for development
have not been uniformly reset in this round. See [LOCAL_REPOSITORY.md](docs/LOCAL_REPOSITORY.md) for the
local state description.

### Using Gitee Mirrors When Connectivity Is Poor

If GitHub connectivity is unreliable, the main project is available from the [Gitee mirror](https://gitee.com/wth_iw0/mpynn).
Available dependency mirrors are listed below. You must still check out **the same full commit listed in the
table**; mirrors may lag behind, so do not simply switch to a mirror's default branch or another version.
If a mirror does not yet contain the specified commit, wait for synchronization or use GitHub.

| Dependency | Gitee mirror |
| --- | --- |
| MicroPython | https://gitee.com/wth_iw0/micropython |
| ulab | https://gitee.com/wth_iw0/micropython-ulab |
| TinyUSB | https://gitee.com/wth_iw0/tinyusb |
| VC4 runtime | https://gitee.com/wth_iw0/vc4-runtime |
| TFLM-VC4 external source | https://gitee.com/wth_iw0/tflite-micro-vc4 |

There is no need to modify and commit `.gitmodules` for local network conditions. Set local Git configuration
from the mpynn root directory:

```sh
git submodule init
git config submodule.src/micropython.url https://gitee.com/wth_iw0/micropython
git config submodule.src/omv/modules/ulab.url https://gitee.com/wth_iw0/micropython-ulab
git config submodule.src/lib/tinyusb.url https://gitee.com/wth_iw0/tinyusb
git config submodule.lib/vc4-runtime.url https://gitee.com/wth_iw0/vc4-runtime
git submodule update --init lib/micropython modules/ulab lib/tinyusb lib/vc4-runtime
```

`git submodule sync` restores the URLs from `.gitmodules`; set local overrides after sync when mirrors are
needed. The external TFLM-VC4 repository can likewise be cloned from Gitee into `tflite-micro`, followed by
checking out the pinned commit. `libtflm-mpynn` and Circle continue to use the Gitee URLs in the dependency
table, with their commits unchanged.

## Building RPI1B

Initialize the required first-level submodules from the mpynn root directory:

```sh
git submodule update --init lib/micropython lib/tinyusb modules/ulab \
  lib/tflm/libtflm lib/vc4-runtime lib/circle
```

GNU Make, Python 3, a matching ARM bare-metal toolchain, and nested dependencies such as micropython-lib/mbedTLS
required by the manifests are needed. These are already prepared in the existing development workspace.
For a fresh clone, complete the standard MicroPython dependency setup; initializing first-level submodules
does not mean that all nested dependencies are ready.

ARM TFLM-VC4 implementation and build repository: [iw0-wth/tflite-micro-vc4](https://github.com/iw0-wth/tflite-micro-vc4).
The source baseline used by this project is pinned to [`7cfd402ebb0cafa95021bc893ddcd74d4ef7f952`](https://github.com/iw0-wth/tflite-micro-vc4/commit/7cfd402ebb0cafa95021bc893ddcd74d4ef7f952).
Its role differs from `lib/tflm/libtflm`, which holds headers/library assets, and `lib/vc4-runtime`, which
provides the hardware runtime.

**The current Pi Makefile links by default to an ARM TFLM-VC4 archive built separately in the sibling
workspace directory `../tflite-micro`.** In a new workspace, obtain the source from the repository above and
name its local directory `tflite-micro`, alongside mpynn. The CPU reference archive in `lib/tflm/libtflm`
cannot be treated as a VC4-specialized archive. Before the first build, prepare compatible source/overlays
and build with `TARGET=rpi1b CO_PROCESSOR=vc4`, or set `TFLM_LIB` to the absolute path of an existing compatible
ARM TFLM-VC4 archive. This external source repository is not currently a first-level submodule of the main
repository. Explicitly check out the pinned commit above; do not treat the remote default branch as a fixed version:

```sh
# Run from the workspace root, with mpynn and tflite-micro as sibling directories.
git clone https://github.com/iw0-wth/tflite-micro-vc4.git tflite-micro
git -C tflite-micro checkout --detach 7cfd402ebb0cafa95021bc893ddcd74d4ef7f952
```

See [TFLM-VC4 integration](lib/vc4-runtime/integrations/tflm/README.md) for details.

Windows/MSYS2 example for this workspace:

```sh
export PATH=/e/arm-none-eabi/bin:/usr/bin:$PATH
cd /d/openmv_aicore/mpynn
make -C ports/raspberrypi/boards/RPI1B -j8 PYTHON=D:/anaconda3/python.exe

# Compatible top-level entry point; also goes through board selection:
make TARGET=RPI1B -j8 PYTHON=D:/anaconda3/python.exe
```

You can append `TFLM_LIB=<absolute-path-to-ARM-VC4-archive>`. On POSIX, use a matching `arm-none-eabi-`
toolchain and the local Python 3. Output defaults to `build/RPI1B/bin/`, including the image, ELF, map,
and layout report. Objects, Circle build stages, and tool outputs also stay under `build/`, without
modifying existing upstream source code.

By default, `make` or `make ... kernel` produces only the kernel. To create a complete SD image, use:

```sh
make -C ports/raspberrypi/boards/RPI1B sd-image -j8 \
  PYTHON=D:/anaconda3/python.exe SD_BOOT_DIR=/d/openmv_aicore/RPI1B-SD/boot
```

`sd-image` first builds the current kernel, then packages local boot files, the current board configuration,
and the kernel into `build/RPI1B/bin/mpynn-RPI1B-sd.img`. By default, it contains a single 128 MiB FAT16
partition aligned to 1 MiB, for a total image size of 129 MiB. After flashing to a larger card, the remaining
space stays unallocated and is not automatically expanded. Change the partition size with `SD_PARTITION_MIB`.
`SD_INCLUDE_DEMO=1` copies the categorized demos and their models into `/demo` on the partition; explicitly
add custom files with `SD_EXTRA_DIR`. No demos or startup scripts are inserted by default. Enabling demos
only copies files; it does not run them automatically or freeze them into the kernel.

Use the generated image with the board's boot configuration and matching Raspberry Pi boot firmware.
The build does not format or write to a physical SD card. UART0 uses 115200 8N1. See the
[RPI1B build instructions](ports/raspberrypi/boards/RPI1B/README.md) for detailed steps and adding new boards.

## Test and Demo Layout

Development tests live in the sibling workspace directory `../tests/`, rather than inside the mpynn source
repository. The RPI port's smoke tests, acceptance tests, benchmarks, and test-model generators have moved to
`../tests/raspberrypi/`. The port retains only manifests, build tools, image/QSTR checks, and their required
utilities. Compile-time configuration constraints remain in the port, so normal firmware builds do not
require the external test directory to exist.

User-facing operational examples are collected in [demo](demo/README.md), organized under `system/`
(system), `network/` (networking), and `ai/` (model applications). They do not import the test tree or
development fixtures. [textcls](demo/ai/textcls/README.md) includes an English text classification model,
vocabulary, and 11 class labels. Run it with `from demo.ai import textcls; textcls.run()` or supply your own
text; its raw scores are not probabilities. Test scripts handle assertions, golden comparisons, and failure
paths; demos show explicit arguments, usage, and resource cleanup. The [VC4 acceleration scorer](demo/ai/vc4_acceleration/README.md)
includes its model and input. Run `from demo.ai import vc4_acceleration; vc4_acceleration.run()` to display
CPU/VC4 scores for the same model, average timings, speedup, and GPU dispatch evidence from the current run,
without generating your own test fixtures. Tests belonging to the independent `vc4-runtime` submodule are
managed by that project and are outside the scope of this main-project test migration.

## Validation Status and Scope

- Pi1B has hardware test records for basic REPL, SD reads/writes, basic TCP echo, and VC4 FP32 FC.
- The reported 1024x2048 dense FC test covers the original/negated input, all outputs, layouts/counters,
  and model reconstruction after deinitialization. At 700/250, CPU time was about 64.07 ms and packed16
  about 9.77 ms, or approximately **6.56x** speedup. The maximum GPU error was about `1.33514408e-05`,
  passing fixed absolute/relative tolerances.
- Those performance figures belong to the firmware with the corresponding build ID at that time.
  Subsequent changes, including extracting the independent runtime and making log snapshots the default,
  have passed host/ARM static validation; they do not automatically inherit the older binary's hardware validation.
- Host tests cover real MicroPython native ML, TFLM float/int8, file media, tensor ownership, platform
  callbacks, packed/uniform layouts, error fallback, and resource reclamation. They do not simulate QPU arithmetic.
- Most peripherals, electrical behavior, full networking/TLS scenarios, real timeout/deferred-free fault
  injection, and thermal stability still require hardware acceptance testing individually. A speedup for
  one model cannot be generalized to all networks.

Historical status documents may contain old defaults, old hashes, and items unfinished at the time.
Read them alongside the source and recorded build IDs. Do not infer support from the old OpenMV README
or from retained directories.

## Directory Guide and Further Reading

| Directory/document | Purpose |
| --- | --- |
| [ports/raspberrypi](ports/raspberrypi/README.md) | Current bare-metal port, Circle adaptation, networking/machine interfaces |
| [ports/raspberrypi/boards/RPI1B](ports/raspberrypi/boards/RPI1B/README.md) | 1B board entry point and configuration selection |
| [boards/RPI1B](boards/RPI1B/board_config.mk) | Single source for the current board architecture, feature configuration, and boot clocks |
| [ports/windows](ports/windows/README.md) | Windows native ML validation port |
| [lib/vc4-runtime](lib/vc4-runtime/README.md) | Project-owned independent runtime and TFLM-VC4 technical documentation |
| [scripts/libraries/ml](scripts/libraries/ml/ml-core/ml/model.py) | Public ML Python facade and utilities |
| [modules/image_file](modules/image_file/image_file.mk) / [modules/audio](modules/audio/audio_file.c) | Independent native file-image/audio modules |
| [demo](demo/README.md) | User demos and board-side entry points; historical image information requires checking |
| [../tests](../tests/README.md) (alongside mpynn) | Independent development test tree, including host/ARM/board acceptance tests and test-model generators |
| [docs/LOCAL_REPOSITORY.md](docs/LOCAL_REPOSITORY.md) | Local baseline, submodule pointers, and development-copy notes |

## Licenses and Port Boundaries

**The RPI/Circle port is distributed under Circle's GPLv3 requirements.** The current
[raspberrypi port](ports/raspberrypi/README.md) depends on and links Circle. Raspberry Pi firmware containing
its platform adaptation code must comply with GPLv3; existing copyright statements and license notices in
each source file must still be retained.

This port's licensing boundary does not mean that the entire mpynn repository has been relicensed under GPLv3:

| Scope | Licensing notes |
| --- | --- |
| RPI/Circle port and firmware linking Circle | Must comply with Circle's GPLv3 requirements, including the VC4 Circle platform adapter that remains inside the port |
| Independent `vc4-runtime` | Retains its own license; the independent runtime core uses MIT and is not uniformly relicensed under GPLv3 because the RPI port uses it |
| `tflite-micro-vc4` / TFLM operator integration | Retains the original licenses of the relevant TFLM source, including Apache-2.0; does not depend on Circle |
| Other ports | Distributed according to their own source licenses and the licenses of dependencies actually linked; do not inherit the RPI/Circle port's GPLv3 |
| Retained OpenMV code and other third-party components | Retain their respective copyright, licenses, and conditions of use; are not relicensed by the project name or port organization |

The independent VC4 components can be used in other projects through non-Circle platform backends. Their
independent licenses do not remove the GPLv3 requirements applicable to firmware that links them into Circle.
For individual files, the owning component's license and source declarations apply. This section explains
component and port boundaries; it does not override or remove existing license conditions.
