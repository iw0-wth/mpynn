// SPDX-License-Identifier: MIT
// Circle owns startup, MMU, exception vectors, device memory and C++ lifetime.
#include <circle/actled.h>
#include <circle/devicenameservice.h>
#include <circle/exceptionhandler.h>
#include <circle/interrupt.h>
#include <circle/koptions.h>
#include <circle/logger.h>
#include <circle/serial.h>
#include <circle/usb/usbhcidevice.h>
#include <circle/netdevice.h>
#include <circle/net/netsubsystem.h>
#include <circle/sched/scheduler.h>
#include <circle/synchronize.h>
#include <circle/startup.h>
#include <circle/timer.h>
#include <circle/alloc.h>
#include <circle/memory.h>
#include <circle/machineinfo.h>
#include "board_config.h"
#include "circle_bridge.h"
#include "console_tx.h"
#include <SDCard/emmc.h>
#include "sdcard_bridge.h"
#include "network_bridge.h"
#include "rtc_bridge.h"
#include "vc4_runtime.h"
#include "vc4_circle_platform.h"
#include <circle/gpiomanager.h>
#include "gpio_bridge.h"
extern "C" void mpynn_gpio_irq_attach_manager(void *manager);
extern "C" void mpynn_gpio_irq_attach_manager(void *manager);

#ifndef MPYNN_VC4_POLL_STRIDE
#define MPYNN_VC4_POLL_STRIDE 4096u
#endif
#ifndef MPYNN_VC4_WAIT_SLEEP_US
#define MPYNN_VC4_WAIT_SLEEP_US 0u
#endif
#if MPYNN_VC4_POLL_STRIDE == 0 || \
    (MPYNN_VC4_POLL_STRIDE & (MPYNN_VC4_POLL_STRIDE - 1)) != 0
#error MPYNN_VC4_POLL_STRIDE must be a power of two
#endif

