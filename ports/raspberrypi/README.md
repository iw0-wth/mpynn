# mpynn Raspberry Pi / Circle port

## Scope and current status

See [STATUS.md](STATUS.md) for actual build/test evidence and remaining work.

This is a staged bare-metal port, not a claim of complete Raspberry Pi support.
The first build target is **RPI1B**, BCM2835 / ARM1176JZF-S / AArch32 / VFP hard-float.
Circle is vendored at `../../lib/circle` (moved from the workspace's `circle-master`,
51.1.1 / CIRCLEVER 510101). Standard MicroPython is `../../lib/micropython` (1.29.0).
Neither upstream tree is replaced with the old bare-metal Raspberry Pi port.

Phase 1 implements the Circle kernel entry, UART0 REPL, GC heap, raw/friendly REPL,
soft reset, Ctrl-C polling, microsecond/millisecond timing, JSON, select and
f-strings. The development build now also includes the `machine` base described
below, plus onboard boot SD storage and FAT/VFS mounted as writable root storage.
The boot SD is not exposed as a removable `machine.SDCard` device.
Circle USB Ethernet and its cooperative IPv4/DHCP tasks are now integrated;
Python `network.LAN()` and the limited IPv4 UDP socket subset are integrated;
TCP/DNS/TLS and ML backend remain pending. The Python ML package's
image dependency is separated independently;
this is **not** proof that inference works. The workspace RPI1B-SD folder remains
the frozen phase-1 UART build and is not overwritten by development builds.

The user supplied a Pi 1B Rev2 phase-1 UART log showing the banner, friendly prompt
and Thonny entering raw REPL. That image then failed Thonny helper import because
it lacked os. The current development image includes os/VFS, but SD/USB/DHCP and
complete Thonny startup remain board-unverified. Host stub tests, cross-compilation,
ELF inspection and physical-board results are distinct verification levels.

## VC4 runtime boundary

The self-owned runtime now lives at `../../lib/vc4-runtime` with its own CMake
build, versioned C platform callback API, TFLM FC integration payload, local
shader sources and host platform tests. Its technical README records the full
PiTorch -> resident weights -> multi-tile -> packed16 progression and board
measurements. The runtime compilation has no Circle or MicroPython headers.
`vc4_runtime_bcm2835.cpp` in this port is now only the Circle backend:
firmware property envelope, checked CPU mapping, cache/barriers, MMIO, clocks,
timer, logger and cooperative wait services. Kernel startup binds it explicitly
before `vc4_init`. Other frameworks can bind their own platform table.

Firmware links sources from the new library. Old shader/packing/header paths in
the port are compatibility forwarding shims; the old `vc4_runtime.c` is a legacy
unavailable-host test stub and is no longer linked into the real Pi firmware.
No existing library checkout was modified for this extraction. The refactored
binary still needs board regression; earlier packed16 measurements do not by
themselves validate this new platform boundary.

## Test tools and demos

The project's development tests are now outside the source repository at
`../../../tests/raspberrypi/` (workspace/tests, sibling to mpynn). That directory
owns board smoke/acceptance scripts, VC4 benchmarks and model fixture generators.
The production port retains manifest/build/image validation tools only. Its
`config_checks.c` is part of `check-config`, so normal firmware builds do not
require the external test tree. User-facing examples stay in `../../demo/` and
must not import development tests. The independent VC4 library manages its own
tests separately inside its submodule.

## Build (Windows MSYS2)

The initial environment uses MSYS2 GNU Make, native Python and Arm GCC 15.2.Rel1.
Run from MSYS2 Bash; do not use the WSL launcher as an assumed POSIX installation:

```sh
export PATH=/e/arm-none-eabi/bin:/usr/bin:$PATH
cd /d/openmv_aicore/mpynn
make -C ports/raspberrypi/boards/RPI1B -j6 PYTHON=D:/anaconda3/python.exe
```

