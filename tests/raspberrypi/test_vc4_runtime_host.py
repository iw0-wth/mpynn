# SPDX-License-Identifier: MIT
"""Host checks for the port-owned VC4 runtime boundary.

These tests compile and execute the real C implementation.  They intentionally
expect the current stage to be unsupported: neither host nor ARM compilation is
allowed to claim VC4 availability.  The CPU reference is a separately named,
explicit fallback and is tested against hand-computed FP32 results.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
MPYNN = ROOT / "mpynn"
PORT = MPYNN / "ports" / "raspberrypi"
SOURCE = PORT / "vc4_runtime.c"
HEADER = PORT / "vc4_runtime.h"


HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "vc4_runtime.h"

static void assert_close(float got, float want) {
    assert(fabsf(got - want) < 1.0e-6f);
}

int main(void) {
    vc4_buffer_t buffer = {0, 0, 0, 0};
    uint32_t uniforms[1] = {0x2000u};
    float weights[16 * 3];
    float input[3] = {2.0f, -1.0f, 0.5f};
    float output[16];
    float short_weights[3 * 2] = {
        1.0f, 2.0f,
        -3.0f, 4.0f,
        0.25f, -2.0f
    };
    float short_input[2] = {4.0f, -0.5f};
    float short_output[3] = {0.0f, 0.0f, 0.0f};
    unsigned row;

    /* Stub state is explicit on every architecture, including ARM builds. */
    assert(vc4_init() == VC4_STATUS_UNAVAILABLE);
    assert(vc4_runtime_status() == VC4_STATUS_UNAVAILABLE);
    assert(vc4_is_available() == 0);
    assert(vc4_is_enabled() == 1);
    assert(vc4_set_enabled(1) == VC4_STATUS_OK);
    assert(vc4_is_enabled() == 1);
    assert(vc4_is_available() == 0);  /* host must never fake GPU support */
    assert(vc4_set_enabled(0) == VC4_STATUS_OK);
    assert(vc4_is_enabled() == 0);
    assert(vc4_should_offload_fp32(16, 4096) == 0);
    assert(strcmp(vc4_status_string(VC4_STATUS_TIMEOUT),
                  "vc4 dispatch timeout") == 0);
    assert(vc4_shutdown() == VC4_STATUS_UNAVAILABLE);

    /* Allocation never turns ordinary host memory into a fake GPU buffer. */
    assert(vc4_alloc(0, 4096, 0, &buffer) == VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_alloc(64, 3, 0, &buffer) == VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_alloc(64, 4096, 0, &buffer) == VC4_STATUS_UNAVAILABLE);
    assert(buffer.cpu == 0 && buffer.bus == 0 && buffer.handle == 0 &&
           buffer.bytes == 0);
    assert(vc4_free(&buffer) == VC4_STATUS_OK);
    assert(vc4_free(0) == VC4_STATUS_INVALID_ARGUMENT);

    /* Launch validates alignment/count/finite timeout before unsupported status. */
    assert(vc4_launch(0, uniforms, 1, 1000) == VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_launch(0x2004u, uniforms, 1, 1000) == VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_launch(0x2000u, uniforms, 1, 0) == VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_launch(0x2000u, uniforms, 13, 1000) == VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_launch(0x2000u, uniforms, 1, 1000) == VC4_STATUS_UNAVAILABLE);

    for (row = 0; row < 16; ++row) {
        weights[row * 3 + 0] = (float)(row + 1);
        weights[row * 3 + 1] = (float)(-2 * (int)(row + 1));
        weights[row * 3 + 2] = (float)(row % 3) * 0.25f;
        output[row] = 1234.0f;
    }

    /* VC4 matvec shape and pointer checks are distinct from unavailable status. */
    assert(vc4_matvec_fp32(weights, 0, input, 15, 3, 1, output) ==
           VC4_STATUS_INVALID_SHAPE);
    assert(vc4_matvec_fp32(weights, 0, input, 16, 0, 1, output) ==
           VC4_STATUS_INVALID_SHAPE);
    assert(vc4_matvec_fp32(weights, 0, input, 16, 3, 0, output) ==
           VC4_STATUS_INVALID_SHAPE);
    assert(vc4_matvec_fp32(weights, 0, input, 16, 3, 13, output) ==
           VC4_STATUS_INVALID_SHAPE);
    assert(vc4_matvec_fp32(0, 0, input, 16, 3, 1, output) ==
           VC4_STATUS_INVALID_ARGUMENT);
    assert(vc4_matvec_fp32(weights, 0, input, 16, 3, 1, output) ==
           VC4_STATUS_UNAVAILABLE);
    for (row = 0; row < 16; ++row) assert(output[row] == 1234.0f);

    /* CPU fallback is explicit and supports ordinary non-VC4 output shapes. */
    assert(vc4_cpu_matvec_fp32(short_weights, short_input, 3, 2,
                               short_output) == VC4_STATUS_OK);
    assert_close(short_output[0], 3.0f);
    assert_close(short_output[1], -14.0f);
    assert_close(short_output[2], 2.0f);
    memset(short_output, 0, sizeof(short_output));
    assert(vc4_matvec_fp32_cpu(short_weights, short_input, 3, 2,
                               short_output) == VC4_STATUS_OK);
    assert_close(short_output[0], 3.0f);
    assert_close(short_output[1], -14.0f);
    assert_close(short_output[2], 2.0f);
    assert(vc4_cpu_matvec_fp32(short_weights, short_input, 0, 2,
                               short_output) == VC4_STATUS_INVALID_SHAPE);
    assert(vc4_cpu_matvec_fp32(short_weights, short_input, 3, 0,
                               short_output) == VC4_STATUS_INVALID_SHAPE);
    assert(vc4_cpu_matvec_fp32(0, short_input, 3, 2,
                               short_output) == VC4_STATUS_INVALID_ARGUMENT);
    return 0;
}
'''


def _compiler_from_env(name, default_names):
    configured = os.environ.get(name)
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
    for candidate in default_names:
        path = Path(candidate)
        if path.is_file():
            return path
        found = shutil.which(candidate)
        if found:
            return Path(found)
    return None


def _run(command):
    executable = Path(command[0])
    env = os.environ.copy()
    if executable.parent != Path('.'):
        env["PATH"] = str(executable.parent) + os.pathsep + env.get("PATH", "")
    result = subprocess.run([str(item) for item in command], env=env,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, (
        "command failed: " + " ".join(map(str, command)) + "\n" +
        result.stdout + result.stderr
    )


def test_vc4_runtime_host_stub_and_cpu_reference():
    compiler = _compiler_from_env(
        "MPYNN_HOST_GCC", ("gcc", "clang", "E:/msys64/ucrt64/bin/gcc.exe"))
    if compiler is None:
        pytest.skip("host C compiler not available")
    with tempfile.TemporaryDirectory(prefix="vc4-runtime-host-") as folder:
        folder = Path(folder)
        harness = folder / "test_vc4_runtime.c"
        executable = folder / ("test_vc4_runtime.exe" if os.name == "nt"
                               else "test_vc4_runtime")
        harness.write_text(HARNESS, encoding="utf-8")
        _run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
              "-Wconversion", "-I" + str(PORT), str(harness), str(SOURCE),
              "-lm", "-o", executable])
        _run([executable])


def test_vc4_runtime_arm_source_compiles_without_acceleration_claim():
    """Cross-compile syntax only when the repository's ARM GCC is available."""
    compiler = _compiler_from_env(
        "MPYNN_ARM_GCC", ("arm-none-eabi-gcc",
                           "E:/arm-none-eabi/bin/arm-none-eabi-gcc.exe"))
    if compiler is None:
        pytest.skip("ARM GCC not available")
    _run([compiler, "-mcpu=arm1176jzf-s", "-marm", "-mfpu=vfp",
          "-mfloat-abi=hard", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
          "-ffreestanding", "-fsyntax-only", "-I" + str(PORT), str(SOURCE)])
    # This assertion protects the staged contract even if a future compiler
    # invocation changes: ARM support is compile-only until the real runtime is
    # implemented, never an architecture-name shortcut.
    source_text = SOURCE.read_text(encoding="utf-8")
    assert "return 0;" in source_text
    assert "VC4_STATUS_UNAVAILABLE" in source_text
    assert "PUT32" not in source_text
    assert "GET32" not in source_text
    assert "mailbox" in source_text.lower()


if __name__ == "__main__":
    test_vc4_runtime_host_stub_and_cpu_reference()
''