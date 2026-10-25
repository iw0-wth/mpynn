# Public float16/int32 tensor codec proposal

Status: int32 codec support is integrated into the Raspberry Pi TFLM backend/binding and registered in the owned Raspberry Pi and Windows host-module build fragments. Public float16 remains deliberately unintegrated: the codec retains standalone e conversion helpers, but the TFLM backend does not map kTfLiteFloat16. Int32 public model I/O exposes dtype 'i'; predict(raw_output=True) returns owned raw bytearrays to preserve all values. Binding/codec host suites and ARMv6 syntax tests pass. The generated real int32 RESHAPE fixture test is present but requires a parent build/runtime check before claiming end-to-end success.

## Findings

- `uml_backend.cpp:tensor_dtype` currently exports only B/b/H/h/f. TFLite's public type enum includes kTfLiteFloat16=10 and kTfLiteInt32=2, but availability of a type in that enum does not establish support by every registered kernel. A model must still allocate and invoke successfully with its selected operations.
- `uml_binding.c:uml_dtype_size`, validation, storage and output paths currently understand only those five types. Every non-f tensor requires positive finite scale and is treated as quantized. Adding e/i only to backend mapping would break validation or silently misinterpret integer shape/index data.
- ulab's ndarray enum supports uint8/int8/uint16/int16/native float and optional complex. Raspberry Pi config uses binary32 `mp_float_t` and MPZ Python integers. There is no float16 or int32 ndarray dtype registration API.
- `ULAB_HAS_USER_MODULE` exposes functions from the vendor `code/user/user.c`. It is a namespace extension, not a dtype dispatch hook. Enabling it or adding an exported conversion function cannot update ndarray constructors, item size, strides, indexing, casts, arithmetic or ufunc dispatch. Implementing actual new dtypes would require extensive vendor changes and tests. The user module is also disabled by default.
- MicroPython's `py/binary.c` supports the struct e format, but its half converters are static. The software encoder's rounding differs from ties-to-even, loses a mantissa carry, and can produce a sign-bit artifact for sufficiently large finite values. The companion host probe demonstrates concrete cases. Reusing its conversion implicitly would make the codec contract depend on native _Float16 availability.
- `mp_binary_set_val` explicitly disables overflow checks for exact Python MPZ integers. It is not safe to use generic struct i packing as the range check.
- Existing image tensor conversion is limited to f/b/B. A model codec belongs in the port, not in the image module: shape/index int32 tensors are independent of images. Image preprocessing can later target the codec or fill its owned scratch buffer.

## Minimal ABI change, when integrated together

Preserve `uml_tensor_info` layout and `char dtype`. Add documented format constants in a port-owned header:

| TFLite type | Code | Storage | Conversion meaning |
| --- | --- | --- | --- |
| kTfLiteFloat16 | e | 2 bytes, IEEE binary16 | Floating values; no affine quantization |
| kTfLiteInt32 | i | 4 bytes, signed int32 | Exact integer values; no affine quantization initially |

These are tensor storage codes, independent of ulab ndarray dtype codes. Backend maps these codes only when the binding codec understands them. No enum ordinal is substituted for a typecode. Existing B/b/H/h quantization behavior remains separate from raw i storage.

For the initial implementation reject affine-quantized i tensors and unsupported per-axis quantization with a clear exception. TFLite's scalar params alone cannot establish per-axis quantization support: inspect `tensor->quantization` and distinguish absent metadata from affine metadata. Treat e as floating storage and ignore its ordinary zero scale/zero-point defaults. Do not infer quantization merely from `dtype != 'f'`.

## Proposed Python contract

The standalone development module can be named `tensor_codec`; a later binding may call its C functions directly. Public entry points:

```python
pack(value, shape, dtype) -> bytearray
unpack(raw, shape, dtype, *, raw_output=False) -> ulab.ndarray | bytearray
# Later model integration:
model.predict(inputs, *, callback=None, raw_output=False)
```