The compatibility entry `make TARGET=RPI1B PYTHON=D:/anaconda3/python.exe`
delegates through this same board entry. See the [RPI1B build guide](boards/RPI1B/README.md)
for configuration ownership, command inspection, output paths and adding boards.
The shared port directory also accepts `make BOARD=RPI1B PYTHON=D:/anaconda3/python.exe`.

On POSIX hosts use a matching arm-none-eabi toolchain and Python 3. The prefix is
configurable with `CROSS_COMPILE=...`. CMake is not needed for this Circle phase.
The top-level RPI1B route does not require OpenMV SDK and does not enter the old
port makefiles. Other target names are still the original reference routes.

Default `all` / explicit `kernel` outputs are under `../../build/RPI1B/bin`:
kernel.elf, kernel.map and kernel.img. Optional `sd-image` builds that kernel
first and packages an MBR + 128 MiB FAT16 volume using locally supplied
`SD_BOOT_DIR` firmware. `SD_INCLUDE_DEMO=1` copies the classified demo tree as
`/demo`; default images contain no demo or automatic main script. Remaining
space on a larger card is left unpartitioned. See the board build guide for
`SD_PARTITION_MIB`, `SD_EXTRA_DIR`, output/report variables and flashing scope.
MicroPython objects live under `../../build/RPI1B/micropython`. Circle core is
staged under `../../build/RPI1B/circle`, leaving upstream source unchanged. The
helper fingerprints sources, headers, toolchain identity and settings and rejects
unowned stages or unsafe cleanup paths. Only RPI1B is accepted. Additional boards
need their own configuration and build stage before they can be enabled.

## Boot and UART

Use a FAT boot partition with the matching Raspberry Pi firmware files described
in `../../lib/circle/boot/README`: bootcode.bin, start.elf, fixup.dat and their
license. Firmware downloads are NOT part of a normal build. Place kernel.img and
`../../boards/RPI1B/config.txt` on that partition. Do not overwrite an existing
SD card automatically. The generated kernel alone is not a complete SD image.

UART0 uses 115200 8N1, GPIO14 TX / GPIO15 RX (physical pins 8 / 10); use a 3.3V
TTL USB-to-UART adapter and common ground. No HDMI console or OpenMV IDE is used.
Ctrl-A: raw REPL, Ctrl-B: friendly REPL, Ctrl-C: interrupt Python, Ctrl-D at an
empty prompt: soft reset. Circle's IRQ driver buffers received bytes; the VM
services a separate bounded ring and handles Ctrl-C in Python context. Overflow
is counted and ordinary bytes may be discarded; the port does not promise
lossless unthrottled uploads. Raw-paste flow control and hardware stress tests
must be checked before long inference workloads.

Paste `../../../tests/raspberrypi/repl_smoke.py` through Ctrl-E paste mode, then run
again after at least 20 Ctrl-D resets. Test Ctrl-C during a Python busy loop.
Do not report this test as passed until the UART output is actually captured.

## Architecture invariants

- Circle alone owns boot, MMU, vector tables, IRQ stacks, heap and C++ constructors.
- GC receives one 16 MiB allocation from Circle, not a 16 MiB kernel `.bss` array.
- The VM stack limit is 64 KiB, below Circle's default 128 KiB kernel stack.
- C++ methods return through a plain C bridge before MicroPython raises exceptions.
  NLR must not bypass live C++ RAII objects.
- Private `mpynn_setjmp`/`mpynn_longjmp` preserve ARM core registers and d8-d15;
  they do not replace Circle's integer-only setjmp symbols. This also supports
  conservative GC register capture. Only AArch32 is implemented.
- Soft reset resets VM state, not Circle platform objects.
- No OpenMV protocol, CSI, sensor, framebuffer/image preview, display, TinyUSB,
  STAI or Cortex-M TFLM binary is linked into the Pi target.
- Standard MP stdio/REPL is intentionally retained; OpenMV IDE transport is not.

## Implemented machine base (board testing pending)

