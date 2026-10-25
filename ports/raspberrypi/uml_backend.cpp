/* SPDX-License-Identifier: MIT */
#include "uml_backend.h"

#include <new>
#include <stddef.h>
#include <stdint.h>

#include "flatbuffers/verifier.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

namespace {

using tflite::MicroInterpreter;
using tflite::MicroMutableOpResolver;
using ::TfLiteTensor;
using ::TfLiteType;

constexpr uint32_t kLiveMagic = 0x554D4C31u;  // UML1
constexpr uint32_t kDeadMagic = 0x554D4C30u;  // UML0
constexpr size_t kArenaAlignment = 16;
constexpr size_t kMinimumArenaSize = 1024;
constexpr unsigned kMaxTensorDimensions = 4;
using Resolver = MicroMutableOpResolver<128>;

/* The context is entirely caller-owned. The interpreter is placement-new'd. */
struct alignas(16) Context {
    uint32_t magic;
    uint32_t reserved;
    const uint8_t *model_data;
    size_t model_size;
    void *arena;
    size_t arena_size;
    const tflite::Model *model;
    Resolver resolver;
    alignas(MicroInterpreter) uint8_t interpreter_storage[sizeof(MicroInterpreter)];
    MicroInterpreter *interpreter;
};

static_assert(alignof(Context) >= kArenaAlignment,
              "UML backend state must preserve 16-byte alignment");

static Context *context_from(void *storage) {
    return reinterpret_cast<Context *>(storage);
}

static const Context *context_from_const(const void *storage) {
    return reinterpret_cast<const Context *>(storage);
}

static bool context_live(const Context *context) {
    return context != nullptr && context->magic == kLiveMagic &&
           context->interpreter != nullptr;
}

static char tensor_dtype(TfLiteType type) {
    switch (type) {
        case kTfLiteUInt8: return 'B';
        case kTfLiteInt8: return 'b';
        case kTfLiteUInt16: return 'H';
        case kTfLiteInt16: return 'h';
        case kTfLiteFloat32: return 'f';
        case kTfLiteInt32: return 'i';
        default: return '\0';
    }
}

static void add_reference_ops(Resolver *resolver) {
    /* Keep this list in sync with the reference archive; Ethos-U is excluded. */
    resolver->AddAbs();
    resolver->AddAdd();
    resolver->AddAddN();
    resolver->AddArgMax();
    resolver->AddArgMin();
    resolver->AddAssignVariable();
    resolver->AddAveragePool2D();
    resolver->AddBatchMatMul();
    resolver->AddBatchToSpaceNd();
    resolver->AddBroadcastArgs();
    resolver->AddBroadcastTo();
    resolver->AddCallOnce();
    resolver->AddCast();
    resolver->AddCeil();
    resolver->AddCircularBuffer();
    resolver->AddConcatenation();
    resolver->AddConv2D();
    resolver->AddCos();
    resolver->AddCumSum();
    resolver->AddDelay();
    resolver->AddDepthToSpace();
    resolver->AddDepthwiseConv2D();
    resolver->AddDequantize();
    resolver->AddDiv();
    resolver->AddElu();
    resolver->AddEmbeddingLookup();
    resolver->AddEnergy();
    resolver->AddEqual();
    resolver->AddExp();
    resolver->AddExpandDims();
    resolver->AddFftAutoScale();
    resolver->AddFill();
    resolver->AddFilterBank();
    resolver->AddFilterBankLog();
    resolver->AddFilterBankSpectralSubtraction();
    resolver->AddFilterBankSquareRoot();
    resolver->AddFloor();
    resolver->AddFloorDiv();
    resolver->AddFloorMod();
    resolver->AddFramer();
    resolver->AddFullyConnected();
    resolver->AddGather();
    resolver->AddGatherNd();
    resolver->AddGreater();
    resolver->AddGreaterEqual();
    resolver->AddHardSwish();
    resolver->AddIf();
    resolver->AddIrfft();
    resolver->AddL2Normalization();
    resolver->AddL2Pool2D();
    resolver->AddLeakyRelu();
    resolver->AddLess();
    resolver->AddLessEqual();
    resolver->AddLog();
    resolver->AddLogSoftmax();
    resolver->AddLogicalAnd();
    resolver->AddLogicalNot();
    resolver->AddLogicalOr();
    resolver->AddLogistic();
    resolver->AddMaxPool2D();
    resolver->AddMaximum();
    resolver->AddMean();
    resolver->AddMinimum();
    resolver->AddMirrorPad();
    resolver->AddMul();
    resolver->AddNeg();
    resolver->AddNotEqual();
    resolver->AddOverlapAdd();
    resolver->AddPCAN();
    resolver->AddPack();
    resolver->AddPad();
    resolver->AddPadV2();
    resolver->AddPrelu();
    resolver->AddQuantize();
    resolver->AddReadVariable();
    resolver->AddReduceMax();
    resolver->AddRelu();
    resolver->AddRelu6();
    resolver->AddReshape();
    resolver->AddResizeBilinear();
    resolver->AddResizeNearestNeighbor();
    resolver->AddRfft();
    resolver->AddRound();
    resolver->AddRsqrt();
    resolver->AddSelectV2();
    resolver->AddShape();
    resolver->AddSin();
    resolver->AddSlice();
    resolver->AddSoftmax();
    resolver->AddSpaceToBatchNd();
    resolver->AddSpaceToDepth();
    resolver->AddSplit();
    resolver->AddSplitV();
    resolver->AddSqrt();
    resolver->AddSquare();
    resolver->AddSquaredDifference();
    resolver->AddSqueeze();
    resolver->AddStacker();
    resolver->AddStridedSlice();
    resolver->AddSub();
    resolver->AddSum();
    resolver->AddSvdf();
    resolver->AddTanh();
    resolver->AddTranspose();
    resolver->AddTransposeConv();
    resolver->AddUnidirectionalSequenceLSTM();
    resolver->AddUnpack();
    resolver->AddVarHandle();
    resolver->AddWhile();
    resolver->AddWindow();
    resolver->AddZerosLike();
}

static bool model_structure_valid(const tflite::Model *model) {
    if (model == nullptr || model->operator_codes() == nullptr ||
        model->operator_codes()->size() == 0 || model->subgraphs() == nullptr ||
        model->subgraphs()->size() == 0 || model->buffers() == nullptr) {
        return false;
    }
    for (flatbuffers::uoffset_t graph_index = 0;
         graph_index < model->subgraphs()->size(); ++graph_index) {
        const tflite::SubGraph *graph = model->subgraphs()->Get(graph_index);
        if (graph == nullptr || graph->tensors() == nullptr ||
            graph->inputs() == nullptr || graph->outputs() == nullptr ||
            graph->operators() == nullptr || graph->tensors()->size() == 0) {
            return false;
        }
        const size_t tensor_count = graph->tensors()->size();
        for (flatbuffers::uoffset_t i = 0; i < graph->inputs()->size(); ++i) {
            if (graph->inputs()->Get(i) < 0 ||
                static_cast<size_t>(graph->inputs()->Get(i)) >= tensor_count) {
                return false;
            }
        }
        for (flatbuffers::uoffset_t i = 0; i < graph->outputs()->size(); ++i) {
            if (graph->outputs()->Get(i) < 0 ||
                static_cast<size_t>(graph->outputs()->Get(i)) >= tensor_count) {
                return false;
            }
        }
        for (flatbuffers::uoffset_t i = 0; i < graph->operators()->size(); ++i) {
            const tflite::Operator *op = graph->operators()->Get(i);
            if (op == nullptr || op->opcode_index() >= model->operator_codes()->size()) {
                return false;
            }
        }
    }
    return true;
}

static TfLiteTensor *get_tensor(const Context *context, int input_output,
                                size_t index) {
    if (!context_live(context)) return nullptr;
    if (input_output == 0) {
        if (index >= context->interpreter->inputs_size()) return nullptr;
        return context->interpreter->input(index);
    }
    if (input_output == 1) {
        if (index >= context->interpreter->outputs_size()) return nullptr;
        return context->interpreter->output(index);
    }
    return nullptr;
}

}  // namespace

