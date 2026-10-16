"""Offline safety and data-integrity tests for the optional Phase07 draft importer."""
from __future__ import annotations
import importlib.util
import json
import sqlite3
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('model_onboarding', HERE / 'scripts/model_onboarding.py')
onboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(onboard)


def seeded(tmp_path):
    path = tmp_path / 'controller.sqlite3'
    with sqlite3.connect(path) as c:
        c.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE workflows(id TEXT PRIMARY KEY,name TEXT NOT NULL,api_prompt TEXT NOT NULL);
        CREATE TABLE model_families(id TEXT PRIMARY KEY,name TEXT NOT NULL,vendor TEXT NOT NULL,
          modality TEXT NOT NULL,description TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE model_versions(id TEXT PRIMARY KEY,family_id TEXT REFERENCES model_families(id),
          revision TEXT NOT NULL,license_id TEXT NOT NULL,artifact_sha256 TEXT NOT NULL,
          precision TEXT NOT NULL,vram_gb INTEGER NOT NULL,capabilities_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL,UNIQUE(family_id,revision));
        CREATE TABLE model_artifacts(id TEXT PRIMARY KEY,model_id TEXT,kind TEXT,sha256 TEXT,size_bytes INTEGER,logical_name TEXT);
        ''')
        c.execute("INSERT INTO workflows VALUES(?,?,?)",(
            'legacy-1','Legacy portrait',json.dumps({
                '1': {'class_type':'CheckpointLoaderSimple', 'inputs':{'ckpt_name':'models/portrait.safetensors'}},
                '2': {'class_type':'KSampler','inputs':{'seed':123}},
            })))
    return path


def manifest():
    return {'format':'comfyui-model-draft-import-v1','models':[
        {'family':{'name':'RealModel','vendor':'Example','modality':'image','description':'Offline test'},
         'model':{'revision':'1.0','license_id':'MIT','artifact_sha256':'ab'*32,
                  'precision':'fp8','vram_gb':24,'capabilities':{'supports_image':True}}}
    ]}


def test_legacy_workflow_count_and_sanitized_loader_metadata(tmp_path):
    source=seeded(tmp_path)
    with onboard.connect(source) as c:
        r=onboard.inspect(c)
    assert r['workflows_count']==1
    assert r['counts']['model_versions']==0
    assert r['workflows'][0]['loader_nodes'][0]['filenames']==['portrait.safetensors']
    assert not r['catalog_eligible']
    assert 'prompt' not in json.dumps(r)
    assert onboard.safe_filename('https://private/image?token=secret') is None


def test_missing_verification_is_never_turned_into_ready(tmp_path):
    source=seeded(tmp_path)
    backup=tmp_path/'offline-backup.sqlite3'
    r=onboard.import_drafts(source,manifest(),backup)
    assert r['runtime_verified'] is False
    assert r['catalog_visible'] is False
    assert backup.is_file()
    with onboard.connect(source) as c:
        assert c.execute('SELECT status FROM model_versions').fetchone()[0]=='draft'
        assert c.execute('SELECT COUNT(*) FROM workflows').fetchone()[0]==1
    with pytest.raises(ValueError,match='NEW'):
        onboard.import_drafts(source,manifest(),backup)
    assert onboard.import_drafts(source,manifest(),tmp_path/'second-backup.sqlite3')['models'][0]['result']=='unchanged'


def test_invalid_manifest_does_not_touch_database(tmp_path):
    source=seeded(tmp_path)
    backup=tmp_path/'unused-backup.sqlite3'
    bad=manifest();bad['models'][0]['model']['artifact_sha256']='0'*64
    with pytest.raises(ValueError):onboard.import_drafts(source,bad,backup)
    assert not backup.exists()
    with onboard.connect(source) as c:
        assert c.execute('SELECT count(*) FROM model_versions').fetchone()[0]==0


def test_conflicting_revision_rolls_back(tmp_path):
    source=seeded(tmp_path)
    onboard.import_drafts(source,manifest(),tmp_path/'first.sqlite3')
    bad=manifest();bad['models'][0]['model']['artifact_sha256']='cd'*32
    with pytest.raises(ValueError,match='immutable metadata'):
        onboard.import_drafts(source,bad,tmp_path/'different.sqlite3')
    with onboard.connect(source) as c:
        assert c.execute('SELECT COUNT(*) FROM model_versions').fetchone()[0]==1


def test_reviewed_stop_mock_is_sha_pinned_and_auth_asserted(tmp_path):
    spec=importlib.util.spec_from_file_location('ci_fixture_fixes', HERE/'scripts/ci_fixture_fixes.py')
    fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(fx)
    fixture=(HERE/'tests/check_frontend_backend_upgrade.py').read_bytes()
    assert fx.is_reviewed_stop_test(fixture)
    assert not fx.is_reviewed_stop_test(fixture+b'# unreviewed change\n')
