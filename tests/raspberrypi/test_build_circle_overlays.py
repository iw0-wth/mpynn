# SPDX-License-Identifier: MIT
"""Overlay staging regressions; temporary trees and fake make only."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

import test_build_circle as fixtures

circle = fixtures.circle


class CircleOverlayTests(unittest.TestCase):
    write = fixtures.CircleBuildTests.write
    run_build = fixtures.CircleBuildTests.run_build
    records = fixtures.CircleBuildTests.records

    def setUp(self):
        fixtures.CircleBuildTests.setUp(self)
        self.overlays = self.root / 'overrides'
        for name in circle.OVERLAY_FILES:
            path = self.overlays / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('patched ' + name).encode())
        self.write('include/circle/net/netconnection.h', 'original header')

    def snapshot(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob('*') if p.is_file()}

    def test_overlay_applies_only_to_stage_and_invalidates_signature(self):
        before = self.snapshot(self.source)
        overlays_before = self.snapshot(self.overlays)
        self.run_build(overlays=self.overlays)
        state = json.loads((self.build / circle.STATE).read_text())
        name = 'include/circle/net/netconnection.h'
        self.assertEqual((self.build / name).read_bytes(), overlays_before[name])
        self.assertFalse((self.build / 'lib/net/tcpconnection.cpp').exists())
        self.assertEqual(state['configuration']['overlays']['files'][name],
                         hashlib.sha256(overlays_before[name]).hexdigest())
        self.assertEqual(self.snapshot(self.source), before)
        self.assertEqual(self.snapshot(self.overlays), overlays_before)
        # Even an inactive overlay participates in the build identity.
        (self.overlays / 'lib/net/tcpconnection.cpp').write_bytes(b'new patch')
        self.run_build(overlays=self.overlays)
        updated = json.loads((self.build / circle.STATE).read_text())
        self.assertNotEqual(state['signature'], updated['signature'])
        self.assertFalse(self.records()[-1]['archive_before'])
        self.assertEqual(self.snapshot(self.source), before)

    def test_allowlist_replaces_selected_files_only(self):
        inputs = {name: b'original' for name in circle.OVERLAY_FILES}
        inputs['lib/Makefile'] = b'original makefile'
        (self.overlays / 'lib/Makefile').write_bytes(b'unlisted makefile')
        identity = circle.overlay_inputs(inputs, self.overlays, self.source, self.build)
        self.assertEqual(inputs['lib/Makefile'], b'original makefile')
        self.assertEqual(set(identity['files']), set(circle.OVERLAY_FILES))
        for name in circle.OVERLAY_FILES:
            self.assertEqual(inputs[name], (self.overlays / name).read_bytes())

    def test_rejects_overlay_link_file_directory_and_root(self):
        # Mock link detection so this also exercises Windows without symlink privilege.
        for relative in ('', 'include', 'include/circle/net/netconnection.h'):
            linked = self.overlays / relative
            with self.subTest(relative=relative), mock.patch.object(
                    circle, 'is_link', side_effect=lambda p: Path(p) == linked):
                with self.assertRaisesRegex(circle.BuildError, 'symlinks/junctions'):
                    self.run_build(overlays=self.overlays)
        self.assertEqual(self.snapshot(self.source)['include/circle/net/netconnection.h'],
                         b'original header')

    def test_rejects_overlay_build_overlap_before_make(self):
        self.build.mkdir(parents=True)
        with self.assertRaisesRegex(circle.BuildError, 'must not overlap'):
            self.run_build(overlays=self.build)
        self.assertFalse((self.build / 'make-record.json').exists())

    def test_missing_overlay_fails_without_source_mutations(self):
        before = self.snapshot(self.source)
        with self.assertRaises((circle.BuildError, FileNotFoundError)):
            self.run_build(overlays=self.root / 'missing')
        self.assertEqual(self.snapshot(self.source), before)