extern "C" size_t uml_backend_state_size(void) {
    return sizeof(Context);
}

extern "C" size_t uml_backend_state_align(void) {
    return alignof(Context);
}

extern "C" int uml_backend_create(void *state_storage, size_t state_size,
                                   const void *model_data, size_t model_size,
                                   void *arena, size_t arena_size) {
    if (state_storage == nullptr || model_data == nullptr || arena == nullptr ||
        state_size < sizeof(Context) || model_size == 0 || arena_size == 0) {
        return UML_BACKEND_BAD_ARGUMENT;
    }
    if ((reinterpret_cast<uintptr_t>(state_storage) & (alignof(Context) - 1)) != 0) {
        return UML_BACKEND_STATE_MISALIGNED;
    }
    if ((reinterpret_cast<uintptr_t>(arena) & (kArenaAlignment - 1)) != 0) {
        return UML_BACKEND_ARENA_MISALIGNED;
    }
    if (arena_size < kMinimumArenaSize) {
        return UML_BACKEND_TENSOR_ALLOCATION_FAILED;
    }

    Context *context = context_from(state_storage);
    context->magic = kDeadMagic;
    context->reserved = 0;
    context->model_data = nullptr;
    context->model_size = 0;
    context->arena = nullptr;
    context->arena_size = 0;
    context->model = nullptr;
    context->interpreter = nullptr;

    /* Verify before GetModel: malformed input never reaches generated accessors. */
    if (model_size >= FLATBUFFERS_MAX_BUFFER_SIZE) {
        return UML_BACKEND_MODEL_INVALID;
    }
    flatbuffers::Verifier verifier(reinterpret_cast<const uint8_t *>(model_data),
                                   model_size);
    if (!tflite::VerifyModelBuffer(verifier)) {
        return UML_BACKEND_MODEL_INVALID;
    }
    const tflite::Model *model = tflite::GetModel(model_data);
    if (model == nullptr || model->version() != TFLITE_SCHEMA_VERSION) {
        return UML_BACKEND_SCHEMA_UNSUPPORTED;
    }
    if (!model_structure_valid(model)) {
        return UML_BACKEND_MODEL_INVALID;
    }

    new (&context->resolver) Resolver();
    add_reference_ops(&context->resolver);
    context->model_data = reinterpret_cast<const uint8_t *>(model_data);
    context->model_size = model_size;
    context->arena = arena;
    context->arena_size = arena_size;
    context->model = model;
    context->interpreter = new (context->interpreter_storage)
        MicroInterpreter(context->model, context->resolver,
                         reinterpret_cast<uint8_t *>(arena), arena_size);
    if (context->interpreter->AllocateTensors() != kTfLiteOk) {
        context->interpreter->~MicroInterpreter();
        context->interpreter = nullptr;
        context->model = nullptr;
        return UML_BACKEND_TENSOR_ALLOCATION_FAILED;
    }
    context->magic = kLiveMagic;
    return UML_BACKEND_OK;
}

