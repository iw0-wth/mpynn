// SPDX-License-Identifier: MIT
// Builds a tiny schema-valid public INT32 input/output RESHAPE fixture.
#include "flatbuffers/flatbuffers.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include <fstream>
#include <vector>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    flatbuffers::FlatBufferBuilder builder(1024);
    fprintf(stderr, "stage shapes\n");
    const int32_t input_shape_data[] = {4};
    const int32_t target_shape_data[] = {2};
    const int32_t output_shape_data[] = {2, 2};
    auto input_shape = builder.CreateVector<int32_t>(input_shape_data, 1); fprintf(stderr, "shape1\\n");
    auto target_shape = builder.CreateVector<int32_t>(target_shape_data, 1); fprintf(stderr, "shape2\\n");
    auto output_shape = builder.CreateVector<int32_t>(output_shape_data, 2); fprintf(stderr, "shape3\\n");
    auto input = tflite::CreateTensor(builder, input_shape, tflite::TensorType_INT32, 0,
                                      builder.CreateString("public_input"));
    auto shape_const = tflite::CreateTensor(builder, target_shape, tflite::TensorType_INT32, 1,
                                            builder.CreateString("reshape_shape"));
    auto output = tflite::CreateTensor(builder, output_shape, tflite::TensorType_INT32, 0,
                                       builder.CreateString("public_output"));
    const int32_t desired_shape[] = {2, 2};
    auto reshape_options = tflite::CreateReshapeOptions(builder,
        builder.CreateVector<int32_t>(desired_shape, 2));
    const int32_t op_input_data[] = {0, 1};
    const int32_t op_output_data[] = {2};
    auto op_inputs = builder.CreateVector<int32_t>(op_input_data, 2);
    auto op_outputs = builder.CreateVector<int32_t>(op_output_data, 1);
    auto reshape = tflite::CreateOperator(builder, 0, op_inputs, op_outputs,
        tflite::BuiltinOptions_ReshapeOptions, reshape_options.Union());
    const flatbuffers::Offset<tflite::Tensor> tensor_data[] = {input, shape_const, output};
    auto tensors = builder.CreateVector(tensor_data, 3);
    const int32_t graph_input_data[] = {0};
    const int32_t graph_output_data[] = {2};
    auto graph_inputs = builder.CreateVector<int32_t>(graph_input_data, 1);
    auto graph_outputs = builder.CreateVector<int32_t>(graph_output_data, 1);
    const flatbuffers::Offset<tflite::Operator> operator_data[] = {reshape};
    auto operators = builder.CreateVector(operator_data, 1);
    auto graph = tflite::CreateSubGraph(builder, tensors, graph_inputs, graph_outputs, operators,
                                        builder.CreateString("int32_public_io"));
    auto op_code = tflite::CreateOperatorCode(builder,
        static_cast<int8_t>(tflite::BuiltinOperator_RESHAPE), 0, 1,
        tflite::BuiltinOperator_RESHAPE);
    const uint8_t shape_bytes[] = {2, 0, 0, 0, 2, 0, 0, 0};
    auto shape_data = builder.CreateVector<uint8_t>(shape_bytes, sizeof(shape_bytes));
    fprintf(stderr, "stage buffers\n");
    auto buffers = builder.CreateVector<flatbuffers::Offset<tflite::Buffer>>({
        tflite::CreateBuffer(builder), tflite::CreateBuffer(builder, shape_data)});
    const flatbuffers::Offset<tflite::OperatorCode> opcode_data[] = {op_code};
    const flatbuffers::Offset<tflite::SubGraph> graph_data[] = {graph};
    auto model = tflite::CreateModel(builder, 3,
        builder.CreateVector(opcode_data, 1), builder.CreateVector(graph_data, 1),
        builder.CreateString("uml public int32 input/output test"), buffers);
    tflite::FinishModelBuffer(builder, model);
    std::ofstream stream(argv[1], std::ios::binary);
    stream.write(reinterpret_cast<const char *>(builder.GetBufferPointer()), builder.GetSize());
    return stream.good() ? 0 : 1;
}
