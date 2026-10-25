# SPDX-License-Identifier: MIT
# Raspberry Pi 1 Model B / BCM2835 selection for the shared Circle port.
# Keep the original board directory as the single source of configuration:
# board_config.mk owns RASPPI/AARCH/ARCH_FLAGS; board_config.h and ulab_config.h
# are included by C/C++; config.txt owns the tested ARM/core clock settings.
BOARD_DIR ?= $(MPYNN_TOP)/boards/RPI1B
include $(BOARD_DIR)/board_config.mk
# VC4 defaults are inherited unchanged from the shared port Makefile:
# ENABLE=1, MULTI_TILE=1, PACKED_WEIGHTS=1, PROFILE_COUNTERS=1,
# POLL_STRIDE=256, WAIT_SLEEP_US=10. Command-line overrides remain supported.
