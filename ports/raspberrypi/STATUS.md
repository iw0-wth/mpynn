# Raspberry Pi port implementation status

## TFLM/ML follow-up

Removed the port-specific `modules/requests` tree; manifest now freezes standard
micropython-lib requests. Added `scripts/libraries/ml` to the Raspberry Pi manifest.
Built `D:/openmv_aicore/tflite-micro` independently with its Makefile custom
`rpi1b` target using ARM1176JZF-S ARM state hard-float VFP flags, reference kernels
only and no CMSIS-NN/CMSIS-DSP/Ethos-U. The resulting 190-member archive is copied
as `lib/tflm/libtflm/lib/libtflm-rpi1b-armv6-reference.a` and linked by the Pi1B
Makefile. The native `uml_binding.c` + `uml_backend.cpp` pair now enables
`MICROPY_PY_ML_TFLM`, with predict/callback/callable-input contracts and GC-owned
buffers. ulab 6.12.0 is compiled from `modules/ulab/code` with four-dimensional
arrays. File-based image (PNG/BMP/PNM, JPEG unsupported) and WAV/PCM audio native
modules are linked without camera/IDE/MCU HAL code. Full ARM build currently passes
with a 1,386,328-byte image, and ELF symbols prove all four native modules and real
TFLM Invoke/AllocateTensors are included. These are static build results, not Pi
hardware inference evidence. See `ML_STATUS.md` for runtime verification gaps and
`OPENMV_CUTS.md` for the retained-vs-removed OpenMV scope.


## Requests architecture cleanup

Removed the port-specific Python requests fork and changed `manifest.py` to require
standard read-only micropython-lib requests. Python requests no longer exposes the
mpynn-only `ssl_context=` keyword. TLS remains MicroPython's standard mbedTLS
`tls.SSLContext` API; Raspberry Pi differences stay in C/port glue. Standard requests
freezing and ARM build pass; physical HTTPS/certificate-chain behavior remains board
work.


## Follow-up goal — Soft buses, Timer and Pin IRQ

MicroPython SoftI2C/SoftSPI are re-enabled through port-owned GPIO HAL and validated
external wrappers (bounded parameters, distinct pins, open-drain release, safe
bit-banging). machine.Timer is enabled with 8 bounded virtual slots, Circle 100Hz
period rounding, periodic/one-shot modes, scheduler-only Python callbacks, GC roots,
generation invalidation and queue-full retention. Pin.irq supports rising/falling
triggers with hard callbacks rejected, ARM Circle GPIO manager wiring, static IRQ
latches, generation/coalescing and VM-context callbacks; non-ARM host stubs preserve
native tests. Final host machine19, socket132, TCP33 pass. Final ARM static image
713536 bytes, raw SHA256 `419ac412206162414b7d5f2440d5b01a26b2eb97bbebd2c784d387b9eccca4ff`,
build_id `ce2cf6e5333117bd090f4939af9ef93624f295baf63fb7920e14c5f921a3debe` matches
embedded identity. lib unchanged, hardware_tested=false. Warnings are existing
MicroPython country-code/sign-compare plus harmless HAL macro redefinition. Timer,
Soft buses and Pin IRQ remain unverified on physical Pi hardware.


## Round 218 — WDT safe integration and final static build

Added machine.WDT with explicit seconds timeout1..15; unarmed WDT() performs no MMIO,
feed/restart uses Circle Start(saved timeout), never immediate-reboot Restart().
Singleton ownership, IRQ/FIQ/task validation, snapshot, deinit and soft-reset stop are
covered by strict native binding2 plus complete machine suite18. A second IRQ restore
after GC sweep prevents a finalizer from leaving a watchdog armed under masked IRQs.
Full socket132/TCP33, machine18 and readonly1 pass. Final ARM static build is image
698472 bytes, raw SHA256 `841e1b1dd25c4f77b6092c1545b5f5b4f1ba3979224b2a1762d63949b28f56bd`,
embedded build_id `940456aa6df2a68488e1d6506bbbf313f58b38f35ba8dbbf811bff3c007272cc`.
lib unchanged; hardware_tested=false. I2C/SPI/WDT code-level complete; Timer/PWM/UART/
Pin IRQ remain deliberately disabled. Pi electrical/watchdog tests remain user-side.


