"""Phase12 opt-in scheduling metadata; only apply to a disposable SQLite backup.

No user/job backfill, existing GPU controller unchanged. Foreign keys ON required.
"""
from __future__ import annotations
import hashlib, sqlite3
from datetime import datetime, timezone
REVISION='012_gpu_scheduler_planning'
DDL=(
'''CREATE TABLE scheduler_profile_policy(
 revision_id TEXT PRIMARY KEY REFERENCES deployment_profile_revisions(id),
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 max_owner_running INTEGER NOT NULL DEFAULT 1 CHECK(max_owner_running BETWEEN 1 AND 8),
 max_owner_queued INTEGER NOT NULL DEFAULT 8 CHECK(max_owner_queued BETWEEN 1 AND 100),
 aging_seconds INTEGER NOT NULL DEFAULT 300 CHECK(aging_seconds BETWEEN 30 AND 86400),
 idle_seconds INTEGER NOT NULL DEFAULT 900 CHECK(idle_seconds BETWEEN 120 AND 86400),
 rate_minor_per_hour INTEGER CHECK(rate_minor_per_hour>=0),
 currency TEXT CHECK(currency IS NULL OR (length(currency)=3 AND currency GLOB '[A-Z][A-Z][A-Z]')),
 CHECK((rate_minor_per_hour IS NULL)=(currency IS NULL)))''',
'''CREATE TABLE scheduler_job_intents(
 job_id TEXT PRIMARY KEY REFERENCES jobs(id),
 owner_user_id TEXT NOT NULL REFERENCES users(id),
 compilation_id TEXT NOT NULL REFERENCES workflow_compilations(id),
 model_version_id TEXT NOT NULL REFERENCES model_versions(id),
 priority_class TEXT NOT NULL DEFAULT 'standard' CHECK(priority_class IN ('standard','entitled_high')),
 disposition TEXT NOT NULL DEFAULT 'eligible' CHECK(disposition IN ('eligible','held')),
 hold_reason TEXT CHECK(hold_reason IS NULL OR hold_reason IN ('quota','budget','manual_review')),
 created_at TEXT NOT NULL,
 CHECK((disposition='held')=(hold_reason IS NOT NULL)))''',
'''CREATE TRIGGER scheduler_intent_owner BEFORE INSERT ON scheduler_job_intents BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM jobs j JOIN users u ON u.id=j.owner_user_id
 WHERE j.id=NEW.job_id AND j.owner_user_id=NEW.owner_user_id AND j.ownership_state='verified'
 AND j.state='pending' AND j.execution_mode='direct' AND u.status='active' AND u.email_verified_at IS NOT NULL)
 THEN RAISE(ABORT,'verified pending owner required') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM workflow_compilations w
 WHERE w.id=NEW.compilation_id AND w.owner_user_id=NEW.owner_user_id AND w.model_version_id=NEW.model_version_id)
 THEN RAISE(ABORT,'compilation owner/model mismatch') END;
 END''',
'''CREATE TRIGGER scheduler_intent_no_owner_change BEFORE UPDATE OF owner_user_id,job_id,compilation_id,model_version_id ON scheduler_job_intents
 BEGIN SELECT RAISE(ABORT,'immutable scheduling identity'); END''',
'''CREATE TABLE scheduler_instances(
 id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES deployment_profile_revisions(id),
 provider_instance_id TEXT NOT NULL UNIQUE, provider_state TEXT NOT NULL DEFAULT 'unknown'
 CHECK(provider_state IN ('unknown','pulling','starting','worker_connect','model_loading','ready','running','idle','stopping','stopped')),
 provider_ready INTEGER CHECK(provider_ready IN (0,1)), model_ready INTEGER CHECK(model_ready IN (0,1)),
 provider_pending_change INTEGER NOT NULL DEFAULT 1 CHECK(provider_pending_change IN (0,1)),
 provider_observed_at REAL, worker_observed_at REAL,
 CHECK(provider_observed_at IS NULL OR provider_observed_at>0))''',
'''CREATE TABLE instance_allocations(
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),owner_user_id TEXT NOT NULL REFERENCES users(id),
 instance_id TEXT NOT NULL REFERENCES scheduler_instances(id), revision_id TEXT NOT NULL REFERENCES deployment_profile_revisions(id),
 allocation_type TEXT NOT NULL DEFAULT 'shared_job' CHECK(allocation_type IN ('shared_job','dedicated_session')),
 state TEXT NOT NULL DEFAULT 'planned' CHECK(state IN ('planned','active','released','expired','uncertain')),
 attempt_id TEXT REFERENCES job_attempts(id), lease_until REAL NOT NULL CHECK(lease_until>0),
 allocated_at REAL NOT NULL CHECK(allocated_at>0),released_at REAL,
 quoted_rate_minor_per_hour INTEGER CHECK(quoted_rate_minor_per_hour>=0),currency TEXT,
 CHECK((quoted_rate_minor_per_hour IS NULL)=(currency IS NULL)),
 CHECK(currency IS NULL OR (length(currency)=3 AND currency GLOB '[A-Z][A-Z][A-Z]')),
 CHECK((state IN ('planned','active','uncertain'))=(released_at IS NULL)))''',
'''CREATE UNIQUE INDEX scheduler_one_live_job ON instance_allocations(job_id) WHERE state IN ('planned','active','uncertain')''',
'''CREATE UNIQUE INDEX scheduler_one_live_instance ON instance_allocations(instance_id) WHERE state IN ('planned','active','uncertain')''',
'''CREATE INDEX scheduler_alloc_owner ON instance_allocations(owner_user_id,allocated_at DESC)''',
'''CREATE TRIGGER scheduler_allocation_owner BEFORE INSERT ON instance_allocations BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM scheduler_job_intents i JOIN jobs j ON j.id=i.job_id
 WHERE i.job_id=NEW.job_id AND i.owner_user_id=NEW.owner_user_id AND j.owner_user_id=i.owner_user_id
 AND j.ownership_state='verified' AND j.state='pending') THEN RAISE(ABORT,'allocation owner or job state invalid') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM scheduler_instances s WHERE s.id=NEW.instance_id
 AND s.revision_id=NEW.revision_id) THEN RAISE(ABORT,'allocation profile mismatch') END;
 END''',
'''CREATE TRIGGER scheduler_allocation_identity_lock BEFORE UPDATE OF job_id,owner_user_id,instance_id,revision_id,allocation_type ON instance_allocations
 BEGIN SELECT RAISE(ABORT,'allocation identity immutable'); END''',
'''CREATE TABLE scheduler_owner_turns(revision_id TEXT NOT NULL REFERENCES deployment_profile_revisions(id),
 owner_user_id TEXT NOT NULL REFERENCES users(id),served INTEGER NOT NULL DEFAULT 0 CHECK(served>=0),
 last_served_at REAL,PRIMARY KEY(revision_id,owner_user_id))''',
'''CREATE TABLE scheduler_scale_intents(id TEXT PRIMARY KEY,revision_id TEXT NOT NULL REFERENCES deployment_profile_revisions(id),
 action TEXT NOT NULL CHECK(action IN ('start','stop','drain','hold')),
 state TEXT NOT NULL DEFAULT 'requested' CHECK(state IN ('requested','provider_confirmed','cancelled','unconfirmed')),
 requested_at REAL NOT NULL,confirmed_at REAL,reason_code TEXT NOT NULL,
 requested_by TEXT NOT NULL,provider_reference TEXT,
 CHECK(state!='provider_confirmed' OR (confirmed_at IS NOT NULL AND provider_reference IS NOT NULL)))''',
'''CREATE UNIQUE INDEX scheduler_one_scale_pending ON scheduler_scale_intents(revision_id) WHERE state IN ('requested','unconfirmed')''',
'''CREATE TABLE scheduler_usage_ledger(id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL REFERENCES users(id),
 allocation_id TEXT NOT NULL REFERENCES instance_allocations(id),kind TEXT NOT NULL CHECK(kind IN ('estimated','provider_actual')),
 duration_seconds REAL NOT NULL CHECK(duration_seconds>=0),amount_minor INTEGER NOT NULL CHECK(amount_minor>=0),
 currency TEXT NOT NULL CHECK(length(currency)=3 AND currency GLOB '[A-Z][A-Z][A-Z]'),
 source TEXT NOT NULL,source_ref TEXT NOT NULL,observed_at TEXT NOT NULL,
 UNIQUE(allocation_id,kind,source_ref),
 CHECK(kind!='provider_actual' OR (source='provider_invoice_verified' AND length(source_ref)>=10)))''',
'''CREATE TRIGGER scheduler_usage_owner BEFORE INSERT ON scheduler_usage_ledger BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM instance_allocations a WHERE a.id=NEW.allocation_id
 AND a.owner_user_id=NEW.owner_user_id) THEN RAISE(ABORT,'ledger owner mismatch') END; END''',
'''CREATE TRIGGER scheduler_usage_immutable BEFORE UPDATE ON scheduler_usage_ledger BEGIN SELECT RAISE(ABORT,'immutable ledger'); END''',
'''CREATE TRIGGER scheduler_usage_no_delete BEFORE DELETE ON scheduler_usage_ledger BEGIN SELECT RAISE(ABORT,'immutable ledger'); END''',
'''CREATE INDEX scheduler_intents_owner ON scheduler_job_intents(owner_user_id,disposition,created_at)'''
)
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()
def migrate(c:sqlite3.Connection)->bool:
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000');c.execute('BEGIN IMMEDIATE')
 try:
  names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  required={'schema_migrations','users','jobs','job_attempts','workflow_compilations','model_versions',
    'deployment_profiles','deployment_profile_revisions','worker_images','image_model_compatibility','model_deployment_compatibility'}
  if not required<=names:raise RuntimeError('Prerequisite Phase01/03/07/09/11 schema missing')
  for name,cols in {'jobs':{'owner_user_id','ownership_state','state','execution_mode'},'workflow_compilations':{'owner_user_id','model_version_id'}}.items():
   actual={r[1] for r in c.execute(f'PRAGMA table_info({name})')}
   if not cols<=actual:raise RuntimeError('Owner-bound schema missing: '+name)
  found=c.execute('SELECT checksum FROM schema_migrations WHERE revision=?',(REVISION,)).fetchone()
  if found:
   if found[0]!=CHECKSUM:raise RuntimeError('Phase12 migration checksum mismatch')
   c.commit();return False
  for sql in DDL:c.execute(sql)
  c.execute('INSERT INTO schema_migrations(revision,applied_at,checksum) VALUES(?,?,?)',
     (REVISION,datetime.now(timezone.utc).isoformat(),CHECKSUM))
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('Migration failed FK checks')
  c.commit();return True
 except BaseException:c.rollback();raise
