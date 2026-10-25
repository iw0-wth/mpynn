# SPDX-License-Identifier: MIT
"""Run read-only micropython-lib ssl over a recording fake native tls module."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch, mock_open

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'lib/micropython/lib/micropython-lib/python-stdlib/ssl/ssl.py'

class SSLWrapperTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        calls=self.calls
        class Context:
            def __init__(self,*args): self.verify_mode=2;calls.append(('context',args))
            def load_verify_locations(self,ca): calls.append(('ca',ca))
            def load_cert_chain(self,cert,key): calls.append(('chain',cert,key))
            def wrap_socket(self,sock,**kwargs): calls.append(('wrap',sock,kwargs));return 'wrapped'
        native=types.ModuleType('tls')
        native.SSLContext=Context
        native.CERT_NONE=0;native.CERT_REQUIRED=2
        native.PROTOCOL_TLS_CLIENT=1;native.PROTOCOL_TLS_SERVER=2
        spec=importlib.util.spec_from_file_location('mpynn_ssl_wrapper', SOURCE)
        self.ssl=importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules',{'tls':native}): spec.loader.exec_module(self.ssl)

    def test_manifest_freezes_standard_ssl(self):
        source=(ROOT/'ports/raspberrypi/manifest.py').read_text(encoding='utf-8')
        self.assertIn('require("ssl")',source)

    def test_context_default_and_verified_cadata(self):
        context=self.ssl.SSLContext(1)
        self.assertEqual(context.verify_mode,0)
        context.verify_mode=2
        context.load_verify_locations(cadata=b'CA')
        self.assertEqual(context.verify_mode,2)
        self.assertIn(('ca',b'CA'),self.calls)

    def test_file_ca_and_certificates(self):
        context=self.ssl.SSLContext(1)
        with patch('builtins.open', mock_open(read_data=b'PEM')) as files:
            context.load_verify_locations(cafile='/ca.pem')
            files.assert_called_once_with('/ca.pem','rb')
        self.assertIn(('ca',b'PEM'),self.calls)
        context.load_cert_chain(b'CERT',b'KEY')
        self.assertIn(('chain',b'CERT',b'KEY'),self.calls)

    def test_wrap_passes_hostname_handshake_and_context(self):
        context=self.ssl.SSLContext(1);context.verify_mode=2
        self.assertEqual(context.wrap_socket('socket',server_hostname='host',do_handshake_on_connect=False),'wrapped')
        self.assertEqual(self.calls[-1],('wrap','socket',{'server_side':False,'do_handshake_on_connect':False,'server_hostname':'host'}))

if __name__=='__main__':unittest.main()
