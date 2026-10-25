# VC4 packed16 layout experiment

Current script location: workspace `tests/raspberrypi/`, sibling to mpynn
(relative to this document: `../../../tests/raspberrypi/`). Acceptance/benchmark
scripts and `make_vc4_*_fixture.py` have moved there. Historical port paths below
refer to earlier builds; use the external test tree for current source. Normal
user-model examples are maintained in `mpynn/demo/`.

Status: the user ran both profile images on Pi1B at ARM 700 / CORE 250 MHz.
Latest repaired-firmware dense report (board build ID
`36005fb99a00455612b4e0d0e0d95816e5601aaff302e0285f24e963811b2139`) reached
`DENSE PASS: both inputs, all outputs, layout/counters and model reload`:
CPU 64.066668 ms, packed16 9.766666 ms, speedup 6.559727x. Both GPU input sets
and the recreated model had error 1.33514408e-05; CPU error 2.3841858e-07.
Eight fresh counter samples and diagnostic rearm were logged. Final reload is
now board-proven for this dense fixture; timeout/thermal stress and repeated
manual snapshot retention are not implied by that result.

Historical measurements before the parser repair follow:
The subsequent standalone dense run checked original and negated inputs:
packed VC4 10.033334 ms vs CPU 64.166664 ms (6.395x), row-major VC4 111.2 ms
vs CPU 64.2 ms. Both GPU layouts had max error 1.33514408e-05 within the fixed
absolute/relative tolerance; CPU error was 2.3841858e-07. The run stopped only
at log parsing (`bytes.splitlines` absent), before the final reload check.
That parser has been changed to `split(b'\n')` and checked on real host
MicroPython; this is not yet a board-verified final reload pass.
The old identity runner reports row-major VC4 115.3–116.0 ms/invoke versus
packed16 14.5–15.1 ms, with CPU 69.9–70.3 ms and error 9.5367432e-07.
This supports an identity-fixture end-to-end speedup of about 4.7–4.8x vs CPU.
The first dense attempt imported an obsolete common runner and failed before
dense inference; the later standalone run above did perform dense inference.
Full final PASS/reload and repeated diagnostic sessions still need verification.

## What changes

Row-major `W[o][k]` is copied once during TFLM Prepare into:

```text
packed[(o/16)*K*16 + k*16 + o%16] = W[o*K+k]
```

Weight byte count is unchanged. The CPU source stays row-major, including when
`machine.vc4(False)` selects CPU fallback. The packed shader keeps one SIMD lane
per output row, uses `lane*4` starting offsets and a 64-byte K stride. Input TMU1,
output layout, VPM rows and tile ownership are unchanged. No lane reduction is
introduced. `vc4_copy_to_buffer` remains a generic byte copy; the new optional
`vc4_upload_weights_fp32` receives dimensions and selects the build's layout.
The runtime checks layout metadata before dispatching packed weights.

The 8 KB separation at K=2048 is established by the old address formula. A fixed
16x bandwidth loss is only a hypothesis: cache reuse/conflicts and TMU latency
must be measured. Previous multi-tile board data (one launch still about 109 ms)
rejected the earlier claim that 18 ms/tile was mostly host launch overhead.

## Hardware counter evidence from the user's generic identity run

Means across the eight reported dispatch samples (raw, V3D-wide counters):

| Metric | Row-major | Packed16 | Row-major / packed |
| --- | ---: | ---: | ---: |
| dispatch microseconds | 110327.5 | 8992.5 | 12.27 |
| valid instruction cycles | 7347040 | 7346832 | 1.00003 |
| TMU wait | 288149101.5 | 16741148.5 | 17.21 |
| texture cache miss | 2101248 | 136532.875 | 15.39 |
| L2 miss | 2097975.375 | 132619.25 | 15.82 |

Texture quads remain 4194304; scoreboard, VDW and VCD stalls are zero in these
samples. Instruction work is effectively unchanged while TMU/cache costs drop.
This strongly supports the strided-weight-access diagnosis. These counters are
not memory byte counts or utilization percentages. Macro timings are from an
old runner, include public binding/other overhead, and should not be equated to
these bounded early-dispatch samples. The supplied output `MULTITILE ACCEPTANCE`
and absence of `changed_input_error` identify that old runner; no dense results
are inferred from it.

