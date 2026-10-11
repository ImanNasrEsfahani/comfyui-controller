from pathlib import Path
import importlib.util,sqlite3
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('phase14_db',ROOT/'scripts/phase14_db_drill.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def make_db(tmp_path,*,with_bad=False):
    path=tmp_path/'isolated.sqlite3';c=sqlite3.connect(path)
    c.executescript('''PRAGMA foreign_keys=ON;
    CREATE TABLE users(id TEXT PRIMARY KEY);
    CREATE TABLE jobs(id TEXT PRIMARY KEY,owner_user_id TEXT,ownership_state TEXT);
    CREATE TABLE input_assets(id TEXT PRIMARY KEY,owner_user_id TEXT);
    INSERT INTO users VALUES('A');
    INSERT INTO users VALUES('B');
    INSERT INTO jobs VALUES('j1','A','verified');
    INSERT INTO input_assets VALUES('a1','B');''')
    if with_bad:c.execute("INSERT INTO jobs VALUES('j2',NULL,'unknown')")
    c.commit();c.close();return path

def test_requires_explicit_isolated_ack(tmp_path):
    with pytest.raises(ValueError,match='acknowledge'):m.drill(make_db(tmp_path))

def test_dry_restore_source_unchanged(tmp_path):
    db=make_db(tmp_path);before=m.digest(db)
    r=m.drill(db,acknowledged=True)
    assert r['status']=='PASS_OFFLINE_ONLY' and r['count_parity']
    assert r['foreign_key_violations']==0 and r['integrity_check']=='ok'
    assert r['source_sha256']==before==m.digest(db)
    assert r['counts']['jobs']==1 and r['production_restore_verified'] is False

def test_unowned_job_blocks(tmp_path):
    r=m.drill(make_db(tmp_path,with_bad=True),True)
    assert r['status']=='BLOCKED' and r['owner_audit']['jobs']['unverified_count']==1

def test_wal_copy_refusal(tmp_path):
    db=make_db(tmp_path);Path(str(db)+'-wal').touch()
    with pytest.raises(ValueError,match='WAL/SHM'):m.drill(db,True)

def test_invalid_sqlite_refusal(tmp_path):
    db=tmp_path/'fake.sqlite3';db.write_bytes(b'Z'*200)
    with pytest.raises(sqlite3.DatabaseError):m.drill(db,True)

def test_no_user_ids_in_evidence(tmp_path):
    r=m.drill(make_db(tmp_path),True)
    assert '"A"' not in str(r) and '"B"' not in str(r)