- `Pin(bcm)` uses BCM GPIO numbers, NOT physical header positions. Only Pi 1B P1
  26-pin Rev1/Rev2 pads are accepted. GPIO14/15 belong to the REPL and are rejected.
  Rev1 uses BCM0/1/21 where Rev2 uses BCM2/3/27. Unknown board models are rejected.
- `Pin(id)` only returns an immutable singleton reference. Configure with
  `Pin(id, Pin.IN/OUT, pull=None/PULL_UP/PULL_DOWN, value=...)` or `pin.init(...)`.
  `value()`, `pin()`, `on()`, `off()` and `deinit()` are implemented. Access before
  initialization raises an error. Repeated references share hardware state.
- Output latch is set before enabling output. Input-mode writes preload the latch.
  Deinit returns a claimed pad to input/no-pull; unclaimed pads are untouched.
  A central owner token prevents future buses and Pin from silently stealing pads.
- `reset()` invokes Circle reboot; `soft_reset()` uses standard MP SystemExit.
  VM soft reset restores IRQs and releases claimed Pin resources after finalizers.
- `disable_irq()` returns an IRQ-mask token (0 or 128); `enable_irq(token)` restores
  that bit only. Use try/finally for critical sections; do not perform I/O, allocate
  or wait there. This masks hardware IRQs, not the Python scheduler/GC.
- `unique_id()` returns the 64-bit firmware serial as eight big-endian bytes.
  `freq()` queries the ARM clock, with measured -> configured rate fallback;
  failures raise OSError(EIO). Setter is explicitly unsupported. Mailbox calls
  while IRQs are masked raise OSError(EBUSY).
- `idle()` cooperatively services pending work, not a low-power sleep promise.
  Port-specific `board_info()` returns model, raw revision and RAM MiB.
- No fake `reset_cause`, lightsleep/deepsleep, UART class, Pin.irq,
  Timer/PWM or SDCard is exposed at this stage. Port-owned I2C/SPI/WDT are enabled.

Run `../../../tests/raspberrypi/machine_smoke.py` on an actual board. It does not drive
GPIO outputs automatically. Electrical latch/edge behavior needs a scope test.
The UART TX bridge now retries temporary buffer-full writes with a 250 ms
no-progress bound; errors/timeouts increment a diagnostic counter rather than
silently treating backpressure as normal success.

## Port-owned machine.WDT (board testing pending)

`machine.WDT(id=0, timeout=seconds)` uses Circle's BCM watchdog. This port's
**timeout unit is whole seconds, 1 through 15 inclusive**, not the milliseconds
used by many other MicroPython ports. Invalid ID/timeout and IRQ/FIQ-masked
contexts fail before watchdog construction or MMIO. Only ID 0 exists and repeated
constructors return one stable singleton; no GC allocation owns the hardware.

For safety, `WDT()` / `WDT(0)` only obtain that reference and perform no MMIO.
They do not start or refresh a watchdog. Only an **explicit valid timeout** arms
it. `feed()` and the port extension `restart()` rearm the saved timeout using
Circle `Start(timeout)`. Circle `Restart()` is an immediate hardware reboot, not
a feed operation, and is deliberately never used by these methods. There is no
background feed or automatic watchdog startup. A deliberately armed watchdog
will reboot the board if the application fails to feed it.

```python
from machine import WDT
w = WDT()                  # unarmed reference; feed raises ENODEV until configured
assert WDT(0) is w
w = WDT(0, timeout=15)      # explicit opt-in: board can now reboot after 15 seconds
try:
    w.feed()               # refresh the full 15-second interval
    print(w.is_running(), w.time_left())  # diagnostic extensions, whole seconds
finally:
    w.deinit()             # explicitly Stop, then release native ownership
```

`deinit()` is idempotent. After deinit or soft reset, feed does not silently arm
an old timeout; explicitly construct with a timeout again. Soft reset stops the
watchdog immediately after restoring IRQs, before GC finalizers/network cleanup,
and stops again before `mp_deinit()` in case a finalizer explicitly rearms it.
Watchdog ownership is entirely separate from the GPIO registry;
no pad is claimed, configured or released. All operations reject IRQ or FIQ
masking with `OSError(EBUSY)`. No Timer/PWM/UART surface is added.

