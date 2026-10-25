# SPDX-License-Identifier: MIT
import builtins
from pathlib import Path
import runpy
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

class StorageDiagnoseTests(unittest.TestCase):
    def run_script(self, machine):
        modules={'machine':machine,'os':types.SimpleNamespace(uname=lambda:('mpynn',),getcwd=lambda:'/',listdir=lambda p:[],statvfs=lambda p:(1,1,1,1,1,1,1,1,1,1)),
                 'sys':types.SimpleNamespace(implementation=('mpy',))}
        with patch.dict('sys.modules',modules),patch('builtins.print') as output:
            runpy.run_path(str(HERE/'storage_diagnose.py'),run_name='__main__')
        return [str(c) for c in output.call_args_list]

    def test_old_image_warning_is_non_destructive(self):
        out=self.run_script(types.SimpleNamespace())
        self.assertTrue(any('predates' in line for line in out))
        self.assertTrue(any('STORAGE_DIAG_DONE_NO_WRITES' in line for line in out))

    def test_current_image_queries_info_but_does_not_write(self):
        info_calls=[]
        machine=types.SimpleNamespace(RTC=object,storage_info=lambda:info_calls.append(1) or {'ready':1},
            logs=lambda:b'',board_info=lambda:{'build_id':'x'})
        out=self.run_script(machine)
        self.assertEqual(info_calls,[1])
        self.assertTrue(any('STORAGE_DIAG_DONE_NO_WRITES' in line for line in out))

if __name__=='__main__':unittest.main()
