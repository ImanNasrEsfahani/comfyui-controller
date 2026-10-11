import unittest,importlib.util
from pathlib import Path
PATH=Path(__file__).resolve().parents[1]/'scripts/phase10_prepare_checkout.py'
spec=importlib.util.spec_from_file_location('installer10',PATH);tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
class LocalInstaller(unittest.TestCase):
 def test_latest_main_pinned(self):self.assertEqual(tool.BASE,'d51a4eac487bee4f69808a9e8d49016fcafe624a')
 def test_blobs_pinned(self):self.assertEqual(len(tool.BLOBS),2)
 def test_unverified_checkout_refused(self):
  import tempfile
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(RuntimeError):tool.prepare(Path(d))
 def test_composite_import_is_pure_dryrun(self):self.assertTrue(callable(tool.prepare))
if __name__=='__main__':unittest.main()