Strict native tests compile the real C binding and C++ bridge against VM/Circle
doubles with warnings-as-errors and cover validation, IRQ/FIQ guards, singleton
ownership, safe feed, diagnostics and deinit/reset lifecycle. They do not prove
physical watchdog expiry, reboot or elapsed-time accuracy on a board. Do not run
an unattended expiry test or risk SD writes without explicit user consent.

## Boot SD and FAT/VFS (board testing pending)

Circle's CEMMCDevice wraps SDHOST on this Pi 1 configuration. Do not instantiate
CSDHOSTDevice as the block disk directly. Circle core, partition helper and SDCard
archives are built in the signed stage (`--with-sd`); Circle FAT is not mounted.
Standard MicroPython oofatfs is the sole active filesystem implementation.

- The onboard card is internal boot storage, like MCU internal flash. It is not
  exposed as `machine.SDCard`. The C block bridge remains private to FAT/VFS and
  uses 512-byte blocks, aligned bounce sectors, range checks and IRQ guards.
- Transfers use a 32-byte-aligned bounce sector, so arbitrary bytearray/memoryview
  alignment cannot violate Circle DMA constraints. Operations are synchronous.
- Startup attempts `/` writable with `mkfs=False`. Missing/unusable SD or invalid
  FAT does not cause formatting; initialization/mount errors lead to the REPL.
  The underlying device is initialized once, not recreated on every VM reset.
  `boot.py` and `main.py` are loaded from `/`; Thonny file operations target this
  root VFS. A disposable/backup card is required before testing writes.
- Successful mount adds `/` and `/lib` to sys.path. Friendly-mode startup executes
  `/boot.py` and then `/main.py` if boot succeeds; raw-mode soft reboot mounts but
  skips user scripts. Ctrl-C can interrupt Python startup code.
- On soft reset native FAT file finalizers close files before heap reclamation;
  only non-GC Circle sync is called afterwards. The next VM creates fresh mounts.
- No RTC is installed: writable FAT timestamps use the configured fixed fallback
  (2018-01-01), not a fabricated wall-clock time. No hot-swap support is claimed.

Use `../../../tests/raspberrypi/sd_smoke.py` for non-destructive board validation.
For an intentional writable test, use only a backed-up disposable SD card.
The startup mount is already writable; use the root VFS directly:

```python
import os
with open('/mpynn-test.txt', 'w') as f:
    f.write('mpynn SD test\\n')
os.sync()
os.remove('/mpynn-test.txt')
os.sync()
```

Never mount a second FAT instance over the boot card or perform raw writes while
its root filesystem is mounted. The bridge serializes individual transfers, not
independent filesystem caches. Writes can damage the boot partition; no test/build
command writes a physical card automatically.

## USB Ethernet / IPv4 bring-up (board testing pending)

- Pi 1B DWHCI enumerates the onboard LAN9512 via Circle's SMSC951x driver.
  The upstream USB factory also requires input and partition helper archives;
  these are built in the isolated stage, not a second mounted filesystem.
- Circle net and scheduler archives are included. A kernel-owned scheduler drives
  PHY, network processing and DHCP from cooperative task context. Nonblocking
  initialization does not wait for a cable or DHCP lease before entering REPL.
- VM I/O polling yields only with IRQs enabled, outside ISR context and without
  recursive entry. Circle owns all network task stacks/allocations. Those tasks
  must never invoke Python or retain pointers into the MicroPython GC heap.
- After startup Circle logging is detached from UART to preserve raw REPL byte
  framing. `machine.logs()` now defaults to a non-consuming snapshot of the full
  retained ring (`clear=False, limit=16384`), so repeated inspection retains the
  same evidence. Explicit `machine.logs(clear=True)` consumes returned bytes;
  a smaller `limit` consumes only that portion. The 16 KiB ring retains at most
  16383 bytes and overwrites oldest content when full. Reading does not trigger
  new VC4 samples; `machine.vc4_reset_diagnostics()` rearms the first-eight limit.