## Round 213 — bounded I2C/SPI and machine integration

I2C and SPI are now enabled as safe hardware machine classes; SoftI2C/SoftSPI remain
disabled. I2C uses fixed Pi1 device1 BCM2/3 ownership, 100ms bounded Circle
Read/Write/repeated-start, task-context checks, deferred/finalizer-safe cleanup and
NACK/timeout mapping. SPI0 claims BCM7/8/9/10/11 atomically before construction,
uses manual external CS, bounded full-duplex transfers, 8-bit MSB format, overlap/
length/context validation, rollback and VM-reset cleanup. Host machine surface16,
SPI native/bridge8, I2C binding1+bridge1 and socket132/TCP33 all pass; readonly1
passes. ARM full build passes with image696888 bytes, SHA256
`2112ded5f7ba4a869dafdcfaf82decaee96905131f3029e31d664b6d7bd61190`, build_id
`bd46327ae863dd9fab2890c83d127dc6c13b1f9a229b6ac5abaafb41758a9135`; static only,
no hardware claim. lib unchanged. Timer/PWM/WDT/UART/IRQ remain deliberately disabled.


## Round 212 — I2C/SPI overlays staged, APIs not enabled

Port-owned I2C and SPI Circle overrides now contain bounded transfer deadlines,
pre-MMIO argument checks and cleanup paths; build_circle allowlist includes their
headers/sources. I2C host test exists but MinGW exits silently on bare-metal doubles
and is skipped; SPI host compiler has the same environment limitation. ARM staging
compiles the override objects successfully. No machine I2C/SPI Python class is
enabled yet because GPIO ownership/wrapper integration remains to review. Timer
wrapper has not landed. Socket tests remain green.


## Round 212 — peripheral overlays pending validation

I2C port-owned overlay and timeout host harness are present, but this environment's
MinGW C++ compiler terminates silently on the bare-metal Circle doubles, so the test
is skipped rather than claimed. ARM build remains the authoritative compile check.
SPI overlay is still being implemented/tested; Timer wrapper has not landed. No
machine flags enabled yet.


## Round 208 — directional timeout integration verified

Direction timeout wrapper13, adapter73 and readonly1 pass. Grep audit confirms every
retry path carries a captured direction deadline: UDP send/recv, TCP send/recv,
sendall, accept; connect keeps common timeout. Invalid timeout values are rejected
before NIC, settimeout resets overrides, accepted children are blocking/default.
ARM build from this source is685880 bytes (previous checkpoint before later half-close
parser changes); current tree still needs a final full build after all changes.
Next work is remaining IPv4 socket options/details, then bounded I2C/SPI.


## Round 207 — independent directional socket timeouts

Added SO_SNDTIMEO/SO_RCVTIMEO for supported UDP/TCP sockets. Values accept integer
milliseconds or fixed 4-byte milliseconds/8-byte sec,usec buffers, with aligned
copy, range checks and upward sub-ms rounding before lazy NIC. Direction overrides
are independent; zero means infinite, nonblocking common timeout wins, settimeout/
setblocking resets both, accepted children default blocking/no overrides. Send/recv/
sendto/recvfrom/accept/sendall snapshot direction deadlines; connect retains common
mode. No native blocking API or NIC side effects on invalid values. Wrapper13 and
adapter73 (101 new directional scenarios), socket integration132, gettimeout1,
readonly1 pass. ARM/static image685880 bytes SHA256
`6b5df01c8a86abf0087f222861ad5a0ca775e23a167b6fa181c68e10faf36756`, build_id
`a3a3de639e940d69a56ba80e51f066f97611f07e5b3591fbd00ad38aa96d40bf`; embedded.
Half-close and TCP options/header bounds remain port-owned tested; machine buses still
queued. No Pi wire test.


