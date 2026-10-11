"""Source-blob guard and phase07+phase08 transform smoke tests; not a full checkout test."""
import unittest,importlib.util,hashlib,tempfile,shutil
from pathlib import Path
P=Path(__file__).resolve().parents[1]

def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
class PatchTests(unittest.TestCase):
 def setUp(self):
  self.p=load(P/'scripts/phase08_prepare_checkout.py','patch08')
  self.p07=load(P/'scripts/phase07_prepare_checkout.py','patch07')
 def test_audited_frontend_replacements_are_exact(self):
  for name,expected in self.p.REPLACEMENT_SHA256.items():
   path=P/name
   self.assertTrue(path.is_file(),name)
   self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),expected)
 def test_main_includes_registry_and_parameter_router_without_legacy_deletion(self):
  main=('from . import db, storage, salad, salad_control, job_lifecycle, settings_store, direct_queue, contracts\n'
       'app = FastAPI(title=settings.app_name, version="1.3.0")\n'
       '@app.get("/health")\ndef keep():pass\n')
  result=self.p.main_transform(main,self.p07)
  self.assertIn('app.include_router(parameters_router)',result)
  self.assertIn('app.include_router(registry_router)',result)
  self.assertIn('@app.get("/health")',result)
  with self.assertRaises(RuntimeError):self.p.main_transform(result,self.p07)
 def test_wrong_sha_rejected(self):
  self.assertEqual(len(self.p.BASE),40)
  self.assertNotEqual(self.p.BLOBS['backend/app/main.py'],'deadbeef')