Initially support e/i in this codec. Keep existing quantized input paths until a deliberate common conversion refactor. `dtype` accepts exactly one ASCII character or its integer ordinal, consistently with the existing callback convention. Unknown formats raise ValueError. `shape` is a tuple/list of 0 through 4 strictly positive integer dimensions. Empty shape denotes one scalar. Reject bool dimensions, negative/zero dimensions, products or byte counts exceeding SIZE_MAX, and configured maximum storage size. A default bound matching the existing 64 MiB arena cap is reasonable. Validate the shape before allocating.

`pack` always returns an independently owned, correctly sized bytearray. Accept:

- ulab real ndarrays of exactly the tensor rank and shape. Iterate logical row-major order, including reversed and strided views. ulab's scalar limitation is explicit: a scalar tensor may accept only a one-element vector for this input path, and yields a one-element vector on output.
- Flat Python list/tuple containing exactly the shape product. The shape is supplied separately; reject nested lists rather than guessing shape or recursively consuming an unbounded iterable.
- Numeric `array.array`, iterated as numeric values with exact element count. Do not treat it as arbitrary raw bytes, because its native itemsize and typecode can differ from the tensor format.
- bytes, bytearray or memoryview as raw packed bytes, exactly equal to tensor byte count. They use native little-endian Raspberry Pi tensor representation, with no quantization or numerical conversion. memoryview is explicitly a raw-byte path even when created from a typed array; document this rather than guessing.
- Callable invoked as `value(scratch, tuple(shape), ord(dtype))`. Scratch is a zero-filled owned bytearray of exactly the packed size. Ignore the callable's return value. Reacquire its buffer and verify exact length after the call. A callback exception propagates; resizing raises ValueError; no copy into the live tensor occurs until successful completion. Retaining scratch is safe. Never create a bytearray by reference to an arena tensor.

For i numeric input, the initial contract accepts integer values only, rejecting floats and complex values (including ndarray FLOAT) with TypeError. This avoids a surprising implicit truncation policy. Accept bool as 0/1 only if explicitly documented; the recommended initial contract rejects bool. Range-check using exact Python integer conversion/comparison before converting to C int32; outside [-2147483648,2147483647] raises OverflowError. On 32-bit MPZ builds, `mp_obj_get_int` with its checked overflow behavior is suitable for the exact signed32 range; do not use its truncated variant or cast a Python float. Generic arrays with a wider integer dtype must still pass this bound check. ulab integer dtypes are at most 16-bit and fit directly.

