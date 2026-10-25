# Native file image subset

This module supplies a native built-in `image` module for Raspberry Pi file
images and CPU tensor preprocessing. It is a bounded subset of the OpenMV
Python image API, implemented in C without sensor, camera, framebuffer, IDE
preview, display, or Python image-library dependencies.

## Supported input files

`image.Image(path)` reads a complete file through the mounted VFS/SD filesystem;
it does not require a camera or framebuffer. For ML preprocessing, use a normal
PNG/BMP/PNM with valid headers and dimensions 1..8192. Any aspect ratio is
accepted: `Normalization` resizes it with its draw hints and background policy.
Decoded file and image storage are bounded to 64 MiB.

- PNG through the unchanged OpenMV copy of **LodePNG 20220109**. Grayscale,
  RGB, palette, alpha, and supported PNG bit depths are handled by LodePNG.
  Loaded pixels use RGB565; alpha is composited over black. CRC and zlib
  validation remain enabled. Ancillary metadata is not retained.
- BMP with a Windows DIB header of at least 40 bytes, uncompressed 24-bit BGR or
  32-bit BGRX pixels, top-down or bottom-up rows, including row padding. BMP
  alpha bytes are ignored. Compressed, indexed, and bitfield BMPs are rejected.
- Netpbm P1/P2/P3 ASCII and P4/P5/P6 binary PBM/PGM/PPM, including comments,
  CRLF headers, and sample maxima up to 65535. PBM black/white is converted to
  8-bit grayscale; 16-bit samples are reduced to 8-bit. PPM uses RGB565.

JPEG is **not supported** and raises `NotImplementedError`. The existing OpenMV
JPEG decoder has assumptions about EXIF offsets, unchecked marker/table access
within fixed buffers, and ARM DSP helpers; it was not linked into this bounded
file-image implementation. Unknown image formats are rejected explicitly.

File bytes and decoded image storage are limited to 64 MiB each. Dimensions
must be 1 through 8192 on both axes, and products are checked before allocation.
PNG temporary allocations have an additional aggregate 64 MiB cap; the codec
allocators use real MicroPython GC storage without triggering collection or
raising while LodePNG owns temporary pointers. Allocation failures return a
codec status and all temporaries are released before Python raises. These are
limits, not promises that every largest image fits in available board RAM.

## Native API

- `Image(path[, copy_to_fb=False])` loads through VFS stream seek/read/close,
  closes on errors, checks exact reads, and owns the decoded pixel storage.
- `Image(width, height, pixformat=RGB565, *, buffer=None)` creates an owned,
  zero-filled image. `buffer=` requires a writable buffer large enough for the
  pixels and **copies its initial contents**; it is not a zero-copy view.
- `width()`, `height()`, `format()`, `size()`, `get_pixel(x,y[,rgbtuple=True])`,
  `set_pixel(x,y,value)` expose dimensions, storage bytes, and pixels. Grayscale
  values are 0..255. RGB565 pixels accept/return RGB tuples or packed 16-bit
  values; RGB channels are rounded to the RGB565 representation.
- `copy(roi=None, *, x_scale=1, y_scale=1)` returns an independent crop/resize.
  `resize(width,height, *, hint=BILINEAR)` returns an independent resized image.
- `to_grayscale(*, copy=False)` / `grayscale(...)` return a grayscale image.
  The default replaces this object's pixel storage; `copy=True` preserves it.
- `draw_image(source,x=0,y=0, *, roi=None,hint=0,x_scale=1,y_scale=1)` performs
  CPU sampling/conversion. `BILINEAR`, `CENTER`, `SCALE_ASPECT_IGNORE`, and
  `BLACK_BACKGROUND` implement the file-to-tensor preprocessing path. Ignoring
  aspect scales to the destination dimensions; CENTER alone fits the ROI while
  preserving aspect. Default draws at source size. Unknown hints are rejected.
  Self/overlapping draws snapshot source pixels before writing.
- `to_ndarray(dtype, *, buffer=None)` accepts `'f'`, `'b'`, `'B'` or their integer
  character codes. Grayscale shape is `(H,W)`; RGB shape is `(H,W,3)`. Float
  values are 0..255, uint8 values are unchanged, and int8 values subtract 128.
  The returned ulab ndarray **always owns its data**. `buffer=` receives an
  initial conversion copy and must be writable and large enough; subsequent
  array operations do not update that buffer. Copies use bytes, so the supplied
  buffer need not be float-aligned. A caller may safely resize/release it later.

Additional file/CPU APIs (audited against `modules/py_image.c`):

- `clone(...)` aliases the existing independent `copy(...)` operation.
- `to_bytes()` and `bytearray()` return owned snapshots of raw pixel storage:
  one byte per grayscale pixel, or two little-endian bytes per RGB565 pixel.
  Unlike OpenMV's aliased `bytearray()`, changing this snapshot cannot change
  or invalidate image storage. The Image deliberately has no raw buffer view.
- Iteration yields row lists: grayscale integers or packed RGB565 integers,
  matching OpenMV's row iterator. Iterators retain the Image as a GC root.
- `clear()` zeroes the image and returns it. `set_pixel((x,y), color)` is also
  accepted, preserving the existing `set_pixel(x,y,color)` signature.
