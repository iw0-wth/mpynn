# SPDX-License-Identifier: MIT
"""Execute extracted production log-ring and VC4 diagnostic-reset methods.

Only the dependency shells are mocked. The C++ methods, runtime-state layouts,
slot constants and ring size are read from the current production sources for
all compilations. These are host method tests, not complete MicroPython binding,
Circle locking/concurrency, GPU/MMIO, or target-board integration tests.
"""
from pathlib import Path
import os
import re
import tempfile

import pytest

from test_vc4_runtime_host import MPYNN, PORT, _compiler_from_env, _run


LOGGER = MPYNN / "lib" / "circle" / "lib" / "logger.cpp"
LOGGER_HEADER = MPYNN / "lib" / "circle" / "include" / "circle" / "logger.h"
KERNEL = PORT / "kernel.cpp"
RUNTIME = MPYNN / "lib" / "vc4-runtime" / "src" / "vc4_runtime.cpp"


def _definition(source, signature, *, trailing_semicolon=False):
    """Extract one real definition, balancing braces outside comments/strings."""
    assert source.count(signature) == 1, f"expected one definition: {signature}"
    start = source.index(signature)
    opening = source.index("{", start)
    # Consume lexical tokens rather than counting braces inside C++ literals.
    tokens = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'
                        r"'(?:\\.|[^'\\])*'|[{}]", re.DOTALL)
    depth = 0
    for token in tokens.finditer(source, opening):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                end = token.end()
                if trailing_semicolon:
                    assert source[end:end + 1] == ";"
                    end += 1
                return source[start:end]
    raise AssertionError(f"unbalanced definition: {signature}")


def _compile_and_run(source, name, *defines):
    compiler = _compiler_from_env(
        "MPYNN_HOST_GXX", ("g++", "clang++", "E:/msys64/ucrt64/bin/g++.exe"))
    if compiler is None:
        pytest.skip("host C++ compiler not available")
    with tempfile.TemporaryDirectory(prefix=name + "-") as folder:
        folder = Path(folder)
        harness = folder / (name + ".cpp")
        executable = folder / (name + (".exe" if os.name == "nt" else ""))
        harness.write_text(source, encoding="utf-8")
        # Avoid picking up incompatible Anaconda/other MinGW runtime DLLs from
        # PATH when the Windows harness uses std::string in the log test.
        runtime_flags = ["-static-libgcc", "-static-libstdc++"] if os.name == "nt" else []
        _run([compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
              *runtime_flags, *defines, "-I" + str(PORT), harness, "-o", executable])
        _run([executable])