## Round 205 — bounded TCP header/options parsing

Fixed PacketReceived data-offset validation before unsigned subtraction/RemoveHeader.
Replaced ScanOptions with bounded boolean parser: EOL/NOP consume one byte; other
TLVs require2..remaining bytes; MSS exactly4. Zero-length unknown options cannot loop;
truncated header/options fail consumed with-1. Negotiated MSS/IW/CWND update only
after full validation. Actual parser5 tests include196608 exhaustive combinations,
Windows exact-bound guard pages, duplicate/SYN/clamp policy and failure atomicity;
actual PacketReceived harness executes invalidoffset/options rejection. TCP33 and
socket120 integration plus readonly1 pass. ARM/static image684936 bytes, SHA256
`6522ded9bc062a8074d66e44737fe42420d71dacd0c193bdf6359a37aa7fcd37`, build_id
`dbf1cd05be7e81f673cceb7a9b359cc88a09dbd68340d0c85963351be745f9e1`, source/embedded
identity match. lib unchanged, no board test claimed. Next: remaining IPv4 options.


## Round 204 — real TCP half-close code milestone

Native Shutdown, transport dispatcher, stream bridge and Python adapter now provide
RD/WR/RDWR without releasing ownership. WR blocks writes and queues real FIN after
accepted TX; FinWait1/2 RX remains usable. RD clears RX/reassembly/cache and drops
future payload while sequence/ACK/FIN handling proceeds. Remote FIN before a queued
local FIN targets LAST_ACK. Repeats and close-after-shutdown are safe. Native send
rechecks shutdown after waiting; RD wakes readers. Local EPIPE does not mask a later
native terminal SO_ERROR. Actual complete PacketReceived runtime harness now passes
(data+FIN, read-shutdown, FinWait1/2, OOO drop, FIN race, ownership guards), plus native
method/transport tests and bridge2/adapter66. Integration TCP27/socket120 and readonly1
pass; demo4 pass, mpy-cross compiled tcp.half_close. Final ARM build684856 bytes,
image SHA256 `d370a0c1ef168a714a7561e770d8993315a326fdc588e65c2a71dd3b158ac068`, build_id
`bc947840c6b495a927f0b4184ad83365180338fa4aebedbcaf3b1c043e8ed233` matches source and
embedded ID. lib unchanged. No Pi wire test claimed. User deferred board acceptance;
remaining IPv4 code items proceed before machine, not repeated evidence-only gates.


## Round 203 — half-close layered tests green, packet harness remains

Current layered tests pass: native method1, stream bridge2 and Python adapter66.
The native harness still checks PacketReceived only by source assertions, not by
executing real data+FIN/out-of-order packets; therefore half-close is not yet marked
complete and I2C/SPI work remains gated. No new production change this round.


## Round 201 — half-close native overlay built

TCP half-close production overlay, transport hook, bridge and Python adapter are now
present. Focused bridge2, adapter66 and native method1 tests pass; ARM build also
passes (684720-byte intermediate image). Native packet-level harness for actual
PacketReceived data+FIN/out-of-order read-shutdown behavior is still missing, so
half-close is not yet marked complete. Machine work remains queued behind it.


## Round 201 — source inventory unchanged

Current source inventory still contains only machine_pin.c, machine_sdcard.c and
machine_bridge.cpp; no new bus/timer/PWM/WDT source appeared. Constructor and machine
surface contract tests remain present. Socket/machine gates and goal remain active;
no code/image change this round.


## Round 200 — constructor guard image checkpoint

All background jobs are collected. Constructor6 and socket-pattern118 passed after
Windows cleanup retry; current ARM image is683832 bytes/image SHA256
`25c380120ff7d325d2f637f7507a400a381969ad5d595878e2e73899cff9b74a`, build_id
`7c35dafaa8b9d58d58d6846e98aa340984e0a1c91a24586dd751eff1819c5c18`, embedded.
Socket hardware matrix and machine bus implementation remain open; goal active.


