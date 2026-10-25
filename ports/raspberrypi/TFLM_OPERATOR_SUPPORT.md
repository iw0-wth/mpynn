# Current TFLM Operator Support

This file describes the actual Pi1B/Windows `uml_backend.cpp` resolver, not the
larger upstream TFLM source tree. The resolver has **111 registrations** and uses
reference/portable kernels only. CMSIS-NN, CMSIS-DSP, Ethos-U and NPU kernels are
not selected.

## Registered operators

The following registrations are present in `add_reference_ops()`:

```text
ABS ADD ADD_N ARG_MAX ARG_MIN ASSIGN_VARIABLE AVERAGE_POOL_2D BATCH_MATMUL
BATCH_TO_SPACE_ND BROADCAST_ARGS BROADCAST_TO CALL_ONCE CAST CEIL
CIRCULAR_BUFFER CONCATENATION CONV_2D COS CUMSUM DELAY DEPTH_TO_SPACE
DEPTHWISE_CONV_2D DEQUANTIZE DIV ELU EMBEDDING_LOOKUP ENERGY EQUAL EXP
EXPAND_DIMS FFT_AUTO_SCALE FILL FILTER_BANK FILTER_BANK_LOG
FILTER_BANK_SPECTRAL_SUBTRACTION FILTER_BANK_SQUARE_ROOT FLOOR FLOOR_DIV
FLOOR_MOD FRAMER FULLY_CONNECTED GATHER GATHER_ND GREATER GREATER_EQUAL
HARD_SWISH IF IRFFT L2_NORMALIZATION L2_POOL_2D LEAKY_RELU LESS LESS_EQUAL
LOG LOG_SOFTMAX LOGICAL_AND LOGICAL_NOT LOGICAL_OR LOGISTIC MAX_POOL_2D
MAXIMUM MEAN MINIMUM MIRROR_PAD MUL NEG NOT_EQUAL OVERLAP_ADD PCAN PACK PAD
PADV2 PRELU QUANTIZE READ_VARIABLE REDUCE_MAX RELU RELU6 RESHAPE
RESIZE_BILINEAR RESIZE_NEAREST_NEIGHBOR RFFT ROUND RSQRT SELECT_V2 SHAPE SIN
SLICE SOFTMAX SPACE_TO_BATCH_ND SPACE_TO_DEPTH SPLIT SPLIT_V SQUARE
SQUARED_DIFFERENCE SQRT SQUEEZE STACKER STRIDED_SLICE SUB SUM SVDF TANH
TRANSPOSE TRANSPOSE_CONV UNIDIRECTIONAL_SEQUENCE_LSTM UNPACK VAR_HANDLE WHILE
WINDOW ZEROS_LIKE
```

`DELAY`, `ENERGY`, `FFT_AUTO_SCALE`, `FILTER_BANK*`, `FRAMER`, `IRFFT`,
`OVERLAP_ADD`, `PCAN`, `RFFT`, `STACKER`, and `WINDOW` are TFLM signal custom
registrations. They are not CMSIS or hardware acceleration.

## Dtype constraints

A registration means that the op exists; it does not mean every tensor dtype is
accepted by its reference kernel. Important constraints from the actual TFLM
sources used by this checkout:

- Model public input/output metadata maps `float32 -> f`, `int8 -> b`,
  `uint8 -> B`, `int16 -> h`, and `uint16 -> H`; the binding rejects other public
  dtypes. Internal model
  tensors may also use `int32`, `bool`, and other TFLite types.
- `GATHER` requires int32 indices and the current kernel accepts float32/int8
  gathered values. It does not accept arbitrary gathered dtypes.
- `SELECT_V2` reference evaluation accepts float32/int8/int16 selected values;
  it does not accept int32 selected values. The original `ml_text_cls`
  `text_cls_f32.tflite` contains an int32 `SELECT_V2`, so it fails Invoke with
  backend status `-10` despite the operator being registered.
- `CAST` supports only the source/destination combinations implemented in
  `tensorflow/lite/micro/kernels/cast.cc`; registration alone is insufficient.
- Convolution, depthwise convolution, fully connected, pooling, arithmetic and
  activation kernels have their own type/quantization constraints. The safe
  model contract is fixed shapes, batch 1, and float32/int8/uint8/int16 tensors
  matching each kernel's TFLM implementation.
- Dynamic shapes, string tensors, and int32 public input tensors are not part of
  the MicroPython binding contract. Text token IDs must be encoded into the
  model's supported float/int16/etc input representation.

## Model results

Verified on the formal Windows MicroPython runtime using the same native UML
binding and a host TFLM reference archive:

- `mpynn/lib/models/yolo_lc_192.tflite`: loads and runs; input `(1,192,192,3)`
  `uint8`, output `(1,12,12,30)` float32.
- `mpynn/lib/models/yolov8n_192.tflite`: loads and runs; input
  `(1,192,192,3)` `uint8`, output `(1,5,756)` float32. A zero-input smoke
  invocation returned a valid output tensor.
- `ml_text_cls/text_cls_f32.tflite`: loads and exposes the expected `(1,50)`
  float32 input and `(1,11)` float32 output, but fails Invoke because of its
  internal int32 `SELECT_V2`.
- `ml_text_cls/text_cls_tflm.tflite`: user-corrected FP32 text model. Size is
  643,304 bytes and SHA-256 is
  `AECD63AFECD8C318691254A7C4E6E591F44C817E4254379E29DB1046B15B38E5`.
  It runs in the formal Windows MicroPython port with input `(1,50)` float32 and
  output `(1,11)` float32. The supplied `mpy_infer_example.py` was executed for:
  `fitness exercise health patient` -> `health_medicine` (about `0.8506`),
  `mechanical trusses device` -> `engineering` (about `0.9330`), and
  `career joined attended helped` -> `career_advice` (about `1.1404`).

The earlier `text_cls_f32.tflite` in the same directory remains incompatible with
this reference kernel because of its internal int32 `SELECT_V2`; use the corrected
`text_cls_tflm.tflite` for this TFLM runtime.

## Candidate model selection

The checkout already contains the most useful first model set:

- `yolo_lc_192.tflite` for a compact quantized detector;
- `yolov8n_192.tflite` for a larger detector;
- `movenet_singlepose_192.tflite`;
- `blazeface_front_128.tflite`;
- `palm_detection_full_192.tflite`;
- `hand_landmarks_full_224.tflite`;
- `person_detect.tflite`;
- `micro_speech.tflite` and `audio_preprocessor.tflite`.

Each model must still be checked for actual op/dtype/arena compatibility before
being presented as supported. A model's presence in `lib/models` is not itself a
runtime claim.
