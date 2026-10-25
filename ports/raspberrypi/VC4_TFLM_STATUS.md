# VC4/TFLM integration status

## Production selection

The user selected the board-validated packed16 + multi-tile path as production.
Port defaults are now `VC4_ENABLE=1`, `VC4_MULTI_TILE=1`,
`VC4_PACKED_WEIGHTS=1`, `VC4_PROFILE_COUNTERS=1`, poll stride 256 / sleep 10 us.
Per the user's production preference, hardware counter samples remain in logs;
the first-eight bound and explicit diagnostic rearm limit logging overhead.
One VC4-specialized ARM TFLM archive supplies FC with CPU fallback; no dual TFLM
archives are linked. ARM700/CORE250 and hard-float VFPv2 remain the baseline.
The production image includes generic linked-QSTR consistency checks (no
package-specific import assertion). Diagnostic snapshots/rearm APIs remain.
The reported 6.56x dense speedup is from the prior profiling board build, not a
fresh board measurement of every subsequently rebuilt binary. Timeout injection
and thermal stress remain separate from the completed dense/reload smoke.

## Implemented in this stage

- TFLM has a `CO_PROCESSOR=vc4` specialization directory:
  `tflite-micro/tensorflow/lite/micro/kernels/vc4/`.
- The specialized FP32 `FULLY_CONNECTED` first checks the port-owned C ABI and
  falls back to the upstream reference kernel when VC4 is unavailable, the shape
  is outside the 16-wide matvec constraint, or the runtime reports unsupported.
- Bias and fused activation are applied on the ARM side after a successful matvec.
  Timeout and I/O failures are hard errors; the code does not free or reuse a
  buffer while a QPU may still be writing it.
- The TFLM host archive was built with `CO_PROCESSOR=vc4`; the specialized object
  is present in the archive. The host FullyConnected test ran 13/13 tests passed,
  including mock VC4 matvec, CPU bias/activation tail and unavailable reference
  fallback.
- The ARMv6 `TARGET=rpi1b CO_PROCESSOR=vc4` archive build has been started using
  the D:/anaconda3 Python toolchain shim. It uses ARM1176 ARM state, hard-float
  VFP and the same reference fallback semantics.
- mpynn now links a BCM2835 runtime bridge and a VC4 FP32 shader object. The Pi
  firmware statically links the bridge and keeps VC4 symbols reachable through
  the linker. The runtime logs the measured ARM/core clocks and probes QPU enable
  through the firmware property channel at boot.
- The project baseline is now explicitly `arm_freq=700` and `core_freq=250`.
  The board reports ARM 700 MHz / CORE 250 MHz and QPU-enable probe `ok`; use
  700/250 for all comparisons. No 900 MHz or over_voltage setting is part of
  the baseline.

## BCM2835 runtime ABI and safety

The runtime implements, behind `vc4_runtime.h`:

- firmware allocation/lock/unlock/release using Circle `CBcmPropertyTags` and the corrected BCM2835 tag `0x0003000c` with size/alignment/flags payload;
- active-handle registry and deferred-free slots so in-flight operator buffers remain tracked through timeout/recovery and shutdown;
- exact returned GPU bus alias retention and BCM2835 low-address CPU mapping;
- QPU enable/disable property calls;
- ARMv6 cache clean/invalidate and data barriers;
- V3D SRQCS/SRQUA/SRQPC dispatch with code/uniform alignment checks;
- 1..12 worker validation;
- finite dispatch timeout;
- in-flight state that prevents workspace/weight reuse after a timeout;
- TFLM allocates one persistent GPU-visible FP32 weight buffer per eligible FC operator in `Prepare`, copies/cleans it once, passes the retained bus address on each `Eval`, and releases it from registration `free`. A timed-out release is deferred by the runtime until V3D completion.
- A separate reusable GPU workspace holds the shader, uniforms, and output; the runtime's bus-zero compatibility path uses a bounded 16-entry weight cache.

No host implementation claims acceleration. On Windows the runtime remains the
stub/reference fallback. BCM2835/Pi1B has now completed the 32x1024 mailbox,
cache-clean, V3D dispatch, output-comparison and model reload smoke test; see the
hardware evidence below. A/B currently shows VC4 slower than CPU, so acceleration
is functional but not yet a performance win.

