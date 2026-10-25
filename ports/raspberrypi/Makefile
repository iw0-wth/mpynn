# SPDX-License-Identifier: MIT
# Native MicroPython core + Circle; no OpenMV SDK or fork-internal board needed.
.DEFAULT_GOAL := all
BOARD ?= RPI1B
MPYNN_TOP ?= ../..
# Each supported board owns its selection file; shared build rules stay here.
BOARD_MK := boards/$(BOARD)/board.mk
ifeq ($(wildcard $(BOARD_MK)),)
$(error Unsupported board '$(BOARD)': missing $(BOARD_MK))
endif
include $(BOARD_MK)
BUILD ?= $(MPYNN_TOP)/build/$(BOARD)/micropython
# Native ARM GCC writes D:/... dependency targets. MSYS /d/... targets are a
# different make node even when they name the same file: normalize BEFORE py.mk
# expands OBJ/HEADER_BUILD, including command-line BUILD overrides.
ifeq ($(OS),Windows_NT)
override BUILD := $(shell cygpath -m "$(abspath $(BUILD))")
endif
CROSS_COMPILE ?= arm-none-eabi-
include $(MPYNN_TOP)/lib/micropython/py/mkenv.mk
# Local adaptation tools never overwrite vendored upstream sources.
MAKE_MANIFEST = $(PYTHON) -B tools/makemanifest.py
QSTR_DEFS := qstrdefsport.h
FROZEN_MANIFEST ?= manifest.py
MPY_LIB_DIR := $(TOP)/lib/micropython-lib
BUILD_ID_HEADER := $(BUILD)/build_identity.h
BUILD_ID_REPORT := $(MPYNN_TOP)/build/$(BOARD)/build_identity.json
VC4_RUNTIME_SOURCE_ID = $(shell $(PYTHON) -B $(MPYNN_TOP)/lib/vc4-runtime/tools/source_id.py)
BUILD_ID_FLAGS = VC4_RUNTIME_SOURCE_ID=$(VC4_RUNTIME_SOURCE_ID) BOARD=$(BOARD) SSL=$(MICROPY_PY_SSL) ABI=$(FLOAT_ABI) ARCH=$(ARCH_FLAGS) VC4=$(VC4_ENABLE) VC4_MULTI_TILE=$(VC4_MULTI_TILE) VC4_PACKED_WEIGHTS=$(VC4_PACKED_WEIGHTS) VC4_PROFILE_COUNTERS=$(VC4_PROFILE_COUNTERS) VC4_POLL_STRIDE=$(VC4_POLL_STRIDE) VC4_WAIT_SLEEP_US=$(VC4_WAIT_SLEEP_US)
$(BUILD_ID_HEADER): FORCE build_identity.py $(BOARD_DIR)/board_config.h Makefile
	$(Q)$(PYTHON) -B build_identity.py --port . --board "$(BOARD_DIR)" --header "$@" --report "$(BUILD_ID_REPORT)" $(foreach f,$(BUILD_ID_FLAGS),--flag="$(f)")
CFLAGS += -I$(BUILD)
# Keep mpy-cross build output outside the read-only MicroPython checkout.
MPY_CROSS_BUILD := $(MPYNN_TOP)/build/$(BOARD)/mpy-cross
ifeq ($(OS),Windows_NT)
MICROPY_MPYCROSS := $(MPY_CROSS_BUILD)/mpy-cross.exe
else
MICROPY_MPYCROSS := $(MPY_CROSS_BUILD)/mpy-cross
endif
# Upstream auto-build assumes tool output is inside mpy-cross; supply our own rule.
MICROPY_MPYCROSS_DEPENDENCY :=
$(BUILD)/frozen_content.c: | $(MICROPY_MPYCROSS)
export MICROPY_MPYCROSS
export PYTHONDONTWRITEBYTECODE := 1
$(MICROPY_MPYCROSS): FORCE
	$(Q)$(MAKE) -C "$(TOP)/mpy-cross" BUILD="$(abspath $(MPY_CROSS_BUILD))" PYTHON="$(PYTHON)" CROSS_COMPILE= USER_C_MODULES= FROZEN_MANIFEST=