For e numeric input, accept Python integers/floats and real ndarray/array values, first convert to binary32 (this port's numerical representation), then convert bits to binary16 using a dedicated rounding-to-nearest, ties-to-even implementation. Preserve signed zero, subnormals and infinities; finite overflow becomes signed infinity; NaN becomes a documented quiet canonical NaN with sign optional or fixed (choose one and test it). Binary32 staging means a double Python build can encounter double rounding; do not promise direct correctly rounded binary64-to-binary16 without implementing it. Raw input preserves exact NaN payloads.

`unpack` requires an exact-size bytes-like source. `raw_output=True` returns an owned bytearray copy preserving every bit. Otherwise return a newly allocated NDARRAY_FLOAT of the tensor shape, scalar represented as shape (1,). Decode e exactly into binary32. Convert i numerically to the port float representation without applying scale/zero point. Document that binary32 cannot exactly represent all int32 values above 2**24; callers needing exact output use raw_output=True and unpack integer values themselves. Quantized integer outputs, if folded in later, retain a separate documented dequantization rule.

For model integration, raw_output=True should return a list of independent bytearrays for all outputs; default preserves the existing list of float ndarrays. Metadata continues to report dtype e/i and tensor shape even when the output container dtype is float.

## Memory safety requirements

1. Validate rank, dimensions, product, itemsize, bytes and non-null tensor data before pointer arithmetic. C codec reads/writes use memcpy or byte operations, avoiding unaligned typed-pointer access and aliasing violations.
2. Pack numeric input into owned scratch first, then copy to arena after full success. A bad element must not invoke inference or partially expose a converted tensor. Multiple-input prediction need not promise rollback of previous inputs, but must not invoke after failure.
3. Keep Python owners rooted across allocations and callbacks. A raw buffer pointer obtained before an allocation can become stale if a GC finalizer resizes a source bytearray; allocate destination first, then reacquire and revalidate source immediately before a no-allocation copy. Do the same for unpack.
4. Snapshot list/tuple element references before conversions that can allocate or invoke Python behavior. Do not retain the list's backing items pointer across those operations. Prefer exact built-in numeric types; arbitrary `__int__`/`__float__` hooks complicate resize/reentrancy safety.
5. Keep model busy/lifetime protection active while callbacks run. Do not expose model arena pointers. Retained input scratch/output arrays remain valid after predict, subsequent inference and model deinit.
6. Shape verification of ulab views uses logical dimensions and signed strides with checked offset arithmetic. Reject malformed/unsupported layouts; do not assume dense contiguous data or infer tensor storage dtype from ndarray dtype.
7. New allocation sizes must also fit ulab's stride/index limits (its strides are int32). Check these separately from SIZE_MAX when producing a float ndarray.

## Implementation and test gates

The implementation combines the portable binary16/signed32 core and MicroPython-facing helpers in `tensor_codec.c/.h`. Define UML_CODEC_CORE_ONLY to build without MicroPython. It registers no module. Public C entry points are `uml_codec_pack(value, ndim, shape, dtype)` and `uml_codec_unpack(raw, ndim, shape, dtype, raw_output)`; dtype is a C char and shape is a checked C size_t vector, so the proposed Python argument parser is deferred. The core exports `uml_codec_float_to_half`, `uml_codec_half_to_float`, exact-size scalar `store_half/load_half/store_int32/load_int32`, and `uml_codec_layout`. Constants UML_CODEC_FLOAT16='e' and UML_CODEC_INT32='i' define independent tensor format codes. Numeric i rejects floats/bools, e canonicalizes NaNs to positive 0x7e00, and byte storage is explicitly little endian. Parent source registration remains deferred until review. Changing the backend mapping is the final integration step, paired with binding validation/store/output support; do not claim float16/int32 model support before that point.

Required tests before enabling model support:

- Exhaust all 65536 binary16 encodings through half-to-float and back; finite values and infinities preserve exact bits, NaNs match the canonical policy. Compare against an independent IEEE reference, not a duplicate algorithm.
- Half ties around 1, the mantissa carry below 2, positive/negative zero, minimum/maximum subnormal, normal boundary, maximum finite 65504, overflow threshold 65520, NaN and infinities; randomized binary32 patterns against Python struct/numpy reference.
- i minimum/maximum, +/-2**24 neighbors, overflow by one, huge MPZ, negative values, float/bool policy, and exact raw output bytes.
- Scalar/rank-four shapes, zero/negative dimensions, shape product/byte/stride overflow, mismatched count, truncated/oversized raw buffers, mismatched ndarray shapes, reversed/strided views, unsupported complex values.
- Callback resize, raised exception, scratch retention, source list mutation, GC during allocation, subsequent inference/deinit ownership, and busy/reentrancy checks.
- Real MicroPython host-runtime tests for list/array/raw/callable paths and ARMv6 syntax compilation. Host C tests alone cannot validate GC lifetime behavior.
- At least one real TFLite int32 public input/output fixture, and a float16 public I/O fixture using kernels actually supported by this TFLM build. Float16 weight constants inside an otherwise float32 model are not evidence of float16 public I/O support.

`mpynn/tests/raspberrypi/test_tensor_codec_host.py` compiles the actual codec C core as a host library and checks all 65536 half encodings plus 100000 deterministic binary32 patterns against Python's independent IEEE struct reference. It checks exact int32 bytes, unaligned access, overflow/non-mutation and layout bounds. A second test compiles the complete codec with MicroPython/ulab stubs and exercises numeric sequences, numeric array iteration, float16 rounding/signed zero, raw copies, output ownership, scalar shape, callback resize/exception/retention, integer overflow/type policy and reversed ndarray input. A third compiles the complete source with actual MicroPython/ulab headers for ARM1176JZF-S under -Wall -Wextra -Werror. All three pass. Stub tests do not establish real GC/finalizer behavior; actual runtime and model fixtures remain integration gates.