LOG_SHELL = r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <string>
using boolean = bool;
constexpr boolean TRUE = true;
constexpr boolean FALSE = false;
struct HostLock {
    bool held = false;
    unsigned acquired = 0;
    unsigned released = 0;
    void Acquire() { assert(!held); held = true; ++acquired; }
    void Release() { assert(held); held = false; ++released; }
};
struct HostTarget {
    std::string text;
    void Write(const char *data, unsigned long length) { text.append(data, length); }
};
class CLogger {
public:
    void Write(const char *pString);
    int Read(void *pBuffer, unsigned nCount, boolean bClear = TRUE);
    boolean m_bOverwriteOldest = TRUE;
    HostTarget *m_pTarget = nullptr;
    char storage[LOGGER_BUFSIZE] = {};
    char *m_pBuffer = storage;
    unsigned m_nInPtr = 0;
    unsigned m_nOutPtr = 0;
    HostLock m_SpinLock;
};
struct Kernel { CLogger logger; };
static Kernel *kernel = nullptr;
'''


LOG_CHECKS = r'''
static void check_bytes(const char *actual, const std::string &expected) {
    assert(std::memcmp(actual, expected.data(), expected.size()) == 0);
}
static std::string pattern(size_t size, unsigned offset = 0) {
    std::string result(size, 'a');
    for (size_t i = 0; i < size; ++i) result[i] = char('!' + (i + offset) % 90);
    return result;
}
int main() {
    static_assert(LOGGER_BUFSIZE == 16 * 1024, "production ring must be 16 KiB");
    constexpr size_t capacity = LOGGER_BUFSIZE - 1;
    char output[LOGGER_BUFSIZE + 2];
    std::memset(output, '~', sizeof(output));
    assert(mpynn_log_read_ex(output, 10, 0) == 0); // no kernel
    assert(mpynn_log_read(output, 10) == 0);
    assert(output[0] == '~');

    Kernel platform;
    kernel = &platform;
    assert(mpynn_log_read_ex(output, 10, 0) == 0); // empty
    assert(mpynn_log_read(output, 10) == 0);
    platform.logger.Write("ab\r\ncd");
    unsigned locks = platform.logger.m_SpinLock.acquired;
    assert(mpynn_log_read_ex(nullptr, 10, 0) == 0);
    assert(mpynn_log_read(nullptr, 10) == 0);
    assert(mpynn_log_read_ex(output, 0, 1) == 0);
    assert(mpynn_log_read_ex(output, LOGGER_BUFSIZE + 1u, 1) == 0);
    assert(mpynn_log_read_ex(output, SIZE_MAX, 1) == 0);
    assert(mpynn_log_read(output, SIZE_MAX) == 0);
    assert(platform.logger.m_SpinLock.acquired == locks);
    assert(output[0] == '~');

    // Repeated peeks retain bytes, partial consumes advance, legacy read consumes.
    assert(mpynn_log_read_ex(output, 3, 0) == 3);
    check_bytes(output, "ab\n");
    assert(output[3] == '~'); // raw bytes, no added terminator
    assert(mpynn_log_read_ex(output, 3, 0) == 3);
    check_bytes(output, "ab\n");
    assert(mpynn_log_read_ex(output, 2, -7) == 2); // every nonzero clear consumes
    check_bytes(output, "ab");
    assert(mpynn_log_read_ex(output, LOGGER_BUFSIZE, 0) == 3);
    check_bytes(output, "\ncd");
    assert(mpynn_log_read(output, LOGGER_BUFSIZE) == 3);
    check_bytes(output, "\ncd");
    assert(mpynn_log_read(output, LOGGER_BUFSIZE) == 0);

    // Position both cursors near the end, then read data crossing index zero.
    std::string initial = pattern(LOGGER_BUFSIZE - 20);
    platform.logger.Write(initial.c_str());
    assert(mpynn_log_read(output, initial.size() - 7) == initial.size() - 7);
    check_bytes(output, initial.substr(0, initial.size() - 7));
    std::string next = pattern(64, 31);
    platform.logger.Write(next.c_str());
    std::string wrapped = initial.substr(initial.size() - 7) + next;
    assert(mpynn_log_read_ex(output, LOGGER_BUFSIZE, 0) == wrapped.size());
    check_bytes(output, wrapped);
    assert(mpynn_log_read_ex(output, LOGGER_BUFSIZE, 0) == wrapped.size());
    check_bytes(output, wrapped);
    assert(mpynn_log_read(output, 11) == 11);
    check_bytes(output, wrapped.substr(0, 11));
    assert(mpynn_log_read(output, LOGGER_BUFSIZE) == wrapped.size() - 11);
    check_bytes(output, wrapped.substr(11));

    // Default overwrite retains exactly the newest 16383 bytes over many wraps.
    for (size_t length : {capacity, size_t(LOGGER_BUFSIZE),
                          size_t(LOGGER_BUFSIZE * 3 + 17)}) {
        Kernel full;
        kernel = &full;
        std::string input = pattern(length);
        full.logger.Write(input.c_str());
        std::string expected = input.substr(length - capacity);
        std::memset(output, '~', sizeof(output));
        assert(mpynn_log_read_ex(output, LOGGER_BUFSIZE, 0) == capacity);
        check_bytes(output, expected);
        assert(output[capacity] == '~');
        assert(mpynn_log_read_ex(output, LOGGER_BUFSIZE, 0) == capacity);
        check_bytes(output, expected);
        assert(mpynn_log_read(output, LOGGER_BUFSIZE) == capacity);
        check_bytes(output, expected);
        assert(mpynn_log_read(output, LOGGER_BUFSIZE) == 0);
        assert(!full.logger.m_SpinLock.held);
        assert(full.logger.m_SpinLock.acquired == full.logger.m_SpinLock.released);
    }

    // The other real Write branch stops accepting bytes when full.
    Kernel no_overwrite;
    kernel = &no_overwrite;
    no_overwrite.logger.m_bOverwriteOldest = FALSE;
    std::string oversized = pattern(LOGGER_BUFSIZE + 23);
    no_overwrite.logger.Write(oversized.c_str());
    assert(mpynn_log_read(output, LOGGER_BUFSIZE) == capacity);
    check_bytes(output, oversized.substr(0, capacity));
    assert(mpynn_log_read(output, LOGGER_BUFSIZE) == 0);

    // A configured output target sees the original text, including CR.
    HostTarget target;
    no_overwrite.logger.m_pTarget = &target;
    no_overwrite.logger.Write("x\r\ny");
    assert(target.text == "x\r\ny");
    assert(mpynn_log_read(output, LOGGER_BUFSIZE) == 3);
    check_bytes(output, "x\ny");
    assert(!no_overwrite.logger.m_SpinLock.held);
    assert(no_overwrite.logger.m_SpinLock.acquired ==
           no_overwrite.logger.m_SpinLock.released);
    return 0;
}
'''


def test_real_circle_log_ring_and_kernel_read_wrappers():
    logger = LOGGER.read_text(encoding="utf-8")
    header = LOGGER_HEADER.read_text(encoding="utf-8")
    kernel = KERNEL.read_text(encoding="utf-8")
    ring_size = re.search(r"^#define\s+LOGGER_BUFSIZE\s+\S+", header, re.MULTILINE)
    assert ring_size, "production logger ring-size definition missing"
    methods = [
        _definition(logger, "void CLogger::Write (const char *pString)"),
        _definition(logger, "int CLogger::Read (void *pBuffer, unsigned nCount, boolean bClear)"),
        _definition(kernel, 'extern "C" size_t mpynn_log_read_ex('),
        _definition(kernel, 'extern "C" size_t mpynn_log_read('),
    ]
    _compile_and_run("\n".join([ring_size.group(), LOG_SHELL, *methods, LOG_CHECKS]),
                     "vc4-log-host")


RESET_SHELL = r'''
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include "vc4_runtime.h"
#include "vc4_platform.h"
class RuntimeLogger {
public:
    void Write(const char *source, vc4_log_level_t severity, const char *format, ...) {
        assert(std::strcmp(source, "vc4") == 0);
        assert(severity == VC4_LOG_NOTICE);
        ++writes;
        va_list arguments;
        va_start(arguments, format);
        int count = std::vsnprintf(message, sizeof(message), format, arguments);
        va_end(arguments);
        assert(count >= 0 && size_t(count) < sizeof(message));
    }
    unsigned writes = 0;
    char message[256] = {};
};
static RuntimeLogger logger;
static bool have_logger = true;
static RuntimeLogger *runtime_logger() { return have_logger ? &logger : nullptr; }
'''


RESET_CHECKS = r'''
static unsigned char cpu_tokens[
    kWeightCacheSlots + kDeferredFreeSlots + kActiveBufferSlots + 1];
