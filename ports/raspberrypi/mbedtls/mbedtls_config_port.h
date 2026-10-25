// SPDX-License-Identifier: MIT
#ifndef MPYNN_MBEDTLS_CONFIG_PORT_H
#define MPYNN_MBEDTLS_CONFIG_PORT_H

#include "tls_random_bridge.h"
#define MBEDTLS_PLATFORM_TIME_MACRO mpynn_tls_time
#define MBEDTLS_PLATFORM_MS_TIME_ALT
#define MBEDTLS_PLATFORM_GMTIME_R_ALT
#define MICROPY_MBEDTLS_CONFIG_BARE_METAL (1)
#include "extmod/mbedtls/mbedtls_config_common.h"

#if !defined(MBEDTLS_HAVE_TIME) || !defined(MBEDTLS_HAVE_TIME_DATE)
#error "Raspberry Pi certificate verification requires UTC time checks"
#endif
// mbedTLS 3.6.6 x509_crt.c returns MBEDTLS_ERR_X509_FATAL_ERROR when
// gmtime_r fails (x509.c's standalone past/future checks also return true).
// The default UTC provider returns unavailable, time() returns -1, and our
// gmtime_r rejects it. Certificate chain verification consequently fails.
// This applies when callers select CERT_REQUIRED. Upstream requests uses
// CERT_NONE by default, which skips certificate verification and needs no UTC.
// The port enables standard SSL in its build; this file supplies clock/RNG hooks.
#endif
