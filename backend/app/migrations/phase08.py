"""Phase08 additive SQL. Explicit invocation against an OFFLINE SQLite COPY only."""
from __future__ import annotations
import hashlib,sqlite3
from datetime import datetime,timezone
REVISION='008_dynamic_parameters_loras_presets'
DDL=(
 '''CREATE TABLE model_parameter_schemas(id TEXT PRIMARY KEY,model_id TEXT NOT NULL REFERENCES model_versions(id),workflow_id TEXT NOT NULL REFERENCES workflows(id),workflow_version TEXT NOT NULL,schema_json TEXT NOT NULL,schema_hash TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),created_at TEXT NOT NULL,UNIQUE(model_id,workflow_id,workflow_version,schema_hash))''',
 '''CREATE INDEX idx_parameter_schema_lookup ON model_parameter_schemas(model_id,workflow_id,status)''',
 '''CREATE TRIGGER parameter_schema_payload_immutable BEFORE UPDATE OF model_id,workflow_id,workflow_version,schema_json,schema_hash ON model_parameter_schemas BEGIN SELECT RAISE(ABORT,'immutable parameter schema'); END''',
 '''CREATE TABLE lora_versions(id TEXT PRIMARY KEY,family_id TEXT NOT NULL REFERENCES model_families(id),name TEXT NOT NULL,revision TEXT NOT NULL,artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),logical_name TEXT NOT NULL,size_bytes INTEGER NOT NULL CHECK(size_bytes>0),min_strength REAL NOT NULL,max_strength REAL NOT NULL,trigger_words_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','tested','deprecated')),created_at TEXT NOT NULL,UNIQUE(family_id,name,revision),CHECK(min_strength<=max_strength))''',
 '''CREATE TRIGGER lora_version_immutable BEFORE UPDATE OF family_id,name,revision,artifact_sha256,logical_name,size_bytes,min_strength,max_strength,trigger_words_json ON lora_versions BEGIN SELECT RAISE(ABORT,'immutable lora version'); END''',
 '''CREATE TABLE model_lora_compatibility(model_id TEXT NOT NULL REFERENCES model_versions(id),lora_id TEXT NOT NULL REFERENCES lora_versions(id),state TEXT NOT NULL DEFAULT 'unknown' CHECK(state IN ('unknown','tested_pass','tested_fail')),evidence_ref TEXT,tested_at TEXT,PRIMARY KEY(model_id,lora_id),CHECK(state!='tested_pass' OR (evidence_ref IS NOT NULL AND tested_at IS NOT NULL)))''',
 '''CREATE TABLE lora_installations(image_id TEXT NOT NULL REFERENCES worker_images(id),lora_id TEXT NOT NULL REFERENCES lora_versions(id),state TEXT NOT NULL DEFAULT 'unknown' CHECK(state IN ('unknown','verified','missing')),observed_sha256 TEXT,tested_at TEXT,PRIMARY KEY(image_id,lora_id),CHECK(state!='verified' OR (observed_sha256 IS NOT NULL AND tested_at IS NOT NULL)))''',
 '''CREATE TABLE user_parameter_presets(id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL REFERENCES users(id),model_id TEXT NOT NULL REFERENCES model_versions(id),workflow_id TEXT NOT NULL REFERENCES workflows(id),workflow_version TEXT NOT NULL,schema_hash TEXT NOT NULL,name TEXT NOT NULL,values_json TEXT NOT NULL,includes_prompt INTEGER NOT NULL DEFAULT 0 CHECK(includes_prompt IN (0,1)),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,deleted_at TEXT)''',
 '''CREATE INDEX idx_parameter_preset_owner ON user_parameter_presets(owner_user_id,created_at DESC)''',
 '''CREATE TABLE parameter_intents(id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL REFERENCES users(id),client_request_id TEXT NOT NULL,request_hash TEXT NOT NULL,model_id TEXT NOT NULL REFERENCES model_versions(id),workflow_id TEXT NOT NULL REFERENCES workflows(id),schema_hash TEXT NOT NULL,snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(owner_user_id,client_request_id))''',
 '''CREATE INDEX idx_parameter_intents_owner ON parameter_intents(owner_user_id,created_at DESC)''',
 '''CREATE TRIGGER parameter_intent_immutable BEFORE UPDATE ON parameter_intents BEGIN SELECT RAISE(ABORT,'immutable resolved intent'); END''',
 '''CREATE TRIGGER parameter_intent_no_delete BEFORE DELETE ON parameter_intents BEGIN SELECT RAISE(ABORT,'immutable resolved intent'); END''',
)
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()
def migrate(c:sqlite3.Connection)->bool:
 c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000');c.execute('BEGIN IMMEDIATE')
 try:
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  required={'schema_migrations','users','workflows','model_versions','model_families','worker_images','deployment_profiles','user_roles'}
  if not required<=tables:raise RuntimeError('Phase01/07 migrations required before Phase08')
  existing=c.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
  if existing:
   if existing['checksum']!=CHECKSUM:raise RuntimeError('Phase08 migration checksum mismatch')
   c.commit();return False
  for statement in DDL:c.execute(statement)
  c.execute('INSERT INTO schema_migrations VALUES(?,?,?)',(REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('Foreign key integrity failure')
  c.commit();return True
 except BaseException:c.rollback();raise
