#include "uml_backend.h"
#include "flatbuffers/flatbuffers.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <stdint.h>
#include <vector>

#define CHECK(expr) do { \
    if (!(expr)) { \
        std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static std::vector<uint8_t> read_file(const char *path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream.good()) { std::fprintf(stderr, "Cannot open %s\n", path); std::exit(1); }
    const std::streamsize size = stream.tellg();
    if (size <= 0) { std::fprintf(stderr, "Empty model file\n"); std::exit(1); }
    stream.seekg(0, std::ios::beg);
    std::vector<uint8_t> data(static_cast<size_t>(size));
    if (!stream.read(reinterpret_cast<char *>(data.data()), size)) {
        std::fprintf(stderr, "Cannot read model file\n"); std::exit(1);
    }
    return data;
}

static std::vector<uint8_t> make_empty_schema3_model(const std::vector<uint8_t> &input) {
    std::vector<uint8_t> output = input;
    const tflite::Model *model = tflite::GetModel(output.data());
    const auto *graphs = model->subgraphs();
    if (graphs == nullptr || graphs->size() == 0) return output;
    const uint8_t *vector_start = reinterpret_cast<const uint8_t *>(graphs);
    const size_t vector_offset = static_cast<size_t>(vector_start - output.data());
    flatbuffers::WriteScalar<flatbuffers::uoffset_t>(output.data() + vector_offset, 0);
    return output;
}

static uint8_t *align_storage(std::vector<uint8_t> *storage, size_t alignment,
                              size_t bytes) {
    storage->resize(bytes + alignment - 1);
    const uintptr_t raw = reinterpret_cast<uintptr_t>(storage->data());
    return reinterpret_cast<uint8_t *>((raw + alignment - 1) & ~(alignment - 1));
}

int main(int argc, char **argv) {
    CHECK(argc == 2);
    const std::vector<uint8_t> model = read_file(argv[1]);
    const std::vector<uint8_t> empty_model = make_empty_schema3_model(model);
    const size_t state_size = uml_backend_state_size();
    const size_t state_align = uml_backend_state_align();
    CHECK(state_size > 0 && state_align >= 16);

    std::vector<uint8_t> state_storage;
    std::vector<uint8_t> arena_storage;
    const size_t arena_size = 1024 * 1024;
    uint8_t *state = align_storage(&state_storage, state_align, state_size);
    uint8_t *arena = align_storage(&arena_storage, 16, arena_size);

    CHECK(uml_backend_create(state, state_size - 1, model.data(), model.size(),
                             arena, arena_size) == UML_BACKEND_BAD_ARGUMENT);
    CHECK(uml_backend_create(state + 1, state_size, model.data(), model.size(),
                             arena, arena_size) == UML_BACKEND_STATE_MISALIGNED);
    CHECK(uml_backend_create(state, state_size, model.data(), model.size(),
                             arena + 1, arena_size - 1) == UML_BACKEND_ARENA_MISALIGNED);

    std::vector<uint8_t> truncated(model.begin(), model.begin() + 8);
    CHECK(uml_backend_create(state, state_size, truncated.data(), truncated.size(),
                             arena, arena_size) == UML_BACKEND_MODEL_INVALID);
    std::vector<uint8_t> malformed(64, 0);
    CHECK(uml_backend_create(state, state_size, malformed.data(), malformed.size(),
                             arena, arena_size) == UML_BACKEND_MODEL_INVALID);
    CHECK(uml_backend_create(state, state_size, empty_model.data(), empty_model.size(),
                             arena, arena_size) == UML_BACKEND_MODEL_INVALID);
    CHECK(uml_backend_destroy(state) == UML_BACKEND_OK);
    CHECK(uml_backend_destroy(state) == UML_BACKEND_OK);

    CHECK(uml_backend_create(state, state_size, model.data(), model.size(),
                             arena, 16) == UML_BACKEND_TENSOR_ALLOCATION_FAILED);
    CHECK(uml_backend_destroy(state) == UML_BACKEND_OK);
    CHECK(uml_backend_create(state, state_size, model.data(), model.size(),
                             arena, arena_size) == UML_BACKEND_OK);

    const size_t inputs = uml_backend_input_count(state);
    const size_t outputs = uml_backend_output_count(state);
    CHECK(inputs > 0 && outputs > 0);
    uml_tensor_info input = {};
    uml_tensor_info output = {};
    CHECK(uml_backend_tensor_info(state, 0, 0, &input) == UML_BACKEND_OK);
    CHECK(uml_backend_tensor_info(state, 1, 0, &output) == UML_BACKEND_OK);
    CHECK(input.data != nullptr && input.bytes >= sizeof(float));
    CHECK(output.data != nullptr && output.bytes >= sizeof(float));
    CHECK(input.dtype == 'f' && output.dtype == 'f');

    const float values[] = {0.0f, 1.0f, 3.0f, 5.0f};
    for (size_t i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        static_cast<float *>(input.data)[0] = values[i];
        CHECK(uml_backend_invoke(state) == UML_BACKEND_OK);
        const float prediction = static_cast<const float *>(output.data)[0];
        CHECK(std::fabs(std::sin(values[i]) - prediction) <= 0.05f);
    }
    CHECK(uml_backend_tensor_info(state, 0, inputs, &input) == UML_BACKEND_INDEX_INVALID);
    CHECK(uml_backend_tensor_info(state, 1, outputs, &output) == UML_BACKEND_INDEX_INVALID);
    CHECK(uml_backend_destroy(state) == UML_BACKEND_OK);
    CHECK(uml_backend_destroy(state) == UML_BACKEND_OK);
    std::puts("uml_backend runtime regression: PASS");
    return 0;
}
