# Windows model validation

The formal Windows runtime is `build/windows-ml/mpynn-ml.exe` and uses a local
256 MiB GC heap for host model validation. It uses the fixed
x86_64 archive `lib/tflm/libtflm/lib/libtflm-windows-x86_64-reference.a`. The host
GC heap is 256 MiB for model validation; this is separate from Pi1B's measured
Circle heap policy.

## Verified models

| Model | SHA-256 | Size | Input | Output | Result |
|---|---|---:|---|---|---|
| `D:/openmv_aicore/ml_text_cls/text_cls_tflm.tflite` | `AECD63AFECD8C318691254A7C4E6E591F44C817E4254379E29DB1046B15B38E5` | 643304 | `(1,50)` float32 | `(1,11)` float32 | example ran: health_medicine 0.8506, engineering 0.9330, career_advice 1.1404 |
| `mpynn/lib/models/yolo_lc_192.tflite` | `49AB539E32A4337A6D9FD379EE348C64C9724806A4B71296DD7DF76941192403` | 339448 | `(1,192,192,3)` uint8 | `(1,12,12,30)` float32 | zero-input native inference passed |
| `mpynn/lib/models/yolov8n_192.tflite` | `039B7A3C84F8AD687ED66749F8214576CF2DB8F645FAB163E3FAAC79282C54D1` | 3228400 | `(1,192,192,3)` uint8 | `(1,5,756)` float32 | zero-input native inference passed |

Run the model-zoo smoke:

```powershell
D:\anaconda3\python.exe -m pytest -q mpynn/tests/raspberrypi/test_model_zoo_runtime.py -s
```

Current result: `1 passed`.

## Text model correction

The original `text_cls_f32.tflite` has an internal int32 `SELECT_V2`. The current
TFLM reference `SELECT_V2` kernel supports float32/int8/int16 selected values, not
int32, so the original file loads and exposes metadata but fails at Invoke.

The user-provided corrected `text_cls_tflm.tflite` removes that incompatibility and
is the model used above. It is not a firmware patch or a change to the read-only
TFLM library.

The original `mpy_infer_example.py` is runnable with the corrected model by passing
`text_cls_tflm.tflite` to `load_model()` or by renaming the selected deployment
file on the SD card. The model's float32 input is appropriate for ulab; no int32
ulab array is required.

## py39/CUDA status

`D:/anaconda3/envs/py39/python.exe` is available and reports Python 3.9.25, but its
current environment has no `tensorflow` and no `tflite_runtime` package. Therefore
no new training or TensorFlow conversion is claimed from that environment. Existing
models and the user-corrected text model were prioritized as requested. CPU training
can be added later after installing a compatible TensorFlow package; CUDA 11.4 is
not required for the reference TFLM runtime tests.
