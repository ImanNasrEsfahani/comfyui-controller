from pathlib import Path
import hashlib,importlib.util,sqlite3
import pytest
from test_phase13_api import make_db
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('m13',ROOT/'backend/app/migrations/phase13.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
spec2=importlib.util.spec_from_file_location('m13copy',ROOT/'scripts/phase13_migrate_copy.py');cp=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(cp)

def test_first_second_migration():
 c=make_db();assert m.migrate(c) is True;assert m.migrate(c) is False
 assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not list(c.execute('PRAGMA foreign_key_check'))
 c.close()

def test_ownership_provenance_and_immutability():
 c=make_db();m.migrate(c)
 base=['videoA','A','input','video/mp4','h264',128,128,1,10,400,'a'*64,'2026-01-01']
 with pytest.raises(sqlite3.IntegrityError):c.execute('INSERT INTO video_media_details VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',[base[0],'B',*base[2:]])
 c.execute('INSERT INTO video_media_details VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',base)
 with pytest.raises(sqlite3.IntegrityError):c.execute('UPDATE video_media_details SET codec=? WHERE asset_id=?',('av1','videoA'))
 with pytest.raises(sqlite3.IntegrityError):c.execute('DELETE FROM video_media_details WHERE asset_id=?',('videoA',))
 with pytest.raises(sqlite3.IntegrityError):
  c.execute('INSERT INTO video_transcode_tasks(id,asset_id,owner_user_id,kind,status,created_at) VALUES(?,?,?,?,?,?)',('t','videoA','B','poster','pending','2026-01-01'))
 c.close()

def test_source_is_unchanged_copy(tmp_path):
 source=tmp_path/'source.db';dest=tmp_path/'copy.db'
 c=make_db();target=sqlite3.connect(source);c.backup(target);target.close();c.close()
 old=hashlib.sha256(source.read_bytes()).hexdigest()
 with pytest.raises(RuntimeError):cp.execute(source,dest,False)
 cp.execute(source,dest,True)
 assert hashlib.sha256(source.read_bytes()).hexdigest()==old
 with sqlite3.connect(dest) as d:assert d.execute("SELECT 1 FROM sqlite_master WHERE name='video_transcode_tasks'").fetchone()
 with pytest.raises(RuntimeError):cp.execute(source,dest,True)
