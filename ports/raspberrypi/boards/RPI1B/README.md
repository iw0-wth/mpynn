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
