# VC4 acceleration demo assets

This package contains a deterministic **synthetic scoring workload**: a dense
projection from 2048 features to 1024 signed scores. It exercises a substantial
FP32 fully connected operation; the scores have no trained classification or
application semantics.

The two runtime assets are bundled here. Copy the complete demo package to the
board; running it does not import or read development tests, the original asset
folder, a desktop Python environment, or the verification artifacts below.

## Provenance and integrity

The destination files were checked to be absent before copying. These are
byte-for-byte copies of the existing, deterministically generated assets in the
workspace's `VC4_FC测试包` folder. The model and reference were copied together;
this demo did not regenerate either file or substitute another workload.

| Bundled file | Original filename | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| [model.tflite](<model.tflite>) | [vc4_fc_dense_1024x2048.tflite](<../../../../VC4_FC测试包/vc4_fc_dense_1024x2048.tflite>) | 8,393,224 | `347fa1d32843d9d269fcd4691be377170562eb358328ebf001ffa04df918ef74` |
| [reference.json](<reference.json>) | [vc4_fc_dense_1024x2048.json](<../../../../VC4_FC测试包/vc4_fc_dense_1024x2048.json>) | 71,927 | `6ad71748fd563b01e2c9518c0b1f55059bc15f56e4c4dfc9bbd36cef4eba2608` |

The model hash also appears as `model_sha256` in the reference. These hashes
identify the supplied bytes; the board demo checks the reference model identifier
without assuming that a board-side SHA-256 implementation is available.

## Serialized model

The TFLite version 3 FlatBuffer has one subgraph and exactly one
`FULLY_CONNECTED` operator. Its weights use the default dense row-major format,
with no fused activation, quantization parameters, sparse representation, or
variable tensors.

| Tensor | Shape | Dtype | Constant payload |
| --- | --- | --- | ---: |
| Input | `[1, 2048]` | FP32 / `FLOAT32` | runtime input |
| Weights | `[1024, 2048]` | FP32 / `FLOAT32` | 8,388,608 bytes = 8 MiB |
| Bias | `[1024]` | FP32 / `FLOAT32` | 4,096 bytes |
| Output | `[1, 1024]` | FP32 / `FLOAT32` | runtime output |

Each invocation computes `y[r] = sum(W[r, c] * x[c]) + b[r]`, for 1024 rows and
2048 columns: **2,097,152 MAC**, followed by 1024 bias additions. All 2,097,152
weights are nonzero: 1,048,308 positive and 1,048,844 negative, ranging from
-0.125 to +0.125. The signed bias contains 480 positive, 484 negative, and 60
zero values, ranging from -0.0625 to +0.0625. The all-nonzero property refers to
the weights; some biases are zero.

The 8 MiB weight payload is separate from the 4 KiB bias, FlatBuffer metadata,
runtime tensor arena, model storage, and any GPU-side prepared weights. Budget
those allocations separately when deploying to a board.

## Reference schema and independent oracle

The bundled JSON uses `schema: 1`, `input_depth: 2048`, and
`output_depth: 1024`. Its fields are:

- `inputs`: 2048 original input values, exactly representable as FP32, ranging
  from -0.499755859375 to +0.499755859375.
- `expected`: 1024 golden outputs for the original input `x`.
- `expected_negated`: 1024 golden outputs for the changed input `-x`.
- `model_sha256`: the model identity shown above.
- `absolute_tolerance` and `relative_tolerance`: both `1e-4`.
- `oracle`: `binary64 dot over exact signed dyadic FP32 weights/input/bias`.

The two cases are `W*x + b` and `W*(-x) + b`. Since the signed bias is retained,
`expected_negated` is not generally the negative of `expected`. Their sum equals
`2*b`, including rows with positive, negative, and zero bias. The demo checks all
1024 outputs per case using the fixed bound
`abs(actual - expected) <= 1e-4 + 1e-4 * abs(expected)`.

Independent host verification read this copied serialized model using the
repository's generated TFLite schema reader, checked its operator, options,
FP32 dtypes, shapes, and constant payloads, then extracted its actual weights and
bias. NumPy float64 dot products for both inputs agreed exactly with all JSON
goldens: maximum absolute error **0.0** in both cases. The separate check of
`expected + expected_negated == 2*b` also had maximum absolute error **0.0**.
This verification used the model's serialized constants rather than the
fixture-generation formulas.

## Actual Windows CPU inference evidence

The existing Windows executable
[mpynn-ml.exe](<../../../build/windows-frozen-ml/mpynn-ml.exe>) was run against these bundled assets
with `sys.path = ['.frozen']`, the real frozen `ml.Model` facade over native
`uml.Model`, `backend='reference'`, a 4 MiB arena, and a 32 MiB MicroPython heap.
Its SHA-256 was
`1d9d5f6b41897a2b3663d82bda0ba8e36444b6507d8dbbd0534724b73a42e887`.
The native runtime reported input/output shapes `((1, 2048),)` / `((1, 1024),)`
and FP32 dtypes `('f',)` / `('f',)`.

| Native reference input | Outputs checked | Maximum absolute error | Result |
| --- | ---: | ---: | --- |
| Original input | 1024 | 2.3841858e-07 | PASS at atol=rtol=1e-4 |
| Negated input | 1024 | 2.3841858e-07 | PASS at atol=rtol=1e-4 |

This is host CPU numerical evidence. VC4 execution and speedup require the board
demo's fresh GPU dispatch diagnostics and timing; the Windows checks establish
no GPU result or acceleration measurement. No ARM build or board run was
performed for this asset verification.

Development-only scripts and evidence are under
`mpynn/build/demo-vc4-acceleration/`:

- [copy_verify_assets.py](<../../../build/demo-vc4-acceleration/copy_verify_assets.py>):
  checks hashes/byte identity and independently decodes and evaluates the model;
  its initial `--copy` mode refuses existing targets.
- [asset-verification.json](<../../../build/demo-vc4-acceleration/asset-verification.json>):
  structural checks, signed/nonzero counts, hashes, sizes, and float64 results.
- [native_reference_check.py](<../../../build/demo-vc4-acceleration/native_reference_check.py>)
  and [run_native_reference.py](<../../../build/demo-vc4-acceleration/run_native_reference.py>):
  actual frozen/native CPU inference and its host launcher.
- [native-reference-output.txt](<../../../build/demo-vc4-acceleration/native-reference-output.txt>):
  executable hash, exit code 0, and both error measurements from the native run.

All desktop Python verification used [python.exe](<D:/anaconda3/python.exe>). To repeat the
verification from the workspace root, without copying or regenerating assets:

```powershell
& 'D:/anaconda3/python.exe' 'mpynn/build/demo-vc4-acceleration/copy_verify_assets.py'
& 'D:/anaconda3/python.exe' 'mpynn/build/demo-vc4-acceleration/run_native_reference.py'
```

Those verification artifacts are development evidence and are not needed on the
board. Neither upstream libraries nor the model's serialized bytes were changed.