## Built artifacts

| Layout | Image bytes | SHA-256 |
| --- | ---: | --- |
| Row-major counter control | 1462232 | `EE72471BBE36D597393B5EAAE18D0DE902BC67E340B82535461A1D7114DF653C` |
| Packed16 counter experiment | 1461632 | `D0C00A4012C41EFCB392B1031A4A98ABAE18FDCE1565F27D07D4C2F4A378B675` |

Build identities are `4f43f9ba45052bd5083b4a316b1ef274c1695479100201456062fb647f8fd639`
(row-major) and `a0b9e46f3987efc4972939f2550aedfa9cdd1b8d9d6950df35046be4eca1a99f`
(packed16). Both are ARM1176 VFPv2 hard-float, multi-tile, counter-enabled, with
poll stride 256 / sleep 10 us. Only packing/layout shader selection differs.
The old production image was not overwritten.

## Log-reader and repeated-sampling repair (v3)

`machine.logs()` historically consumed at most 1024 bytes. Circle's retained
ring has 16 KiB allocated and at most 16383 bytes of content. Repeating a drain
when nothing new was logged correctly returned empty; boot records are not
regenerated. Separately, VC4 once flags and the first-eight sampling limit stopped
new perf/FC records after the first session. These are distinct mechanisms.

The first snapshot API revision kept the consuming no-argument default; that did
not fix repeated plain `machine.logs()` inspection. The current port changes the
public default to a complete retained snapshot (`clear=False, limit=16384`).
Explicit consumption remains available; old drain loops must request it rather
than repeatedly peeking the same bytes:

```python
machine.logs()                          # default snapshot, repeated calls retain evidence
```

The explicit forms and diagnostic rearm are:

```python
machine.logs(clear=False, limit=16384)  # peek retained bytes, no consumption
machine.logs(clear=True, limit=16384)   # consume only returned bytes
machine.vc4_reset_diagnostics()        # rearm bounded samples, no free/shutdown
```

Reset refuses an in-flight dispatch, preserves buffers/state/enable and emits
current clock/layout metadata. It does not clear the ring or replay already
consumed boot records. A snapshot cannot restore bytes previously consumed or
overwritten. The new dense script uses `split(b'\n')` instead of unsupported
`bytes.splitlines()`, automatically selects the supplied image layout or matches
logs, and rearms samples when the new API is present. Successful new-firmware
runs retain their logs for manual inspection. On old firmware it remains usable
for the first run after reboot. Source execution in a fresh namespace avoids
stale `.mpy` or imported module versions.

The packed v3 image is `build/RPI1B/packed-profile-v3/bin/kernel.img`; SHA256
`6717839AF7FF70533266EB2314ED03194131E054552735255B1B5AE6338D0EC3`, build ID
`36dfdd792c17dcb789084477a4e1600f089cb2c7daab0a5e9db2e17251ecc2f9`.
The row-major v3 control is `build/RPI1B/rowmajor-profile-v3/bin/kernel.img`;
SHA256 `F32742AB8F9D0BFB3C2F1F97DA4954498105A7B4C01660425EFFF500D3EF7A84`,
build ID `f4feec8cf5a4614cb9954e880270a9264b0dc6a32fac7715a9453a189378449e`.
Both compile and link the new APIs with VFPv2 hard-float and unchanged shader
selection. Log snapshot/rearm interfaces are host-tested but not yet board-tested.

## Pinned v3 acceptance bundle

Use `VC4_FC测试包/VC4_packed16_v3_board_test.zip` to avoid mixed script versions.
The ZIP is 2451378 bytes, SHA-256
`F0F26F6DE9B0A6520EA5785412432E87B91778564372BE5BF44498E92E2D9CBA`.
Its four core files were verified both before compression and after reading the
archive: packed-v3 kernel image, dense-standalone-3 script, dense model and JSON.
`README_板测步骤.txt` contains the two-run test; `SHA256_manifest.json` pins all
four hashes. The source/script bundle is fixed; no further host repetition can
establish the remaining board-only log/rearm/reload behavior.

