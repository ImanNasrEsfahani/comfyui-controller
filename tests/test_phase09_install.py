import unittest,importlib.util,hashlib,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer09',ROOT/'scripts/phase09_prepare_checkout.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class Installation(unittest.TestCase):
 def test_commit_is_pinned(self):self.assertEqual(module.BASE,'3d7e2539cec80f7087188101fd30b38f161011ec')
 def test_replacement_hashes_match(self):
  archived_revision='d51a4eac487bee4f69808a9e8d49016fcafe624a'
  for p,digest in module.REPLACEMENTS.items():
   archived=subprocess.check_output(['git','-C',str(ROOT),'show',archived_revision+':'+p])
   self.assertEqual(hashlib.sha256(archived).hexdigest(),digest,p)
   self.assertTrue((ROOT/p).is_file(),p)
 def test_reject_bad_anchor(self):
  with self.assertRaises(RuntimeError):module.once('wrong','must match','replacement')
 def test_main_transform_guards_once(self):
  class Eight:
   @staticmethod
   def main_transform(source,phase07):return source
  source='from .parameters_api import router as parameters_router\n        app.include_router(parameters_router)\n'
  result=module.main_transform(source,Eight,None)
  self.assertIn('from .workflow_api import router as workflow_router',result)
  self.assertIn('WORKFLOW_COMPILER_ENABLED',result)
  with self.assertRaises(RuntimeError):module.main_transform(result,Eight,None)
 def test_wrong_checkout_refused(self):
  from tempfile import TemporaryDirectory
  with TemporaryDirectory() as d:
   with self.assertRaisesRegex(RuntimeError,'complete local Git checkout'):module.run(Path(d))
if __name__=='__main__':unittest.main()
