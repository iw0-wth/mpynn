from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "ports" / "raspberrypi"
HEADER = PORT / "uml_backend.h"
SOURCE = PORT / "uml_backend.cpp"


def test_uml_backend_is_pure_c_abi_and_has_opaque_state_contract():
    header = HEADER.read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")

    assert 'extern "C"' in header
    for name in (
        "uml_backend_state_size",
        "uml_backend_state_align",
        "uml_backend_create",
        "uml_backend_destroy",
        "uml_backend_input_count",
        "uml_backend_output_count",
        "uml_backend_tensor_info",
        "uml_backend_invoke",
    ):
        assert name in header
    for field in (
        "void *data",
        "size_t bytes",
        "unsigned ndim",
        "int32_t shape[4]",
        "char dtype",
        "float scale",
        "int32_t zero_point",
    ):
        assert field in header

    forbidden = ("py/", "micropython", "circle/", '"circle', "MP_", "mp_")
    assert not any(token in source.lower() for token in forbidden)
    assert "MicroMutableOpResolver<128>" in source
    assert "AddEthosU" not in source
    assert "flatbuffers::Verifier" in source
    assert "VerifyModelBuffer" in source
    assert "TFLITE_SCHEMA_VERSION" in source
    assert "kArenaAlignment = 16" in source


def test_reference_archive_is_present():
    archive = (
        ROOT
        / "lib"
        / "tflm"
        / "libtflm"
        / "lib"
        / "libtflm-rpi1b-armv6-reference.a"
    )
    assert archive.is_file()
    assert archive.stat().st_size > 100000
