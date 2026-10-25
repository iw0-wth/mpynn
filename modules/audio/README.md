# File-backed `audio` native module

This module is intentionally independent of USB, I2S, ADC, PDM, DMA, and MCU
HALs. It owns the file source implementation in `audio_file.c` and the parent
integration declaration in `audio_file.h`.

## Build integration (parent port)

The common OpenMV module makefile only wildcards `mpynn/modules/*.c`, so a
parent build must explicitly add:

```make
SRC_USERMOD += $(USERMOD_DIR)/audio/audio_file.c
CFLAGS_USERMOD += -I$(USERMOD_DIR)/audio -DMICROPY_PY_AUDIO_FILE=1
```

For a CMake parent, add `audio/audio_file.c` to the user module target and add
`audio/` as a private include directory. Do not enable a board audio HAL for
this source.

## VM hook and reset hook

Call `audio_file_poll()` from the parent port's normal VM/attachio poll path,
never from an IRQ or DMA callback. Each call performs at most one bounded VFS
read (`samples * channels * 2` bytes) and invokes `callback(buf)` only on the
VM thread. A port may instead expose `audio.poll()` for an explicit VM-side
poll in a host test; it is not a Python polyfill.

Call `audio_file_deinit()` while resetting/deinitialising the VM. It closes the
VFS stream, releases the callback and buffer roots, invalidates the generation,
and suppresses stale queued work. `stop_streaming()` is idempotent and also
invalidates the generation. A callback may stop streaming safely; reentrant
start/poll/deinit operations are rejected or suppressed.

## API and end semantics

```python
audio.init(channels=1, frequency=16000, samples=320,
           source=path, format="wav")
audio.start_streaming(callback)
audio.stop_streaming()
audio.deinit()
audio.is_streaming()
audio.eof()
```

`format="wav"` accepts RIFF/WAVE PCM16 little-endian only. RIFF chunk order is
not assumed; unknown chunks, odd-size padding, truncated chunks, and 32-bit
size/boundary overflow are checked. `fmt ` channels/frequency must match
`init`. `format="pcm"` is explicit raw PCM16 little-endian with no header.

`is_streaming()` and `eof()` expose terminal state so a consumer can leave its
listen loop when the source is exhausted. At EOF there is no zero padding and no repeated empty callback. A short final
frame is rejected/stopped without a callback; a valid short final frame (for a
WAV data size smaller than `samples`) is delivered with its exact byte length,
then streaming stops. No resampling or channel conversion is performed.

## Tests and limits

The project test tree is workspace `tests/`, sibling to mpynn (relative to this
module: `../../../tests/`). User-facing file audio examples are maintained in
`../../demo/ml.py` and do not import that external test tree.

`tests/raspberrypi/test_audio_file_wav.py` and
`tests/raspberrypi/test_audio_file_pcm.py` cover fixture construction, chunk
padding/overflow expectations, bounded callbacks, explicit raw PCM, EOF, and
reentrant stop behavior. They are host-safe and do not claim Raspberry Pi
hardware coverage. When the native module is present in a MicroPython image,
the same tests exercise its VFS path; otherwise CPython checks the fixture and
contract portions only.