static float source_tokens[kWeightCacheSlots];
static void seed_state() {
    // Zero padding too: full-object comparisons detect every unintended write.
    std::memset(&g_state, 0, sizeof(g_state));
    g_state.initialized = 1;
    g_state.qpu_enabled = 1;
    g_state.enabled = 1;
    g_state.inflight_count = 23u;
    g_state.use_sequence = 47u;
    g_state.arm_clock_hz = 700123456u;
    g_state.core_clock_hz = 250987654u;
    g_state.success_logged = 2;
    g_state.gate_logged = 3;
    g_state.allocation_logged = 4;
    g_state.allocation_failure_logged = 5;
    g_state.copy_logged = 6;
    g_state.dispatch_failure_logged = 7;
    g_state.dispatch_log_count = 8u;
    g_state.matvec_log_count = 9u;
    for (uint32_t i = 0; i < kWeightCacheSlots; ++i) {
        WeightCacheEntry &entry = g_state.weights[i];
        entry.buffer = {&cpu_tokens[i], 0xC0001000u + i * 4096u,
                        101u + i, 2048u + i};
        entry.source = &source_tokens[i];
        entry.bytes = 1000u + i;
        entry.output_depth = 16u * (i + 1u);
        entry.input_depth = 32u + i;
        entry.last_used = 50u + i;
        entry.release_pending = int(i % 2u);
    }
    for (uint32_t i = 0; i < kActiveBufferSlots; ++i) {
        g_state.active_buffers[i] = {
            0xC1001000u + i * 4096u, 201u + i, 4000u + i,
            &cpu_tokens[kWeightCacheSlots + kDeferredFreeSlots + i],
            64u + i, 128u + i};
    }
    for (uint32_t i = 0; i < kDeferredFreeSlots; ++i) {
        g_state.deferred_free[i] = {&cpu_tokens[kWeightCacheSlots + i],
                                   0xC2001000u + i * 4096u, 401u + i, 8000u + i};
    }
    g_state.workspace = {
        &cpu_tokens[kWeightCacheSlots + kDeferredFreeSlots + kActiveBufferSlots],
        0xC3001000u, 999u, 65536u};
    logger.writes = 0;
    have_logger = true;
}
static RuntimeState snapshot() {
    RuntimeState result;
    std::memcpy(&result, &g_state, sizeof(result));
    return result;
}
static void assert_state(const RuntimeState &expected) {
    assert(std::memcmp(&g_state, &expected, sizeof(g_state)) == 0);
}
static void clear_expected_diagnostics(RuntimeState &expected) {
    expected.success_logged = 0;
    expected.gate_logged = 0;
    expected.allocation_logged = 0;
    expected.allocation_failure_logged = 0;
    expected.copy_logged = 0;
    expected.dispatch_failure_logged = 0;
    expected.dispatch_log_count = 0;
    expected.matvec_log_count = 0;
}
int main() {
    // Busy is rejected without even logging or modifying diagnostic counters.
    for (int busy : {1, -1}) {
        for (int initialized : {0, 1}) {
            seed_state();
            g_state.dispatch_inflight = busy;
            g_state.initialized = initialized;
            RuntimeState before = snapshot();
            assert(vc4_reset_diagnostics() == VC4_STATUS_TIMEOUT);
            assert_state(before);
            assert(logger.writes == 0);
        }
    }
    // All unavailable idle combinations are also read-only.
    for (int initialized : {0, 1}) {
        for (int qpu_enabled : {0, 1}) {
            if (initialized && qpu_enabled) continue;
            seed_state();
            g_state.initialized = initialized;
            g_state.qpu_enabled = qpu_enabled;
            RuntimeState before = snapshot();
            assert(vc4_reset_diagnostics() == VC4_STATUS_UNAVAILABLE);
            assert_state(before);
            assert(logger.writes == 0);
        }
    }
    for (int enabled : {0, 1}) {
        seed_state();
        g_state.enabled = enabled;
        RuntimeState expected = snapshot();
        clear_expected_diagnostics(expected);
        assert(vc4_reset_diagnostics() == VC4_STATUS_OK);
        // Covers every slot/metadata byte in weights, active/deferred buffers,
        // workspace, all enable/clock/lifecycle fields, and future state fields.
        assert_state(expected);
        assert(logger.writes == 1);
        char message[256];
        std::snprintf(message, sizeof(message),
                      "VC4 diagnostics rearmed: arm_mhz=700 core_mhz=250 packed16=%u profile=%u",
                      unsigned(VC4_RUNTIME_PACKED_WEIGHTS), unsigned(VC4_RUNTIME_PROFILE_COUNTERS));
        assert(std::strcmp(logger.message, message) == 0);
        // State reset is idempotent; each successful call still emits a notice.
        assert(vc4_reset_diagnostics() == VC4_STATUS_OK);
        assert_state(expected);
        assert(logger.writes == 2);
    }
    seed_state();
    have_logger = false;
    RuntimeState expected = snapshot();
    clear_expected_diagnostics(expected);
    assert(vc4_reset_diagnostics() == VC4_STATUS_OK);
    assert_state(expected);
    assert(logger.writes == 0);
    assert(vc4_reset_diagnostics() == VC4_STATUS_OK);
    assert_state(expected);
    return 0;
}
'''


@pytest.mark.parametrize("packed,profile", [(0, 0), (1, 1), (1, 0)])
def test_real_vc4_diagnostic_reset_preserves_runtime_state(packed, profile):
    runtime = RUNTIME.read_text(encoding="utf-8")
    # Extract only state dependencies; no allocator, free, mailbox or MMIO code
    # or implementation is supplied. Unexpected calls fail compilation/linking.
    constants = []
    for name in ("kWeightCacheSlots", "kDeferredFreeSlots", "kActiveBufferSlots"):
        match = re.search(r"^constexpr uint32_t " + name + r"\s*=\s*[^;]+;",
                          runtime, re.MULTILINE)
        assert match, f"missing runtime state constant: {name}"
        constants.append(match.group())
    definitions = [
        _definition(runtime, "struct " + name + " {", trailing_semicolon=True)
        for name in ("ActiveBufferRecord", "WeightCacheEntry", "RuntimeState")
    ]
    state = re.search(r"^RuntimeState g_state\s*=\s*\{\};", runtime, re.MULTILINE)
    assert state, "missing production runtime-state initializer"
    reset = _definition(runtime, 'extern "C" vc4_status_t vc4_reset_diagnostics(')
    source = "\n".join(["#include <initializer_list>", RESET_SHELL, *constants,
                        *definitions, state.group(), reset, RESET_CHECKS])
    _compile_and_run(source, "vc4-reset-host",
                     "-I" + str(RUNTIME.parent.parent / "include"),
                     f"-DVC4_RUNTIME_PACKED_WEIGHTS={packed}",
                     f"-DVC4_RUNTIME_PROFILE_COUNTERS={profile}")
