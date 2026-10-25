"""Generate a tiny FP32 FC model for BCM2835 VC4 smoke testing.

Run with D:\\anaconda3\\python.exe. The model has a 16x1024 FP32 weight matrix, so it meets the first VC4
matvec output-depth constraint and exceeds the conservative clock-scaled
offload crossover while remaining small enough for a Pi smoke test.
"""
import argparse
import struct
import sys
from pathlib import Path

import flatbuffers

ROOT = Path(__file__).resolve().parents[3]
TFLM_PYTHON = ROOT / "tflite-micro" / "tensorflow" / "lite" / "python"
sys.path.insert(0, str(TFLM_PYTHON))
import schema_py_generated as schema  # noqa: E402


def make_model(output_path: Path, input_depth: int = 1024,
               output_depth: int = 16, allow_unaligned: bool = False,
               *, weights_data=None, bias_data=None) -> None:
    if input_depth < 1 or output_depth < 1 or (output_depth % 16 and not allow_unaligned):
        raise ValueError("input_depth >= 1 and output_depth must be a positive multiple of 16")
    if weights_data is None:
        weights = [1.0 if row == col else 0.0
                   for row in range(output_depth) for col in range(input_depth)]
    else:
        weights = weights_data
    bias = ([float(row) * 0.01 for row in range(output_depth)]
            if bias_data is None else bias_data)
    if len(weights) != output_depth * input_depth or len(bias) != output_depth:
        raise ValueError("fixture weight/bias element count mismatch")
    weight_bytes = struct.pack("<%df" % len(weights), *weights)
    bias_bytes = struct.pack("<%df" % len(bias), *bias)

    input_tensor = schema.TensorT()
    input_tensor.shape = [1, input_depth]
    input_tensor.type = schema.TensorType.FLOAT32
    input_tensor.buffer = 0
    input_tensor.name = "input"

    weight_tensor = schema.TensorT()
    weight_tensor.shape = [output_depth, input_depth]
    weight_tensor.type = schema.TensorType.FLOAT32
    weight_tensor.buffer = 1
    weight_tensor.name = "weights"

    bias_tensor = schema.TensorT()
    bias_tensor.shape = [output_depth]
    bias_tensor.type = schema.TensorType.FLOAT32
    bias_tensor.buffer = 2
    bias_tensor.name = "bias"

    output_tensor = schema.TensorT()
    output_tensor.shape = [1, output_depth]
    output_tensor.type = schema.TensorType.FLOAT32
    output_tensor.buffer = 0
    output_tensor.name = "output"

    options = schema.FullyConnectedOptionsT()
    options.fusedActivationFunction = schema.ActivationFunctionType.NONE
    options.weightsFormat = schema.FullyConnectedOptionsWeightsFormat.DEFAULT
    options.keepNumDims = False
    options.asymmetricQuantizeInputs = False

    opcode = schema.OperatorCodeT()
    opcode.builtinCode = schema.BuiltinOperator.FULLY_CONNECTED
    opcode.deprecatedBuiltinCode = schema.BuiltinOperator.FULLY_CONNECTED
    opcode.version = 1

    operator = schema.OperatorT()
    operator.opcodeIndex = 0
    operator.inputs = [0, 1, 2]
    operator.outputs = [3]
    operator.builtinOptionsType = schema.BuiltinOptions.FullyConnectedOptions
    operator.builtinOptions = options

    subgraph = schema.SubGraphT()
    subgraph.tensors = [input_tensor, weight_tensor, bias_tensor, output_tensor]
    subgraph.inputs = [0]
    subgraph.outputs = [3]
    subgraph.operators = [operator]
    subgraph.name = "vc4_fc_smoke"

    empty = schema.BufferT()
    weight_buffer = schema.BufferT()
    weight_buffer.data = list(weight_bytes)
    bias_buffer = schema.BufferT()
    bias_buffer.data = list(bias_bytes)

    model = schema.ModelT()
    model.version = 3
    model.operatorCodes = [opcode]
    model.subgraphs = [subgraph]
    model.buffers = [empty, weight_buffer, bias_buffer]
    model.description = "VC4 FP32 FullyConnected hardware smoke fixture"

    builder = flatbuffers.Builder(1024)
    root = model.Pack(builder)
    builder.Finish(root, file_identifier=b"TFL3")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(builder.Output())
    print("wrote", output_path, "bytes", output_path.stat().st_size)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--input-depth", type=int, default=1024)
    parser.add_argument("--output-depth", type=int, default=16)
    parser.add_argument("--allow-unaligned-output", action="store_true")
    args = parser.parse_args()
    make_model(args.output, args.input_depth, args.output_depth,
               args.allow_unaligned_output)
