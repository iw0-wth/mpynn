# SPDX-License-Identifier: MIT
"""Compile the real Pi kernel against minimal host Circle fakes (no ARM build)."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'ports/raspberrypi'
BOARD = ROOT / 'boards/RPI1B'
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')

# Only external Circle dependencies are faked. The kernel and all its local
# headers, including console_tx.h and both attach declarations, remain real.
CIRCLE_HEADERS = (
    'circle/actled.h',
    'circle/devicenameservice.h',
    'circle/exceptionhandler.h',
    'circle/interrupt.h',
    'circle/gpiomanager.h',
    'circle/koptions.h',
    'circle/logger.h',
    'circle/serial.h',
    'circle/usb/usbhcidevice.h',
    'circle/netdevice.h',
    'circle/net/netsubsystem.h',
    'circle/sched/scheduler.h',
    'circle/synchronize.h',
    'circle/startup.h',
    'circle/timer.h',
    'circle/alloc.h',
    'SDCard/emmc.h',
)

FAKE_CIRCLE = r'''#pragma once
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>

using boolean = bool;
constexpr boolean TRUE = true;
constexpr boolean FALSE = false;
constexpr unsigned TASK_LEVEL = 0;

enum TLogSeverity { LogError, LogWarning, LogNotice };
enum TNetDeviceType { NetDeviceTypeEthernet, NetDeviceTypeOther };

namespace fake {
inline bool sd_ok = true;
inline bool usb_ok = true;
inline bool nic_present = true;
inline bool ethernet = true;
inline bool network_ok = true;
inline unsigned execution_level = TASK_LEVEL;
inline unsigned gpio_init_calls = 0;
inline unsigned gpio_attach_calls = 0;
inline void *gpio_attached = nullptr;
inline unsigned sd_attach_calls = 0;
inline void *sd_attached = nullptr;
inline int sd_attached_ready = -1;
inline unsigned net_attach_calls = 0;
inline void *net_attached = nullptr;
inline int net_attached_ready = -1;
inline unsigned usb_init_calls = 0;
inline unsigned nic_lookups = 0;
inline unsigned net_init_calls = 0;
inline bool wait_for_activate = true;
inline unsigned running_queries = 0;
inline unsigned yields = 0;
inline void (*on_yield)() = nullptr;
inline unsigned serial_baud = 0;
inline unsigned serial_options = 999;
inline unsigned logger_init_calls = 0;
inline void *initial_log_target = nullptr;
inline void *log_target = nullptr;
inline unsigned target_changes = 0;
inline unsigned log_writes = 0;
inline unsigned serial_log_writes = 0;
inline unsigned log_reads = 0;
inline unsigned log_read_length = 0;
inline bool log_read_clear = false;
inline int log_read_result = 0;
inline unsigned event = 0;
inline unsigned logger_init_event = 0;
inline unsigned target_change_event = 0;
inline unsigned vm_event = 0;
inline unsigned vm_calls = 0;
inline uint64_t ticks = 0;
struct VMEntered {};
struct UnexpectedHalt {};
}

class CActLED { public: void Blink(unsigned) {} };
class CKernelOptions { public: unsigned GetLogLevel() { return 0; } };
class CDeviceNameService {};
class CExceptionHandler {};
class CInterruptSystem { public: bool Initialize() { return true; } };
class CGPIOManager {
public:
    explicit CGPIOManager(CInterruptSystem *interrupt) { assert(interrupt); }
    bool Initialize() { ++fake::gpio_init_calls; return true; }
};
class CDevice {};
class CSerialDevice : public CDevice {
public:
    explicit CSerialDevice(CInterruptSystem *) {}
    bool Initialize(unsigned baud) { fake::serial_baud = baud; return true; }
    void SetOptions(unsigned options) { fake::serial_options = options; }
    int Read(void *, size_t) { return 0; }
    int Write(const void *, size_t length) { return static_cast<int>(length); }
};
class CTimer {
public:
    explicit CTimer(CInterruptSystem *) {}
    bool Initialize() { return true; }
    bool SetTime(unsigned, bool) { return true; }
    bool GetUniversalTime(unsigned *seconds, unsigned *usec) { *seconds = 946684800; *usec = 0; return true; }
    static uint64_t GetClockTicks64() { return ++fake::ticks; }
};
class CLogger {
public:
    CLogger(unsigned, CTimer *) {}
    bool Initialize(CDevice *target) {
        ++fake::logger_init_calls;
        fake::initial_log_target = target;
        fake::log_target = target;
        fake::logger_init_event = ++fake::event;
        return true;
    }
    void Write(const char *, TLogSeverity, const char *, ...) {
        ++fake::log_writes;
        if (fake::log_target) ++fake::serial_log_writes;
        ++fake::event;
    }
    void SetNewTarget(CDevice *target) {
        fake::log_target = target;
        ++fake::target_changes;
        fake::target_change_event = ++fake::event;
    }
    int Read(void *buffer, unsigned length, boolean clear) {
        ++fake::log_reads;
        fake::log_read_length = length;
        fake::log_read_clear = clear;
        for (int i = 0; i < fake::log_read_result &&
                        static_cast<unsigned>(i) < length; ++i) {
            static_cast<char *>(buffer)[i] = 'L';
        }
        return fake::log_read_result;
    }
};
class CEMMCDevice {
public:
    CEMMCDevice(CInterruptSystem *, CTimer *, CActLED *) {}
    bool Initialize() { return fake::sd_ok; }
};
class CUSBHCIDevice {
public:
    CUSBHCIDevice(CInterruptSystem *, CTimer *) {}
    bool Initialize() { ++fake::usb_init_calls; return fake::usb_ok; }
};
class CNetDevice {
public:
    static CNetDevice *GetNetDevice(unsigned index) {
        assert(index == 0);
        ++fake::nic_lookups;
        static CNetDevice device;
        return fake::nic_present ? &device : nullptr;
    }
    TNetDeviceType GetType() {
        return fake::ethernet ? NetDeviceTypeEthernet : NetDeviceTypeOther;
    }
};
class CNetSubSystem {
public:
    bool Initialize(boolean wait = TRUE) {
        ++fake::net_init_calls;
        fake::wait_for_activate = wait;
        return fake::network_ok;
    }
    bool IsRunning() { ++fake::running_queries; return false; }
};
class CScheduler {
public:
    void Yield() {
        ++fake::yields;
        // A broken reentrancy guard fails immediately instead of overflowing
        // the host stack; the callback models logging from a network task.
        assert(fake::yields < 10);
        if (fake::on_yield) fake::on_yield();
    }
};
inline unsigned CurrentExecutionLevel() { return fake::execution_level; }
[[noreturn]] inline void halt() { throw fake::UnexpectedHalt{}; }
'''

HARNESS = r'''#include <cassert>
#include <cstdlib>
#include <string>
#include <fake_circle.h>
#include "network_bridge.h"

// Compile the production translation unit, not a copied implementation.
#define main firmware_main
#include "kernel.cpp"
#undef main

extern "C" void mpynn_gpio_irq_attach_manager(void *manager) {
    assert(fake::gpio_init_calls == 1);
    assert(manager);
    ++fake::gpio_attach_calls;
    fake::gpio_attached = manager;
}
extern "C" void mpynn_sd_attach(void *device, int initialized) {
    ++fake::sd_attach_calls;
    fake::sd_attached = device;
    fake::sd_attached_ready = initialized;
}
extern "C" void mpynn_network_attach(void *network, int initialized) {
    ++fake::net_attach_calls;
    fake::net_attached = network;
    fake::net_attached_ready = initialized;
}

// The real declaration is noreturn: throwing preserves that contract and lets
// the host observe firmware startup without executing a VM or halting a Pi.
extern "C" void mpynn_vm_run(void *heap, size_t heap_size) {
    assert(kernel);
    assert(heap);
    assert(heap_size == MPYNN_GC_HEAP_SIZE);
    ++fake::vm_calls;
    fake::vm_event = ++fake::event;
    assert(fake::logger_init_calls == 1);
    assert(fake::initial_log_target == static_cast<CDevice *>(&kernel->serial));
    assert(fake::log_target == nullptr);
    assert(fake::target_changes == 1);
    assert(fake::logger_init_event < fake::target_change_event);
    assert(fake::target_change_event < fake::vm_event);
    assert(fake::serial_log_writes > 0);
    const unsigned serial_before = fake::serial_log_writes;
    const unsigned logs_before = fake::log_writes;
    kernel->logger.Write("fake-net", LogNotice, "background DHCP log");
    assert(fake::serial_log_writes == serial_before);
    assert(fake::log_writes == logs_before + 1);
    std::free(heap);
    throw fake::VMEntered{};
}

static void initialize_case(const std::string &scenario) {
    fake::sd_ok = scenario != "sd_failure";
    fake::usb_ok = scenario != "usb_failure";
    fake::nic_present = scenario != "no_nic";
    fake::ethernet = scenario != "other_nic";
    fake::network_ok = scenario != "network_failure";
    Kernel platform;
    kernel = &platform;
    assert(!platform.network_ready);
    assert(platform.Initialize());
    assert(fake::gpio_init_calls == 1);
    assert(fake::gpio_attach_calls == 1);
    assert(fake::gpio_attached == &platform.gpio_manager);
    assert(fake::serial_baud == MPYNN_UART_BAUD);
    assert(fake::serial_options == 0);
    assert(fake::logger_init_calls == 1);
    assert(fake::initial_log_target == static_cast<CDevice *>(&platform.serial));
    assert(fake::log_target == static_cast<CDevice *>(&platform.serial));
    assert(fake::target_changes == 0);
    assert(fake::log_writes > 0);
    assert(fake::serial_log_writes == fake::log_writes);
    assert(fake::sd_attach_calls == 1);
    assert(fake::sd_attached == &platform.sdcard);
    assert(fake::sd_attached_ready == static_cast<int>(fake::sd_ok));
    assert(fake::usb_init_calls == 1);
    assert(fake::nic_lookups == static_cast<unsigned>(fake::usb_ok));
    const bool attempted = fake::usb_ok && fake::nic_present && fake::ethernet;
    assert(fake::net_init_calls == static_cast<unsigned>(attempted));
    if (attempted) assert(fake::wait_for_activate == FALSE);
    assert(fake::running_queries == 0);
    assert(fake::yields == 0); // Initialize must not wait cooperatively for DHCP.
    const bool ready = attempted && fake::network_ok;
    assert(platform.network_ready == ready);
    assert(fake::net_attach_calls == static_cast<unsigned>(ready));
    if (ready) {
        assert(fake::net_attached == &platform.net);
        assert(fake::net_attached_ready == 1);
    }
    kernel = nullptr;
}

static void poll_case() {
    assert(kernel == nullptr);
    mpynn_platform_poll();
    assert(fake::yields == 0);
    Kernel platform;
    kernel = &platform;
    for (bool ready : {false, true}) {
        platform.network_ready = ready;
        for (unsigned level : {TASK_LEVEL, 1u, 2u}) {
            fake::execution_level = level;
            const unsigned before = fake::yields;
            mpynn_platform_poll();
            assert(fake::yields == before +
                   static_cast<unsigned>(ready && level == TASK_LEVEL));
        }
    }
    fake::execution_level = TASK_LEVEL;
    fake::on_yield = mpynn_platform_poll;
    const unsigned before = fake::yields;
    mpynn_platform_poll();
    assert(fake::yields == before + 1); // Nested poll never yields again.
    mpynn_platform_poll();
    assert(fake::yields == before + 2); // Guard resets after the outer yield.
    fake::on_yield = nullptr;
    kernel = nullptr;
}

static void logs_case() {
    char buffer[1026] = {};
    assert(kernel == nullptr);
    assert(mpynn_log_read(buffer, 1) == 0);
    assert(fake::log_reads == 0);
    Kernel platform;
    kernel = &platform;
    assert(mpynn_log_read(nullptr, 1) == 0);
    assert(mpynn_log_read(buffer, 0) == 0);
    assert(mpynn_log_read(buffer, 1025) == 0);
    assert(mpynn_log_read(buffer, static_cast<size_t>(-1)) == 0);
    assert(fake::log_reads == 0);

    buffer[0] = 'A';
    buffer[1025] = 'Z';
    fake::log_read_result = 1024;
    assert(mpynn_log_read(buffer + 1, 1024) == 1024);
    assert(fake::log_reads == 1);
    assert(fake::log_read_length == 1024);
    assert(fake::log_read_clear == TRUE);
    assert(buffer[0] == 'A' && buffer[1025] == 'Z');
    for (unsigned i = 1; i <= 1024; ++i) assert(buffer[i] == 'L');

    fake::log_read_result = 1;
    assert(mpynn_log_read(buffer, 1) == 1);
    assert(fake::log_read_length == 1);
    fake::log_read_result = 3;
    assert(mpynn_log_read(buffer, 10) == 3); // Preserve a short ring read.
    fake::log_read_result = 0;
    assert(mpynn_log_read(buffer, 1024) == 0);
    fake::log_read_result = -1;
    assert(mpynn_log_read(buffer, 1024) == 0);
    assert(fake::log_reads == 5);
    kernel = nullptr;
}

static void firmware_case() {
    bool entered = false;
    try {
        firmware_main();
        assert(false && "firmware_main returned instead of entering the VM");
    } catch (const fake::VMEntered &) {
        entered = true;
        // The stack-owned platform has unwound; do not dereference its pointer.
        kernel = nullptr;
    }
    assert(entered);
    assert(fake::vm_calls == 1);
    assert(fake::log_target == nullptr);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string scenario(argv[1]);
    if (scenario == "poll") poll_case();
    else if (scenario == "logs") logs_case();
    else if (scenario == "firmware") firmware_case();
    else {
        assert(scenario == "success" || scenario == "sd_failure" ||
               scenario == "usb_failure" || scenario == "no_nic" ||
               scenario == "other_nic" || scenario == "network_failure");
        initialize_case(scenario);
    }
    return 0;
}
'''


class KernelHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Missing/broken host tools are errors, not skipped coverage.
        if not CXX.is_file():
            raise FileNotFoundError(f'Required host compiler not found: {CXX}')
        cls.env = os.environ.copy()
        cls.env['PATH'] = str(CXX.parent) + os.pathsep + cls.env.get('PATH', '')
        temporary = tempfile.TemporaryDirectory(prefix='mpynn-kernel-host-')
        def cleanup():
            # Windows may briefly retain the just-exited EXE mapping. Retry only
            # this known TemporaryDirectory, bounded; persistent failure is real.
            for attempt in range(21):
                try:
                    temporary.cleanup()
                    return
                except PermissionError:
                    if attempt == 20:
                        raise
                    time.sleep(0.1)
        cls.addClassCleanup(cleanup)
        root = Path(temporary.name)
        (root / 'fake_circle.h').write_text(FAKE_CIRCLE, encoding='ascii')
        for name in CIRCLE_HEADERS:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#pragma once\n#include <fake_circle.h>\n', encoding='ascii')
        harness = root / 'kernel_host.cpp'
        harness.write_text(HARNESS, encoding='ascii')
        cls.executable = root / 'kernel_host.exe'
        command = [
            str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
            '-I' + str(root), '-I' + str(PORT), '-I' + str(BOARD),
            str(harness), '-o', str(cls.executable),
        ]
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=60, env=cls.env)
        if result.returncode:
            raise AssertionError(
                f'Host kernel compilation failed ({result.returncode}):\n'
                + result.stdout + result.stderr)

    def run_case(self, scenario):
        # Each scenario owns fresh kernel/static fake state in its own process.
        result = subprocess.run([str(self.executable), scenario],
                                capture_output=True, text=True, timeout=15,
                                env=self.env)
        self.assertEqual(result.returncode, 0,
                         f'{scenario}:\n{result.stdout}{result.stderr}')

    def test_initialize_success_is_nonblocking_and_attaches_network(self):
        self.run_case('success')

    def test_sd_failure_preserves_repl_and_network(self):
        self.run_case('sd_failure')

    def test_usb_failure_preserves_repl(self):
        self.run_case('usb_failure')

    def test_missing_nic_preserves_repl(self):
        self.run_case('no_nic')

    def test_non_ethernet_device_preserves_repl(self):
        self.run_case('other_nic')

    def test_network_initialize_failure_preserves_repl(self):
        self.run_case('network_failure')

    def test_poll_requires_network_task_context_and_blocks_reentry(self):
        self.run_case('poll')

    def test_log_read_validates_arguments_and_caps_at_1024(self):
        self.run_case('logs')

    def test_firmware_starts_on_serial_and_detaches_logger_before_vm(self):
        self.run_case('firmware')


if __name__ == '__main__':
    unittest.main()
