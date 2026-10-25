# Local Circle integration patches

Upstream licences are preserved. lib/circle is read-only upstream source.
Local adapted copies live in upstream_overrides/circle under this port, with
Circle-relative paths. build_circle.py applies only allowlisted copies to its
owned build stage and hashes them into the build signature. Glue compilation
uses override headers before upstream headers. No build writes into lib/circle;
these adaptations are not represented as accepted upstream fixes.

## TCP Connect waiter lifetime

Affected source:
- `lib/circle/include/circle/net/tcpconnection.h`
- `lib/circle/lib/net/tcpconnection.cpp`

A SYN_SENT connection receiving RST enters Closed and signals its event.
Signalling only marks the connecting task ready. Before that task resumes,
CTransportLayer::Process may delete Closed connections in its cleanup loop.
Connect would subsequently read m_nErrno through a deleted object.

Add an initialized Connect-waiter counter, increment around Event.Wait and
exclude waiting connections from IsTerminated. The decrement and final error
read occur without a cooperative yield. Once Connect returns, the next transport
pass can reclaim a Closed connection. This relies on the current single-core,
cooperative network-task usage, not a general multithreaded reference count.

`test_tcp_waiter_lifetime.py` compiles the real extracted Connect and IsTerminated
method bodies with a deterministic event hook. It checks Closed-but-waiting is
not reclaimable and becomes reclaimable after error return, and successful/
early-error paths leave no pin. This is narrower than an actual packet/scheduler
integration test. Full ARM compilation covers the actual class and source file.

## Retained handles and nonblocking stream status

Opt-in TCP owner references retain a terminated object and its native handle slot
until bridge ownership is released. Process skips terminated owned connections;
legacy callers and UDP keep their existing unowned behavior. Bridge take/claim
transfers one reference rather than reacquiring it. Explicit close releases it.
This requires the single-core cooperative scheduling contract; stale raw integers
outside the ownership contract are not safe capabilities.

GetTerminalError preserves RST/timeout errors; IsReceiveEOF requires received FIN,
empty native RX queue and no error. Bridge RX cache must also drain before EOF.
Neither modifies legacy Receive return values, preserving Circle caller behavior.

## TCP header and options bounds

PacketReceived rejects data offsets below the 20-byte base header or beyond the
available packet before subtraction, header removal or options scanning. ScanOptions
returns boolean; every non-EOL/NOP option must include a length in2..remaining, and
MSS must be exactly4 bytes. EOL/NOP may occupy the final byte. Candidate MSS is
committed only after the full declared area validates, so a later malformed TLV
cannot partially change MSS/IW/CWND. Unknown valid options are skipped, SYN-only
MSS negotiation and existing clamp/window formula remain. Tests execute the actual
parser (196608 combinations and exact-bound guard pages) and complete packet handler
for malformed offsets/options. All changes are port-owned, not in lib/.

## TCP Nagle option

Original Circle sends sub-MSS queued buffers whenever the peer/congestion windows
permit, even with bytes in flight; it has no Nagle gate. Both constructor defaults
remain TCP_NODELAY=1 to preserve that behavior. Explicit TCP_NODELAY=0 enables
short-segment deferral with outstanding data; value1 bypasses only this gate after
the unchanged window/congestion check. Policy setters do not yield, allocate or
send immediately. Python caches pre-connect policy and applies it after stream
transfer; accepted sockets inherit the listener's explicit setting. Failure to
apply closes the acquired stream and does not publish an unusable connection.

## TCP shutdown capability boundary

Unmodified Circle Close is not a half-close API. The port-owned overrides now add
CTCPConnection::Shutdown and CTransportLayer::Shutdown: WR blocks new sends and
queues FIN behind accepted TX, while Receive/GetStatus keep the receive direction
usable in FIN_WAIT. RD drains RX without touching TX; PacketReceived still advances
TCP sequence/ACK but drops in-order and out-of-order unread payload. A peer FIN before
a queued local FIN switches the FIN target to LAST_ACK. Repeated shutdown/Close calls
are safe without asserting or duplicating the FIN sequence number.

Bridge shutdown keeps native owner references and generation tokens until close,
clears its cached RX tail only on successful RD, suppresses WR poll readiness and
returns EPIPE for writes after WR. Python SO_ERROR does not latch local EPIPE as a
terminal error. Pending connects are not promoted by shutdown. Host tests execute
actual native Shutdown/Receive/Process and complete PacketReceived, plus bridge and
adapter lifecycles. These are code-level host tests; wire behavior remains for Pi
acceptance later. All source changes stay outside lib/.