- `network.LAN()` exposes `active()`, `isconnected()`, `ifconfig()` and `status()`.
  `ifconfig()` returns IPv4/mask/gateway/DNS. `ifconfig((ip, mask, gateway, dns))`
  applies a static tuple; `ifconfig('dhcp')` resets it and asynchronously requests
  a new DHCP lease. Close existing sockets before changing addresses. Changes
  persist across VM soft reset, but cold boot defaults to DHCP. Invalid tuples
  do not change state; old DHCP exchanges cannot overwrite a new static tuple.
  Address changes flush ARP and route caches; no IP conflict probe is implemented. `machine.network_info()` remains
  a port-specific diagnostic dictionary with present, initialized, link,
  isconnected, dhcp, mac, speed_code and ifconfig. `ifconfig` contains four
  dotted IPv4 strings (IP, mask, gateway, DNS). `isconnected` requires Ethernet
  presence, current link and Circle running state (a DHCP lease or static configuration),
  not merely successful library initialization. `speed_code` is Circle's enum,
  NOT Mbps: 0/1=10 half/full, 2/3=100 half/full, 4/5=1000 half/full, 6 unknown.
  When absent, mac/speed_code are None.
- Network tasks persist across VM soft reset. Construct `network.LAN()` to register
  the singleton NIC, then use `socket(AF_INET, SOCK_DGRAM)` for numeric IPv4 UDP.
  Supported operations: wildcard/current-LAN-IP bind, sendto/recvfrom, connected send/recv,
  settimeout/setblocking, select.poll, close and SO_BROADCAST. UDP connect updates
  default peer in place and preserves the local port; reconnect clears old queued
  datagrams. Receive filtering follows Circle's peer/broadcast/multicast policy.
  Explicit sendto uses its supplied destination without changing the default peer.
  Eight live UDP handles maximum; duplicate
  explicit ports and DHCP port 68 are rejected. Zero-payload UDP send/receive are
  implemented through a port-owned Circle adaptation. Empty received datagrams
  retain peer metadata and differ from EAGAIN. Declared UDP length is validated,
  checksummed and trailing padding removed. Wire-level round-trip tests are pending.
  VM reset closes all adapter-owned UDP handles without restarting DHCP.
