# SPDX-License-Identifier: MIT
# Standalone board entry. Run shared recipes from the port directory so all
# upstream source paths, QSTR rules and Windows BUILD normalization stay intact.
.DEFAULT_GOAL := all
.PHONY: all $(MAKECMDGOALS)
all $(filter-out all,$(MAKECMDGOALS)):
	$(MAKE) -C ../.. BOARD=RPI1B $@