## Passive handshake readiness

IsAcceptReady excludes SynReceived half-open connections. Passive Established
and CloseWait without an error are ready. Accept allows CloseWait so a peer FIN
immediately after handshake does not discard an otherwise valid accepted stream.
The listener bridge calls Accept only after IsAcceptReady, never waiting inside
Circle Accept on the VM stack. Extracted actual method tests cover early FIN/RST;
wire-level handshake and scheduler stress testing are still required.

## Bounded ephemeral port selection

UDP Bind(port0), TCP Listen(port0) and Connect(local_port0) scan at most the complete 60000..60999
range. Existing connections with matching protocol, including retained terminated
TCP objects, reserve their number. Protocol namespaces are independent. Exhaustion
returns NET_ERROR_INVALID_VALUE after releasing the lock; native allocation is not
attempted. A vacant pointer-array slot may remain for later reuse. The mapping is
currently EINVAL, not EADDRINUSE. Explicit-port collision and bind reservation
are separate unfinished contracts.

## UDP zero payload, declared length and ownership

The UDP adaptation accepts zero-byte payloads (header length eight) for send and
receive. PacketReceived rejects a declared UDP length smaller than the header or
larger than the available IP payload, checks checksum over the declared length,
and strips trailing bytes before queueing. Empty payload remains a real queued
buffer with peer metadata, distinct from an empty queue.

NetworkLayer::Send consumes a packet on failure as well as success. The adapted
UDP Send/SendTo pass a copy to that layer, retain the original on failure, and
consume the original on success. This establishes the caller-delete-on-error
contract used by Circle CSocket and the port bridge. It adds one bounded frame
copy per outgoing datagram; OOM recovery is still limited by Circle allocation.
Connected UDP adds nonblocking SetPeer/SetUDPPeer to update an existing UDP
connection without replacing its bound port or broadcast option. It clears stale
pending errors and queued packets when changing peer. The bridge exposes separate
connected Send; ReceiveFrom uses native active-peer filtering. Reconnect failure
preserves the previous peer. Explicit SendTo on active connections uses its supplied
destination independently, while Send continues using the connected default peer.

UDP SO_ERROR uses TakePendingError/TakeUDPError to consume only the saved errno,
without changing peer, binding, queued packet/metadata or connection lifetime.
A consumed error is cached before Python allocation; allocation failure preserves
it for retry. New UDP notifications can report a new error later (unlike a TCP
terminal condition, which remains terminal). Fresh unopened UDP queries stay local.
Current Circle ICMP notifications map destination-unreachable to EHOSTUNREACH;
ICMP subcodes are not exposed as a distinct ECONNREFUSED here.

These changes are only in the port adaptation; lib/circle remains unedited.

## Runtime IPv4 configuration

CNetSubSystem::Configure copies a static tuple or resets to asynchronous DHCP.
The platform-lifetime DHCP worker uses request generations to cancel obsolete
exchange stacks before committing addresses or clearing newer state; it is never
deleted while running. Short sleep pieces allow mode changes during backoff.
ARP timers/deferred frames and route caches flush on configuration changes. Caller
must close application sockets before changing IP; existing transports are not
recreated and live sockets are not migrated. Static tuples are validated before
mutation; no automatic IP conflict detection or persistent boot setting exists.
Renew/rebind compares all four config fields with OR: any one changed address,
mask, gateway or DNS triggers ConfigChanged and reacquisition. The previous AND
ignored a changed DNS/gateway unless every field changed; unchanged config renews
lease times without tearing it down. Host tests cover twelve ACK combinations.

## SDHOST error propagation and busy completion

The port copy of sdhost.cpp stores previous-command and software PIO timeouts
in the MMC request error fields and preserves helper errors in transfer_pio.
Busy IRQ errors now complete the request synchronously through tasklet_finish
instead of relying on another interrupt that may never arrive. An active PIO
iterator is stopped and its transferred byte count is reset on this abort.
Regression tests use extracted real methods and MMC structures with simulated
registers; they do not establish the cause or resolution of the reported board
first-write EIO. Hardware status/logs and persistence tests are still required.