extern "C" int uml_backend_destroy(void *state_storage) {
    if (state_storage == nullptr) return UML_BACKEND_BAD_ARGUMENT;
    if ((reinterpret_cast<uintptr_t>(state_storage) & (alignof(Context) - 1)) != 0) {
        return UML_BACKEND_STATE_MISALIGNED;
    }
    Context *context = context_from(state_storage);
    if (context->magic != kLiveMagic) {
        /* A failed or already destroyed context has no owned live object. */
        return UML_BACKEND_OK;
    }
    if (context->interpreter != nullptr) {
        context->interpreter->~MicroInterpreter();
        context->interpreter = nullptr;
    }
    context->model = nullptr;
    context->model_data = nullptr;
    context->arena = nullptr;
    context->magic = kDeadMagic;
    return UML_BACKEND_OK;
}

extern "C" size_t uml_backend_input_count(const void *state_storage) {
    const Context *context = context_from_const(state_storage);
    return context_live(context) ? context->interpreter->inputs_size() : 0;
}

extern "C" size_t uml_backend_output_count(const void *state_storage) {
    const Context *context = context_from_const(state_storage);
    return context_live(context) ? context->interpreter->outputs_size() : 0;
}

extern "C" int uml_backend_tensor_info(const void *state_storage,
                                        int input_output, size_t index,
                                        uml_tensor_info *info) {
    if (info == nullptr) return UML_BACKEND_BAD_ARGUMENT;
    const Context *context = context_from_const(state_storage);
    TfLiteTensor *tensor = get_tensor(context, input_output, index);
    if (tensor == nullptr) return UML_BACKEND_INDEX_INVALID;
    if (tensor->dims == nullptr || tensor->dims->size < 0 ||
        static_cast<unsigned>(tensor->dims->size) > kMaxTensorDimensions) {
        return UML_BACKEND_TENSOR_UNSUPPORTED;
    }
    const char dtype = tensor_dtype(tensor->type);
    if (dtype == '\0') return UML_BACKEND_TENSOR_UNSUPPORTED;
    // Public int32 tensors represent integer values (indices, shapes, tokens).
    // Affine-quantized int32 needs a separate contract; never silently ignore it.
    if (dtype == 'i' && tensor->quantization.type != kTfLiteNoQuantization) {
        if (tensor->quantization.type != kTfLiteAffineQuantization ||
            tensor->quantization.params == nullptr) return UML_BACKEND_TENSOR_UNSUPPORTED;
        const auto *affine = static_cast<const TfLiteAffineQuantization *>(tensor->quantization.params);
        if (affine->scale != nullptr && affine->scale->size > 0) {
            return UML_BACKEND_TENSOR_UNSUPPORTED;
        }
    }

    info->data = tensor->data.data;
    info->bytes = tensor->bytes;
    info->ndim = static_cast<unsigned>(tensor->dims->size);
    for (unsigned i = 0; i < kMaxTensorDimensions; ++i) {
        info->shape[i] = i < info->ndim ? tensor->dims->data[i] : 0;
    }
    info->dtype = dtype;
    info->scale = tensor->params.scale;
    info->zero_point = tensor->params.zero_point;
    return UML_BACKEND_OK;
}

extern "C" int uml_backend_invoke(void *state_storage) {
    Context *context = context_from(state_storage);
    if (!context_live(context)) return UML_BACKEND_BAD_ARGUMENT;
    return context->interpreter->Invoke() == kTfLiteOk
               ? UML_BACKEND_OK
               : UML_BACKEND_INVOKE_FAILED;
}
