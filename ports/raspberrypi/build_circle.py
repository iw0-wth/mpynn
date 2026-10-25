#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build Circle's RPI1B libraries without writing into the upstream checkout.

Defaults are relative to this script, not the current directory. --build is the
stage itself; the core archive is always <build>/lib/libcircle.a. By default only
include/, top-level lib/ files and Rules.mk are staged. --with-sd also stages
top-level sources, headers and Makefiles from lib/fs and addon/SDCard.
--with-usb adds lib/input and lib/usb; --with-net requires --with-usb and adds
lib/sched and lib/net. Selected archives build in that order after the core. No samples,
FatFs or CFATFileSystem implementations are staged or mounted. Upstream Config.mk and
Config2.mk are deliberately NOT inherited: this helper owns the RPI1B settings.
The bundled Circle source uses allowlisted upstream_overrides/circle files in
this port. Overrides replace selected files only in the stage; their paths and
hashes participate in the build signature. Custom --source trees opt in with
--overlays. Both input trees are read-only, and overlay links are rejected.

Example from ports/raspberrypi (the caller must link the staged archive):
    python3 build_circle.py --build ../../build/RPI1B/circle \
        --prefix arm-none-eabi- --make make --jobs 4
    # Add --with-sd for all three archives; this helper does not link a kernel.

