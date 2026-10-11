"""Non-silent Python CI fan-out and exit propagation; all fixtures local."""
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ci_python_matrix',ROOT/'scripts/ci_python_matrix.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_no_tests_is_error(tmp_path):
 (tmp_path/'tests').mkdir()
 assert m.run(tmp_path)==2

def test_rejects_outside_test_dir(tmp_path):
 (tmp_path/'tests').mkdir()
 (tmp_path/'bad.py').write_text('')
 assert m.run(tmp_path,files=[Path('bad.py')])==2

def test_path_traversal_is_not_allowed(tmp_path):
 (tmp_path/'tests').mkdir()
 (tmp_path/'bad.py').write_text('')
 assert m.run(tmp_path,files=[Path('tests/../bad.py')])==2

def test_failure_is_reported_and_next_file_still_runs(tmp_path,capsys):
 d=tmp_path/'tests';d.mkdir()
 for name in ('test_a.py','test_b.py'):(d/name).write_text('pass\n')
 calls=[]
 def fake_run(cmd,**kw):
  calls.append(cmd);return subprocess.CompletedProcess(cmd,1 if 'test_a.py' in cmd[-1] else 0)
 with patch.object(m.subprocess,'run',fake_run):
  assert m.run(tmp_path,files=[Path('tests/test_a.py'),Path('tests/test_b.py')])==1
 assert len(calls)==2
 assert 'failed=1' in capsys.readouterr().out

def test_focused_file_only(tmp_path):
 d=tmp_path/'tests';d.mkdir();(d/'test_ok.py').write_text('def test_ok(): assert True\n')
 assert m.run(tmp_path,files=[Path('tests/test_ok.py')],python=sys.executable)==0