class Kernel {
public:
    Kernel() : gpio_manager(&interrupt), serial(&interrupt), timer(&interrupt), logger(options.GetLogLevel(), &timer),
               sdcard(&interrupt, &timer, &led), usb(&interrupt, &timer) {}
    bool Initialize() {
        if (!interrupt.Initialize()) return false;
        if (!gpio_manager.Initialize()) return false;
        mpynn_gpio_irq_attach_manager(&gpio_manager);
        if (!serial.Initialize(MPYNN_UART_BAUD)) return false;
        // Preserve raw REPL bytes; MicroPython performs cooked newline output.
        serial.SetOptions(0);
        if (!logger.Initialize(&serial)) return false;
        if (!timer.Initialize()) return false;
        // No battery-backed RTC on Pi 1B: software clock starts at 2000-01-01.
        // This is intentionally not marked TLS-trusted or persistent.
        if (mpynn_rtc_boot_software_epoch(946684800u) != 0) return false;
        led.Blink(2);
        // CEMMCDevice wraps SDHOST when Circle's USE_SDHOST is selected (Pi 1).
        // Initialization is platform lifetime only, never repeated on VM reset.
        bool sd_ok = sdcard.Initialize();
        mpynn_sd_attach(&sdcard, sd_ok);
        if (!sd_ok) logger.Write("mpynn", LogWarning, "SD unavailable; continuing to UART REPL");
        // Pi 1B's onboard LAN9512 sits behind DWHCI USB Host. USB failure must
        // not take down the UART REPL or a local AI workload.
        if (!usb.Initialize()) {
            logger.Write("mpynn", LogWarning, "USB Host unavailable; Ethernet disabled");
        } else {
            CNetDevice *eth = CNetDevice::GetNetDevice(0);
            logger.Write("mpynn", eth ? LogNotice : LogWarning,
                         eth ? "Onboard USB Ethernet enumerated" : "LAN9512 not enumerated");
            if (eth && eth->GetType() == NetDeviceTypeEthernet) {
                // Nonblocking init: DHCP runs in Circle's cooperative net task.
                if (net.Initialize(FALSE)) {
                    mpynn_network_attach(&net, true);
                    network_ready = true;
                    logger.Write("mpynn", LogNotice, "Circle IPv4/DHCP initialized");
                } else {
                    logger.Write("mpynn", LogWarning, "Network init failed; UART REPL remains available");
                }
            }
        }
        const unsigned arm_hz = CMachineInfo::Get()->GetClockRate(CLOCK_ID_ARM);
        const unsigned core_hz = CMachineInfo::Get()->GetClockRate(CLOCK_ID_CORE);
        logger.Write("mpynn", LogNotice,
                     "Pi1B clocks: ARM %u MHz, CORE %u MHz; VC4 QPU runtime is separately probed",
                     arm_hz / 1000000u, core_hz / 1000000u);
        vc4_status_t vc4_status = mpynn_vc4_bind_circle();
        if (vc4_status == VC4_STATUS_OK) vc4_status = vc4_init();
        logger.Write("mpynn", vc4_status == VC4_STATUS_OK ? LogNotice : LogWarning,
                     "VC4 QPU-enable probe: %s", vc4_status_string(vc4_status));
        return true;
    }
    // Construction order follows Circle. No framebuffer, display or IDE.
    CActLED led;
    CKernelOptions options;
    CDeviceNameService devices;
    CExceptionHandler exceptions;
    CInterruptSystem interrupt;
    CGPIOManager gpio_manager;
    CSerialDevice serial; // Circle IRQ RX buffer; Python runs only in VM context
    CTimer timer;
    CLogger logger;
    CEMMCDevice sdcard;
    CUSBHCIDevice usb;
    CScheduler scheduler;
    CNetSubSystem net;
    bool network_ready = false;
};
static Kernel *kernel;
static size_t g_circle_low_free;
static size_t g_gc_heap_size;
static size_t g_circle_heap_reserve;
extern "C" size_t mpynn_circle_low_free(void) { return g_circle_low_free; }
extern "C" size_t mpynn_gc_heap_size(void) { return g_gc_heap_size; }
extern "C" size_t mpynn_circle_heap_reserve(void) { return g_circle_heap_reserve; }
static bool rtc_valid;
static unsigned rtc_source;
extern "C" int mpynn_rtc_get_utc(uint32_t *seconds, unsigned *valid, unsigned *source) {
    if (!kernel || !seconds || !valid || !source || CurrentExecutionLevel() != TASK_LEVEL) return -1;
    unsigned current_seconds = 0;
    unsigned usec = 0;
    boolean ok = kernel->timer.GetUniversalTime(&current_seconds, &usec);
    if (!ok) return -1;
    *seconds = current_seconds;
    *valid = rtc_valid && ok && *seconds != 0;
    *source = *valid ? rtc_source : 0;
    return 0;
}
extern "C" int mpynn_rtc_boot_software_epoch(uint32_t seconds) {
    if (!kernel || !seconds || !kernel->timer.SetTime(seconds, FALSE)) return -1;
    rtc_valid = false;
    rtc_source = 0;
    return 0;
}
extern "C" int mpynn_rtc_set_utc(uint32_t seconds) {
    if (!kernel || CurrentExecutionLevel() != TASK_LEVEL || seconds > INT32_MAX) return -1;
    if (!kernel->timer.SetTime(seconds, FALSE)) return -1;
    rtc_valid = true;
    rtc_source = 1;
    return 0;
}
// Debugger-visible counters: UART faults are not silently treated as valid data.
volatile unsigned mpynn_uart_rx_errors;
volatile unsigned mpynn_uart_tx_stalls;
extern "C" int mpynn_console_read(void) {
    unsigned char byte;
    int result = kernel->serial.Read(&byte, 1);
    if (result < 0) ++mpynn_uart_rx_errors;
    return result == 1 ? byte : -1;
}
extern "C" size_t mpynn_console_write(const char *data, size_t length) {
    size_t written = mpynn_console_write_all(data, length,
        [](const char *buffer, size_t size) { return kernel->serial.Write(buffer, size); },
        []() { return CTimer::GetClockTicks64(); },
        []() { mpynn_platform_poll(); });
    if (written != length) ++mpynn_uart_tx_stalls;
    return written;
}
extern "C" size_t mpynn_log_read_ex(char *buffer, size_t length, int clear) {
    if (!kernel || !buffer || !length || length > LOGGER_BUFSIZE) return 0;
    int count = kernel->logger.Read(buffer, (unsigned)length, clear ? TRUE : FALSE);
    return count > 0 ? (size_t)count : 0;
}
extern "C" size_t mpynn_log_read(char *buffer, size_t length) {
    return mpynn_log_read_ex(buffer, length, 1);
}
extern "C" uint64_t mpynn_ticks_us64(void) {
    return CTimer::GetClockTicks64();
}
extern "C" void mpynn_platform_poll(void) {
    // Circle's net task calls CNetSubSystem::Process. Yield only from task
    // context with IRQs enabled, never re-enter from its own UART logging.
    static bool yielding;
    static unsigned poll_count;
    if (yielding || !kernel || !kernel->network_ready ||
        !CScheduler::IsActive() || CurrentExecutionLevel() != TASK_LEVEL) return;
    /* Don't pay a full scheduler switch on every MMIO poll; give cooperative
     * tasks a timeslice at a configurable power-of-two poll stride while a QPU
     * dispatch is in flight. */
    if ((++poll_count & (MPYNN_VC4_POLL_STRIDE - 1u)) != 0u) return;
    yielding = true;
#if MPYNN_VC4_WAIT_SLEEP_US > 0
    kernel->scheduler.usSleep(MPYNN_VC4_WAIT_SLEEP_US);
#else
    kernel->scheduler.Yield();
#endif
    yielding = false;
}
extern "C" void mpynn_platform_halt(void) {
    halt();
    for (;;) {}
}

int main(void) {
    // Intentionally never destruct platform devices on a MicroPython soft reset.
    Kernel platform;
    kernel = &platform;
    if (!platform.Initialize()) mpynn_platform_halt();
    const size_t circle_free = CMemorySystem::Get()->GetHeapFreeSpace(HEAP_LOW);
    const size_t reserve = MPYNN_CIRCLE_HEAP_RESERVE;
    g_circle_low_free = circle_free;
    g_circle_heap_reserve = reserve;
    if (circle_free <= reserve || circle_free - reserve < MPYNN_GC_HEAP_MIN) {
        platform.logger.Write("mpynn", LogError, "Insufficient measured Circle heap for MicroPython");
        mpynn_platform_halt();
    }
    const size_t gc_heap_size = circle_free - reserve;
    g_gc_heap_size = gc_heap_size;
    void *heap = malloc(gc_heap_size);
    if (!heap) {
        platform.logger.Write("mpynn", LogError, "Cannot allocate measured MicroPython GC heap");
        mpynn_platform_halt();
    }
    platform.logger.Write("mpynn", LogNotice,
                         "Pi1B RAM: Circle low free %u MiB, MicroPython GC %u MiB, reserve %u MiB",
                         (unsigned)(circle_free / (1024 * 1024)),
                         (unsigned)(gc_heap_size / (1024 * 1024)),
                         (unsigned)(reserve / (1024 * 1024)));
    // Background DHCP/PHY logs must never interleave with raw REPL framing.
    // Circle keeps its bounded internal log ring; read it via machine.logs().
    platform.logger.SetNewTarget(nullptr);
    mpynn_vm_run(heap, gc_heap_size);
}
