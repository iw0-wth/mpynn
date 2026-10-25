# SPDX-License-Identifier: MIT
# Parent: include after SRC_C := and before OBJ, then SRC_C += $(IMAGE_FILE_SRC_C).
IMAGE_FILE_DIR := modules/image_file
IMAGE_FILE_SRC_C := $(addprefix $(IMAGE_FILE_DIR)/,modimage.c image_core.c png_codec.c lodepng.c)
VPATH += $(MPYNN_TOP)
CFLAGS += -I$(MPYNN_TOP)/$(IMAGE_FILE_DIR)
SRC_QSTR += $(MPYNN_TOP)/$(IMAGE_FILE_DIR)/modimage.c
QSTR_GLOBAL_DEPENDENCIES += $(MPYNN_TOP)/$(IMAGE_FILE_DIR)/image_core.h
