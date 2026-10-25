"""File-backed audio WAV contract tests.

These tests are host-safe and do not claim Raspberry Pi hardware coverage.  When
run under MicroPython with the native module enabled, they exercise the public
API through a temporary VFS file.  Under CPython they still validate fixture
construction and parser edge-case expectations.
"""
import os
import struct
import tempfile


def riff(chunks, riff_size_override=None):
    body = bytearray(b"WAVE")
    for ident, payload in chunks:
        body += ident + struct.pack("<I", len(payload)) + payload
        if len(payload) & 1:
            body += b"\0"
    size = len(body) if riff_size_override is None else riff_size_override
    return b"RIFF" + struct.pack("<I", size) + body


def pcm16_wav(samples, channels=1, rate=16000, extra=b""):
    frames = b"".join(struct.pack("<" + "h" * channels, *frame) for frame in samples)
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * 2, channels * 2, 16)
    return riff([(b"JUNK", extra), (b"fmt ", fmt), (b"data", frames)]), frames


def _audio_or_skip():
    try:
        import audio
        return audio
    except ImportError:
        return None


def test_wav_unknown_odd_chunk_and_exact_callbacks():
    audio = _audio_or_skip()
    wav, frames = pcm16_wav([(1,), (2,), (3,)], extra=b"x")
    if audio is None:
        assert wav[0:4] == b"RIFF"
        assert b"JUNK" in wav
        return
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(wav)
        path = f.name
    calls = []
    try:
        audio.init(channels=1, frequency=16000, samples=2, source=path)
        audio.start_streaming(lambda buf: calls.append(bytes(buf)))
        # Parent poll hook is intentionally explicit in this host test.
        for _ in range(3):
            audio.poll()
        assert calls == [frames[:4], frames[4:]]
    finally:
        audio.deinit()
        os.unlink(path)


def test_wav_bad_riff_size_is_rejected():
    audio = _audio_or_skip()
    wav, _ = pcm16_wav([(1,)], extra=b"")
    bad = wav[:4] + struct.pack("<I", 0xFFFFFFFF) + wav[8:]
    if audio is None:
        assert struct.unpack_from("<I", bad, 4)[0] == 0xFFFFFFFF
        return
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(bad)
        path = f.name
    try:
        try:
            audio.init(source=path)
        except (ValueError, OSError):
            pass
        else:
            raise AssertionError("overflowing RIFF must be rejected")
    finally:
        audio.deinit()
        os.unlink(path)
