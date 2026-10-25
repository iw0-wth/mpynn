# SPDX-License-Identifier: MIT
# Use the standard requests package from read-only micropython-lib.
# No port-specific Python requests implementation is frozen.
require("requests")
# Portable OpenMV ML Python package; native backend is enabled separately only
# when a compatible TFLM archive and binding are linked.
add_library("mpynn-ml", "$(PORT_DIR)/../../scripts/libraries")
require("ml", library="mpynn-ml")
require("bisect")
require("collections-defaultdict")
require("functools")
require("itertools")
require("contextlib")
# User-invoked calibration only; no automatic NTP at boot.
require("ntptime")
# Standard compatibility wrapper from read-only micropython-lib over native tls.
require("ssl")
