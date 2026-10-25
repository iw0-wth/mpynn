# SPDX-License-Identifier: MIT
# Native ulab 6.12.0 (upstream snapshot d161443), with all upstream defaults.
# Include after SRC_C := ... and before SRC_QSTR/OBJ construction, then append:
#   SRC_C += $(ULAB_SRC_C)
# SRC_QSTR is registered here so module discovery and qstr extraction see ulab.
# Setting SRC_USERMOD after py.mk has run does not add objects; avoid that path.
ULAB_DIR := modules/ulab/code
ULAB_SRC_C := $(addprefix $(ULAB_DIR)/, \
    scipy/integrate/integrate.c \
    scipy/linalg/linalg.c \
    scipy/optimize/optimize.c \
    scipy/signal/signal.c \
    scipy/special/special.c \
    ndarray_operators.c \
    ulab_tools.c \
    ndarray.c \
    numpy/ndarray/ndarray_iter.c \
    ndarray_properties.c \
    numpy/approx.c \
    numpy/bitwise.c \
    numpy/compare.c \
    numpy/carray/carray.c \
    numpy/carray/carray_tools.c \
    numpy/create.c \
    numpy/fft/fft.c \
    numpy/fft/fft_tools.c \
    numpy/filter.c \
    numpy/io/io.c \
    numpy/linalg/linalg.c \
    numpy/linalg/linalg_tools.c \
    numpy/numerical.c \
    numpy/poly.c \
    numpy/random/random.c \
    numpy/stats.c \
    numpy/transform.c \
    numpy/vector.c \
    numpy/numpy.c \
    scipy/scipy.c \
    user/user.c \
    utils/utils.c \
    ulab.c)

# Use project-relative source/object names: no ../ escapes from BUILD.
# MicroPython's own TOP points into lib/micropython, not this project root.
VPATH += $(MPYNN_TOP)
CFLAGS += -I$(MPYNN_TOP)/$(ULAB_DIR) -I$(BOARD_DIR)
CFLAGS += -DMODULE_ULAB_ENABLED=1 -DULAB_CONFIG_FILE=\"ulab_config.h\"
SRC_QSTR += $(ULAB_SRC_C)
QSTR_GLOBAL_DEPENDENCIES += ulab.mk $(BOARD_DIR)/ulab_config.h
