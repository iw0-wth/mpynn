# SPDX-License-Identifier: MIT
"""Safety regression tests using temporary inputs and an in-process fake make.

Run with python -B -m unittest discover -s mpynn/tests/raspberrypi \
    -p 'test_build_circle*.py' -v.
No compiler or make subprocess runs here, and no real build output is read.
"""
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import test_build_circle as fixtures

circle = fixtures.circle


class CircleBuildSafetyTests(unittest.TestCase):
    # Reuse helpers, not inheritance: inheriting would run the eight USB tests
    # twice during discovery. All paths belong to the fixture TemporaryDirectory.
    write = fixtures.CircleBuildTests.write
    run_build = fixtures.CircleBuildTests.run_build
    sd_inputs = fixtures.CircleBuildTests.sd_inputs
    usb_inputs = fixtures.CircleBuildTests.usb_inputs

    def setUp(self):
        fixtures.CircleBuildTests.setUp(self)
        self.calls = []
        self.states = []
        self.observed_paths = []
        self.real_put = circle.put
        patch = mock.patch.object(circle, "put", side_effect=self.capture_put)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(circle.subprocess, "run", side_effect=self.fake_make)
        self.make_run = patch.start()
        self.addCleanup(patch.stop)

    def capture_put(self, path, data, build, source):
        if Path(path).name == circle.STATE:
            # Capture state on its way in, rather than read generated output.
            self.states.append(json.loads(data))
        return self.real_put(path, data, build, source)

    def fake_make(self, command, **kwargs):
        directory = Path(command[command.index("-C") + 1])
        target = directory / command[-1]
        self.calls.append({
            "command": list(command), "environment": dict(kwargs["env"]),
            "check": kwargs.get("check"),
            "objects_before": sorted(p.name for p in directory.glob("*.o")),
            "archive_before": target.exists(),
            "observed_before": {p: p.exists() for p in self.observed_paths},
        })
        # Behave like an up-to-date make for unchanged artifacts. Only existence
        # and metadata are inspected; object/archive contents are never read.
        for source in directory.iterdir():
            if source.is_file() and source.suffix in circle.SOURCE_SUFFIXES:
                for suffix in (".o", ".d"):
                    output = source.with_suffix(suffix)
                    if not output.exists():
                        output.write_bytes(b"temporary fake artifact")
        if not target.exists():
            target.write_bytes(b"temporary fake archive")
        return subprocess.CompletedProcess(command, 0)

    def assert_unlocked(self):
        self.assertFalse((self.build / circle.LOCK).exists())

    def test_environment_pollution_is_discarded(self):
        pollution = {
            "MAKEFLAGS": "-e RASPPI=4", "MFLAGS": "-e",
            "MAKEOVERRIDES": "FLOAT_ABI=soft", "MAKEFILES": "evil.mk",
            "CC": "foreign-gcc", "CXX": "foreign-g++", "AR": "foreign-ar",
            "LD": "foreign-ld", "CFLAGS": "-mfloat-abi=soft",
            "CXXFLAGS": "-mcpu=cortex-a72", "CPPFLAGS": "-include evil.h",
            "LDFLAGS": "-L/foreign", "CPATH": "/foreign",
            "C_INCLUDE_PATH": "/foreign", "CPLUS_INCLUDE_PATH": "/foreign",
            "LIBRARY_PATH": "/foreign", "RASPPI": "4", "AARCH": "64",
            "FLOAT_ABI": "soft", "PREFIX": "foreign-", "UNKNOWN_FLAG": "bad",
        }
        self.environ.update(pollution)
        self.environ["SOURCE_DATE_EPOCH"] = "1700000000"
        self.run_build()
        env = self.calls[-1]["environment"]
        self.assertTrue(set(pollution).isdisjoint(env))
        self.assertEqual(set(env), (set(self.environ) & set(
            circle.SYSTEM_ENV + circle.SAFE_BUILD_ENV)) | {"LANG", "LC_ALL"})
        self.assertEqual(env["LANG"], "C")
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["SOURCE_DATE_EPOCH"], "1700000000")

    def test_arm1176_hardfloat_is_fixed_on_make_command_line(self):
        self.environ.update(RASPPI="4", AARCH="64", FLOAT_ABI="soft")
        self.run_build(jobs=3)
        args = self.calls[-1]["command"]
        for fixed in ("RASPPI=1", "AARCH=32", "FLOAT_ABI=hard", "CLANG=0",
                      "STDLIB_SUPPORT=1", "GC_SECTIONS=1", "CHECK_DEPS=1",
                      "KASAN_ENABLED=0", "CIRCLEHOME=..",
                      "ARCHCPU=-mcpu=arm1176jzf-s -marm -mfpu=vfp -mfloat-abi=hard"):
            self.assertIn(fixed, args)
        self.assertIn("PREFIX=arm-none-eabi-", args)
        self.assertIn("-j3", args)
        self.assertTrue(self.calls[-1]["check"])

    def test_upstream_config_files_are_not_inherited(self):
        self.write("Config.mk", "RASPPI=4\nFLOAT_ABI=soft\n")
        self.write("Config2.mk", "AARCH=64\n")
        self.run_build()
        for name in ("Config.mk", "Config2.mk"):
            self.assertFalse((self.build / name).exists())
            self.assertNotIn(name, self.states[-1]["files"])

    def test_stage_config_pollution_is_rejected_before_make(self):
        self.run_build()
        for name in ("Config.mk", "Config2.mk"):
            with self.subTest(name=name):
                config = self.build / name
                config.write_text("FLOAT_ABI=soft\n", encoding="utf-8")
                count = len(self.calls)
                with self.assertRaisesRegex(circle.BuildError, "Unexpected stage configuration"):
                    self.run_build()
                self.assertEqual(len(self.calls), count)
                self.assertTrue(config.exists())
                self.assert_unlocked()
                config.unlink()

    def test_same_size_same_mtime_source_content_invalidates_objects(self):
        self.run_build()
        source = self.source / "lib/core.cpp"
        before = source.stat()
        # Preserve the fixture's platform-specific newline bytes (CRLF on Windows).
        source.write_bytes(source.read_bytes().replace(b"core = 1", b"core = 2"))
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(source.stat().st_size, before.st_size)
        self.assertEqual(source.stat().st_mtime_ns, before.st_mtime_ns)
        previous = self.states[-1]["files"]["lib/core.cpp"]
        self.run_build()
        self.assertNotEqual(self.states[-1]["files"]["lib/core.cpp"], previous)
        self.assertEqual(self.calls[-1]["objects_before"], [])
        self.assertFalse(self.calls[-1]["archive_before"])

    def test_compiler_path_and_version_each_invalidate_signature(self):
        self.run_build()
        for key, value in (("path", "/other/arm-gcc"), ("version", "fake v2")):
            with self.subTest(identity_field=key):
                previous = self.states[-1]["signature"]
                self.tools["gcc"][key] = value
                self.run_build()
                self.assertNotEqual(self.states[-1]["signature"], previous)
                self.assertEqual(self.calls[-1]["objects_before"], [])
                self.assertFalse(self.calls[-1]["archive_before"])

    def test_source_and_stage_overlap_in_both_directions_is_rejected(self):
        for build in (self.source, self.source / "stage", self.root):
            with self.subTest(build=build):
                with self.assertRaisesRegex(circle.BuildError, "must not overlap"):
                    self.run_build(build=build)
        self.make_run.assert_not_called()
        self.assertFalse((self.source / circle.OWNER).exists())
        self.assertFalse((self.root / circle.OWNER).exists())

    def test_nonempty_unowned_stage_is_preserved_and_rejected(self):
        self.build.mkdir(parents=True)
        sentinel = self.build / "user.txt"
        sentinel.write_text("not owned", encoding="utf-8")
        before = sentinel.stat()
        with self.assertRaisesRegex(circle.BuildError, "Nonempty build directory"):
            self.run_build()
        self.make_run.assert_not_called()
        self.assertEqual(sentinel.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(sentinel.stat().st_size, before.st_size)
        self.assertFalse((self.build / circle.OWNER).exists())

    def test_mismatched_owner_identity_is_rejected(self):
        circle.stage_roots(self.source, self.build)
        marker = self.build / circle.OWNER
        identity = {"owner": "mpynn.build_circle", "schema": circle.SCHEMA,
                    "source": str(self.root / "another-source"), "build": str(self.build)}
        marker.write_bytes(circle.encoded(identity))
        before = marker.stat()
        with self.assertRaisesRegex(circle.BuildError, "Nonempty build directory"):
            self.run_build()
        self.make_run.assert_not_called()
        self.assertEqual(marker.stat().st_mtime_ns, before.st_mtime_ns)

    def test_build_symlink_or_junction_components_are_rejected(self):
        # Mock the OS link predicates so this also runs without Windows symlink
        # privileges and on Python versions without Path.is_junction.
        for method in ("is_symlink", "is_junction"):
            for suspect in (self.build, self.build.parent):
                with self.subTest(method=method, suspect=suspect):
                    with mock.patch.object(Path, method, create=True,
                                           new=lambda path, target=suspect: path == target):
                        with self.assertRaisesRegex(circle.BuildError, "symlinks/junctions"):
                            self.run_build()
        self.make_run.assert_not_called()
        self.assertFalse(self.build.exists())

    def test_staged_artifact_symlink_or_junction_is_rejected_before_make(self):
        self.run_build()
        count = len(self.calls)
        for method in ("is_symlink", "is_junction"):
            for suspect in (self.build / "lib", self.build / "lib/core.o",
                            self.build / "lib/libcircle.a"):
                with self.subTest(method=method, suspect=suspect):
                    with mock.patch.object(Path, method, create=True,
                                           new=lambda path, target=suspect: path == target):
                        with self.assertRaisesRegex(circle.BuildError, "symlink/junction"):
                            self.run_build()
                    self.assertEqual(len(self.calls), count)
                    self.assert_unlocked()

    def test_source_symlink_or_junction_is_rejected(self):
        for method in ("is_symlink", "is_junction"):
            for suspect in (self.source / "include", self.source / "lib/core.cpp"):
                with self.subTest(method=method, suspect=suspect):
                    with mock.patch.object(Path, method, create=True,
                                           new=lambda path, target=suspect: path == target):
                        with self.assertRaisesRegex(circle.BuildError, "symlink/junction"):
                            self.run_build()
                    self.assert_unlocked()
        self.make_run.assert_not_called()

    def test_stale_lock_is_not_removed_or_overwritten(self):
        circle.stage_roots(self.source, self.build)
        lock = self.build / circle.LOCK
        lock.write_text("999999999 stale lock", encoding="ascii")
        before = lock.stat()
        with self.assertRaisesRegex(circle.BuildError, "inspect stale lock manually"):
            self.run_build()
        self.make_run.assert_not_called()
        self.assertEqual(lock.stat().st_size, before.st_size)
        self.assertEqual(lock.stat().st_mtime_ns, before.st_mtime_ns)

    def test_modified_obsolete_staged_source_is_not_deleted(self):
        source = self.write("include/circle/obsolete.h", "original\n")
        self.run_build()
        source.unlink()
        staged = self.build / "include/circle/obsolete.h"
        staged.write_text("locally modified content\n", encoding="utf-8")
        before = staged.stat()
        count = len(self.calls)
        with self.assertRaisesRegex(circle.BuildError, "modified staged source"):
            self.run_build()
        self.assertEqual(staged.stat().st_size, before.st_size)
        self.assertEqual(staged.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(len(self.calls), count)
        self.assertTrue((self.build / "lib/core.o").exists())
        self.assert_unlocked()

    def test_unchanged_build_preserves_staged_mtimes_and_objects(self):
        self.run_build()
        names = ("lib/core.cpp", "include/circle/core.h", "Rules.mk", "lib/Makefile",
                 circle.OWNER, circle.STATE, "lib/core.o", "lib/core.d", "lib/libcircle.a")
        stamp = 1_600_000_000_123_456_700
        for name in names:
            os.utime(self.build / name, ns=(stamp, stamp))
        before = {name: (self.build / name).stat().st_mtime_ns for name in names}
        previous = self.states[-1]["signature"]
        self.run_build()
        self.assertEqual(self.states[-1]["signature"], previous)
        self.assertEqual(self.calls[-1]["objects_before"], ["core.o"])
        self.assertTrue(self.calls[-1]["archive_before"])
        self.assertEqual({name: (self.build / name).stat().st_mtime_ns for name in names}, before)

    def test_failed_make_propagates_return_code_and_releases_lock(self):
        failure = subprocess.CalledProcessError(23, ["fake-make"])
        with mock.patch.object(circle.subprocess, "run", side_effect=failure):
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                self.run_build()
        self.assertIs(caught.exception, failure)
        self.assertEqual(caught.exception.returncode, 23)
        self.assert_unlocked()
        self.run_build()
        self.assertEqual(len(self.calls), 1)

    def test_main_reports_make_failure_code_without_swallowing_it(self):
        failure = subprocess.CalledProcessError(17, ["fake-make"])
        with mock.patch.object(circle, "build_circle", side_effect=failure), \
                mock.patch("builtins.print") as report:
            self.assertEqual(circle.main([]), 17)
        self.assertTrue(any("build_circle:" in str(call) for call in report.call_args_list))

    def test_missing_compiler_fails_without_make_and_releases_lock(self):
        self.tool_patch.stop()
        with mock.patch.object(circle.shutil, "which", return_value=None) as which:
            with self.assertRaisesRegex(circle.BuildError, "Toolchain executable not found"):
                self.run_build()
        self.assertEqual(which.call_args.args[0], "arm-none-eabi-gcc")
        self.make_run.assert_not_called()
        self.assert_unlocked()

    def test_shell_unsafe_prefixes_fail_before_compiler_or_make(self):
        prefixes = ["arm none-", "arm\t-", "arm\n-", 'arm"-', "arm'-", "arm`-",
                    "arm$-", "arm;-", "arm&-", "arm|-", "arm<-", "arm>-",
                    "arm(-", "arm)-", "arm{-", "arm}-", "arm*-", "arm?-", "arm!-"]
        with mock.patch.object(circle, "compiler_identity") as compiler:
            for prefix in prefixes:
                with self.subTest(prefix=prefix):
                    with self.assertRaisesRegex(circle.BuildError, "shell-safe toolchain prefix"):
                        self.run_build(prefix=prefix)
                    self.assert_unlocked()
            compiler.assert_not_called()
        self.make_run.assert_not_called()

    def test_nested_sd_usb_cleanup_removes_only_owned_artifacts(self):
        self.sd_inputs()
        self.usb_inputs()
        self.run_build(with_sd=True, with_usb=True)
        owned = [self.build / name for name in (
            "lib/core.o", "lib/core.d", "lib/libcircle.a",
            "lib/fs/partition.o", "lib/fs/partition.d", "lib/fs/libfs.a",
            "addon/SDCard/emmc.o", "addon/SDCard/emmc.d", "addon/SDCard/libsdcard.a",
            "lib/usb/lan7800.o", "lib/usb/lan7800.d", "lib/usb/libusb.a")]
        unrelated = [self.build / name for name in (
            "lib/user.o", "lib/user.a", "lib/fs/user.o", "lib/fs/nested/partition.o",
            "addon/SDCard/user.d", "addon/SDCard/nested/emmc.o",
            "lib/usb/user.o", "lib/usb/nested/lan7800.o", "other/libusb.a")]
        unrelated += [self.source / "lib/core.o", self.root / "outside.o"]
        for path in unrelated:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not owned")
        before = {path: path.stat().st_mtime_ns for path in unrelated}
        self.observed_paths = owned + unrelated
        self.write("include/circle/core.h", "#define CORE 2\n")
        count = len(self.calls)
        self.run_build(with_sd=True, with_usb=True)
        observed = self.calls[count]["observed_before"]
        for path in owned:
            self.assertFalse(observed[path], str(path))
        for path in unrelated:
            self.assertTrue(observed[path], str(path))
            self.assertEqual(path.stat().st_mtime_ns, before[path])

    def test_disabling_sd_and_usb_removes_previous_nested_owned_artifacts(self):
        self.sd_inputs()
        self.usb_inputs()
        self.run_build(with_sd=True, with_usb=True)
        keep = self.build / "addon/SDCard/local.o"
        keep.write_bytes(b"user artifact")
        self.run_build(with_sd=False, with_usb=False)
        for name in ("lib/fs/partition.cpp", "lib/fs/partition.o", "lib/fs/libfs.a",
                     "addon/SDCard/emmc.cpp", "addon/SDCard/emmc.d", "addon/SDCard/libsdcard.a",
                     "lib/usb/lan7800.cpp", "lib/usb/lan7800.o", "lib/usb/libusb.a"):
            self.assertFalse((self.build / name).exists(), name)
        self.assertTrue(keep.exists())
        self.assertEqual(self.calls[-1]["command"][-1], "libcircle.a")

    def test_source_date_epoch_participates_in_signature(self):
        self.environ["SOURCE_DATE_EPOCH"] = "1700000000"
        self.run_build()
        before = self.states[-1]["signature"]
        self.environ["SOURCE_DATE_EPOCH"] = "1700000001"
        self.run_build()
        self.assertNotEqual(self.states[-1]["signature"], before)
        self.assertEqual(self.calls[-1]["environment"]["SOURCE_DATE_EPOCH"], "1700000001")
        self.assertEqual(self.calls[-1]["objects_before"], [])
        self.assertFalse(self.calls[-1]["archive_before"])


if __name__ == "__main__":
    unittest.main()
