# SPDX-License-Identifier: MIT
"""User-facing HTTPS preview must stay bounded and close on all paths."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[2]/'demo/network/https.py'
class HTTPSDemoTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('https_demo',SOURCE)
        self.demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.demo)

    def test_preview_bounded_no_content_property(self):
        class Response:
            status_code=200
            raw=Mock(read=Mock(return_value=b'preview'))
            close=Mock()
            @property
            def content(self): raise AssertionError('must not load entire body')
        response=Response()
        with patch('builtins.print'):
            self.assertEqual(self.demo._show_and_close(response),(200,b'preview'))
        response.raw.read.assert_called_once_with(256)
        response.close.assert_called_once_with()

    def test_read_exception_closes_and_propagates(self):
        response=types.SimpleNamespace(status_code=200,raw=Mock(read=Mock(side_effect=OSError(5))),close=Mock())
        with self.assertRaises(OSError):self.demo._show_and_close(response)
        response.close.assert_called_once_with()

    def test_default_timeout_and_no_time_calibration(self):
        response=types.SimpleNamespace(status_code=200,raw=Mock(read=Mock(return_value=b'')),close=Mock())
        requests=types.SimpleNamespace(get=Mock(return_value=response))
        with patch.dict('sys.modules',{'requests':requests}),patch.object(self.demo,'_lan_ready') as lan,patch.object(self.demo,'sync_time') as clock,patch('builtins.print'):
            self.demo.run('https://example.invalid/')
        lan.assert_called_once_with();clock.assert_not_called()
        requests.get.assert_called_once_with('https://example.invalid/',timeout=10)

if __name__=='__main__':unittest.main()
