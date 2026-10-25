# VC4 multi-tile dispatch plan

## Evidence

The Pi1B 700/250 board run for `input_depth=2048`, `output_depth=1024`,
`worker_count=12` reported five 12-QPU launches plus one 4-QPU launch. The
current row group is `worker_count * 16`, so the dispatch count is:

```text
ceil(1024 / (12 * 16)) = 6
```

Each launch costs roughly 17.6–20.3 ms on the measured board. The ARM spends
about 44k–51k SRQCS polls per launch. This makes dispatch amortization the next
performance experiment. Linear tile scaling alone did not establish fixed
launch overhead: both 4-worker and 12-worker launches perform 16xK MACs per
active QPU. A direct board comparison initially showed additive tile cost: 192x2048
(one dispatch) is 20.57 ms/invoke on VC4, while 1024x2048 (six dispatches) is
119.80 ms/invoke; CPU is 12.67 ms and 65.43 ms respectively. Both models pass
with max error at or below 1e-6.

## Safe current optimizations

Already implemented in `vc4_runtime_bcm2835.cpp`:

- weight upload/cache clean only in TFLM `Prepare`;
- first workspace clean publishes shader, output, uniforms and pointer table;
- later row batches update only two uniform header words per QPU;
- later batches clean only those header cache lines;
- completion invalidates only the GPU-written output range;
- configurable cooperative wait (`VC4_POLL_STRIDE`, `VC4_WAIT_SLEEP_US`);
- bounded dispatch and FC timing logs.

## Required shader ABI change

The current 98-word `matvec_tmu_shader` executes one 16-row tile per QPU and
terminates. A one-launch multi-tile kernel needs an outer row loop in QPU code.
The per-QPU uniform stream should become:

```text
[0] W_base_for_first_tile
[1] output_base_for_first_tile
[2] input_depth
[3] QPU number / VPM row selector
[4] tile_count_for_this_qpu
[5] weight_row_stride_bytes
[6] output_row_stride_bytes
[7] shared input vector bus address (input fetched through TMU1)
```

The shader must keep the input vector resident/re-readable, compute one 16-row
sum, write the VPM/DMA result, advance weight/output bases by one tile, decrement
`tile_count`, and repeat. The host then submits one uniform pointer per QPU and
one V3D scheduler launch for the entire output depth.

Do not edit the 98 machine words by hand. A local Windows vc4asm build is now
available at `vc4asm-master/build-msys3/vc4asm.exe`; it was built with a small
Windows `alloca.h`/`unistd.h` compatibility shim and `M_LN2` definition. As a
toolchain sanity check, assembling PiTorch `matvec_tmu.qasm` with `-V` produced
392 bytes (98 words) whose words match
`pitorch/ops/matvec/matvec_tmu_shader.c` exactly.

An experimental QASM draft is in
`ports/raspberrypi/vc4_matvec_multitile_experimental.qasm`; `vc4asm -V` accepts
it and generates 560 bytes (140 words), also emitting an experimental C array
and header. It reads the shared input vector by TMU1 and loops over 16-row tiles
inside one QPU task. Host tile-layout tests verify complete, non-overlapping row
coverage for 192x2048 and 1024x2048 (3/3 pass). The QASM/binary/C/header all agree at 140 words and the generated binary was
reassembled/disassembled successfully. The experimental runtime translation unit was compiled in an isolated build
directory with `VC4_MULTI_TILE=1`; its object references the 140-word shader,
and the experimental `kernel.elf`/`kernel.img` were linked separately. Host layout
checks verify row ownership and buffer strides, not QPU arithmetic. Keep
`VC4_MULTI_TILE=0` and the 98-word production shader as default. The production
firmware was rebuilt afterward with that default. The build identity signs
`VC4_MULTI_TILE=0`; production SHA-256 is
`AC9EAD9E982B574044B378AA6CA9A26966DAE3ADB4C382A0B201AB36C22EF4B8`, build
identity `218e40f426223e0a5b4dd27fe316a14e3880b4d098afcf3be2e0257ab5072ceb`.

## Experimental board result (Pi1B, 700/250)

The isolated image passed the 1024x2048 acceptance script:

```text
CPU: 69.9 ms/invoke, max_error=9.5367432e-07
VC4 multi-tile: 115.8 ms/invoke, max_error=9.5367432e-07
CPU/VC4 speedup: 0.604x
FC matvec total_us: 108.7–115.1 ms
V3D dispatch: 108.5–115.0 ms, qpus=12, polls=244816–263072
Runtime log: dispatches=1, active_qpus=12, multitile=1
```

This verifies numeric output and one V3D launch for that fixture, but it does
not improve end-to-end latency relative to the old six launches (about
111–118 ms). The shader still serially computes its multiple 16-row tiles per
QPU, so launch reduction did not remove the dominant compute/TMU wait. No
speedup is claimed. Separate timeout/deferred-free stress, teardown/reload, and
thermal validation remain outstanding; keep the production image at
`VC4_MULTI_TILE=0` unless further profiling justifies the experimental branch.

## Acceptance for the new kernel

1. Existing 32x1024 smoke remains bitwise/tolerance-correct.
2. 1024x2048 output matches CPU reference across all 1024 rows.
3. Runtime log shows `dispatches=1`, not six.
4. Timeout and deferred-free behavior remains safe.
5. A/B benchmark reports the new dispatch latency and CPU occupancy; no speedup
   claim is made until the same-board CPU comparison improves.
