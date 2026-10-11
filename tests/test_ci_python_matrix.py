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
  calls.append(cmd)
  bad='test_a.py' in cmd[-1]
  Path(cmd[cmd.index('--junitxml')+1]).write_text('<testsuite tests="1" errors="0" failures="'+('1' if bad else '0')+'" skipped="0"/>')
  return subprocess.CompletedProcess(cmd,1 if bad else 0)
 with patch.object(m.subprocess,'run',fake_run):
  assert m.run(tmp_path,files=[Path('tests/test_a.py'),Path('tests/test_b.py')])==1
 assert len(calls)==2
 assert 'failed=1' in capsys.readouterr().out

def test_focused_file_only(tmp_path):
 d=tmp_path/'tests';d.mkdir();(d/'test_ok.py').write_text('def test_ok(): assert True\n')
 assert m.run(tmp_path,files=[Path('tests/test_ok.py')],python=sys.executable)==0


def test_junit_parser_rejects_empty(tmp_path):
 p=tmp_path/'empty.xml';p.write_text('<testsuite tests="0"/>')
 import pytest
 with pytest.raises(ValueError):m.junit_totals(p)

def test_junit_parser_counts_skips(tmp_path):
 p=tmp_path/'one.xml';p.write_text('<testsuites><testsuite tests="2" errors="0" failures="0" skipped="1"/></testsuites>')
 assert m.junit_totals(p)=={'tests':2,'errors':0,'failures':0,'skipped':1}

def test_json_report_includes_per_file_counts(tmp_path):
 root=tmp_path;d=root/'tests';d.mkdir();(d/'test_pass.py').write_text('def test_ok():assert True\n')
 report=root/'qa'/'test-summary.json'
 assert m.run(root,files=[Path('tests/test_pass.py')],report=report)==0
 import json
 result=json.loads(report.read_text())
 assert result['totals']['tests']==1 and result['status']=='PASS' and result['discovered_files']==1