- `draw_rectangle((x,y,w,h), color=None, thickness=1, fill=False)`,
  `draw_circle((x,y,r), color=None, thickness=1, fill=False)`, and
  `draw_line((x0,y0,x1,y1), color=None, thickness=1)` mutate and return the image.
  `None` means white; colors accept grayscale/packed RGB565 integers or RGB
  tuples. Drawing clips to the image. Rectangular and circular strokes extend
  inward from the specified boundary; line strokes use a centered square brush.
  Raster edges may differ from OpenMV's imlib implementation. Negative sizes
  raise `ValueError`; zero-size rectangles and zero thickness are no-ops.
  Thickness and circle radius are limited to 8192. Signed 32-bit coordinates
  and intermediate arithmetic are checked/bounded; off-image lines clip before
  rasterization, so huge endpoints do not cause huge loops.
- `draw_string((x,y), text, color=None, scale=1, x_spacing=0, y_spacing=0, ...)`
  renders the vendored OpenMV MIT 8x10 font with CPU nearest-neighbor scaling.
  Scale must be finite and in `(0,16]`; spacing is 0..8192. Printable ASCII,
  newline, carriage return, and tab work. Other text raises `NotImplementedError`
  before drawing. `mono_space=False`, rotation, mirror, and flip options also
  raise `NotImplementedError`; default options used by `ml.utils.draw_predictions`
  work. Text backgrounds remain transparent.
- `mean(size)` and `median(size, *, percentile=0.5)` are in-place neighborhood
  filters, as in OpenMV (not whole-image scalar averages). `size` is radius
  0..7, edge samples clamp, RGB565 channels filter independently. A separate
  GC-owned output prevents feedback from modified pixels. Threshold, offset,
  invert, and mask options raise `NotImplementedError` when nondefault.
- `get_hist()` / `get_histogram()` / `histogram()`, `get_stats()` /
  `get_statistics()` / `statistics()`, and `rotation_corr()` explicitly raise
  `NotImplementedError`. OpenMV RGB statistics use LAB channel contracts;
  RGB-channel approximations or perspective rotation placeholders are not used.

All pixel storage is MicroPython GC-owned. Other OpenMV image methods remain
absent and raise normal `AttributeError`; no processing operation returns dummy
results. Existing constructor, pixel access, copy/resize, grayscale, drawing,
and tensor-conversion signatures remain supported.
The format and hint constants are local to this subset; callers should use
`image.GRAYSCALE`, `image.RGB565`, and the exported hint names.

## Build integration and normalization

Include `modules/image_file/image_file.mk` after the port's explicit `SRC_C :=`
assignment and before `OBJ` construction, then append:

```make
include $(MPYNN_TOP)/modules/image_file/image_file.mk
SRC_C += $(IMAGE_FILE_SRC_C)
```

The fragment defines the four project-relative C source paths, module include
directory, VPATH, and the native module source for qstr/module registration.
It expects the existing ulab fragment to supply the ndarray include directory
and four-dimension configuration. The private `imlib.h` is a narrow LodePNG
configuration shim; do not use it as the full OpenMV imlib API.

`ml.Normalization` must explicitly copy the final ndarray back into its scratch
bytearray after applying float normalization, because `to_ndarray(buffer=)`
returns an owned ndarray. The parent integration owns that Python adaptation.
Copy using `array.tobytes()` or another byte-oriented view: a float memoryview's
length is in elements, so a raw `len(memoryview(array))` is not its byte count.

## Provenance and validation

`lodepng.c` and `lodepng.h` are byte-for-byte copies of the original project
files under `lib/imlib`; their original LodePNG license notices are retained.
`image_font.h` vendors the OpenMV MIT `lib/imlib/font.c` glyph data with its
copyright and license retained; only its type/symbol/include are made private.
All other C/header files in this directory are new MIT code. The library source
under `lib` is never modified. `VENDOR.json` records the copied codec hashes.

`test_image_file_native.py` compiles and executes the real codecs/core with
host C, tests valid and invalid PNG/BMP/PNM bytes and pixel/tensor results, and
syntax-checks all four complete C sources for ARM1176 hard float with the real
MicroPython/ulab/board headers and generated qstr data. The host codec harness
uses only allocator stubs. `test_image_file_binding_host.py` executes extracted
real binding functions with bounded MP/VFS stubs to validate owned storage,
file failure cleanup, writable-buffer checks, resizing, and preprocessing.
`test_image_file_board.py` supplies separate SD-card/firmware acceptance and is
skipped by host discovery. Host checks do not prove firmware linking or actual
MicroPython runtime integration; those require a real interpreter/device run.

The additional root `tests/raspberrypi/test_image_api_native.py` compiles and
executes actual drawing/filter/byte-copy/iterator binding functions with strict
host `-Wall -Wextra -Werror`, exercising the pre-existing preprocessing checks
as well. It checks clipped/extreme coordinates, RGB565 guard bytes, real glyph
pixels, unsupported options, row results and owned copies, and runs the same
complete-source ARM1176 hard-float syntax check with real headers and regenerated
qstr data. No new C compilation unit or parent source-list change is required;
`modimage.c` remains the qstr input and must be rescanned/rebuilt for new names.