## Runtime switch in Python

`machine.vc4()` reports whether the process-wide runtime switch is on.
`machine.vc4(False)` forces C reference FC execution; `machine.vc4(True)` allows
eligible FC operations to offload. `ml.Model(..., backend="reference"|"vc4"|"auto")`
is also available: it temporarily selects the requested mode during `Prepare`
and each `predict`, restoring the prior process-wide setting afterward. Since
GPU weights are uploaded in `Prepare`, the setting is scoped around model
construction. `ml.Model` remains the public facade; this small selector is a
reserved extension point, not a new backend implementation or dual-TFLM archive.

## Model and clock adaptation

The confirmed board baseline is ARM 700 MHz / CORE 250 MHz; no 900 MHz or
`over_voltage` setting is used. The first accelerated operation is intentionally
only FP32 FullyConnected:

- output depth must be a positive multiple of 16;
- input depth must be positive;
- weights are row-major FP32;
- the QPU computes `W*x`;
- ARM adds bias and applies fused activation.

The current TFLM wrapper sends 12 workers when the output has enough rows; smaller
outputs use the available number of 16-row worker groups. Runtime logs measured
ARM/core clocks so performance reports use the confirmed 700/250 MHz baseline.
Acceleration speedups are not claimed until the board-side dispatch path and
thermal conditions are measured.

## Validation gate and follow-up architecture

The initial 32x1024 QPU proof is complete on Pi1B. Continue correctness,
performance and failure-recovery tests before extracting an upstreamable runtime;
do not claim a speedup or reusable generic driver yet.

### Board evidence and remaining proof

1. Flash the static Pi1B image, record actual ARM/core clocks and the QPU-enable
   result from serial logs.
2. Run a small supported FP32 matvec through mailbox allocation/lock, GPU bus
   mapping, cache maintenance, V3D dispatch and completion polling.
3. Compare every output with `vc4_cpu_matvec_fp32`; repeat with multiple weights,
   batches and FC layers, then test interpreter/model teardown and reload.
4. Run timeout/error and recovery tests; confirm no in-flight allocation is
   reused or released. The firmware logs the first returned GPU handle, bus
   alias and CPU mapping, first weight upload/cache clean, first completed QPU
   matvec, and a V3D timeout if one occurs. Record board revision, firmware,
   clocks, supply and temperature. If any stage fails, set `VC4_ENABLE=0` and
   retain CPU reference behavior.
5. Benchmark a representative FC at the actual configured clock before tuning
   the provisional crossover threshold.

### After that gate: make the runtime reusable/upstreamable

1. Split a platform-independent `vc4` runtime core (status, buffer ownership,
   launch contract, worker limits, timeout/in-flight state) from a BCM2835
   adapter (Circle property tags, bus mapping, ARM cache/barriers, V3D registers).
2. Keep MicroPython, TFLM, and board-specific clock policy out of the generic
   core. Expose a documented C ABI and explicit platform initialization rather
   than depending on mpynn globals.
3. Add standalone host/mock tests for property-tag wire layout, allocation
   lifetime, bus aliases, dispatch sequencing, timeout and delayed frees; build
   the adapter for both Pi Zero and Pi1B separately.
4. Publish the runtime as a separately buildable port/library with build
   instructions, hardware capability limits, clock/performance data and license
   provenance for the imported shader asset. TFLM then remains a thin optional
   FC kernel integration using that public runtime API.

### A/B performance measurement

Latest board A/B at ARM 700 / CORE 250 MHz for 128x4096 FP32 FC:

```text
Initial VC4: 100 runs / 3991 ms / 39.91 ms per invoke / 13.14 MMAC/s
CPU: 100 runs / 2053 ms / 20.53 ms per invoke / 25.54 MMAC/s
After uniform reuse / scheduler-yield changes, VC4: 100 runs / 3733 ms /
37.33 ms per invoke / 14.04 MMAC/s; CPU recheck: 100 runs / 2056 ms /
20.56 ms per invoke / 25.50 MMAC/s. Both max errors: `1.1920929e-07`.
```

