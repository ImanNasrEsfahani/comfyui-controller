"""Opt-in Phase13 video media metadata. Apply only on backup SQLite COPY."""
import hashlib,sqlite3
from datetime import datetime,timezone
REVISION='013_private_video_pipeline'
DDL=(
'''CREATE TABLE video_media_details(asset_id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL REFERENCES users(id),
  origin_kind TEXT NOT NULL CHECK(origin_kind IN ('input','output')),
  mime_type TEXT NOT NULL CHECK(mime_type IN ('video/mp4','video/webm')),
  codec TEXT NOT NULL,width INTEGER NOT NULL CHECK(width>0),height INTEGER NOT NULL CHECK(height>0),
  duration_seconds REAL NOT NULL CHECK(duration_seconds>0),fps REAL NOT NULL CHECK(fps>0),
  size_bytes INTEGER NOT NULL CHECK(size_bytes>0),sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  verified_at TEXT NOT NULL)''',
'''CREATE TRIGGER video_media_owner BEFORE INSERT ON video_media_details BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM input_assets a WHERE NEW.origin_kind='input' AND a.asset_id=NEW.asset_id
    AND a.owner_user_id=NEW.owner_user_id AND a.ownership_state='verified' AND a.mime_type=NEW.mime_type)
  AND NOT EXISTS(SELECT 1 FROM job_assets a JOIN jobs j ON j.id=a.job_id
    WHERE NEW.origin_kind='output' AND a.asset_id=NEW.asset_id AND a.owner_user_id=NEW.owner_user_id AND a.ownership_state='verified'
      AND a.status='available' AND j.owner_user_id=NEW.owner_user_id AND j.ownership_state='verified'
      AND (j.active_attempt_id IS NULL OR a.attempt_id=j.active_attempt_id) AND a.mime_type=NEW.mime_type)
  THEN RAISE(ABORT,'video media owner mismatch') END;
  END''',
'''CREATE TRIGGER video_original_immutable BEFORE UPDATE ON video_media_details BEGIN SELECT RAISE(ABORT,'immutable original video metadata'); END''',
'''CREATE TRIGGER video_original_no_delete BEFORE DELETE ON video_media_details BEGIN SELECT RAISE(ABORT,'video provenance immutable'); END''',
'''CREATE TABLE video_transcode_tasks(id TEXT PRIMARY KEY,asset_id TEXT NOT NULL REFERENCES video_media_details(asset_id),
 owner_user_id TEXT NOT NULL REFERENCES users(id),kind TEXT NOT NULL CHECK(kind IN ('poster','preview_proxy')),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','ready','failed')),
 worker_version TEXT,attempt_id TEXT,verified_storage_key TEXT,sha256 TEXT,error_code TEXT,
 created_at TEXT NOT NULL,finished_at TEXT,
 UNIQUE(asset_id,kind),CHECK(status!='ready' OR (verified_storage_key IS NOT NULL AND sha256 IS NOT NULL)))''',
'''CREATE TRIGGER video_transcode_owner BEFORE INSERT ON video_transcode_tasks BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM video_media_details m WHERE m.asset_id=NEW.asset_id
 AND m.owner_user_id=NEW.owner_user_id) THEN RAISE(ABORT,'video transcode owner mismatch') END; END''',
'''CREATE INDEX video_owner_index ON video_media_details(owner_user_id,verified_at DESC)''',
'''CREATE INDEX video_tasks_owner_status ON video_transcode_tasks(owner_user_id,status)'''
)
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()
def migrate(c:sqlite3.Connection):
 c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000');c.execute('BEGIN IMMEDIATE')
 try:
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not {'schema_migrations','users','jobs','job_assets','input_assets','asset_variants','asset_deletions'}<=tables:
   raise RuntimeError('Phase06 owner-scoped media schema required')
  row=c.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
  if row:
   if row[0]!=CHECKSUM:raise RuntimeError('Phase13 migration checksum mismatch')
   c.commit();return False
  for sql in DDL:c.execute(sql)
  c.execute('INSERT INTO schema_migrations(revision,applied_at,checksum) VALUES(?,?,?)',
   (REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('FK check failed')
  c.commit();return True
 except BaseException:c.rollback();raise
