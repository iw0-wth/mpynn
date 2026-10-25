// SPDX-License-Identifier: MIT
#ifndef MPYNN_DNS_BRIDGE_H
#define MPYNN_DNS_BRIDGE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Internal platform ABI; no build/Python integration. Calls require TASK_LEVEL
// on the Circle scheduler's core. Return 0 or positive MPYNN errno; only the
// separately scheduled worker yields. No Python/GC pointers survive start.
// Two slots, including completed and abandoned jobs. Tokens use non-wrapping
// generations; exhausted slots retire permanently. Outputs unchanged on error.
// Name is an explicit byte span (no terminator required), 1..253 bytes, ASCII
// letters/digits/hyphens with dot-separated labels of 1..63 bytes; each label
// starts/ends with a letter/digit. One trailing dot is accepted: Circle's
// strtok_r query encoder supports it. No embedded NUL, IDNA or Unicode support.
// Circle treats bare "localhost" as this NIC's address, not loopback.
// SECURITY: upstream Resolve uses sequential transaction IDs, does not verify
// echoed question/answer names, and provides no authenticated DNS. The local
// patch allows full 512-byte responses, but these protocol risks remain;
// host tests exercise bridge ownership, not untrusted DNS packet parsing.
int mpynn_dns_start(const char *name, size_t len, uint32_t *token);
// PENDING/ABANDONED: AGAIN, retaining slot. Success: copy four IPv4 octets and
// free slot. Completed failure: return positive errno AND FREE SLOT, unlike
// tcp_connect_finish. Circle's undifferentiated false maps to IO, not NXDOMAIN.
// Invalid arguments/context do not consume a job. Released/stale token: BADF.
int mpynn_dns_finish(uint32_t token, uint8_t ip[4]);
// Pending: mark abandoned; worker retains name/slot until it returns (cannot
// interrupt Resolve). Repeated pending cancellation succeeds. Completed: free
// immediately. Worker destruction belongs exclusively to Circle's scheduler.
int mpynn_dns_cancel(uint32_t token);
// VM reset cleanup; abandoned jobs remain occupied until native completion.
int mpynn_dns_cancel_all(void);
#ifdef __cplusplus
}
#endif
#endif