VC4 currently takes about 1.82x the CPU time on the 128x4096 recheck; no speedup
claim is justified. The 1024x2048 multi-dispatch recheck measured CPU 65.37
ms/invoke vs VC4 117.60 ms/invoke (speedup 0.556x), with max error `9.54e-07`
on both paths. Dispatch samples were roughly 17.6--20.3 ms each with about
44k--51k SRQCS polls. The latest code reuses each QPU's input uniform across
row batches, cleans only changed uniform headers after the first dispatch, and
uses `VC4_POLL_STRIDE=256`, `VC4_WAIT_SLEEP_US=10` to yield/sleep cooperatively.
The 8 MB weight clean occurs once in Prepare; the hot workspace is much
smaller. Earlier attribution of the roughly 18 ms per tile to fixed launch
cost was not established: reducing six launches to one still took about 109 ms
on the board. Shader execution and memory stalls must be separated using
hardware counters. ARM polling counts alone do not distinguish these causes. The runtime now logs one
`FC matvec timing` record with dispatch count, workspace/uniform bytes and total
microseconds, plus per-dispatch elapsed/poll counts. TFLM `Invoke()` remains
synchronous. A 192x2048 fixture and one-dispatch A/B script were tested on the board:

```text
192x2048 CPU: 12.67 ms/invoke
192x2048 VC4: 20.57 ms/invoke
VC4 dispatches: 1
FC matvec total_us: about 18.4–20.9 ms
```

The 1024x2048 recheck measured:

```text
1024x2048 CPU: 65.43 ms/invoke
1024x2048 VC4: 119.80 ms/invoke
VC4 dispatches: 6
FC matvec total_us: about 111–118 ms
```

Tile durations are nearly additive, but this alone does not prove a fixed
launch cost: the last four-QPU launch handles only 64 rows, while a twelve-QPU
launch handles 192 rows; both assign the same 16x2048 MAC workload per active
QPU. The multi-tile result below rejects the earlier expectation that deleting
five launches would remove 90–100 ms. Next profile memory/TMU/ALU behavior.

An opt-in `VC4_PROFILE_COUNTERS=1` diagnostic build samples raw counters for
idle (13), valid instruction cycles (16), TMU wait (17), scoreboard wait (18),
instruction/uniform cache hits/misses (20–23), texture quads/misses (24–25),
VPM VDW/VCD stall (26–27), and L2 hits/misses (28–29). Event IDs follow Linux
`include/uapi/drm/vc4_drm.h`; enable uses PCTRE bit31 plus slot mask. PiTorch's
profiler IDs/enable sequence must not be copied as-is (it labels event 19 as
execution and omits bit31). Counters are block-wide raw values, not percentages.
The diagnostic image at `build/RPI1B/multitile-profile/bin/kernel.img` has
SHA-256 `BD6D7BA1F58C34B8D3400EEA9E29646EF87862D15EECD77E9C2BD2674A4FDE1E`.
This profiling build is ARM-compiled but not yet hardware-verified.

The port Makefile now accepts `VC4_ENABLE=1` (default) or `VC4_ENABLE=0`.
Build two images from the same source and `TFLM_LIB`, keep `config.txt`, board,
model, input and arena size identical, and run `vc4_hw_smoke.py` on each:

```bash
make -j8 TARGET=RPI1B PYTHON=/d/anaconda3/python.exe VC4_ENABLE=1 \
  TFLM_LIB=/d/openmv_aicore/tflite-micro/gen/rpi1b_x86_64_default_vc4_gcc/lib/libtensorflow-microlite.a
make -j8 TARGET=RPI1B PYTHON=/d/anaconda3/python.exe VC4_ENABLE=0 \
  TFLM_LIB=/d/openmv_aicore/tflite-micro/gen/rpi1b_x86_64_default_vc4_gcc/lib/libtensorflow-microlite.a
```

Use separate output directories or copy each `kernel.img` before rebuilding. For
both images record measured ARM/core clocks, warm-up count, 50–100 steady-state
inferences, total/average time, max CPU-reference error, temperature and any
runtime status. The speedup is `CPU average / VC4 average`; model load and first
`Prepare`/weight upload are reported separately from steady-state inference.

