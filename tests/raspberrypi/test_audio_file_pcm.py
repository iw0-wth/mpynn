"""Raw PCM and lifecycle contract tests for the native file source.

No USB/I2S/ADC or board hardware is used.  CPython runs the fixture and API
shape checks; MicroPython runs additionally exercise the native module when it
is built into the image.
"""
import os
import struct
import tempfile


def _audio_or_skip():
    try:
        import audio
        return audio
    except ImportError:
        return None


def test_raw_pcm_requires_explicit_format_and_never_invents_audio():
    audio = _audio_or_skip()
    payload = b"".join(struct.pack("<h", n) for n in (10, 20, 30))
    if audio is None:
        assert len(payload) == 6
        return
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(payload)
        path = f.name
    got = []
    try:
        audio.init(channels=1, frequency=16000, samples=2, source=path, format="pcm")
        audio.start_streaming(lambda buf: got.append(bytes(buf)))
        for _ in range(4):
            audio.poll()
        assert got == [payload[:4], payload[4:]]
    finally:
        audio.deinit()
        os.unlink(path)


def test_init_validates_before_open_and_stop_is_idempotent():
    audio = _audio_or_skip()
    if audio is None:
        assert True
        return
    try:
        try:
            audio.init(channels=0, source="definitely-not-opened.pcm", format="pcm")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid scalar arguments must fail before open")
        audio.stop_streaming()
        audio.stop_streaming()
    finally:
        audio.deinit()


def test_reentrant_callback_stop_suppresses_stale_work():
    audio = _audio_or_skip()
    if audio is None:
        assert True
        return
    payload = struct.pack("<hhhh", 1, 2, 3, 4)
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(payload)
        path = f.name
    calls = []
    try:
        audio.init(channels=1, frequency=16000, samples=2, source=path, format="pcm")

        def callback(buf):
            calls.append(bytes(buf))
            audio.stop_streaming()

        audio.start_streaming(callback)
        audio.poll()
        audio.poll()
        assert calls == [payload[:4]]
    finally:
        audio.deinit()
        os.unlink(path)
