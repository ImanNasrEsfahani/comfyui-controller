import importlib.util,subprocess,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('p14prepare',ROOT/'scripts/phase14_prepare_checkout.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_blob_git_compatible(tmp_path):
 p=tmp_path/'readme';p.write_bytes(b'abc')
 assert m.blob(p.read_bytes())=='f2ba8f84ab5c1bce84a7b441cb1959cfc7093b7f'

def test_reject_noncheckout(tmp_path):
 try:m.prepare(tmp_path)
 except RuntimeError as e:assert 'git checkout' in str(e)
 else:assert False

def test_reject_unrelated_head_without_modification(tmp_path):
 subprocess.run(['git','init','-q',str(tmp_path)],check=True)
 (tmp_path/'dummy').write_text('unchanged')
 subprocess.run(['git','-C',str(tmp_path),'add','dummy'],check=True)
 subprocess.run(['git','-C',str(tmp_path),'-c','user.email=test@example.org','-c','user.name=CI','commit','-qm','test'],check=True)
 p=tmp_path/'dummy';before=p.read_bytes()
 try:m.prepare(tmp_path)
 except RuntimeError as e:assert 'ancestry' in str(e)
 else:assert False
 assert p.read_bytes()==before

def test_export_requires_checkout(tmp_path):
 target=tmp_path/'export'
 result=subprocess.run([sys.executable,str(ROOT/'scripts/phase14_prepare_checkout.py'),
  '--repo',str(tmp_path),'--export-dir',str(target)],capture_output=True,text=True)
 assert result.returncode==2 and not target.exists()

def test_ancestry_follows_successor_in_real_git(tmp_path):
 subprocess.run(['git','init','-q',str(tmp_path)],check=True)
 def commit(path,data,msg):
  (tmp_path/path).write_text(data)
  subprocess.run(['git','-C',str(tmp_path),'add',path],check=True)
  subprocess.run(['git','-C',str(tmp_path),'-c','user.email=test@example.org','-c','user.name=CI','commit','-qm',msg],check=True)
  return subprocess.check_output(['git','-C',str(tmp_path),'rev-parse','HEAD'],text=True).strip()
 initial=commit('baseline','one','base')
 descendant=commit('changes','two','new')
 assert subprocess.run(['git','-C',str(tmp_path),'merge-base','--is-ancestor',initial,descendant]).returncode==0
 assert subprocess.run(['git','-C',str(tmp_path),'merge-base','--is-ancestor',descendant,initial]).returncode!=0
