"""Additive Phase10 Studio editor state; apply explicitly to a copied SQLite database.

The Phase09 validated/published graph is immutable history; incomplete Studio edits
stay in a separate, access-controlled working draft until explicitly validated.
"""
from __future__ import annotations
import hashlib,sqlite3
from datetime import datetime,timezone
REVISION='010_workflow_studio'
DDL=(
 '''CREATE TABLE studio_drafts (
 version_id TEXT PRIMARY KEY REFERENCES workflow_versions(id),
 revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
 graph_json TEXT NOT NULL, layout_json TEXT NOT NULL, viewport_json TEXT NOT NULL,
 base_checksum TEXT NOT NULL CHECK(length(base_checksum)=64),
 editor_user_id TEXT NOT NULL REFERENCES users(id),updated_at TEXT NOT NULL)''',
 '''CREATE INDEX idx_studio_editor ON studio_drafts(editor_user_id,updated_at DESC)''',
 '''CREATE TRIGGER studio_drafts_no_published_insert BEFORE INSERT ON studio_drafts
 WHEN (SELECT status FROM workflow_versions WHERE id=NEW.version_id) IN ('published','deprecated')
 BEGIN SELECT RAISE(ABORT,'published studio version immutable'); END''',
 '''CREATE TRIGGER studio_drafts_no_published_update BEFORE UPDATE ON studio_drafts
 WHEN (SELECT status FROM workflow_versions WHERE id=NEW.version_id) IN ('published','deprecated')
 BEGIN SELECT RAISE(ABORT,'published studio version immutable'); END''',
)
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()
def migrate(c:sqlite3.Connection)->bool:
 c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000');c.execute('BEGIN IMMEDIATE')
 try:
  names={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not {'workflow_versions','workflow_definitions','workflow_audit','schema_migrations','users'}<=names:
   raise RuntimeError('Phase09 identity and workflow migrations required')
  row=c.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
  if row:
   if row['checksum']!=CHECKSUM:raise RuntimeError('Phase10 checksum mismatch')
   c.commit();return False
  for ddl in DDL:c.execute(ddl)
  c.execute('INSERT INTO schema_migrations(revision,applied_at,checksum) VALUES(?,?,?)',
   (REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('FK validation failed')
  c.commit();return True
 except BaseException:c.rollback();raise