MICROPY_ROM_TEXT_COMPRESSION := 0
MICROPY_VFS_FAT := 1
MICROPY_PY_SSL := 1
MICROPY_SSL_MBEDTLS := 1
# Production uses one VC4-specialized ARM archive with C fallback inside the
# FC overlay. Override TFLM_LIB explicitly for a different integration.
TFLM_TOP := $(MPYNN_TOP)/lib/tflm/libtflm
TFLM_LIB ?= $(MPYNN_TOP)/../tflite-micro/gen/rpi1b_x86_64_default_vc4_gcc/lib/libtensorflow-microlite.a
TFLM_INCLUDE := -I$(TFLM_TOP)/include -I$(TFLM_TOP)/include/third_party \
    -I$(TFLM_TOP)/include/third_party/gemmlowp \
    -I$(TFLM_TOP)/include/third_party/flatbuffers/include
include $(TOP)/py/py.mk
include $(TOP)/extmod/extmod.mk
# Explicit active extension sources: no camera/IDE/network implementations.
SRC_EXTMOD_C := extmod/modmachine.c upstream_overrides/micropython/extmod/machine_i2c.c upstream_overrides/micropython/extmod/machine_spi.c drivers/bus/softspi.c extmod/modjson.c extmod/modselect.c extmod/modtime.c \
    extmod/modos.c extmod/modvfs.c extmod/modnetwork.c upstream_overrides/micropython/extmod/modsocket.c extmod/vfs.c extmod/vfs_blockdev.c \
    extmod/vfs_reader.c extmod/vfs_fat.c extmod/vfs_fat_diskio.c extmod/vfs_fat_file.c \
    extmod/virtpin.c extmod/modtls_mbedtls.c extmod/mbedtls/mbedtls_alt.c shared/libc/abort_.c shared/libc/printf.c

CIRCLEHOME := $(MPYNN_TOP)/lib/circle
CIRCLE_BUILD := $(MPYNN_TOP)/build/$(BOARD)/circle
CIRCLE_JOBS ?= 6
CFLAGS += $(ARCH_FLAGS) -I. -I$(BOARD_DIR) -I$(TOP) -I$(BUILD)
CFLAGS += -std=gnu11 -Wall -Wextra -Wno-unused-parameter -Os -g -DNDEBUG
CFLAGS += -ffunction-sections -fdata-sections -fno-common -fno-builtin
# Board-validated production path: packed16 weights + single-launch tile loop.
# CPU reference remains selectable through machine.vc4(False) or ml backend.
VC4_ENABLE ?= 1
VC4_MULTI_TILE ?= 1
VC4_PACKED_WEIGHTS ?= 1
ifeq ($(VC4_PACKED_WEIGHTS),1)
ifneq ($(VC4_MULTI_TILE),1)
$(error VC4_PACKED_WEIGHTS=1 requires VC4_MULTI_TILE=1)
endif
endif
VC4_PROFILE_COUNTERS ?= 1
VC4_POLL_STRIDE ?= 256
VC4_WAIT_SLEEP_US ?= 10
CFLAGS += -DMPYNN_VC4_BCM2835 -DMPYNN_VC4_ENABLE=$(VC4_ENABLE) \
    -DMPYNN_VC4_MULTI_TILE=$(VC4_MULTI_TILE) \
    -DMPYNN_VC4_PACKED_WEIGHTS=$(VC4_PACKED_WEIGHTS) \
    -DMPYNN_VC4_PROFILE_COUNTERS=$(VC4_PROFILE_COUNTERS) \
    -DMPYNN_VC4_POLL_STRIDE=$(VC4_POLL_STRIDE) \
    -DMPYNN_VC4_WAIT_SLEEP_US=$(VC4_WAIT_SLEEP_US)
SRC_C := mpmain.c build_info.c mphalport.c machine_pin.c soft_bus_hal.c machine_spi.c machine_i2c.c machine_wdt.c machine_timer.c machine_sdcard.c uml_binding.c tensor_codec.c modnetwork_port.c socket_udp_port.c dns_port.c tls_clock.c tls_rtc.c socket_errno_bridge.c shared/netutils/netutils.c shared/timeutils/timeutils.c \
    shared/readline/readline.c shared/runtime/pyexec.c \
    shared/runtime/stdout_helpers.c shared/runtime/interrupt_char.c \
    shared/runtime/gchelper_generic.c shared/runtime/sys_stdio_mphal.c
