#!/usr/bin/env python3
"""Run the port's manifest override using upstream's tool import locations."""
import sys
from pathlib import Path


def main():
    port_dir = Path(__file__).resolve().parents[1]
    upstream_tools = port_dir.parents[1] / "lib" / "micropython" / "tools"
    override = port_dir / "upstream_overrides" / "micropython" / "tools" / "makemanifest.py"
    # manifestfile and mpy_cross live in lib: importing them must not write pyc files.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(upstream_tools))
    # The preserved script locates mpy-cross relative to __file__. Give it the
    # original location while executing the port copy; never copy into lib.
    namespace = {"__name__": "__main__", "__file__": str(upstream_tools / "makemanifest.py")}
    exec(compile(override.read_bytes(), str(override), "exec"), namespace)


if __name__ == "__main__":
    main()
