# mpynn compared with OpenMV

This is a source/configuration comparison against `D:/openmv_aicore/openmv-master`.
The Raspberry Pi 1B port is intentionally an AI/network runtime rather than a camera
firmware. This compares **the active Raspberry Pi build**, not wholesale file
removal: legacy source directories and ports may remain in the checkout but are
not selected by its explicit source list.

## Excluded from the Raspberry Pi runtime

- Camera sensor drivers and sensor board probing (`sensor`/camera capture path).
- Camera imlib frame pipeline, global camera frame buffers, snapshot/stream APIs
  and IDE preview/display pipeline. Independent file-image processing is restored
  through a bounded native module (PNG/BMP/PNM), not through camera buffers.
- OpenMV IDE transport, RPC/debug protocol, WebREPL-style IDE transport and camera
  IDE control paths.
- LCD/display drivers and `MICROPY_PY_DISPLAY` board integration.
- OpenMV board-specific camera GPIO/clock/USB boot contracts.
- OpenMV vision applications and camera demos that depend on `sensor`, `image`,
  `py_image`, framebuffers or camera snapshots.
- OpenMV-specific board fleets and MCU HALs; mpynn currently builds only Pi1B
  ARM1176JZF-S in this port.

## Retained or replaced

- MicroPython VM, filesystem/SD path, standard Python libraries and standard
  micropython-lib packages.
- Circle-owned startup, IRQ, scheduler, USB LAN9512 Ethernet and IPv4 network stack.
- Standard `machine` subset: Pin, RTC, hardware I2C/SPI/WDT, SoftI2C/SoftSPI and
  Timer; Pin IRQ is deferred to VM context. UART/PWM remain intentionally disabled.
- mbedTLS through MicroPython's standard TLS module; no Python-side Circle adapter.
- ML Python package from `scripts/libraries/ml`, native `uml.Model`, native ulab
  6.12.0 with 4D arrays, and separately built Pi1B ARMv6 reference TFLM kernels.
  No CMSIS-NN, CMSIS-DSP, Ethos-U or hardware accelerator is used.
- VFS image subset: PNG/BMP/PNM file decode, pixels, crop/resize/grayscale, ROI draw
  and ndarray conversion; JPEG and the full OpenMV image-analysis API are not
  implemented. The OpenMV LodePNG source is reused with its license retained.
- WAV PCM16/raw PCM file audio, bounded VM callbacks and reset cleanup. Live
  microphone capture and MCU-specific SAI/DFSDM/PDM HAL code are not included.
- Standard micropython-lib requests from the manifest; no Raspberry-Pi-specific
  Python requests fork.

## Deliberately not equivalent

OpenMV's camera/image/IDE behavior is not replaced by a stub. Imports and APIs that
require those features are absent or disabled rather than pretending to provide
camera data. AI inference is model/runtime work over user-provided tensors, not
camera capture. Physical Pi testing remains separate from host/static evidence.
