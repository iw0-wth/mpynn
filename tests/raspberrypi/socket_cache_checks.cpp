// SPDX-License-Identifier: MIT
// Compile-only ARM/Circle ABI check; does not expose Python socket yet.
#include <circle/net/netbuffer.h>
#include "socket_rx_cache.h"
template class MpynnSocketRxCache<CNetBuffer>;