include ulab.mk
include $(MPYNN_TOP)/modules/image_file/image_file.mk
VPATH += $(MPYNN_TOP)
SRC_C += $(ULAB_SRC_C) $(IMAGE_FILE_SRC_C) modules/audio/audio_file.c tflm_libc.c
CFLAGS += -I$(MPYNN_TOP)/modules/audio
VC4_RUNTIME_DIR := $(MPYNN_TOP)/lib/vc4-runtime
include $(VC4_RUNTIME_DIR)/runtime.mk
CFLAGS += -I$(VC4_RUNTIME_DIR)/include
VC4_LIB_OBJ := $(addprefix $(BUILD)/vc4lib/,$(notdir $(VC4_RUNTIME_C_SOURCES:.c=.o))) \
    $(BUILD)/vc4lib/vc4_runtime.o
SRC_QSTR += $(filter-out socket_errno_bridge.c build_info.c,$(SRC_C)) modmachine_port.c
OBJ := $(PY_O) $(addprefix $(BUILD)/,$(SRC_C:.c=.o)) $(BUILD)/context.o
QSTR_GLOBAL_DEPENDENCIES += $(BOARD_DIR)/board_config.h Makefile
$(BUILD)/build_info.o: $(BUILD_ID_HEADER)
$(VC4_LIB_OBJ): $(BUILD_ID_HEADER)
$(BUILD)/vc4lib/%.o: $(VC4_RUNTIME_DIR)/src/%.c
	$(Q)mkdir -p $(dir $@)
	$(Q)$(CC) $(ARCH_FLAGS) -std=c11 -Os -g -ffreestanding -ffunction-sections -fdata-sections \
	    -I$(VC4_RUNTIME_DIR)/include $(VC4_RUNTIME_DEFINES) -MMD -MP -c $< -o $@
$(BUILD)/vc4lib/vc4_runtime.o: $(VC4_RUNTIME_DIR)/src/vc4_runtime.cpp
	$(Q)mkdir -p $(dir $@)
	$(Q)$(CXX) $(ARCH_FLAGS) -std=c++17 -Os -g -ffreestanding -fno-exceptions -fno-rtti \
	    -ffunction-sections -fdata-sections -I$(VC4_RUNTIME_DIR)/include $(VC4_RUNTIME_DEFINES) \
	    -MMD -MP -c $< -o $@
-include $(VC4_LIB_OBJ:.o=.d)
# Generated numeric QSTR IDs are shared by all C and frozen module objects.
# Keep a normal dependency as a port-level safety net in addition to GCC .P.
$(OBJ): $(BUILD)/genhdr/qstrdefs.generated.h

FW_DIR := $(MPYNN_TOP)/build/$(BOARD)/bin
CLEAN_EXTRA += $(FW_DIR)
CIRCLE_GLUE_SRC := kernel.cpp machine_bridge.cpp gpio_bridge.cpp sdcard_bridge.cpp ethernet_bridge.cpp network_bridge.cpp udp_bridge.cpp tcp_connect_bridge.cpp tcp_stream_bridge.cpp tcp_listener_bridge.cpp dns_bridge.cpp tls_random_bridge.cpp
# The SPI C binding and C++ bridge intentionally share a basename; keep their
# objects separate. All bridges use .bridge.o so neither implicit C rule wins.
CIRCLE_GLUE_SRC += machine_spi.cpp machine_i2c.cpp machine_wdt.cpp machine_timer.cpp uml_backend.cpp vc4_runtime_bcm2835.cpp
KERNEL_OBJ := $(addprefix $(BUILD)/,$(CIRCLE_GLUE_SRC:.cpp=.bridge.o))
# Feature variables are embedded in the identity header; rebuild bridges when
# switching shader/layout/profile modes even if their .cpp files did not change.
$(KERNEL_OBJ): $(BUILD_ID_HEADER)
LIBGCC := $(shell $(CC) $(ARCH_FLAGS) -print-libgcc-file-name)
LIBM := $(shell $(CC) $(ARCH_FLAGS) -print-file-name=libm.a)
# Keep VC4 entry points and shader data reachable through --gc-sections even
# before the VC4-specialized TFLM archive is selected.
VC4_FORCE_SYMBOLS := -u vc4_init -u vc4_runtime_status -u vc4_is_available \
    -u vc4_set_enabled -u vc4_is_enabled -u vc4_reset_diagnostics -u vc4_shutdown -u vc4_status_string \
    -u vc4_alloc -u vc4_free -u vc4_launch -u vc4_matvec_fp32 \
    -u vc4_release_weights -u vc4_should_offload_fp32 -u vc4_matvec_shader

# Only the errno translator needs Circle's constants. Do not place Circle libc
# replacements ahead of MicroPython/libc headers for the rest of the C port.
$(BUILD)/socket_errno_bridge.o: CFLAGS += -idirafter $(CIRCLEHOME)/include

