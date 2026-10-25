# RPI1B board build

This directory is the standalone build entry for Raspberry Pi 1 Model B
(BCM2835, ARM1176JZF-S, AArch32, VFP hard-float). Run GNU Make from MSYS2 Bash
on Windows with the native ARM toolchain on PATH:

```sh
export PATH=/e/arm-none-eabi/bin:/usr/bin:$PATH
cd /d/openmv_aicore/mpynn
make -C ports/raspberrypi/boards/RPI1B -j6 PYTHON=D:/anaconda3/python.exe
```

The top-level compatibility entry delegates through this same board entry:

```sh
make TARGET=RPI1B -j6 PYTHON=D:/anaconda3/python.exe
```

## Select kernel or complete SD image

Default `all` (or explicit `kernel`) builds `kernel.img`. The optional `sd-image`
target first builds/checks the current kernel and then packages a complete raw
MBR/FAT16 image; it does not write a card or download boot firmware.

```sh
# Kernel only (default):
make -C ports/raspberrypi/boards/RPI1B kernel -j8 PYTHON=D:/anaconda3/python.exe

# Full SD image, using the existing workspace boot firmware:
make -C ports/raspberrypi/boards/RPI1B sd-image -j8 \
    PYTHON=D:/anaconda3/python.exe \
    SD_BOOT_DIR=/d/openmv_aicore/RPI1B-SD/boot

# Equivalent top-level route:
make TARGET=RPI1B sd-image -j8 PYTHON=D:/anaconda3/python.exe \
    SD_BOOT_DIR=/d/openmv_aicore/RPI1B-SD/boot
```

Default image: `build/RPI1B/bin/mpynn-RPI1B-sd.img`, with a sibling JSON report.
It has a 1 MiB alignment gap and one **128 MiB FAT16 LBA partition**. Image size is
129 MiB; when flashed to a larger card, remaining space stays unpartitioned. No
Linux/rootfs, second data partition, or automatic expansion is added. Boot files
and writable MicroPython `/` share that FAT volume. Free FAT capacity is less than
the partition size because metadata and supplied files occupy space.

| Variable | Default / behavior |
| --- | --- |
| `SD_BOOT_DIR` | `lib/circle/boot` (relative to shared port), must already contain boot firmware |
| `SD_PARTITION_MIB` | `128`; configurable FAT16 partition size, supported 16..2048 MiB |
| `SD_IMAGE` | `$(FW_DIR)/mpynn-$(BOARD)-sd.img` |
| `SD_IMAGE_REPORT` | image basename with `.json` extension |
| `SD_EXTRA_DIR` | empty; optional directory whose contents are copied into FAT root |
| `SD_INCLUDE_DEMO` | `0`; use `1` to copy the project demo as `/demo` |
| `SD_DEMO_DIR` | project `demo/`; optional alternate source when demos are enabled |

Required boot inputs: `bootcode.bin`, `start.elf`, `fixup.dat`, `LICENCE.broadcom`.
The package always uses the **just-built** `kernel.img` and the selected board's
`config.txt` (700/250 baseline), replacing any stale copies in `SD_BOOT_DIR`.
Other boot-directory files are preserved. Extra content cannot overwrite boot
files; name collisions fail. No `boot.py` or `main.py` is inserted implicitly.

To include the classified demos and bundled textcls/VC4 models, append
`SD_INCLUDE_DEMO=1`. They appear as `/demo/system`, `/demo/network`, `/demo/ai` in
the FAT volume, are not frozen into the kernel, and remain manual-run examples.
`SD_EXTRA_DIR` can independently supply user files at the root; to put custom
files under `/demo`, give it a staging directory containing a `demo/` child.
Conflicting files between boot/demo/extra inputs are rejected.
All path overrides should be absolute; relative paths resolve from the common
`ports/raspberrypi` directory. The packer uses Python stdlib only, builds FAT16
short/long names and directories, and reports exact hashes and available space.
It does not require administrator access, a loop device, mkfs or mtools.

Flash the **whole SD image** using an image writer, not by copying the image file
onto a FAT volume. Flashing replaces the destination partition table/files; back
up the chosen card first. Existing bytes outside the written image may remain
physically on a larger card, but no partition exposes them. Actual Pi boot/SD
write verification is separate from host FAT consistency checks.

For configuration validation or command inspection without a full firmware build:

```sh
make -C ports/raspberrypi/boards/RPI1B check-config PYTHON=D:/anaconda3/python.exe
make -C ports/raspberrypi/boards/RPI1B -n PYTHON=D:/anaconda3/python.exe \
    BUILD=/d/openmv_aicore/mpynn/build/RPI1B/micropython \
    -W vc4_matvec_packed_shader.c \
    D:/openmv_aicore/mpynn/build/RPI1B/micropython/vc4_matvec_packed_shader.o
```

The command inspection targets the packed shader object explicitly. GNU Make may
execute recipes containing `$(MAKE)` even with `-n`; the full `all` graph contains
a Circle Python wrapper with such a recipe. Use the targeted form above when no
Circle or firmware build should start.

Both entry points forward requested goals and command-line settings to the shared
port Makefile. Shared recipes run from the port directory, preserving relative
source paths and the existing QSTR dependency rules. On Windows, `BUILD` overrides
(including MSYS `/d/...` paths) are normalized with `cygpath -m` before MicroPython
expands its object and generated-header paths. Set `BUILD` relative to the port
directory, or use an absolute path. `BUILD` changes MicroPython object output;
Circle and firmware outputs retain their board-specific locations.

## Configuration ownership

`board.mk` selects the original `../../../../boards/RPI1B` directory as the
single source of configuration. No configuration files are copied or moved:

- `board_config.mk`: Circle board number, architecture, compiler ABI flags.
- `board_config.h` and `ulab_config.h`: board and module compile-time settings.
- `config.txt`: boot configuration, including the tested 700 MHz ARM / 250 MHz
  core clock baseline. Copy this file alongside `kernel.img` when preparing boot
  media; the build does not write a physical SD card.

The current VC4 defaults stay in the shared port Makefile: `VC4_ENABLE=1`,
`VC4_MULTI_TILE=1`, `VC4_PACKED_WEIGHTS=1`, `VC4_PROFILE_COUNTERS=1`,
`VC4_POLL_STRIDE=256`, `VC4_WAIT_SLEEP_US=10`. Command-line overrides are forwarded.
The existing production TFLM archive selection is unchanged.

Default outputs remain under `mpynn/build/RPI1B`: `micropython/` for MicroPython
objects and generated QSTR headers, `mpy-cross/`, `circle/`, and `bin/` for
`kernel.elf`, `kernel.map`, `kernel.img` and firmware reports.

## Adding a board

Add `ports/raspberrypi/boards/<BOARD>/board.mk` to select that board's configuration
and a board-local Makefile that delegates to the shared port with `BOARD=<BOARD>`.
The shared port accepts only boards with a selection file and reports an explicit
`Unsupported board` error otherwise. Hardware support and Circle build settings
must also be implemented and validated before a new board can build successfully.