The RPI1B CPU/ABI is fixed explicitly. Compiler flags, defines, include/library
search paths and tool overrides from the environment are discarded; only basic
process environment and SOURCE_DATE_EPOCH survive. Parent MAKEFLAGS,
MAKEOVERRIDES and MAKEFILES cannot inject another board or build flags.
Changed configuration, headers, rules, or source inventory invalidate generated
objects in all selected libraries. Unchanged files retain their mtimes. There is
no recursive delete.
A stage must be empty or bear this helper's ownership marker. A stale lock after
an interrupted process must be inspected and removed manually, never forcibly.
"""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


MPYNN = Path(__file__).resolve().parents[2]
OVERRIDES = Path(__file__).resolve().parent / "upstream_overrides/circle"
OVERLAY_FILES = (
    "include/circle/net/netsubsystem.h",
    "include/circle/net/dhcpclient.h",
    "include/circle/net/linklayer.h",
    "include/circle/net/networklayer.h",
    "include/circle/net/arphandler.h",
    "lib/net/netsubsystem.cpp",
    "lib/net/dhcpclient.cpp",
    "include/circle/net/netconnection.h",
    "include/circle/net/tcpconnection.h",
    "include/circle/net/transportlayer.h",
    "include/circle/net/udpconnection.h",
    "lib/net/netconnection.cpp",
    "lib/net/tcpconnection.cpp",
    "lib/net/transportlayer.cpp",
    "lib/net/dnsclient.cpp",
    "lib/net/udpconnection.cpp",
    "include/circle/i2cmaster.h",
    "lib/i2cmaster.cpp",
    "include/circle/spimaster.h",
    "lib/spimaster.cpp",
    "addon/SDCard/sdhost.cpp",
)
OWNER = ".build-circle-owner.json"
STATE = ".build-circle-state.json"
LOCK = ".build-circle-lock"
SCHEMA = 1
FIXED = ("RASPPI=1", "AARCH=32", "STDLIB_SUPPORT=1", "FLOAT_ABI=hard",
         "GC_SECTIONS=1", "CLANG=0", "CHECK_DEPS=1", "KASAN_ENABLED=0",
         "CIRCLEHOME=..",
         "ARCHCPU=-mcpu=arm1176jzf-s -marm -mfpu=vfp -mfloat-abi=hard")
# An allowlist, not a flag denylist: unknown compiler/make variables must not
# change core ABI or layout independently of the port's kernel compilation.
SAFE_BUILD_ENV = ("SOURCE_DATE_EPOCH",)
SYSTEM_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP",
              "TMP", "TMPDIR", "HOME", "USERPROFILE")
ARTIFACT_SUFFIXES = {".o", ".d", ".a", ".obj", ".dep", ".elf", ".img",
                     ".map", ".lst", ".hex", ".cir", ".pyc", ".pyo"}
SOURCE_SUFFIXES = {".c", ".cpp", ".S", ".s"}
HEADER_SUFFIXES = {".h", ".hpp", ".hh", ".hxx"}
# Keep build order explicit. Optional upstream Makefiles use ../..; command-line
# CIRCLEHOME must not retain the core's one-level relative path.
LIBRARIES = (("lib", "libcircle.a", ".."),
             ("lib/fs", "libfs.a", "../.."),
             ("addon/SDCard", "libsdcard.a", "../.."),
             ("lib/input", "libinput.a", "../.."),
             ("lib/usb", "libusb.a", "../.."),
             ("lib/sched", "libsched.a", "../.."),
             ("lib/net", "libnet.a", "../.."))


class BuildError(RuntimeError):
    """An unsafe stage or unsuccessful build."""


def inside(path, root):
    return path == root or root in path.parents


def is_link(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def checked(path, build, source):
    """Check EVERY mutation target, including all existing path components."""
    path = Path(os.path.abspath(path))
    if path == build or not inside(path, build):
        raise BuildError("Refusing mutation outside stage children: %s" % path)
    for parent in (path, *path.parents):
        if is_link(parent):
            raise BuildError("Refusing symlink/junction in stage path: %s" % parent)
    resolved = path.resolve()
    if not inside(resolved, build) or inside(resolved, source):
        raise BuildError("Unsafe stage mutation: %s" % resolved)
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def put(path, data, build, source):
    path = checked(path, build, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    return True


def unlink(path, build, source):
    path = checked(path, build, source)
    if path.exists():
        if not path.is_file():
            raise BuildError("Not a regular generated file: %s" % path)
        path.unlink()


def stage_roots(source, build):
    source = Path(source).resolve(strict=True)
    raw_build = Path(os.path.abspath(build))
    for part in (raw_build, *raw_build.parents):
        if is_link(part):
            raise BuildError("Build path may not use symlinks/junctions: %s" % part)
    build = raw_build.resolve()
    if inside(build, source) or inside(source, build):
        raise BuildError("Source and build must not overlap")
    for name in ("include", "lib", "Rules.mk", "lib/Makefile"):
        if not (source / name).exists():
            raise BuildError("Missing Circle core input: %s" % (source / name))
    identity = {"owner": "mpynn.build_circle", "schema": SCHEMA,
                "source": str(source), "build": str(build)}
    marker = checked(build / OWNER, build, source)
    if build.exists() and any(build.iterdir()):
        if not marker.is_file() or marker.read_bytes() != encoded(identity):
            raise BuildError("Nonempty build directory is not this helper's stage")
    build.mkdir(parents=True, exist_ok=True)
    put(marker, encoded(identity), build, source)
    return source, build


@contextlib.contextmanager
def stage_lock(build, source):
    lock = checked(build / LOCK, build, source)
    try:
        with lock.open("x", encoding="ascii") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError as exc:
        raise BuildError("Stage is locked; inspect stale lock manually: %s" % lock) from exc
    try:
        yield
    finally:
        unlink(lock, build, source)


def selected_libraries(with_sd=False, with_usb=False, with_net=False):
    if with_net and not with_usb:
        raise BuildError("--with-net requires --with-usb")
    libraries = [LIBRARIES[0]]
    if with_sd:
        libraries.extend(LIBRARIES[1:3])
    if with_usb:
        libraries.extend(LIBRARIES[3:5])
    if with_net:
        libraries.extend(LIBRARIES[5:7])
    return tuple(libraries)


def core_inputs(source, with_sd=False, with_usb=False, with_net=False):
    result = {}
    optional = [directory for directory, _, _ in selected_libraries(
        with_sd=with_sd, with_usb=with_usb, with_net=with_net)[1:]]
    directories = ["include", "lib", *optional]
    for name in directories:
        directory = source / name
        for part in (directory, *directory.parents):
            if part == source:
                break
            if is_link(part):
                raise BuildError("Source directory is a symlink/junction: %s" % part)
        if not directory.is_dir():
            raise BuildError("Missing Circle input directory: %s" % directory)
        if name not in ("include", "lib") and not (directory / "Makefile").is_file():
            raise BuildError("Missing Circle library Makefile: %s" % directory)

    def add(path):
        if is_link(path) or not inside(path.resolve(), source):
            raise BuildError("Source symlinks/junctions are not supported: %s" % path)
        if path.suffix.lower() in ARTIFACT_SUFFIXES or path.name.endswith("~"):
            return
        result[path.relative_to(source).as_posix()] = path.read_bytes()

    add(source / "Rules.mk")
    for base, dirs, files in os.walk(source / "include", followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__"})
        for name in dirs:
            if is_link(Path(base) / name):
                raise BuildError("Source header directory is a symlink/junction")
        for name in sorted(files):
            if name != ".git":
                add(Path(base) / name)
    # Preserve the default core inventory. Optional libraries are strictly
    # top-level source/header/Makefile copies: never recurse into samples or fat/.
    for path in sorted((source / "lib").iterdir()):
        if path.name == ".git":
            continue
        if is_link(path):
            raise BuildError("Source library entry is a symlink/junction: %s" % path)
        if path.is_file():
            add(path)
    for name in optional:
        directory = source / name
        for path in sorted(directory.iterdir()):
            if path.name == ".git":
                continue
            if is_link(path):
                raise BuildError("Source library entry is a symlink/junction: %s" % path)
            if path.is_file() and (path.name == "Makefile"
                                   or path.suffix in SOURCE_SUFFIXES | HEADER_SUFFIXES):
                add(path)
    return result


def overlay_inputs(inputs, overlay, source, build):
    """Replace only allowlisted, selected inputs; never mutate either source tree."""
    if overlay is None:
        return None
    root = Path(os.path.abspath(overlay))
    # Check the lexical path before resolve: resolving first would hide links.
    for part in (root, *root.parents):
        if is_link(part):
            raise BuildError("Overlay path may not use symlinks/junctions: %s" % part)
    root = root.resolve(strict=True)
    if inside(root, build) or inside(build, root) or inside(root, source) or inside(source, root):
        raise BuildError("Overlay, source and build must not overlap")
    hashes = {}
    for name in OVERLAY_FILES:
        path = root / name
        for part in (path, *path.parents):
            if part == root:
                break
            if is_link(part):
                raise BuildError("Overlay path may not use symlinks/junctions: %s" % part)
        if not path.is_file() or not inside(path.resolve(), root):
            raise BuildError("Missing or unsafe Circle overlay: %s" % path)
        data = path.read_bytes()
        hashes[name] = digest(data)
        if name in inputs:
            inputs[name] = data
    return {"root": str(root), "files": hashes}


def build_environment(environ):
    env = {key: environ[key] for key in SYSTEM_ENV + SAFE_BUILD_ENV if key in environ}
    env.update({"LC_ALL": "C", "LANG": "C"})
    return env


def compiler_identity(prefix, env):
    tools = {}
    for suffix in ("gcc", "g++", "ar", "ld"):
        name = prefix + suffix
        found = shutil.which(name, path=env.get("PATH", os.defpath))
        if not found:
            raise BuildError("Toolchain executable not found: %s" % name)
        path = Path(found).resolve()
        completed = subprocess.run([str(path), "--version"], env=env,
                                   check=True, capture_output=True, text=True)
        tools[suffix] = {"path": str(path), "version": completed.stdout,
                         "stderr": completed.stderr}
    return tools


def load_state(build, source):
    path = checked(build / STATE, build, source)
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("files"), dict):
        raise BuildError("Invalid stage state; refusing cleanup")
    for name, checksum in state["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise BuildError("Unsafe path in stage manifest")
        checked(build / relative, build, source)
        if not isinstance(checksum, str):
            raise BuildError("Invalid stage file checksum")
    return state


def clean_generated(build, source, names, libraries=None, remove=True):
    libraries = LIBRARIES if libraries is None else libraries
    directories = {Path(directory) for directory, _, _ in libraries}
    paths = {Path(name) for name in names}
    parents = {path.parent for path in paths}
    generated = {Path(directory) / archive for directory, archive, _ in libraries
                 if directory == "lib" or Path(directory) in parents}
    generated.update(path.with_suffix(suffix) for path in paths
                     if path.parent in directories and path.suffix in SOURCE_SUFFIXES
                     for suffix in (".o", ".d"))
    # Preflight every nested output before deleting any file or running make.
    targets = [checked(build / name, build, source) for name in sorted(generated)]
    for path in targets:
        if path.exists() and not path.is_file():
            raise BuildError("Not a regular generated file: %s" % path)
    if remove:
        for path in targets:
            unlink(path, build, source)


def build_circle(source, build, make="make", prefix="arm-none-eabi-", jobs=None,
                 environ=None, with_sd=False, with_usb=False, with_net=False,
                 overlays=None):
    if jobs is not None and jobs < 1:
        raise BuildError("--jobs must be positive")
    libraries = selected_libraries(with_sd=with_sd, with_usb=with_usb, with_net=with_net)
    source_path = Path(source).resolve(strict=True)
    if overlays is None and source_path == (MPYNN / "lib/circle").resolve():
        overlays = OVERRIDES
    # Validate overlay separation before stage_roots creates its ownership marker.
    overlay_data = {name: b"" for name in OVERLAY_FILES}
    overlay_identity = overlay_inputs(overlay_data, overlays, source_path,
                                      Path(build).resolve())
    source, build = stage_roots(source, build)
    with stage_lock(build, source):
        env = build_environment(os.environ if environ is None else environ)
        if "/" in prefix or "\\" in prefix:
            prefix = os.path.abspath(prefix).replace("\\", "/")
        # Circle's recipes execute PREFIX through a shell, not as an argv item.
        # Reject shell metacharacters instead of silently running another tool.
        if any(char.isspace() or char in "\"'`$;&|<>(){}*?!" for char in prefix):
            raise BuildError("--prefix must be a shell-safe toolchain prefix without spaces")
        tools = compiler_identity(prefix, env)
        inputs = core_inputs(source, with_sd=with_sd, with_usb=with_usb, with_net=with_net)
        if overlay_identity is not None:
            inputs.update((name, data) for name, data in overlay_data.items() if name in inputs)
        files = {name: digest(data) for name, data in inputs.items()}
        configuration = {"schema": SCHEMA, "fixed": list(FIXED), "prefix": prefix,
                         "tools": tools, "environment": env, "with_sd": with_sd,
                         "with_usb": with_usb, "with_net": with_net,
                         "libraries": libraries, "overlays": overlay_identity}
        signature = digest(encoded(configuration))
        old = load_state(build, source)
        old_files = old.get("files", {})
        # Makefile and header changes may not be tracked by all upstream rules.
        # Conservatively rebuild all selected libraries on any input change.
        changed = old.get("signature") != signature or old_files != files
        for name, checksum in old_files.items():
            if name not in files:
                obsolete = checked(build / name, build, source)
                if obsolete.exists() and digest(obsolete.read_bytes()) != checksum:
                    raise BuildError("Refusing to delete modified staged source: %s" % name)
        # Validate even reused output paths before allowing make to write them.
        old_libraries = tuple(tuple(item) for item in old.get("configuration", {}).get(
            "libraries", ()))
        cleanup_libraries = tuple(dict.fromkeys(old_libraries + libraries))
        clean_generated(build, source, set(old_files) | set(files),
                        libraries=cleanup_libraries, remove=changed)
        for name in old_files.keys() - files.keys():
            obsolete = checked(build / name, build, source)
            if obsolete.exists() and digest(obsolete.read_bytes()) != old_files[name]:
                raise BuildError("Refusing to delete modified staged source: %s" % name)
            unlink(obsolete, build, source)
        for name, data in inputs.items():
            put(build / name, data, build, source)
        # Do not allow accidental local Config files to bypass our signature.
        for name in ("Config.mk", "Config2.mk"):
            if (build / name).exists():
                raise BuildError("Unexpected stage configuration file: %s" % name)
        put(build / STATE, encoded({"signature": signature,
                                  "configuration": configuration, "files": files}),
            build, source)
        for directory, target, home in libraries:
            command = [str(make)]
            if str(make).lower().endswith(".py"):
                command.insert(0, sys.executable)
            fixed = ["CIRCLEHOME=" + home if item.startswith("CIRCLEHOME=") else item
                     for item in FIXED]
            command += ["-C", str(build / directory), *fixed, "PREFIX=" + prefix]
            if jobs is not None:
                command.append("-j%d" % jobs)
            command.append(target)
            subprocess.run(command, check=True, env=env)
            archive = checked(build / directory / target, build, source)
            if not archive.is_file():
                raise BuildError("make succeeded but did not produce %s" % archive)
        # Keep the public return value and default CLI output backward compatible.
        return build / "lib/libcircle.a"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=MPYNN / "lib/circle")
    parser.add_argument("--build", type=Path, default=MPYNN / "build/RPI1B/circle")
    parser.add_argument("--overlays", type=Path,
                        help="allowlisted Circle overrides (automatic for bundled Circle)")
    parser.add_argument("--make", default="make", help="make executable (or .py test driver)")
    parser.add_argument("--prefix", default="arm-none-eabi-")
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--with-sd", action="store_true",
                        help="also build isolated fs partition and SDCard libraries")
    parser.add_argument("--with-usb", action="store_true",
                        help="also build the isolated input and USB libraries")
    parser.add_argument("--with-net", action="store_true",
                        help="also build isolated scheduler and network libraries (requires --with-usb)")
    args = parser.parse_args(argv)
    try:
        archive = build_circle(**vars(args))
    except (BuildError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("build_circle: %s" % exc, file=sys.stderr)
        return exc.returncode if isinstance(exc, subprocess.CalledProcessError) else 1
    print(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