## Round 199 — constructor image consistency

Constructor6, IPv6 boundary6 and machine surface4 focused tests pass. Current ARM
image is683832 bytes/image SHA256 `25c380120ff7d325d2f637f7507a400a381969ad5d595878e2e73899cff9b74a`,
build_id `7c35dafaa8b9d58d58d6846e98aa340984e0a1c91a24586dd751eff1819c5c18`, and
embedded identity matches. Acceptance/demo IDs updated. Hardware socket matrix and
machine bus implementation remain open.


## Round 198 — constructor guard verified

Constructor harness6 passes strict GCC and exercises all32768 representable
5-bit domain/type/proto triples, invalid negatives/>31 before allocation, defaults,
partial args, lazy AF_INET6 and argument-count errors. A first collection had only
Windows temp-exe teardown locking; bounded cleanup retry was added to the test and
constructor6 plus socket-pattern118 rerun green. Production constructor guards are
ARM-built; machine gates remain unchanged.


## Round 198 — constructor harness double correction pending

The constructor harness compiled cleanly and all invalid/count/source-contract cases
passed. Two valid cases exposed only a host-double assumption: production intentionally
converts valid arguments once for validation and again during retained initialization;
the double expected one conversion. The test is being corrected without production
changes. ARM constructor-guard build already passes; machine gates unchanged.


## Round 197 — constructor harness pending

Production socket constructor width guards are compiled into the ARM image and reject
negative/>31 domain/type/proto values before allocation; AF_INET6 value10 remains a
compatibility construction. The focused host behavior harness has not yet delivered
its final run, so it is not counted as passing. Machine gates and hardware socket
limits remain unchanged.


## Round 196 — constructor width guard in production

Added pre-allocation validation for socket domain/type/proto values: each must fit the
5-bit object fields (0..31), otherwise ValueError is raised before GC allocation.
AF_INET6 value10 remains constructible for compatibility and is rejected later by the
IPv4-only adapter. `(void)type` keeps strict host/ARM builds warning-clean. ARM build
passes with this change; focused constructor behavior harness is still pending.


## Round 195 — constructor field-width follow-up

The AF_INET6 boundary harness covers lazy construction through adapter rejection but
not arbitrary out-of-range constructor bitfield values. The socket object stores
 domain/type/proto in 5-bit fields, so changing constructor conversion semantics
needs an explicit compatibility/error contract. No production change was made;
this follow-up remains open alongside the existing socket limits.


## Round 194 — constructor bitfield audit

Reviewed socket_make_new against MicroPython's 5-bit domain/type/proto fields. The
current constructor accepts arbitrary integer inputs and stores bitfield values;
adapter validation later rejects unsupported families/types, but out-of-range values
can be truncated before that validation. No production change was made without a
compatibility/error-contract test; this remains a follow-up socket issue. Machine
peripheral gates remain unchanged.


## Round 193 — active goal summary

Goal remains active. BOARD_ACCEPTANCE still marks the current image as compiled/static
only, and no machine I2C/SPI/PWM/Timer/WDT enable macro has appeared. Machine surface
contract is present, but missing hardware socket matrix and safe bus/timer wrappers
still prevent completion. No new code, image or evidence this round.


## Round 192 — hardware evidence still absent

BOARD_ACCEPTANCE explicitly marks the current 683648-byte image as compiled/static
only and records no Pi transcript for the socket matrix. No hidden hardware result or
new machine implementation exists in the tree. This external evidence gap and the
Circle API limits remain; goal stays active.


## Round 191 — board procedure syntax review

Reviewed the expanded BOARD_RUN snippets: imports are explicit, poll/SO_ERROR/
endpoint queries and resolver/options demos match the current exposed API, and cleanup
is guarded by finally. This is a procedure review only; no Pi execution transcript
exists, so the network matrix remains pending and no machine transition occurs.


## Round 190 — board evidence procedure expanded

