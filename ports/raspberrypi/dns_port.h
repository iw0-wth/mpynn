// SPDX-License-Identifier: MIT
#ifndef MPYNN_DNS_PORT_H
#define MPYNN_DNS_PORT_H

#include "py/runtime.h"
#include "extmod/modnetwork.h"

// Standard non-LWIP NIC callback: returns zero or a positive MicroPython errno.
int mpynn_gethostbyname(mp_obj_t nic, const char *name, mp_uint_t len, uint8_t *out);

#endif
