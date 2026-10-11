"""Opt-in Phase07 catalog schema; never invoked during startup or on production automatically."""
import sqlite3,hashlib
from datetime import datetime,timezone
REVISION='007_model_image_registry'
DDL=(
'''CREATE TABLE model_families(id TEXT PRIMARY KEY,name TEXT NOT NULL,vendor TEXT NOT NULL,modality TEXT NOT NULL CHECK(modality IN ('image','video','multimodal')),description TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)''',
'''CREATE TABLE model_versions(id TEXT PRIMARY KEY,family_id TEXT NOT NULL REFERENCES model_families(id),revision TEXT NOT NULL,license_id TEXT NOT NULL,artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),precision TEXT NOT NULL,vram_gb INTEGER NOT NULL CHECK(vram_gb>0),capabilities_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','testing','ready','degraded','deprecated')),created_at TEXT NOT NULL,UNIQUE(family_id,revision))''',
'''CREATE TABLE model_artifacts(id TEXT PRIMARY KEY,model_id TEXT NOT NULL REFERENCES model_versions(id),kind TEXT NOT NULL,sha256 TEXT NOT NULL CHECK(length(sha256)=64),size_bytes INTEGER NOT NULL CHECK(size_bytes>0),logical_name TEXT NOT NULL)''',
'''CREATE TABLE worker_images(id TEXT PRIMARY KEY,name TEXT NOT NULL,repo TEXT NOT NULL,tag TEXT NOT NULL,digest TEXT NOT NULL UNIQUE,build_sha TEXT,node_inventory_json TEXT NOT NULL,comfyui_version TEXT,signature_status TEXT NOT NULL DEFAULT 'unknown' CHECK(signature_status IN ('unknown','verified','failed')),status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','testing','approved','deprecated')),created_at TEXT NOT NULL)''',
'''CREATE TRIGGER worker_digest_immutable BEFORE UPDATE OF digest,repo,tag ON worker_images BEGIN SELECT RAISE(ABORT,'immutable image identity'); END''',
'''CREATE TABLE image_model_compatibility(image_id TEXT NOT NULL REFERENCES worker_images(id),model_id TEXT NOT NULL REFERENCES model_versions(id),state TEXT NOT NULL DEFAULT 'unknown' CHECK(state IN ('unknown','tested_pass','tested_fail')),evidence_ref TEXT,tested_at TEXT,PRIMARY KEY(image_id,model_id),CHECK(state!='tested_pass' OR (evidence_ref IS NOT NULL AND tested_at IS NOT NULL)))''',
'''CREATE TABLE gpu_profiles(id TEXT PRIMARY KEY,name TEXT NOT NULL,gpu_family TEXT NOT NULL,provider TEXT NOT NULL CHECK(provider='salad'),vram_gb INTEGER NOT NULL CHECK(vram_gb>0),ram_gb INTEGER NOT NULL CHECK(ram_gb>0),cpu_count INTEGER NOT NULL CHECK(cpu_count>0),disk_gb INTEGER NOT NULL CHECK(disk_gb>0),shm_mb INTEGER NOT NULL CHECK(shm_mb>0))''',
'''CREATE TABLE deployment_profiles(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,active_revision_id TEXT,created_at TEXT NOT NULL)''',
'''CREATE TABLE deployment_profile_revisions(id TEXT PRIMARY KEY,profile_id TEXT NOT NULL REFERENCES deployment_profiles(id),version INTEGER NOT NULL,image_id TEXT NOT NULL REFERENCES worker_images(id),gpu_id TEXT NOT NULL REFERENCES gpu_profiles(id),config_json TEXT NOT NULL,env_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','validated','approved','active','retired')),created_by TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,UNIQUE(profile_id,version))''',
'''CREATE TRIGGER revision_payload_immutable BEFORE UPDATE OF image_id,gpu_id,config_json,env_json,profile_id,version,created_by ON deployment_profile_revisions BEGIN SELECT RAISE(ABORT,'immutable revision'); END''',
'''CREATE TABLE deployment_variable_schema(key TEXT PRIMARY KEY,value_type TEXT NOT NULL,default_json TEXT,enum_json TEXT,min_value REAL,max_value REAL,secret INTEGER NOT NULL DEFAULT 0,restart_required INTEGER NOT NULL DEFAULT 1,scope TEXT NOT NULL)''',
'''CREATE TABLE model_deployment_compatibility(model_id TEXT NOT NULL REFERENCES model_versions(id),revision_id TEXT NOT NULL REFERENCES deployment_profile_revisions(id),state TEXT NOT NULL DEFAULT 'unknown' CHECK(state IN ('unknown','tested_pass','tested_fail')),evidence_ref TEXT,tested_at TEXT,PRIMARY KEY(model_id,revision_id),CHECK(state!='tested_pass' OR (evidence_ref IS NOT NULL AND tested_at IS NOT NULL)))''',
'''CREATE TABLE registry_audit(id TEXT PRIMARY KEY,actor_id TEXT REFERENCES users(id),action TEXT NOT NULL,resource_id TEXT NOT NULL,at TEXT NOT NULL)''',
'''CREATE TRIGGER registry_audit_protect_update BEFORE UPDATE ON registry_audit BEGIN SELECT RAISE(ABORT,'audit immutable'); END''',
'''CREATE TRIGGER registry_audit_protect_delete BEFORE DELETE ON registry_audit BEGIN SELECT RAISE(ABORT,'audit immutable'); END''',
'''CREATE INDEX registry_model_family ON model_versions(family_id,status)''',
'''CREATE INDEX registry_profile_revision ON deployment_profile_revisions(profile_id,version DESC)''',
)
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()
VARS=[('COMFYUI_PORT','integer','3000',None,1,65535,0,1,'profile'),('WORKER_MODE','enum','"direct"','["direct","queue"]',None,None,0,1,'profile'),('LOG_LEVEL','enum','"INFO"','["DEBUG","INFO","WARNING","ERROR"]',None,None,0,1,'profile'),('WORKER_CONCURRENCY','integer','1',None,1,8,0,1,'profile'),('R2_ACCESS_KEY_REF','secret',None,None,None,None,1,1,'profile')]
def migrate(c:sqlite3.Connection)->bool:
 c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000');c.execute('BEGIN IMMEDIATE')
 try:
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not {'users','schema_migrations','jobs','account_audit_logs'}<=tables:raise RuntimeError('Prerequisite Phase01/05 tables unavailable')
  old=c.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
  if old:
   if old['checksum']!=CHECKSUM:raise RuntimeError('Migration checksum mismatch')
   c.commit();return False
  for sql in DDL:c.execute(sql)
  c.executemany('INSERT INTO deployment_variable_schema VALUES(?,?,?,?,?,?,?,?,?)',VARS)
  c.execute('INSERT INTO schema_migrations VALUES(?,?,?)',(REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('Foreign key mismatch')
  c.commit();return True
 except BaseException:c.rollback();raise
