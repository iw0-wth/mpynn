# JPEG status

`openmv-master/lib/imlib/jpegd.c` is a software JPEG decoder. It is not a hardware
JPEG dependency and its main decode path is scalar C, but it cannot be copied into
the bounded VFS image module unchanged.

The source's parser and entropy refill path have unsafe assumptions for malformed
or truncated input: marker/segment lengths are not consistently checked against the
current window, APP1 EXIF/TIFF offsets are not range-checked, `JPEGFilter` assumes
non-empty data, and refill accounting can expose invalid reads. The lower wrapper
also depends on OpenMV `image_t`, UMA, framebuffer/imlib and MicroPython exception
APIs. Strict alignment and endian-safe byte loads would need further adaptation.

The current image module therefore keeps JPEG explicitly unsupported and raises
`NotImplementedError`. PNG/BMP/PNM remain supported with bounded, owned buffers.
A future JPEG implementation must either fully harden these paths and add malformed
JPEG tests, or use a separately audited decoder. A preflight marker scan alone is
insufficient because the decoder must itself remain safe during parsing and entropy
refill. No OpenMV `lib` source is modified.
