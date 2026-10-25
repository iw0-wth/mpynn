# SPDX-License-Identifier: MIT
"""Verify user demo safety without touching a real SD card."""
import importlib.util
import io
from pathlib import Path
import types
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[2]/'demo/storage.py'

class StorageDemoTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('storage_demo', SOURCE)
        self.demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.demo)

    def test_write_requires_opt_in(self):
        with patch('builtins.open') as create:
            with self.assertRaises(ValueError): self.demo.prepare()
            create.assert_not_called()

    def test_exclusive_create_refuses_existing_file_without_cleanup(self):
        fake=types.SimpleNamespace(sync=lambda:self.fail('must not sync after failed create'),
                                   remove=lambda path:self.fail('must not remove'))
        with patch.dict('sys.modules',{'os':fake}),patch('builtins.open',side_effect=FileExistsError()) as create,patch.object(self.demo,'_failure'):
            with self.assertRaises(FileExistsError):self.demo.prepare(write=True)
            self.assertEqual(create.call_args.args,(self.demo.PATH,'xb'))

    def test_write_failure_preserved_and_no_retry_or_delete(self):
        class File:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def write(self,data):raise OSError(5)
        fake=types.SimpleNamespace(sync=lambda:self.fail('must not sync'),remove=lambda path:self.fail('must not delete'))
        with patch.dict('sys.modules',{'os':fake}),patch('builtins.open',return_value=File()) as create,patch.object(self.demo,'_failure') as diagnostic:
            with self.assertRaises(OSError):self.demo.prepare(write=True)
            self.assertEqual(create.call_count,1)
            self.assertEqual(diagnostic.call_args.args[0],'write')

    def test_postboot_verify_is_read_only_and_does_not_delete(self):
        with patch('builtins.open',return_value=io.BytesIO(self.demo.PAYLOAD)) as read,patch('builtins.print'):
            self.demo.verify_after_reboot()
            self.assertEqual(read.call_args.args,(self.demo.PATH,'rb'))

    def test_cleanup_rejects_unknown_or_partial_content(self):
        with patch('builtins.open',return_value=io.BytesIO(b'unknown')),patch('os.remove') as remove:
            with self.assertRaises(ValueError):self.demo.cleanup(confirm=True)
            remove.assert_not_called()

if __name__=='__main__':unittest.main()