### Current build and hardware status

- The final ARMv6 `CO_PROCESSOR=vc4` TFLM archive has been rebuilt with the
  bare-metal logger stripped and the latest FC wrapper.
- mpynn has linked that archive plus the BCM2835 bridge. The current Pi1B ELF map
  includes `Register_FULLY_CONNECTED`, `vc4_init`, `vc4_alloc`,
  `vc4_copy_to_buffer`, `vc4_launch`, `vc4_matvec_fp32`, and the shader symbol.
- Runtime fixes include the BCM2835 `0x0003000c` allocate tag, checked payload
  layout, clock-scaled offload gate, alignment/overflow guards, active allocation
  records, and deferred release after timeout.
- Host FC tests: 15/15 pass, including mock acceleration, unavailable
  reference fallback, allocation/copy failure fallback, and timeout-as-error paths.
- Runtime host/ARM-stub tests: 2/2 passed; the host runtime remains unavailable.
- A deterministic FP32 FC fixture generator is now available at
  `make_vc4_fc_fixture.py`; for example:

  ```bash
  /d/anaconda3/python.exe ports/raspberrypi/make_vc4_fc_fixture.py \
    build/host-tests/vc4_fc_fp32.tflite --input-depth 1024 --output-depth 16
  ```

  It produces identity rows plus known bias, suitable for board CPU-vs-VC4
  output comparison. `vc4_hw_smoke.py` uses `/vc4_fc_fp32.tflite` because this
  port mounts the onboard SD as the VFS root (`/`), not at `/sd`.
- Hand-built FC models that omit the `FullyConnectedOptions` FlatBuffers union
  can be Python-schema-readable but fail the C++ verifier as backend status -5
  (`UML_BACKEND_MODEL_INVALID`) before CPU fallback is possible. The ladder
  repair tool `vc4_ladder_bench/repair_fc_model.py` emits verifier-safe models;
  the repaired `L_1024_15` remains a deliberate non-16-depth CPU fallback test.
- A read-only Windows `chkdsk G:` scan confirmed the `USUSUSUS.usu` issue is
  FAT32 corruption: every repeated entry is reported as a folder with a
  non-zero file size and invalid first allocation unit. It found 3,565,568
  bytes in 9 recoverable files and did not apply `/F` repair because the volume
  was in use. Back up and unmount the card before any repair.
- A separate `vc4_fc_32x1024.tflite` fixture and
  `vc4_hw_smoke_32x1024.py` were staged on G:; the script expects output shape
  `(1, 32)`. The initial run hit the gate but rejected a valid upper-SDRAM bus
  alias; after validating against total board RAM, the next run completed
  mailbox allocation, cache clean, and QPU dispatch.
- The VC4 FC CPU-fallback path now uses a four-accumulator VFPv2 FP32 loop on
  ARM hard-float builds, reducing scalar FMAC dependency-chain latency; host and
  other architectures still use the upstream TFLM reference implementation.
  ARM firmware disassembly confirms VFP `vmla.f32` instructions. Host FC suite
  remains 15/15; the optimized CPU path still needs a new board numerical stress
  test and A/B measurement.
- `vc4_ab_switch_bench_128x4096.py` now runs CPU reference and VC4 modes on the
  same firmware via `machine.vc4(False/True)`, recreating the model after each
  switch to ensure Prepare sees the mode. It holds input, model, arena, warmup
  and repeat count constant and reports speedup and output error.
- Pi1B 32x1024 smoke completed real mailbox allocation (`handle=4`,
  `bytes=131072`, `bus=5ebd9000`), weight upload/cache clean, and V3D/QPU
  dispatch (`in=1024 out=32 workers=12`). Output max CPU-reference error was
  `2.98e-08`; teardown/reload passed at 700/250 MHz.
- A same-board 128x4096 A/B measured VC4 39.91 ms/invoke (100 runs) vs CPU
  reference 20.53 ms/invoke, max error `1.1920929e-07` both. Current VC4 is
  about 1.94x slower; functional offload is proven, acceleration is not.
