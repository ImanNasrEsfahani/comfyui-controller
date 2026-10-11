"""Phase06 additive asset variants/reuse/deletion schema. EXPLICIT offline migration only."""
from __future__ import annotations
import hashlib, sqlite3
from datetime import datetime,timezone
REVISION='006_private_gallery'
DDL=(
 '''CREATE TABLE asset_variants (
 id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, owner_user_id TEXT NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL CHECK(kind IN ('thumbnail','poster','preview_proxy')),
 storage_key TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL,
 width INTEGER, height INTEGER, size_bytes INTEGER NOT NULL CHECK(size_bytes>0),
 verified_at TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(asset_id,owner_user_id,kind))''',
 '''CREATE INDEX idx_variants_asset ON asset_variants(owner_user_id,asset_id)''',
 '''CREATE TRIGGER guard_variant_owner BEFORE INSERT ON asset_variants BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM input_assets i WHERE i.asset_id=NEW.asset_id
 AND i.owner_user_id=NEW.owner_user_id AND i.ownership_state='verified')
 AND NOT EXISTS(SELECT 1 FROM job_assets a JOIN jobs j ON j.id=a.job_id
 WHERE a.asset_id=NEW.asset_id AND a.owner_user_id=NEW.owner_user_id AND a.ownership_state='verified'
 AND j.owner_user_id=NEW.owner_user_id AND j.ownership_state='verified'
 AND a.status='available' AND j.hidden=0)
 THEN RAISE(ABORT,'variant asset owner not verified') END;
 END''',
 '''CREATE TABLE asset_deletions (
 asset_id TEXT NOT NULL, owner_user_id TEXT NOT NULL REFERENCES users(id),
 deleted_at TEXT NOT NULL, PRIMARY KEY(asset_id,owner_user_id))''',
 '''CREATE INDEX idx_asset_deletions_user ON asset_deletions(owner_user_id,deleted_at)''',
 '''CREATE TABLE job_input_assets (
 job_id TEXT NOT NULL REFERENCES jobs(id), slot_key TEXT NOT NULL, position INTEGER NOT NULL CHECK(position>=0),
 asset_id TEXT NOT NULL, owner_user_id TEXT NOT NULL REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('identity','clothing','pose','background','mask','start_frame','end_frame','reference')),
 source_job_id TEXT REFERENCES jobs(id), bound_at TEXT NOT NULL,
 PRIMARY KEY(job_id,slot_key,position))''',
 '''CREATE INDEX idx_input_asset_reference ON job_input_assets(owner_user_id,asset_id)''',
 '''CREATE TRIGGER guard_reference_owner BEFORE INSERT ON job_input_assets BEGIN
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM jobs WHERE id=NEW.job_id AND owner_user_id=NEW.owner_user_id
 AND ownership_state='verified' AND hidden=0) THEN RAISE(ABORT,'invalid destination owner') END;
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM input_assets WHERE asset_id=NEW.asset_id AND owner_user_id=NEW.owner_user_id
 AND ownership_state='verified') AND NOT EXISTS (SELECT 1 FROM job_assets a JOIN jobs j ON j.id=a.job_id
 WHERE a.asset_id=NEW.asset_id AND a.owner_user_id=NEW.owner_user_id AND a.ownership_state='verified'
 AND a.status='available' AND j.owner_user_id=NEW.owner_user_id AND j.ownership_state='verified' AND j.hidden=0
 AND (j.active_attempt_id IS NULL OR a.attempt_id=j.active_attempt_id))
 THEN RAISE(ABORT,'asset owner not verified') END;
 SELECT CASE WHEN NEW.source_job_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM job_assets src JOIN jobs sj ON sj.id=src.job_id
  WHERE src.asset_id=NEW.asset_id AND src.job_id=NEW.source_job_id
  AND src.owner_user_id=NEW.owner_user_id AND src.ownership_state='verified'
  AND src.status='available' AND sj.owner_user_id=NEW.owner_user_id
  AND sj.ownership_state='verified') THEN RAISE(ABORT,'source Job does not own output') END;
 SELECT CASE WHEN EXISTS (SELECT 1 FROM asset_deletions WHERE asset_id=NEW.asset_id
 AND owner_user_id=NEW.owner_user_id) THEN RAISE(ABORT,'asset was deleted') END;
 END''',
 '''CREATE TRIGGER guard_reference_immutable BEFORE UPDATE ON job_input_assets BEGIN SELECT RAISE(ABORT,'immutable reference'); END''',
 '''CREATE TRIGGER guard_reference_no_delete BEFORE DELETE ON job_input_assets BEGIN SELECT RAISE(ABORT,'immutable reference'); END''',
)
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()

def migrate(conn:sqlite3.Connection)->bool:
 conn.row_factory=sqlite3.Row
 conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA busy_timeout=5000')
 conn.execute('BEGIN IMMEDIATE')
 try:
  required={'schema_migrations','users','jobs','job_assets','input_assets'}
  actual={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not required.issubset(actual):raise RuntimeError('Phase01/02/03 verified schema is required')
  for name in ('jobs','input_assets','job_assets'):
   cols={r[1] for r in conn.execute(f'PRAGMA table_info({name})')}
   if not {'owner_user_id','ownership_state'}.issubset(cols):raise RuntimeError('Owner columns missing')
  old=conn.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
  if old:
   if old['checksum']!=CHECKSUM:raise RuntimeError('Migration checksum changed')
   conn.commit();return False
  for ddl in DDL:conn.execute(ddl)
  conn.execute('INSERT INTO schema_migrations(revision,applied_at,checksum) VALUES(?,?,?)',
               (REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
  if list(conn.execute('PRAGMA foreign_key_check')):raise RuntimeError('Foreign key errors')
  conn.commit();return True
 except BaseException:
  conn.rollback();raise
