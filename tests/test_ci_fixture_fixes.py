"""SHA-locked fixture patcher verifies auth is not weakened by CI repair."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ci_fixtures',ROOT/'scripts/ci_fixture_fixes.py')
fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(fx)

AXIS='TEST_ENV = {\n' + fx.AXIS_ANCHOR + '\n}\n'
UPGRADE='def demo(self):\n' + ''.join('    '+x+'\n' for x in fx.UPGRADE_REPLACEMENTS)

def make(tmp_path,monkeypatch):
    samples={'tests/test_axis_04.py':AXIS,'tests/check_frontend_backend_upgrade.py':UPGRADE}
    for p,c in samples.items():
        dest=tmp_path/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(c)
    monkeypatch.setattr(fx,'BASE_BLOBS',{p:fx.blob(v.encode()) for p,v in samples.items()})
    return samples

def test_only_two_expected_files(monkeypatch,tmp_path):
    files=make(tmp_path,monkeypatch)
    assert fx.run(tmp_path)==0
    for p,original in files.items():assert (tmp_path/p).read_text()==original
    assert fx.run(tmp_path,apply=True)==0
    assert fx.run(tmp_path,check=True)==0
    assert fx.run(tmp_path,apply=True)==0
    assert fx.run(tmp_path,check=True)==0
    for p in files:compile((tmp_path/p).read_text(),p,'exec')

def test_admin_access_not_bypassed(monkeypatch,tmp_path):
    make(tmp_path,monkeypatch)
    fx.run(tmp_path,apply=True)
    c=(tmp_path/'tests/check_frontend_backend_upgrade.py').read_text()
    for new in fx.UPGRADE_REPLACEMENTS.values():assert new in c
    assert 'headers=ADMIN' in c
    assert 'self.client.get("/api/jobs")' not in c
    assert 'self.client.get("/api/salad/instances")' not in c

def test_refuse_unreviewed_changes(monkeypatch,tmp_path):
    make(tmp_path,monkeypatch)
    p=tmp_path/'tests/test_axis_04.py';p.write_text(p.read_text()+'# surprise\n')
    with pytest.raises(RuntimeError): fx.run(tmp_path,apply=True)
    assert not fx.AXIS_EXTRA in p.read_text()

def test_wrong_or_missing_fixture_fails(monkeypatch,tmp_path):
    make(tmp_path,monkeypatch)
    with pytest.raises(RuntimeError): fx.run(tmp_path,check=True)
    (tmp_path/'tests/check_frontend_backend_upgrade.py').unlink()
    with pytest.raises(RuntimeError): fx.run(tmp_path,apply=True)

def test_git_blob_matches_grounded_commit():
    assert fx.BASE_BLOBS['tests/test_axis_04.py']=='fedc4ed639ff0be94b375b72d1816b2964763b2f'
    assert fx.BASE_BLOBS['tests/check_frontend_backend_upgrade.py']=='afcceb5944eb731f37e676b4ae4db9ac6c6df013'
