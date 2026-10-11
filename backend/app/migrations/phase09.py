"""Explicit additive schema for offline/staging SQLite COPY. No startup migrations."""
from __future__ import annotations
import hashlib, sqlite3
from datetime import datetime,timezone
REVISION='009_versioned_safe_workflows'
DDL=(
 '''CREATE TABLE workflow_definitions (id TEXT PRIMARY KEY,title TEXT NOT NULL,intent TEXT NOT NULL,
 scope TEXT NOT NULL CHECK(scope IN ('user','system')),owner_user_id TEXT REFERENCES users(id),
 active_version_id TEXT,created_at TEXT NOT NULL,
 CHECK((scope='user' AND owner_user_id IS NOT NULL) OR (scope='system' AND owner_user_id IS NULL)))''',
 '''CREATE TABLE workflow_versions (id TEXT PRIMARY KEY,definition_id TEXT NOT NULL REFERENCES workflow_definitions(id),
 version INTEGER NOT NULL CHECK(version>0),model_version_id TEXT NOT NULL REFERENCES model_versions(id),
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','validated','published','deprecated')),
 graph_json TEXT NOT NULL,graph_checksum TEXT NOT NULL CHECK(length(graph_checksum)=64),
 compiled_template_json TEXT,compiled_hash TEXT,created_by TEXT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,validated_at TEXT,published_at TEXT,
 UNIQUE(definition_id,version))''',
 '''CREATE INDEX idx_workflow_versions_definition ON workflow_versions(definition_id,version DESC)''',
 '''CREATE INDEX idx_workflow_definitions_owner ON workflow_definitions(owner_user_id,created_at DESC)''',
 '''CREATE TRIGGER protect_published_workflow BEFORE UPDATE ON workflow_versions
 WHEN OLD.status IN ('published','deprecated') BEGIN SELECT RAISE(ABORT,'published workflow version immutable'); END''',
 '''CREATE TRIGGER protect_workflow_version_delete BEFORE DELETE ON workflow_versions
 BEGIN SELECT RAISE(ABORT,'workflow version deletion prohibited'); END''',
 '''CREATE TABLE workflow_compilations (id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL REFERENCES users(id),
 client_request_id TEXT NOT NULL, request_hash TEXT NOT NULL,workflow_version_id TEXT NOT NULL REFERENCES workflow_versions(id),
 model_version_id TEXT NOT NULL REFERENCES model_versions(id), graph_json TEXT NOT NULL, graph_hash TEXT NOT NULL,
 snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(owner_user_id,client_request_id))''',
 '''CREATE INDEX idx_workflow_compilation_owner ON workflow_compilations(owner_user_id,created_at DESC)''',
 '''CREATE TRIGGER protect_workflow_compilation_update BEFORE UPDATE ON workflow_compilations BEGIN SELECT RAISE(ABORT,'immutable compile snapshot'); END''',
 '''CREATE TRIGGER protect_workflow_compilation_delete BEFORE DELETE ON workflow_compilations BEGIN SELECT RAISE(ABORT,'immutable compile snapshot'); END''',
 '''CREATE TABLE workflow_audit (id TEXT PRIMARY KEY,actor_id TEXT NOT NULL REFERENCES users(id),
 action TEXT NOT NULL,definition_id TEXT,version_id TEXT,created_at TEXT NOT NULL)''',
 '''CREATE TRIGGER protect_workflow_audit_update BEFORE UPDATE ON workflow_audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END''',
 '''CREATE TRIGGER protect_workflow_audit_delete BEFORE DELETE ON workflow_audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END''',
)
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()
def migrate(c:sqlite3.Connection)->bool:
 c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000');c.execute('BEGIN IMMEDIATE')
 try:
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  required={'schema_migrations','users','model_versions','workflows','jobs','model_deployment_compatibility'}
  if not required<=tables:raise RuntimeError('Prerequisite identity, model registry and jobs tables missing')
  row=c.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
  if row:
   if row['checksum']!=CHECKSUM:raise RuntimeError('Phase09 schema checksum mismatch')
   c.commit();return False
  for sql in DDL:c.execute(sql)
  c.execute('INSERT INTO schema_migrations VALUES(?,?,?)',(REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('Foreign key violations')
  c.commit();return True
 except BaseException:c.rollback();raise