.PHONY: circle all check-config
all: check-config $(FW_DIR)/kernel.img
check-config:
	$(Q)$(CC) $(CFLAGS) -fsyntax-only $(MPYNN_TOP)/tests/raspberrypi/config_checks.c
# Configuration-signed build stage: never reuse another board's Circle objects.
circle:
	$(Q)$(PYTHON) build_circle.py --source "$(CIRCLEHOME)" --build "$(CIRCLE_BUILD)" \
	    --make "$(MAKE)" --prefix "$(CROSS_COMPILE)" --jobs $(CIRCLE_JOBS) --with-sd --with-usb --with-net

$(KERNEL_OBJ): $(BUILD)/%.bridge.o: %.cpp $(BOARD_DIR)/board_config.h Makefile
	$(Q)mkdir -p $(dir $@)
	$(Q)$(CXX) $(ARCH_FLAGS) $(if $(findstring uml_backend.cpp,$<),-std=c++11,-std=c++17 -ffreestanding) -Wall -Os -g \
	    -fno-exceptions -fno-rtti -ffunction-sections -fdata-sections \
	    -DMPYNN_VC4_BCM2835 -DMPYNN_VC4_ENABLE=$(VC4_ENABLE) \
	    -DMPYNN_VC4_MULTI_TILE=$(VC4_MULTI_TILE) \
	    -DMPYNN_VC4_PACKED_WEIGHTS=$(VC4_PACKED_WEIGHTS) \
	    -DMPYNN_VC4_PROFILE_COUNTERS=$(VC4_PROFILE_COUNTERS) \
	    -DMPYNN_VC4_POLL_STRIDE=$(VC4_POLL_STRIDE) \
	    -DMPYNN_VC4_WAIT_SLEEP_US=$(VC4_WAIT_SLEEP_US) \
	    $(if $(findstring uml_backend.cpp,$<),-DTF_LITE_STATIC_MEMORY -DTF_LITE_DISABLE_X86_NEON -DKERNELS_OPTIMIZED_FOR_SIZE -DTF_LITE_STRIP_ERROR_STRINGS $(TFLM_INCLUDE),-nostdinc++ -DAARCH=$(AARCH) -DRASPPI=$(RASPPI) -DSTDLIB_SUPPORT=1 -D__circle__=510101 -Iupstream_overrides/circle/include -I$(CIRCLEHOME)/include -I$(CIRCLEHOME)/addon) \
	    -I$(BOARD_DIR) -I. -I$(VC4_RUNTIME_DIR)/include -MMD -MP -MF $(@:.o=.d) -c $< -o $@

-include $(KERNEL_OBJ:.o=.d)

$(FW_DIR)/kernel.elf: $(OBJ) $(KERNEL_OBJ) $(VC4_LIB_OBJ) $(CIRCLEHOME)/circle.ld $(TFLM_LIB) circle
	$(Q)mkdir -p $(FW_DIR)
	$(Q)$(LD) --section-start=.init=0x8000 --gc-sections --no-warn-rwx-segments -z noexecstack $(VC4_FORCE_SYMBOLS) \
	    -T $(CIRCLEHOME)/circle.ld -Map=$(FW_DIR)/kernel.map -o $@ \
	    $(KERNEL_OBJ) $(VC4_LIB_OBJ) $(OBJ) --start-group $(CIRCLE_BUILD)/lib/libcircle.a \
	    $(CIRCLE_BUILD)/lib/fs/libfs.a $(CIRCLE_BUILD)/addon/SDCard/libsdcard.a \
	    $(CIRCLE_BUILD)/lib/usb/libusb.a $(CIRCLE_BUILD)/lib/input/libinput.a \
	    $(CIRCLE_BUILD)/lib/net/libnet.a $(CIRCLE_BUILD)/lib/sched/libsched.a \
	    $(TFLM_LIB) "$(LIBM)" "$(LIBGCC)" --end-group
	$(Q)$(SIZE) $@

$(FW_DIR)/kernel.img: $(FW_DIR)/kernel.elf check_frozen_qstr.py check_firmware.py
	$(Q)$(PYTHON) check_frozen_qstr.py $< $(BUILD)/genhdr/qstrdefs.generated.h
	$(Q)$(OBJCOPY) -O binary $< $@
	$(Q)$(PYTHON) check_firmware.py $< $@ --report $(FW_DIR)/layout.json

include $(TOP)/py/mkrules.mk
