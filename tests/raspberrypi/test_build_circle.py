# SPDX-License-Identifier: MIT
"""Run with python -B -m unittest discover -s mpynn/tests/raspberrypi -p test_build_circle.py.

All builds use temporary fixtures and a Python fake make; no ARM compiler runs.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[2] / "ports/raspberrypi/build_circle.py"
SPEC = importlib.util.spec_from_file_location("build_circle", SCRIPT)
circle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(circle)

FAKE_MAKE = '''import json, os, pathlib, sys
args = sys.argv[1:]
root = pathlib.Path(args[args.index('-C') + 1])
target = args[-1]
home = next(arg.split('=', 1)[1] for arg in args if arg.startswith('CIRCLEHOME='))
stage = (root / home).resolve()
assert (stage / '.build-circle-owner.json').is_file()
assert (stage / 'include/circle/core.h').is_file()
assert (stage / 'Rules.mk').is_file()
record = {'args': args, 'environment': dict(os.environ),
          'directory': root.relative_to(stage).as_posix(),
          'objects_before': sorted(p.name for p in root.glob('*.o')),
          'archive_before': (root / target).exists()}
(stage / 'make-record.json').write_text(json.dumps(record), encoding='utf-8')
log = stage / 'make-records.json'
records = json.loads(log.read_text(encoding='utf-8')) if log.exists() else []
log.write_text(json.dumps(records + [record]), encoding='utf-8')
for source in root.iterdir():
    if source.is_file() and source.suffix in {'.c', '.cpp', '.S', '.s'}:
        source.with_suffix('.o').write_bytes(b'fake object')
        source.with_suffix('.d').write_text(source.stem + '.o: ' + source.name + '\\n',
                                           encoding='utf-8')
(root / target).write_bytes(b'fake archive' if target == 'libcircle.a'
                            else ('fake ' + target).encode('ascii'))
'''


class CircleBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.build = self.root / "out/circle"
        self.write("include/circle/core.h", "#define CORE 1\n")
        self.write("lib/Makefile", "all: libcircle.a\n")
        self.write("lib/core.cpp", "int core = 1;\n")
        self.write("Rules.mk", "RASPPI ?= 1\n")
        self.make = self.root / "fake make.py"
        self.make.write_text(FAKE_MAKE, encoding="utf-8")
        self.tools = {name: {"path": "/tools/arm-" + name, "version": "fake v1"}
                      for name in ("gcc", "g++", "ar", "ld")}
        self.tool_patch = mock.patch.object(circle, "compiler_identity", return_value=self.tools)
        self.tool_patch.start()
        self.addCleanup(self.tool_patch.stop)
        self.environ = dict(os.environ)

    def write(self, name, text):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_build(self, **kwargs):
        options = dict(source=self.source, build=self.build, make=str(self.make),
                       prefix="arm-none-eabi-", environ=self.environ)
        options.update(kwargs)
        return circle.build_circle(**options)

    def records(self):
        return json.loads((self.build / "make-records.json").read_text(encoding="utf-8"))

    def usb_inputs(self):
        self.write("lib/input/Makefile", "CIRCLEHOME = ../..\nOBJS = keyboardbehaviour.o\n"
                   "all: libinput.a\ninclude $(CIRCLEHOME)/Rules.mk\n")
        self.write("lib/input/keyboardbehaviour.cpp", "// fake input source\n")
        self.write("lib/usb/Makefile", "CIRCLEHOME = ../..\nOBJS = lan7800.o smsc951x.o\n"
                   "all: libusb.a\ninclude $(CIRCLEHOME)/Rules.mk\n")
        self.write("lib/usb/lan7800.cpp", "// fake usb source\n")
        self.write("lib/usb/smsc951x.cpp", "// fake usb source\n")
        self.write("lib/usb/usbdevice.h", "// fake usb header\n")

    def net_inputs(self):
        self.write("lib/sched/Makefile", "CIRCLEHOME = ../..\nOBJS = scheduler.o\n"
                   "all: libsched.a\ninclude $(CIRCLEHOME)/Rules.mk\n")
        self.write("lib/sched/scheduler.cpp", "// fake scheduler source\n")
        self.write("lib/sched/scheduler.h", "// fake scheduler header\n")
        self.write("lib/net/Makefile", "CIRCLEHOME = ../..\nOBJS = netsubsystem.o\n"
                   "all: libnet.a\ninclude $(CIRCLEHOME)/Rules.mk\n")
        self.write("lib/net/netsubsystem.cpp", "// fake network source\n")
        self.write("lib/net/netconfig.h", "// fake network header\n")

    def sd_inputs(self):
        self.write("lib/fs/Makefile", "CIRCLEHOME = ../..\nOBJS = partition.o partitionmanager.o\n"
                   "libfs.a: $(OBJS)\ninclude $(CIRCLEHOME)/Rules.mk\n")
        self.write("addon/SDCard/Makefile", "CIRCLEHOME = ../..\n"
                    "OBJS = emmc.o mmchost.o sdhost.o\nall: libsdcard.a\n"
                    "include $(CIRCLEHOME)/Rules.mk\nlibsdcard.a: $(OBJS)\n")
        for name in ("lib/fs/partition.cpp", "lib/fs/partitionmanager.cpp",
                     "addon/SDCard/emmc.cpp", "addon/SDCard/mmchost.cpp",
                     "addon/SDCard/sdhost.cpp"):
            self.write(name, "// fake source\n")
        for name in ("emmc.h", "mmchost.h", "sdhost.h", "mmc.h", "mmcerror.h"):
            self.write("addon/SDCard/" + name, "// fake header\n")
        self.write("include/circle/fs/partitionmanager.h", "// partition header\n")

    def test_four_sd_usb_combinations(self):
        self.sd_inputs()
        self.usb_inputs()
        expected = {
            (False, False): ["libcircle.a"],
            (True, False): ["libcircle.a", "libfs.a", "libsdcard.a"],
            (False, True): ["libcircle.a", "libinput.a", "libusb.a"],
            (True, True): ["libcircle.a", "libfs.a", "libsdcard.a", "libinput.a", "libusb.a"],
        }
        for (sd, usb), targets in expected.items():
            with self.subTest(sd=sd, usb=usb):
                self.run_build(with_sd=sd, with_usb=usb)
                actual = [record["args"][-1] for record in self.records()]
                self.assertEqual(actual[-len(targets):], targets)
                state = json.loads((self.build / circle.STATE).read_text())
                self.assertEqual(state["configuration"]["with_sd"], sd)
                self.assertEqual(state["configuration"]["with_usb"], usb)
                self.assertEqual((self.build / "lib/libcircle.a").read_bytes(), b"fake archive")
                if usb:
                    self.assertEqual((self.build / "lib/usb/libusb.a").read_bytes(),
                                     b"fake libusb.a")
                    usb_record = self.records()[-1]
                    self.assertEqual(usb_record["directory"], "lib/usb")
                    self.assertIn("CIRCLEHOME=../..", usb_record["args"])

    def test_net_combinations_build_after_usb_with_fixed_arguments(self):
        self.sd_inputs()
        self.usb_inputs()
        self.net_inputs()
        for sd in (False, True):
            with self.subTest(sd=sd):
                archive = self.run_build(with_sd=sd, with_usb=True, with_net=True, jobs=3)
                targets = ["libcircle.a"]
                if sd:
                    targets += ["libfs.a", "libsdcard.a"]
                targets += ["libinput.a", "libusb.a", "libsched.a", "libnet.a"]
                records = self.records()[-len(targets):]
                self.assertEqual([record["args"][-1] for record in records], targets)
                self.assertEqual(archive, self.build / "lib/libcircle.a")
                for record in records:
                    home = ".." if record["directory"] == "lib" else "../.."
                    fixed = ["CIRCLEHOME=" + home if arg.startswith("CIRCLEHOME=")
                             else arg for arg in circle.FIXED]
                    self.assertEqual(record["args"], ["-C", str(self.build / record["directory"]),
                                     *fixed, "PREFIX=arm-none-eabi-", "-j3", record["args"][-1]])
                for directory, target in (("lib/sched", "libsched.a"), ("lib/net", "libnet.a")):
                    self.assertEqual((self.build / directory / target).read_bytes(),
                                     ("fake " + target).encode("ascii"))
                state = json.loads((self.build / circle.STATE).read_text())
                self.assertTrue(state["configuration"]["with_net"])
                self.assertEqual(state["configuration"]["libraries"][-2:],
                                 [["lib/sched", "libsched.a", "../.."],
                                  ["lib/net", "libnet.a", "../.."]])

    def test_net_without_usb_is_rejected_before_stage_or_tools(self):
        with mock.patch.object(circle, "compiler_identity") as compiler:
            for sd in (False, True):
                with self.subTest(sd=sd):
                    with self.assertRaisesRegex(circle.BuildError, "--with-net requires --with-usb"):
                        self.run_build(with_sd=sd, with_net=True)
            compiler.assert_not_called()
        self.assertFalse(self.build.exists())

    def test_missing_net_or_sched_makefile_fails_before_make(self):
        self.usb_inputs()
        self.net_inputs()
        for directory in ("lib/net", "lib/sched"):
            with self.subTest(directory=directory):
                makefile = self.source / directory / "Makefile"
                content = makefile.read_bytes()
                makefile.unlink()
                try:
                    with self.assertRaisesRegex(circle.BuildError, "Missing Circle library Makefile"):
                        self.run_build(with_usb=True, with_net=True)
                    self.assertFalse((self.build / "make-records.json").exists())
                    self.assertFalse((self.build / circle.LOCK).exists())
                finally:
                    makefile.write_bytes(content)

    def test_net_stages_only_top_level_sources_headers_and_makefiles(self):
        self.usb_inputs()
        self.net_inputs()
        for directory in ("lib/sched", "lib/net"):
            for name in ("sample/main.cpp", "nested/private.h", "old.o", "old.a", "notes.txt"):
                self.write(directory + "/" + name, "excluded\n")
        self.run_build(with_usb=True, with_net=True)
        for name in ("lib/sched/Makefile", "lib/sched/scheduler.cpp", "lib/sched/scheduler.h",
                     "lib/net/Makefile", "lib/net/netsubsystem.cpp", "lib/net/netconfig.h"):
            self.assertTrue((self.build / name).is_file(), name)
        for directory in ("lib/sched", "lib/net"):
            for name in ("sample", "nested", "old.o", "old.a", "notes.txt"):
                self.assertFalse((self.build / directory / name).exists())
        self.assertFalse((self.build / "lib/fs").exists())
        self.assertFalse((self.build / "addon").exists())

    def test_net_toggle_changes_signature_and_cleans_only_owned_paths(self):
        self.usb_inputs()
        self.net_inputs()
        self.run_build(with_usb=True)
        before = json.loads((self.build / circle.STATE).read_text())
        self.run_build(with_usb=True, with_net=True)
        after = json.loads((self.build / circle.STATE).read_text())
        self.assertNotEqual(before["signature"], after["signature"])
        preserved = [self.build / directory / name for directory in ("lib/sched", "lib/net")
                     for name in ("local.o", "local.a", "nested/keep.o", "notes.txt")]
        preserved += [self.source / "lib/net/netsubsystem.o", self.root / "outside.a"]
        for path in preserved:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not owned")
        stamps = {path: path.stat().st_mtime_ns for path in preserved}
        self.run_build(with_usb=True)
        for name in ("lib/sched/Makefile", "lib/sched/scheduler.cpp", "lib/sched/scheduler.h",
                     "lib/sched/scheduler.o", "lib/sched/scheduler.d", "lib/sched/libsched.a",
                     "lib/net/Makefile", "lib/net/netsubsystem.cpp", "lib/net/netconfig.h",
                     "lib/net/netsubsystem.o", "lib/net/netsubsystem.d", "lib/net/libnet.a"):
            self.assertFalse((self.build / name).exists(), name)
        for path in preserved:
            self.assertEqual(path.read_bytes(), b"not owned")
            self.assertEqual(path.stat().st_mtime_ns, stamps[path])
        self.assertEqual([record["args"][-1] for record in self.records()[-3:]],
                         ["libcircle.a", "libinput.a", "libusb.a"])
        final = json.loads((self.build / circle.STATE).read_text())
        self.assertEqual(before["signature"], final["signature"])
        self.assertFalse(final["configuration"]["with_net"])

    def test_net_input_changes_invalidate_all_seven_libraries(self):
        self.sd_inputs()
        self.usb_inputs()
        self.net_inputs()
        self.run_build(with_sd=True, with_usb=True, with_net=True)
        for name in ("lib/net/netconfig.h", "lib/net/netsubsystem.cpp", "lib/sched/Makefile",
                     "lib/sched/newtask.cpp"):
            with self.subTest(name=name):
                self.write(name, "// changed or added\n")
                self.run_build(with_sd=True, with_usb=True, with_net=True)
                for record in self.records()[-7:]:
                    self.assertEqual(record["objects_before"], [])
                    self.assertFalse(record["archive_before"])
        self.run_build(with_sd=True, with_usb=True, with_net=True)
        for record in self.records()[-7:]:
            self.assertTrue(record["objects_before"])
            self.assertTrue(record["archive_before"])

    def test_net_modified_obsolete_source_is_preserved_before_cleanup(self):
        self.usb_inputs()
        self.net_inputs()
        self.run_build(with_usb=True, with_net=True)
        staged = self.build / "lib/net/netconfig.h"
        staged.write_text("user changes\n")
        count = len(self.records())
        with self.assertRaisesRegex(circle.BuildError, "modified staged source"):
            self.run_build(with_usb=True)
        self.assertEqual(staged.read_text(), "user changes\n")
        self.assertEqual(len(self.records()), count)
        self.assertTrue((self.build / "lib/net/libnet.a").is_file())
        self.assertFalse((self.build / circle.LOCK).exists())

    def test_net_rejects_unowned_stage(self):
        self.usb_inputs()
        self.net_inputs()
        self.build.mkdir(parents=True)
        sentinel = self.build / "sentinel.txt"
        sentinel.write_text("not owned")
        with self.assertRaisesRegex(circle.BuildError, "Nonempty build directory"):
            self.run_build(with_usb=True, with_net=True)
        self.assertEqual(sentinel.read_text(), "not owned")
        self.assertFalse((self.build / circle.OWNER).exists())
        self.assertFalse((self.build / "make-records.json").exists())

    def test_net_inherits_tool_environment_isolation(self):
        self.usb_inputs()
        self.net_inputs()
        pollution = {"CC": "evil-gcc", "CXX": "evil-g++", "AR": "evil-ar", "LD": "evil-ld",
                     "MAKEFLAGS": "-e RASPPI=4", "MAKEFILES": "evil.mk", "PREFIX": "evil-",
                     "CFLAGS": "-mfloat-abi=soft", "LDFLAGS": "-L/evil", "CPATH": "/evil"}
        self.environ.update(pollution)
        self.run_build(with_usb=True, with_net=True)
        for record in self.records():
            self.assertTrue(set(pollution).isdisjoint(record["environment"]))
            self.assertIn("PREFIX=arm-none-eabi-", record["args"])
            self.assertIn("FLOAT_ABI=hard", record["args"])

    def test_usb_requires_only_its_makefile_and_top_level_inputs(self):
        self.usb_inputs()
        self.write("lib/usb/sample/main.cpp", "excluded\n")
        self.write("lib/usb/addon/not-staged.cpp", "excluded\n")
        self.run_build(with_usb=True)
        for name in ("lib/input/Makefile", "lib/input/keyboardbehaviour.cpp",
                     "lib/usb/Makefile", "lib/usb/lan7800.cpp", "lib/usb/usbdevice.h"):
            self.assertTrue((self.build / name).is_file())
        for name in ("lib/usb/sample", "lib/usb/addon"):
            self.assertFalse((self.build / name).exists())
        self.assertFalse((self.build / "lib/fs").exists())
        self.assertFalse((self.build / "addon").exists())

    def test_usb_toggle_invalidates_rebuild_and_removes_only_owned_paths(self):
        self.usb_inputs()
        self.run_build()
        before = json.loads((self.build / circle.STATE).read_text())
        self.run_build(with_usb=True)
        after = json.loads((self.build / circle.STATE).read_text())
        self.assertNotEqual(before["signature"], after["signature"])
        self.assertEqual(self.records()[-1]["args"][-1], "libusb.a")
        keep = self.build / "lib/usb/local.txt"
        keep.write_text("preserve")
        self.run_build()
        self.assertEqual(keep.read_text(), "preserve")
        for name in ("lib/input/Makefile", "lib/input/keyboardbehaviour.cpp",
                     "lib/input/keyboardbehaviour.o", "lib/input/libinput.a",
                     "lib/usb/Makefile", "lib/usb/lan7800.cpp", "lib/usb/lan7800.o",
                     "lib/usb/lan7800.d", "lib/usb/libusb.a"):
            self.assertFalse((self.build / name).exists(), name)

    def test_usb_input_changes_invalidate_every_selected_library(self):
        self.usb_inputs()
        self.run_build(with_usb=True)
        self.write("lib/usb/lan7800.cpp", "// changed\n")
        self.run_build(with_usb=True)
        for record in self.records()[-2:]:
            self.assertEqual(record["objects_before"], [])
            self.assertFalse(record["archive_before"])

    def test_usb_directory_symlinks_and_modified_staged_files_are_rejected(self):
        self.usb_inputs()
        self.run_build(with_usb=True)
        staged = self.build / "lib/usb/usbdevice.h"
        (self.source / "lib/usb/usbdevice.h").unlink()
        staged.write_text("user change")
        with self.assertRaisesRegex(circle.BuildError, "modified staged source"):
            self.run_build(with_usb=False)
        self.assertEqual(staged.read_text(), "user change")

    def test_sd_default_remains_unchanged(self):
        self.run_build()
        self.assertEqual([r["args"][-1] for r in self.records()], ["libcircle.a"])
        self.assertFalse(json.loads((self.build / circle.STATE).read_text())
                         ["configuration"]["with_sd"])
        self.assertFalse(json.loads((self.build / circle.STATE).read_text())
                         ["configuration"]["with_usb"])

    def test_missing_usb_makefile_fails_before_make(self):
        self.usb_inputs()
        (self.source / "lib/usb/Makefile").unlink()
        with self.assertRaisesRegex(circle.BuildError, "Missing Circle library Makefile"):
            self.run_build(with_usb=True)
        self.assertFalse((self.build / "make-records.json").exists())

    def test_main_parses_both_independent_switches(self):
        archive = self.build / "lib/libcircle.a"
        with mock.patch.object(circle, "build_circle", return_value=archive) as build, \
                mock.patch("builtins.print"):
            self.assertEqual(circle.main(["--with-usb"]), 0)
            self.assertTrue(build.call_args.kwargs["with_usb"])
            self.assertFalse(build.call_args.kwargs["with_sd"])
            self.assertEqual(circle.main(["--with-sd", "--with-usb"]), 0)
            self.assertTrue(build.call_args.kwargs["with_usb"])
            self.assertTrue(build.call_args.kwargs["with_sd"])


if __name__ == "__main__":
    unittest.main()