Remaining board evidence: final DENSE PASS including reload, two successful runs
without reboot with fresh perf samples, and repeated non-consuming snapshots.
Timeout/deferred-free fault injection and thermal stability are not covered by
this smoke test and must not be inferred from a DENSE PASS.

## Original profile image board test

Use ARM 700 MHz / CORE 250 MHz and the existing boot configuration. For these
original images, reboot for each run because the first-eight sample budget has
no rearm API. The v3 images above support explicit rearm without reboot. Put these
files at the SD root:

- `vc4_fc_1024x2048.tflite` from the workspace fixture directory;
- current `vc4_multitile_acceptance_1024x2048.py` (updated: all input entries
  nonzero/distinct; changed-input check; rejects NaN/Inf; 8 warmups/30 repeats);
- `vc4_packed_acceptance.py` for the packed experiment.

1. Row-major control image: `build/RPI1B/rowmajor-profile/bin/kernel.img`.
   Copy it as the boot `kernel.img`, reboot and run:

   ```python
   import vc4_multitile_acceptance_1024x2048 as bench
   bench.run(require_counters=True)
   ```

2. Packed experiment image: `build/RPI1B/packed-profile/bin/kernel.img`.
   Copy it as the boot `kernel.img`, reboot and run:

   ```python
   exec(open('/vc4_packed_acceptance.py').read())
   ```

The TFLite model remains the same row-major file for both builds; do not repack
the model offline. The packed image performs shape-aware packing at Prepare.
Check `packed16=1` in the FC summary and upload log for the packed build.

Return all three `V3D perf` records, `FC matvec timing`, CPU/VC4 average times,
max_error/changed_input_error and `machine.board_info()` from each build.
Raw counters are V3D-wide, not utilization percentages. Counter events follow
Linux VC4 UAPI: idle=13, exec=16, TMU wait=17, scoreboard=18, instruction/uniform
cache=20..23, texture quads/misses=24..25, VPM stall=26..27, L2=28..29. PCTRE bit31
is enabled. Existing enabled counters are left untouched. Counter register
mapping was cross-checked against Linux; physical counter behavior still needs
this board test.

## Dense signed-weight follow-up

The same two images also support an independent dense fixture; no firmware
change is required. Copy these additional files to SD root:

- `vc4_fc_dense_1024x2048.tflite` and `vc4_fc_dense_1024x2048.json` from the
  workspace fixture directory;
- Replace `vc4_dense_acceptance.py` with the standalone version from workspace `tests/raspberrypi/`.
  It prints `SCRIPT_VERSION: dense-standalone-3` before any tests and imports no
  common benchmark script. No replacement firmware or common module is needed.

Reboot before the test. To bypass a cached Python module or stale `.mpy` file,
execute the copied source into a fresh namespace. On row-major control:

```python
scope = {'__name__': 'dense_test'}
exec(open('/vc4_dense_acceptance.py').read(), scope)
scope['run'](require_packed=False)
```

On packed16:

```python
scope = {'__name__': 'dense_test'}
exec(open('/vc4_dense_acceptance.py').read(), scope)
scope['run'](require_packed=True)
```

The model has all-nonzero signed dyadic weights and bias. Its model SHA-256 is
`347FA1D32843D9D269FCD4691BE377170562EB358328EBF001FFA04DF918EF74`.
The JSON contains independent binary64 dot-product goldens for the original and
negated inputs. The standalone runner verifies schema, expected model hash and
fixed tolerances; streams the model SHA256 where hashlib is available; checks
every output with absolute/relative tolerance; changes inputs on the same model;
then recreates and runs another GPU model. It restores the switch and frees the
model on errors. Missing hashlib is explicitly printed, never reported as a hash
pass. On a board run, return SCRIPT_VERSION and board_info along with the logs.
The actual host MicroPython/TFLM interpreter executed the standalone version
with both input sets, model hash verification and recreation, with max error
`2.3841858e-07`; this is CPU-only evidence, not GPU validation.
The small-fixture test also decodes serialized weights and compares a serial dot
against the generated reference, including repeatable model bytes.

These runners cover numerical/changed-input smoke and steady-state timing, not
fault-injection timeout/deferred-free or thermal stress. Do not promote a layout
based only on identity weights, host simulation, or successful assembly.