- Runtime now reuses each QPU's input uniforms across row-batch dispatches,
  reports up to eight dispatch timing samples including poll counts, and yields
  cooperatively every 256 V3D status polls. This is not asynchronous Invoke;
  remeasure on board before deciding further scheduling or shader changes.
- The isolated experimental multi-tile shader was tested on Pi1B at ARM 700 /
  CORE 250 MHz for 1024x2048: CPU 69.9 ms/invoke, VC4 115.8 ms/invoke, both
  max error `9.5367432e-07`. Runtime reported one 12-QPU dispatch per Invoke
  (`dispatches=1`, `multitile=1`) at 108.5–115.1 ms; polls were 244816–263072.
  This confirms numerical correctness and launch reduction but is not a speedup:
  CPU/VC4 is 0.604x, and latency is approximately the same as the previous six
  dispatches. The shader still spends time serially looping over tiles and
  polling. Production remains `VC4_MULTI_TILE=0`; timeout/deferred-free stress,
  teardown/reload, and thermal stability remain pending.
- Packed16 profiling image has now run on the identity fixture: CPU about
  70 ms/invoke versus packed VC4 14.5–15.1 ms/invoke, error `9.5367432e-07`.
  Row-major VC4 remains 115.3–116 ms. Across the eight generic-run samples,
  dispatch time averaged 110.33 ms vs 8.99 ms; raw exec cycles were effectively
  unchanged (7347040 vs 7346832), TMU wait dropped 17.21x, texture misses 15.39x,
  and L2 misses 15.82x. This supports the strided-memory bottleneck and a 4.7–4.8x
  identity-fixture public-API speedup vs CPU. Do not infer raw SDRAM bytes or
  counter utilization percentages from these counts.
- Dense board validation failed before loading the dense model: the old common
  script auto-ran identity inference and had no `validate_output` symbol. The
  replacement `vc4_dense_acceptance.py` is standalone, prints
  `SCRIPT_VERSION: dense-standalone-2`, verifies model/reference metadata and
  rejects NaN/Inf; it no longer imports the old common script. Actual host
  MicroPython/TFLM ran both dense input sets and model recreation with max error
  `2.3841858e-07`. Later board runs reached dense original/negated input checks:
  CPU 64.17–64.2 ms, row-major VC4 111.2 ms, packed16 VC4 10.033334 ms (6.395x
  vs its CPU baseline, 11.08x vs row-major VC4). Both GPU layouts gave max error
  `1.33514408e-05`, within fixed 1e-4 absolute + relative tolerance; CPU gave
  `2.3841858e-07`. The script stopped afterward because this MicroPython bytes
  type lacks `splitlines()`, before final model reload. Script v3 uses
  `split(b'\n')`, auto-detects layout, and is verified by real host MicroPython
  log parsing. Final reload, timeout/deferred-free and thermal stress remain.
- Log diagnostics v3 originally preserved the legacy consuming default. The
  later default-read fix now makes `machine.logs()` a retained full-ring snapshot
  (`clear=False, limit=16384`); only explicit `clear=True` consumes returned bytes.
  Benchmark readers use one snapshot rather than repeating a default drain loop.
  The API also supplies
  `machine.vc4_reset_diagnostics()` to rearm the first-eight samples without
  freeing buffers. Busy in-flight reset is rejected. Host tests use real
  MicroPython argcheck plus extracted production binding/bridge/Circle ring and
  actual reset/state definitions; they do not claim VM/IRQ/GPU board coverage.
  The user's subsequent Pi1B build `36005fb99a00455612b4e0d0e0d95816e5601aaff302e0285f24e963811b2139`
  logged diagnostic rearm, eight fresh counter samples and final DENSE PASS with
  model reload. CPU 64.066668 ms vs packed16 9.766666 ms gives 6.559727x speedup;
  GPU max/changed-input/reload error 1.33514408e-05 passed the fixed tolerance.
  This also confirms frozen ml import works in that tested build. Manual repeated
  snapshot retention, timeout/deferred-free fault injection and thermal stress
  are not established by that report.
