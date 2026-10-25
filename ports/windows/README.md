# mpynn Windows ML validation port

This is the formal host-validation port for mpynn's native ML stack. It uses the
read-only upstream MicroPython Windows port at `lib/micropython/ports/windows`
without changing it or using Raspberry Pi/Circle runtime code.

The port links the fixed x86_64 reference TFLM archive:

```text
lib/tflm/libtflm/lib/libtflm-windows-x86_64-reference.a
```

The archive is reference/portable TFLM only: no CMSIS-NN, CMSIS-DSP, Ethos-U, NPU,
or hardware acceleration. It is not the ARMv6 Pi1B archive.

## Build from PowerShell

```powershell
$script = "cd /d/openmv_aicore/mpynn/lib/micropython/ports/windows && export PATH=/e/msys64/ucrt64/bin:/e/msys64/usr/bin:`$PATH && make BUILD=../../../../build/windows-ml VARIANT_DIR=../../../../ports/windows/variant FROZEN_MANIFEST= PROG=mpynn-ml.exe USER_C_MODULES=../../../../ports/windows/user_modules PYTHON=/d/anaconda3/python.exe"
& 'E:\msys64\usr\bin\bash.exe' -lc $script
```

`PROG=mpynn-ml.exe` is intentional because the upstream Windows port's strip
rule uses the program name verbatim. The resulting executable is a real MicroPython Windows interpreter with native
`uml`, `ulab`, `image`, and `audio`. The verified current executable is:

```text
build/windows-ml/mpynn-ml.exe
```

Size: 1,352,704 bytes.
SHA-256: `6E8E50DAFB0DC6AEDF582B02D59A543BCF22A426D728A2943DCF97CE3A71877B`.
The variant uses a 256 MiB GC heap for host model validation.
The fixed archive is 2,168,122 bytes and is selected by
`ports/windows/user_modules/micropython.mk`, so this build no longer depends on
the temporary `build/host-tests` archive path.

Run the runtime test with `MPYNN_ML_RUNTIME` pointing at the resulting executable:

```powershell
$env:MPYNN_ML_RUNTIME = 'D:\openmv_aicore\mpynn\build\windows-ml\mpynn-ml.exe'
D:\anaconda3\python.exe -m pytest -q mpynn/tests/raspberrypi/test_ml_native_runtime.py -s
```

The verified result is `1 passed`. This validates the host ABI and ML behavior; it
is not Pi hardware evidence.

## Model zoo smoke

The repository-level model smoke is:

```powershell
D:\anaconda3\python.exe -m pytest -q mpynn/tests/raspberrypi/test_model_zoo_runtime.py -s
```

It runs the user-corrected `D:/openmv_aicore/ml_text_cls/text_cls_tflm.tflite`,
`lib/models/yolo_lc_192.tflite`, and `lib/models/yolov8n_192.tflite` through the
same native Windows runtime. The current result is `1 passed`:

- text FP32 input `(1,50)` -> FP32 output `(1,11)`;
- YOLO-LC uint8 input `(1,192,192,3)` -> FP32 `(1,12,12,30)`;
- YOLOv8n uint8 input `(1,192,192,3)` -> FP32 `(1,5,756)`.

The Windows host variant uses a 256 MiB GC heap for large model validation. The
Pi1B port uses measured Circle low-memory heap with a 32 MiB Circle reserve; it
does not use the Windows heap setting.
