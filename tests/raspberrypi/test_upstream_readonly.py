# SPDX-License-Identifier: MIT
"""Local baseline guards restored vendor files against accidental patching.

This records exact restored workspace bytes, not an assertion of upstream Git
identity. Deliberate dependency upgrades need a reviewed baseline update.
"""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
BASELINE=ROOT/'ports/raspberrypi/upstream_overrides/restored-sources.json'

class UpstreamReadOnlyTests(unittest.TestCase):
    def test_restored_vendor_files_are_unchanged(self):
        entries=json.loads(BASELINE.read_text(encoding='utf-8-sig'))
        self.assertEqual(len(entries),12)
        for entry in entries:
            with self.subTest(path=entry['path']):
                self.assertTrue(entry['path'].startswith('lib/'))
                actual=hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()
                self.assertEqual(actual,entry['sha256'], 'Do not edit lib; adapt a copy in the port')

if __name__=='__main__':unittest.main()