Expanded demo/BOARD_RUN.md with real-board checks for SO_ERROR, TCP_NODELAY, resolver
flags, strict endpoint rejection, nonblocking poll/peer/local queries, timeout and
soft-reset resource reuse. This prepares the missing hardware matrix but does not
claim it was run; no Pi transcript is available. Socket and machine gates remain
active.


## Round 189 — concrete blockers remain, goal not blocked yet

The remaining blockers are concrete: no Pi hardware network matrix has been supplied
for DHCP/UDP/TCP/DNS/TLS/timeout stress, Circle has no safe TCP half-close API, and
Pi1 Circle I2C/SPI transfer loops lack bounded polling. These conditions prevent
claiming socket completion or exposing new machine buses, but the goal policy's
repeated-blocker threshold has not been reached; goal remains active.


## Round 188 — no untracked peripheral transition

Current tree contains only machine_pin.c, machine_sdcard.c and the existing
machine_bridge.cpp; no new I2C/SPI/PWM/WDT/Timer source or enable macro appeared.
Machine tests remain the Pin bridge10/surface4 contracts. Socket has no new code
change and its documented limits remain open. Goal remains active.


## Round 187 — final active-state checkpoint

All background work is collected. Evidence remains: full port412 (one optional skip),
AI15, Pin bridge10, machine surface4 and IPv6 boundary6. The current socket gaps
and unimplemented machine buses remain unchanged, so the goal is correctly left
active rather than marked complete.


## Round 186 — final lightweight gate check

Both machine surface and IPv6 exclusion contract tests are present in the current
workspace. Status records continue to identify socket half-close/option/board-matrix
limits and unimplemented machine buses. Goal remains active; no code, image or board
change this round.


## Round 184 — IPv6 boundary test completed

Focused IPv6 exclusion harness6 passes with strict GCC: actual AF_INET6 globals table,
resolver pre-DNS/NIC rejection, native udp_socket no-allocation rejection and
bind/connect/listen family paths; IPv4 controls verify the doubles are live. No
IPPROTO_IPV6 or production networking code was added. Machine surface gate4 also
passes; socket/machine objective remains active.


## Round 182 — IPv6 exclusion contract

IPv6 remains intentionally excluded rather than partially implemented. The port
retains AF_INET6 compatibility, while native socket creation rejects AF_INET6 with
EAFNOSUPPORT before private-state allocation or Circle/native calls; getaddrinfo
rejects IPv6 family before DNS. The vendored non-lwIP modnetwork.h has no
MOD_NETWORK_IPPROTO_IPV6 definition, so the commented upstream-like entry is not an
active export and no invented protocol constant is added. A focused boundary harness
is being added to keep this contract stable. Machine peripherals remain gated behind
unfinished socket and hardware-network evidence.

## Round 181 — machine surface contract rechecked

Re-read the discoverable surface test and actual port config. It verifies production
registration guards with positive controls, not a hand-written fake table; production
flags still leave I2C/SPI/PWM/WDT/Timer disabled. Socket compatibility and hardware
matrix gates remain open. No code/image change this round.

## Round 180 — status consistency check

Current goal remains active. The machine surface test is discoverable, and the user
checklist/status consistently state that it is only a non-exposure guard; new I2C,
SPI, Timer, PWM, WDT and Pin IRQ remain unimplemented. Socket's documented limits
remain unchanged. No code, image or hardware evidence changed this round.

## Round 179 — machine gate test is in tree

The machine surface gate is now a discoverable test file in the current tree:
`test_machine_surface_host.py` passes4, while Pin bridge passes10 and the latest
full port collection passes412 with one optional skip. The gate checks actual config,
upstream registration guards and Makefile wiring; it does not implement I2C/SPI or
other peripherals. Socket remains active and no machine production code was added.

## Round 178 — no phase transition

Rechecked current checklist, status and machine config: no I2C/SPI/PWM/WDT/Timer
flags are enabled; surface contract remains a non-exposure guard. Socket half-close,
remaining options and board network evidence remain open. No production, image or
machine change this round; goal stays active.
