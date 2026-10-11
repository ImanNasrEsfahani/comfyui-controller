"""Source-pinned patch and Worker asset inheritance sanity checks, synthetic only."""
import sys
import sqlite3
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'scripts/phase03_prepare_checkout.py'
spec=importlib.util.spec_from_file_location('phase03_installer',PATH)
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)

RECORD_ANCHOR='''def save_assets(c, assets):
    for asset in assets:
        fields = list(asset)
        c.execute("INSERT INTO job_assets(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ") ON CONFLICT(job_id,storage_key) DO NOTHING", list(asset.values()))'''


def test_main_patch_inserts_router_first():
    text='import os\n'+patch.IMPORT_ANCHOR+'\n'+patch.APP_ANCHOR+'\n# existing legacy routes\n'
    result=patch.transform(text)
    assert result.index('app.include_router(owner_router)') < result.index('# existing legacy routes')
    assert 'app.include_router(auth_router)' in result


def test_main_patch_refuses_unexpected_anchor():
    import pytest
    with pytest.raises(RuntimeError):patch.transform('from fastapi import FastAPI\n')


def test_worker_results_inherit_owner_and_never_trust_worker_metadata():
    c=sqlite3.connect(':memory:')
    c.row_factory=sqlite3.Row
    c.executescript('''CREATE TABLE jobs(id TEXT PRIMARY KEY,owner_user_id TEXT,ownership_state TEXT);
      CREATE TABLE job_assets(asset_id TEXT PRIMARY KEY,job_id TEXT,storage_key TEXT,
        status TEXT,owner_user_id TEXT,ownership_state TEXT,UNIQUE(job_id,storage_key));''')
    c.execute("INSERT INTO jobs VALUES ('jA','user-A','verified')")
    c.execute("INSERT INTO jobs VALUES ('jQ',NULL,'unclaimed')")
    exec(patch.transform_records(RECORD_ANCHOR),globals(),locals_copy:={})
    save=locals_copy['save_assets']
    save(c,[dict(asset_id='a1',job_id='jA',storage_key='outputs/jA/a1.png',status='available',
                 owner_user_id='user-B',ownership_state='verified')])
    row=c.execute("SELECT owner_user_id,ownership_state FROM job_assets WHERE asset_id='a1'").fetchone()
    assert tuple(row)==('user-A','verified')
    save(c,[dict(asset_id='q1',job_id='jQ',storage_key='outputs/jQ/q1.png',status='available')])
    row=c.execute("SELECT owner_user_id,ownership_state FROM job_assets WHERE asset_id='q1'").fetchone()
    assert tuple(row)==(None,'unclaimed')


def test_worker_legacy_compatible_without_owner_columns():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
    c.executescript('''CREATE TABLE jobs(id TEXT PRIMARY KEY);
      CREATE TABLE job_assets(asset_id TEXT PRIMARY KEY,job_id TEXT,storage_key TEXT,status TEXT,
        UNIQUE(job_id,storage_key));''')
    c.execute("INSERT INTO jobs VALUES ('legacy')")
    local={};exec(patch.transform_records(RECORD_ANCHOR),{},local)
    local['save_assets'](c,[dict(asset_id='old',job_id='legacy',storage_key='outputs/legacy/old.png',status='available')])
    assert c.execute("SELECT count(*) FROM job_assets").fetchone()[0]==1
