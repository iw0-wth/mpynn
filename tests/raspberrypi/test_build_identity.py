# SPDX-License-Identifier: MIT
"""Host-only build-identity contract tests; all inputs and outputs are temporary.

Run with python -B -m unittest discover -s mpynn/tests/raspberrypi \
    -p 'test_build_identity.py' -v. No firmware, compiler, or make is invoked.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


IDENTITY_SCRIPT = (Path(__file__).resolve().parents[2]
                   / "ports/raspberrypi/build_identity.py")
spec = importlib.util.spec_from_file_location("raspberrypi_build_identity", IDENTITY_SCRIPT)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class BuildIdentityTests(unittest.TestCase):
    SOURCES = {
        "port/main.c": b"int main(void) { return 0; }\n",
        "port/include/api.h": b"#define API_VERSION 1\n",
        "port/nested/device.cpp": b"int device = 1;\n",
        "port/boot/start.S": b".global _start\n",
        "port/boot/helper.s": b"nop\n",
        "port/config.mk": b"CFLAGS += -O2\n",
        "port/tool.py": b"VALUE = 1\n",
        "port/Makefile": b"all:\n\t@true\n",
        "port/nested/Makefile": b"include ../config.mk\n",
        "board/mpconfigboard.h": b"#define BOARD_NAME \"fixture\"\n",
        "board/mpconfigboard.mk": b"BOARD_FLAGS = -DBOARD\n",
        "board/nested/pins.c": b"int pins[] = {1, 2};\n",
        "board/nested/Makefile": b"all:\n\t@true\n",
    }
    EXCLUDED = {
        "port/README.md": b"documentation\n",
        "port/docs/design.txt": b"design notes\n",
        "port/image.png": b"not a real image",
        "port/main.o": b"object artifact",
        "port/firmware.bin": b"binary artifact",
        "port/tool.pyc": b"bytecode",
        "port/__pycache__/cached.py": b"not source\n",
        "port/nested/__pycache__/cached.c": b"not source either\n",
        "board/README.rst": b"board documentation\n",
        "board/__pycache__/Makefile": b"not configuration\n",
    }

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.port = self.root / "port"
        self.board = self.root / "board"
        self.flags = ["-O2", "-DTEST=1"]
        # Deliberately create files in reverse order, not lexical traversal order.
        for name, data in reversed(list({**self.SOURCES, **self.EXCLUDED}.items())):
            self.write(name, data)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def collect(self, flags=None):
        return identity.collect_identity(
            self.port, self.board, self.flags if flags is None else flags)

    def run_cli(self, header, report, flags=None):
        command = [sys.executable, "-B", str(IDENTITY_SCRIPT),
                   "--port", str(self.port), "--board", str(self.board),
                   "--header", str(header), "--report", str(report)]
        # Equals form also tests values beginning with '-', accepted by argparse.
        for flag in self.flags if flags is None else flags:
            command.append("--flag=" + flag)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def snapshot_inputs(self):
        return {path.relative_to(self.root).as_posix():
                (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)
                for tree in (self.port, self.board)
                for path in tree.rglob("*") if path.is_file()}

    def test_schema_scope_sorted_relative_paths_and_content_hashes(self):
        report = self.collect()
        self.assertEqual(report["schema"], 1)
        self.assertEqual(report["scope"], "port-and-board-source")
        self.assertRegex(report["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(report["flags"], self.flags)
        self.assertEqual(report["files"], [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(self.SOURCES.items())
        ])
        for item in report["files"]:
            self.assertFalse(Path(item["path"]).is_absolute())
            self.assertNotIn("\\", item["path"])

    def test_repeated_collection_is_deterministic_and_does_not_mutate_flags(self):
        before = list(self.flags)
        first = self.collect()
        self.assertEqual(first, self.collect())
        self.assertEqual(self.flags, before)

    def test_creation_order_and_root_relocation_do_not_change_identity(self):
        relocated = self.root / "different-location"
        for name, data in sorted({**self.SOURCES, **self.EXCLUDED}.items()):
            path = relocated / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.assertEqual(self.collect(), identity.collect_identity(
            relocated / "port", relocated / "board", list(self.flags)))

    def test_mtimes_do_not_change_identity(self):
        before = self.collect()
        for tree in (self.port, self.board):
            for path in tree.rglob("*"):
                if path.is_file():
                    os.utime(path, ns=(1_500_000_000_000_000_000,
                                       1_500_000_123_000_000_000))
        self.assertEqual(self.collect(), before)

    def test_documents_artifacts_and_pycache_do_not_change_identity(self):
        before = self.collect()
        for name in self.EXCLUDED:
            self.write(name, b"changed excluded content\n")
        self.write("port/new-doc.md", b"new documentation\n")
        self.write("board/nested/__pycache__/new.h", b"ignored header\n")
        self.assertEqual(self.collect(), before)

    def test_each_source_and_configuration_kind_changes_identity(self):
        before = self.collect()
        for name, data in self.SOURCES.items():
            with self.subTest(path=name):
                path = self.root / name
                metadata = path.stat()
                # Keep size and mtime fixed: content, not metadata, is the input.
                replacement = bytes([data[0] ^ 1]) + data[1:]
                path.write_bytes(replacement)
                os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                changed = self.collect()
                self.assertNotEqual(changed["sha256"], before["sha256"])
                changed_files = {entry["path"]: entry["sha256"]
                                 for entry in changed["files"]}
                self.assertEqual(changed_files[name], hashlib.sha256(replacement).hexdigest())
                path.write_bytes(data)
                os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        self.assertEqual(self.collect(), before)

    def test_adding_removing_and_renaming_source_changes_identity(self):
        before = self.collect()
        extra = self.write("board/extra.c", b"int extra;\n")
        self.assertNotEqual(self.collect()["sha256"], before["sha256"])
        extra.unlink()
        self.assertEqual(self.collect(), before)
        source = self.port / "main.c"
        renamed = self.port / "renamed.c"
        source.rename(renamed)
        self.assertNotEqual(self.collect()["sha256"], before["sha256"])
        renamed.unlink()
        self.assertNotEqual(self.collect()["sha256"], before["sha256"])

    def test_flags_change_identity_and_empty_flags_are_supported(self):
        before = self.collect()
        for flags in ([], ["-O3", "-DTEST=1"], self.flags + ["-DEXTRA=1"]):
            with self.subTest(flags=flags):
                changed = self.collect(flags)
                self.assertEqual(changed["flags"], flags)
                self.assertEqual(changed["files"], before["files"])
                self.assertNotEqual(changed["sha256"], before["sha256"])

    def test_readonly_inputs_are_unchanged_by_collection_and_cli(self):
        paths = [path for tree in (self.port, self.board)
                 for path in tree.rglob("*") if path.is_file()]
        modes = {path: path.stat().st_mode for path in paths}
        try:
            for path in paths:
                path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            before = self.snapshot_inputs()
            report = self.collect()
            output = self.root / "output"
            output.mkdir()
            self.run_cli(output / "identity.h", output / "identity.json")
            self.assertEqual(self.collect(), report)
            self.assertEqual(self.snapshot_inputs(), before)
        finally:
            # Windows cannot remove read-only files during temporary cleanup.
            for path, mode in modes.items():
                path.chmod(mode)

    def test_cli_header_report_and_repeat_preserve_output_mtimes(self):
        output = self.root / "output"
        output.mkdir()
        header, report = output / "identity.h", output / "identity.json"
        self.run_cli(header, report)
        expected = self.collect()
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), expected)
        self.assertIn('#define MPYNN_PORT_BUILD_ID "' + expected["sha256"] + '"',
                      header.read_text(encoding="utf-8"))
        for path in (header, report):
            os.utime(path, ns=(1_500_000_000_000_000_000, 1_500_000_000_000_000_000))
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in (header, report)}
        self.run_cli(header, report)
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns)
                          for path in (header, report)}, before)

    def test_cli_parent_relative_output_is_not_inside_input(self):
        output=self.root/'output'
        self.run_cli(self.port/'..'/'output'/'identity.h', self.port/'..'/'output'/'identity.json')
        self.assertEqual(json.loads((output/'identity.json').read_text()),self.collect())

    def test_cli_changed_flags_refresh_both_outputs(self):
        output = self.root / "output"
        output.mkdir()
        header, report = output / "identity.h", output / "identity.json"
        self.run_cli(header, report)
        old_header = header.read_bytes()
        flags = ["-O3", "-DTEST=2", "-DTEST=2"]
        self.run_cli(header, report, flags)
        expected = self.collect(flags)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), expected)
        self.assertNotEqual(header.read_bytes(), old_header)
        self.assertIn(expected["sha256"], header.read_text(encoding="utf-8"))

    def test_mock_symlink_file_directory_and_root_are_rejected(self):
        original = Path.is_symlink
        for suspect in (self.port / "main.c", self.port / "nested", self.port, self.board):
            with self.subTest(path=suspect):
                def is_symlink(path):
                    return path == suspect or original(path)
                with mock.patch.object(Path, "is_symlink", autospec=True,
                                       side_effect=is_symlink):
                    with self.assertRaises((ValueError, RuntimeError, OSError)):
                        self.collect()

    def test_real_symlink_is_rejected_when_creation_is_permitted(self):
        link = self.port / "linked.c"
        try:
            link.symlink_to(self.board / "nested/pins.c")
        except (OSError, NotImplementedError) as error:
            self.skipTest("Symlink creation unavailable; mock rejection covered: " + str(error))
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.collect()

    @unittest.skipUnless(os.name == "nt" and hasattr(Path, "is_junction"),
                         "Windows Path.is_junction unavailable")
    def test_mock_windows_junction_directory_and_root_are_rejected(self):
        original = Path.is_junction
        for suspect in (self.port / "nested", self.port, self.board):
            with self.subTest(path=suspect):
                def is_junction(path):
                    return path == suspect or original(path)
                with mock.patch.object(Path, "is_junction", autospec=True,
                                       side_effect=is_junction):
                    with self.assertRaises((ValueError, RuntimeError, OSError)):
                        self.collect()


if __name__ == "__main__":
    unittest.main()
