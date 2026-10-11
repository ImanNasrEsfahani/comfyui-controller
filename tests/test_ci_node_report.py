from pathlib import Path
import importlib.util
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('node_report',ROOT/'scripts/ci_node_report.py')
node=importlib.util.module_from_spec(spec);spec.loader.exec_module(node)

def tap(tests=3, passed=2, skipped=1, fail=0,cancelled=0,todo=0):
 return '\n'.join(f'# {key} {v}' for key,v in (
  ('tests',tests),('pass',passed),('fail',fail),('cancelled',cancelled),('skipped',skipped),('todo',todo)))
def test_skip_not_failure():
 out=node.parse(tap());assert out['status']=='PASS' and out['skipped']==1 and out['pass']==2
def test_failure_still_fails():
 assert node.parse(tap(passed=1,fail=1))['status']=='FAIL'
def test_no_tests_fails():
 with pytest.raises(ValueError):node.parse(tap(tests=0,passed=0,skipped=0))
def test_missing_summary_fails():
 with pytest.raises(ValueError):node.parse('# tests 3\n# pass 3\n')
def test_inconsistent_totals_fail():
 with pytest.raises(ValueError):node.parse(tap(tests=2,passed=2,skipped=1))


def test_unreported_results_fail():
 with pytest.raises(ValueError):node.parse(tap(tests=4,passed=2,skipped=1))
