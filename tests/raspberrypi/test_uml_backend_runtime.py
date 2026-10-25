import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


MPYNN = Path(__file__).resolve().parents[2]
ROOT = MPYNN.parent
PORT = MPYNN / "ports" / "raspberrypi"
HOST_OUT = MPYNN / "build" / "host-tests" / "uml_backend"
ARCHIVE = HOST_OUT / "genrel" / "linux_x86_64_release_gcc" / "lib" / "libtensorflow-microlite.a"
MODEL = ROOT / "tflite-micro" / "tensorflow" / "lite" / "micro" / "examples" / "hello_world" / "models" / "hello_world_float.tflite"


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_uml_backend_runtime_regression():
    gxx = Path(os.environ.get("UML_BACKEND_GXX", r"E:\msys64\ucrt64\bin\g++.exe"))
    if not gxx.is_file():
        pytest.skip(f"host compiler not found: {gxx}")
    if not ARCHIVE.is_file():
        pytest.skip(f"host TFLM archive not found: {ARCHIVE}")
    if not MODEL.is_file():
        pytest.fail(f"test model not found: {MODEL}")

    HOST_OUT.mkdir(parents=True, exist_ok=True)
    include = ROOT / "tflite-micro"
    downloads = include / "tensorflow" / "lite" / "micro" / "tools" / "make" / "downloads"
    obj = HOST_OUT / "uml_backend_runtime.o"
    exe = HOST_OUT / "uml_backend_runtime_test.exe"
    common = [
        "-std=c++11",
        "-fno-exceptions",
        "-fno-rtti",
        "-DNDEBUG",
        "-DTF_LITE_STATIC_MEMORY",
        "-DTF_LITE_DISABLE_X86_NEON",
        "-DKERNELS_OPTIMIZED_FOR_SPEED",
        "-DTF_LITE_STRIP_ERROR_STRINGS",
        f"-I{PORT}",
        f"-I{include}",
        f"-I{downloads / 'flatbuffers' / 'include'}",
        f"-I{downloads / 'gemmlowp'}",
        f"-I{downloads / 'ruy'}",
        f"-I{downloads / 'kissfft'}",
    ]
    env = os.environ.copy()
    env["PATH"] = r"E:\msys64\ucrt64\bin;" + env.get("PATH", "")
    subprocess.run(
        [str(gxx), *common, "-c", str(PORT / "uml_backend.cpp"), "-o", str(obj)],
        check=True,
        cwd=ROOT,
        env=env,
    )
    subprocess.run(
        [
            str(gxx),
            "-std=c++11",
            f"-I{PORT}",
            f"-I{include}",
            f"-I{downloads / 'flatbuffers' / 'include'}",
            f"-I{downloads / 'gemmlowp'}",
            f"-I{downloads / 'ruy'}",
            f"-I{downloads / 'kissfft'}",
            str(Path(__file__).with_name("uml_backend_runtime_test.cpp")),
            str(obj),
            str(ARCHIVE),
            "-lm",
            "-o",
            str(exe),
        ],
        check=True,
        cwd=ROOT,
        env=env,
    )
    run = subprocess.run(
        [str(exe), str(MODEL)],
        check=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert "uml_backend runtime regression: PASS" in run.stdout
    report = {
        "compiler": str(gxx),
        "compiler_flags": common,
        "model": str(MODEL),
        "model_sha256": _sha256(MODEL),
        "host_archive": str(ARCHIVE),
        "host_archive_sha256": _sha256(ARCHIVE),
        "verification": "native Windows host execution; TFLM x86_64 host archive; no Raspberry Pi runtime",
        "stdout": run.stdout.strip(),
    }
    (HOST_OUT / "uml_backend_runtime_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
