MPYNN_TOP := $(abspath $(USERMOD_DIR)/../..)
ULAB_DIR := $(MPYNN_TOP)/modules/ulab/code
IMAGE_FILE_DIR := $(MPYNN_TOP)/modules/image_file
AUDIO_DIR := $(MPYNN_TOP)/modules/audio
RPI_PORT_DIR := $(MPYNN_TOP)/ports/raspberrypi

_HOST_MOD_DIR := $(USERMOD_DIR)
USERMOD_DIR := $(ULAB_DIR)
include $(ULAB_DIR)/micropython.mk
USERMOD_DIR := $(_HOST_MOD_DIR)

VPATH += $(MPYNN_TOP)
SRC_USERMOD += modules/image_file/modimage.c
SRC_USERMOD += modules/image_file/image_core.c
SRC_USERMOD += modules/image_file/png_codec.c
SRC_USERMOD += modules/image_file/lodepng.c
SRC_USERMOD += modules/audio/audio_file.c
SRC_USERMOD += ports/raspberrypi/uml_binding.c
SRC_USERMOD += ports/raspberrypi/tensor_codec.c
SRC_USERMOD_CXX += ports/raspberrypi/uml_backend.cpp

TFLM_DIR := $(MPYNN_TOP)/lib/tflm/libtflm/include
TFLM_ARCHIVE := $(MPYNN_TOP)/build/host-tests/uml_backend/genrel/linux_x86_64_release_gcc/lib/libtensorflow-microlite.a
CFLAGS_USERMOD += -I$(MPYNN_TOP)/modules/ulab/code \
    -I$(IMAGE_FILE_DIR) -I$(AUDIO_DIR) \
    -I$(TFLM_DIR) -I$(TFLM_DIR)/third_party/flatbuffers/include -I$(TFLM_DIR)/third_party/gemmlowp \
    -I$(TFLM_DIR)/tensorflow \
    -DULAB_CONFIG_FILE=\"$(MPYNN_TOP)/boards/RPI1B/ulab_config.h\"
CXXFLAGS_USERMOD += -I$(RPI_PORT_DIR) -I$(TFLM_DIR) -I$(TFLM_DIR)/third_party/flatbuffers/include -I$(TFLM_DIR)/third_party/gemmlowp \
    -DTF_LITE_STATIC_MEMORY -DTF_LITE_DISABLE_X86_NEON -DKERNELS_OPTIMIZED_FOR_SIZE \
    -DTF_LITE_STRIP_ERROR_STRINGS -std=gnu++11 -fno-rtti -fno-exceptions
LDFLAGS_USERMOD += $(TFLM_ARCHIVE)
LIBS_USERMOD += -lstdc++