- TCP clients now support numeric-IP connect, send/recv/sendall, timeouts, poll and close;
  sendall uses one total timeout across chunks and does not overwrite socket timeout.
  Finite positive settimeout values round UP to the next millisecond; sub-millisecond
  requests remain finite waits, not nonblocking. Zero is nonblocking, None blocking.
  Negative/NaN/infinite/out-of-range inputs fail before changing the timeout.
  recv_into and recvfrom_into accept writable buffers and perform one receive;
  nbytes=0 uses the full capacity, and nonzero flags are explicitly unsupported.
  Nonblocking connect uses EINPROGRESS and completion through poll.
  getpeername reports the copied remote endpoint. getsockname reports native local
  port and current NIC IP for connected sockets, saved bind IP for binds/listeners,
  wildcard:0 for fresh sockets, and ENOTCONN while native TCP connect is pending. TCP servers
  support wildcard bind/listen/accept, two listeners and backlog clamped to 1..4.
  listen on an unbound TCP socket selects the default NIC and implicitly assigns
  an ephemeral port; getsockname reports it. Invalid backlog/family/type and closed
  sockets fail before NIC selection. Native open/query failures preserve IDLE
  so an explicit bind or listener retry is still possible.
  bind(port=0) records an ephemeral request; listen assigns a free port shared by
  all backlog candidates and getsockname then returns it. Before listen the recorded
  port is still zero. Accepted sockets default to blocking and own independent streams.
  accept validates closed/family/type/listening before child allocation. If Python
  tuple/address construction fails after native accept, that child stream is closed
  immediately and the original exception is preserved; the parent stays listening.
  Bound-client connect passes the recorded local port to the native worker,
  including zero for automatic assignment. Explicit TCP local-port conflicts are
  rejected against live/native Circle entries and pending VM jobs. Bind-time
  reservation is retained through close/deinit for explicit nonzero TCP binds;
  port zero remains ephemeral. `SO_BROADCAST` is supported for
  UDP; REUSEADDR/KEEPALIVE remain exported but operations return EOPNOTSUPP.
  SO_SNDTIMEO/SO_RCVTIMEO support independent TCP/UDP direction limits: integer
  milliseconds or fixed native-endian int32 buffers (4-byte ms / 8-byte sec,usec).
  Zero means infinite, timeval fractions round upward to ms, range0..INT32_MAX ms.
  getsockopt returns integer ms (or raw integer-prefix bytes); gettimeout still shows
  the common socket mode. Nonblocking takes precedence. settimeout/setblocking reset
  direction overrides, accepted children start blocking without inherited limits.
  Send/recv/accept/sendall snapshot their direction's total deadline per operation;
  connect keeps the common settimeout deadline. No native blocking API is used. `setsockopt` validates option/type/protocol and value buffers before
  lazy NIC selection; supported values are copied from possibly unaligned buffers.
  `getsockopt` supports SO_TYPE, UDP SO_BROADCAST and TCP/UDP SO_ERROR.
  UDP SO_ERROR consumes only the pending native errno, preserves queued datagrams,
  and can report new later ICMP errors. Fresh queries do not create native handles.
  TCP_NODELAY at IPPROTO_TCP supports set/query before connect, while connected,
  and inheritance by accepted children. Historical Circle default is 1 (Nagle
  disabled); explicit 0 defers sub-MSS segments while data remains unacknowledged.
  Both values preserve peer/congestion windows and backpressure. Setters do not
  immediately send; the network Process task applies the policy to queued data.
  SO_ERROR checks pending completion once without waiting, reports terminal errno
  once, and preserves sticky connection failure. Zero while still pending is not
  proof of success: use poll and getpeername. Failed result allocation preserves
  the pending errno. IPv4 DNS and standard ssl/mbedTLS
  are linked. `getaddrinfo` supports IPv4 A lookup plus static service names
  http/https/ntp/domain/ssh/telnet/ftp and decimal port strings; unknown or
  conflicting services return EOPNOTSUPP. AF_INET6 is retained as a compatibility
  constant, but IPv6 operations return EAFNOSUPPORT. Resolver supports AI_PASSIVE,
  AI_NUMERICHOST and AI_NUMERICSERV (other flags rejected): host=None selects wildcard
  with PASSIVE or 127.0.0.1 without it, port=None selects0; bothNone rejected.
  This loopback value is address resolution only, not Circle loopback routing.
  Numeric-only flags forbid DNS and named-service lookup. All resolver calls match
  whole dotted-decimal literals strictly; malformed digits/dots return EINVAL with
  no DNS. Names with alphabetic suffixes go to DNS intact, never a numeric prefix.
  bind/connect/sendto endpoint tuples also require exact dotted decimal IPv4 and
  ports0..65535 (empty host retains wildcard semantics). Invalid endpoints fail
  before NIC selection. Direct hostname endpoints are not resolved here; use
  getaddrinfo first. Closed endpoint operations return EBADF before parsing;
  on-board DNS/TLS traffic and handshakes remain unverified.
  Native connection jobs and stream handles are bounded to four each; abandoned
  native connects retain job slots until Circle finishes. Board tests are pending.
  socket.shutdown(how) supports SHUT_RD=0, SHUT_WR=1 and SHUT_RDWR=2 on connected/
  accepted TCP through the port-owned Circle Shutdown extension. SHUT_WR rejects
  new writes with EPIPE and queues a real FIN after accepted writes, while receive
  remains usable in FIN_WAIT1/2. SHUT_RD drops cached/queued RX and makes reads EOF;
  incoming payload is discarded while TCP ACK/sequence processing continues.
  Repeated calls are idempotent; shutdown does not release native ownership or local
  port reservations. Call close() to release resources. Native errors are preserved;
  a local post-SHUT_WR EPIPE does not hide later terminal errors from SO_ERROR.
  UDP/unsupported protocol requests return EOPNOTSUPP, invalid integer
  modes EINVAL, unsupported families EAFNOSUPPORT, and closed sockets EBADF.
  Fresh, bound, listening, pending and failed TCP sockets return ENOTCONN; shutdown
  does not select a NIC or promote/cancel pending connects. Noninteger modes use
  the standard MicroPython integer conversion errors. Closed sockets take precedence.
  Generic socket constants may exist even when their operation returns EOPNOTSUPP.
  Do not infer protocol support merely from importing socket or linking libnet.a.
- Circle's synchronous SD operations and long C inference can delay cooperative
  networking; concurrent USB/SD/REPL/inference stress tests are still required.

User-facing standalone demos and the acceptance checklist are in `../../demo/`;
development unit/host test files remain under `../../../tests/raspberrypi/` and are
not the user demo package. User has confirmed SD reads/writes now work on Pi1B
Rev2; network and complete power-persistence/Thonny evidence are tracked separately. RTC is a software wall clock starting at
2000-01-01 on cold boot; datetime/init and time calendar APIs share it. Default
requests HTTPS preserves upstream CERT_NONE and needs no calibration; explicit
CERT_REQUIRED verification uses calibrated RTC UTC and a caller-loaded CA.
Unmodified upstream ntptime is frozen for explicit user-managed calibration;
call network.LAN() before ntptime.settime(). No NTP request runs automatically.
Paired user UDP/TCP tools are in `../../demo/network/`, with instructions in
`../../demo/README.md`.

## Next stages (ordered)

1. Physical-board SD root read/write, error-path and soft-reset validation.
2. USB Host -> **Pi 1B onboard LAN9512 RJ45** -> Circle Ethernet, static IPv4,
   ARP/ICMP, DHCP. External USB NIC/keyboard/storage is not a prerequisite.
3. network.LAN, TCP/UDP sockets, DNS, nonblocking/timeout/EOF mapping, select.poll,
   small-buffer receive caching and socket cleanup on VM reset. Use one network
   stack (Circle), not Circle TCP/IP and lwIP simultaneously.
4. I2C/SPI (first synchronous), SoftI2C/SoftSPI, Pin IRQ, Timer, PWM, WDT. Track
   pinmux/shared clocks and validate Pi 1B Rev1/Rev2 26-pin header differences.
5. Optional RTC/calendar clock, DMA, more boards. No unsupported ADC/DAC or
   low-power behavior is exposed as a fake successful implementation.
6. AI core/ulab + optional offline image preprocessor. No TFLM/QPU implementation
   here; retain explicit backend/allocator/cache-service boundaries for it.

Network processing must progress in REPL waits, VM hooks and blocking calls;
long native inference will require cooperative service points as well. Python
callbacks/GC/filesystem calls must never execute directly inside hardware IRQs.

## Dependencies and remaining constraints

- `modules/ulab` is declared in old metadata but its sources are absent: no
  ndarray.h was found. Need the user's supplied compatible source before enabling
  the real AI C module. Do not fetch an arbitrary version or fake the ndarray ABI.
- Existing `lib/tflm` CPU-specific Cortex-M archives are not Pi 1 ARMv6 backends.
- Old ports/boards remain reference sources; they are not promised buildable with
  standard MP 1.29, and they are outside the Pi default dependency graph.
- Preserve upstream licensing notices. In particular the OpenMV ML source contains
  a non-commercial condition, and Circle includes GPL notices. Do not relabel the
  combined distribution MIT merely because new glue files carry MIT headers.
