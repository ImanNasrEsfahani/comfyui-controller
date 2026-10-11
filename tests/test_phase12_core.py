"""Isolated SQLite contract tests with fabricated A/B users; no provider/network."""
from __future__ import annotations
import sqlite3,time,sys,importlib.util
from pathlib import Path
from datetime import datetime,timezone,timedelta
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app import scheduler_v12 as sched
from app.migrations import phase12 as schema

NOW=time.time()

def make_db():
 c=sqlite3.connect(':memory:',check_same_thread=False);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
 c.executescript('''
 CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT);
 CREATE TABLE users(id TEXT PRIMARY KEY,status TEXT,email_verified_at TEXT);
 CREATE TABLE jobs(id TEXT PRIMARY KEY,owner_user_id TEXT REFERENCES users(id),ownership_state TEXT,state TEXT,
 execution_mode TEXT,next_attempt_at REAL);
 CREATE TABLE job_attempts(id TEXT PRIMARY KEY);
 CREATE TABLE model_versions(id TEXT PRIMARY KEY,status TEXT);
 CREATE TABLE workflow_versions(id TEXT PRIMARY KEY,status TEXT);
 CREATE TABLE workflow_compilations(id TEXT PRIMARY KEY,owner_user_id TEXT,model_version_id TEXT,workflow_version_id TEXT);
 CREATE TABLE worker_images(id TEXT PRIMARY KEY,digest TEXT,signature_status TEXT,status TEXT);
 CREATE TABLE gpu_profiles(id TEXT PRIMARY KEY);
 CREATE TABLE deployment_profiles(id TEXT PRIMARY KEY,active_revision_id TEXT);
 CREATE TABLE deployment_profile_revisions(id TEXT PRIMARY KEY,profile_id TEXT REFERENCES deployment_profiles(id),image_id TEXT,gpu_id TEXT,status TEXT);
 CREATE TABLE image_model_compatibility(image_id TEXT,model_id TEXT,state TEXT);
 CREATE TABLE model_deployment_compatibility(revision_id TEXT,model_id TEXT,state TEXT);
 ''')
 for u in ['A','B','C']:
  c.execute('INSERT INTO users VALUES(?,?,?)',(u,'active','2026-01-01T00:00:00+00:00'))
 c.execute("INSERT INTO model_versions VALUES('model-1','ready')")
 c.execute("INSERT INTO model_versions VALUES('model-2','ready')")
 c.execute("INSERT INTO workflow_versions VALUES('wfv-1','published')")
 c.execute("INSERT INTO worker_images VALUES('image-1',?,'verified','approved')",('ghcr.io/test/image@sha256:'+'a'*64,))
 c.execute("INSERT INTO worker_images VALUES('image-2',?,'verified','approved')",('ghcr.io/test/video@sha256:'+'b'*64,))
 c.execute("INSERT INTO gpu_profiles VALUES('gpu-1')")
 c.execute("INSERT INTO deployment_profiles VALUES('profile-1','rev-1')")
 c.execute("INSERT INTO deployment_profiles VALUES('profile-2','rev-2')")
 c.execute("INSERT INTO deployment_profile_revisions VALUES('rev-1','profile-1','image-1','gpu-1','active')")
 c.execute("INSERT INTO deployment_profile_revisions VALUES('rev-2','profile-2','image-2','gpu-1','active')")
 c.execute("INSERT INTO image_model_compatibility VALUES('image-1','model-1','tested_pass')")
 c.execute("INSERT INTO model_deployment_compatibility VALUES('rev-1','model-1','tested_pass')")
 c.execute("INSERT INTO image_model_compatibility VALUES('image-2','model-2','tested_pass')")
 c.execute("INSERT INTO model_deployment_compatibility VALUES('rev-2','model-2','tested_pass')")
 c.commit();schema.migrate(c)
 c.execute('''INSERT INTO scheduler_profile_policy(revision_id,enabled,max_owner_running,max_owner_queued,
 aging_seconds,idle_seconds,rate_minor_per_hour,currency) VALUES('rev-1',1,1,8,300,900,300,'CAD')''')
 c.execute('''INSERT INTO scheduler_profile_policy(revision_id,enabled,max_owner_running,max_owner_queued,
 aging_seconds,idle_seconds) VALUES('rev-2',1,1,8,300,900)''')
 c.execute("INSERT INTO scheduler_instances VALUES('inst-1','rev-1','provider-1','ready',1,1,0,?,?)",(NOW,NOW))
 c.execute("INSERT INTO scheduler_instances VALUES('inst-2','rev-2','provider-2','ready',1,1,0,?,?)",(NOW,NOW))
 c.commit();return c

@pytest.fixture
def c():
 c=make_db();yield c;c.close()

def add(c,u,n,model='model-1',priority='standard',age=40,disposition='eligible'):
 name=f'{u}-{n}';when=datetime.fromtimestamp(NOW-age,timezone.utc).isoformat()
 c.execute("INSERT INTO jobs VALUES(?,?,'verified','pending','direct',0)",(name,u))
 c.execute('INSERT INTO workflow_compilations VALUES(?,?,?,?)',(f'comp-{name}',u,model,'wfv-1'))
 reason=None if disposition=='eligible' else 'quota'
 c.execute('INSERT INTO scheduler_job_intents VALUES(?,?,?,?,?,?,?,?)',
  (name,u,f'comp-{name}',model,priority,disposition,reason,when))
 c.commit();return name

def test_migration_idempotence(c):
 assert schema.migrate(c) is False
 assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not c.execute('PRAGMA foreign_key_check').fetchall()

def test_fresh_schema_refuses_missing_prerequisites():
 c=sqlite3.connect(':memory:',check_same_thread=False);c.execute('CREATE TABLE schema_migrations(revision TEXT,checksum TEXT)');c.commit()
 with pytest.raises(RuntimeError,match='Prerequisite'):schema.migrate(c)

def test_no_jobs(c):assert sched.select(c,'rev-1',NOW) is None

def test_scoped_candidate(c):
 add(c,'A',1);add(c,'B',1,model='model-2')
 assert sched.select(c,'rev-1',NOW)['owner_user_id']=='A'
 assert sched.select(c,'rev-2',NOW)['owner_user_id']=='B'

def test_no_unverified_model_fallback(c):
 add(c,'A',1);c.execute("UPDATE image_model_compatibility SET state='tested_fail'");c.commit()
 assert sched.select(c,'rev-1',NOW) is None

def test_unsigned_runtime_refused(c):
 add(c,'A',1);c.execute("UPDATE worker_images SET signature_status='unknown'");c.commit()
 with pytest.raises(sched.Blocked):sched.select(c,'rev-1',NOW)

def test_unpublished_workflow_refused(c):
 add(c,'A',1);c.execute("UPDATE workflow_versions SET status='draft'");c.commit()
 assert sched.select(c,'rev-1',NOW) is None

def test_held_quota_not_selected(c):
 add(c,'A',1,disposition='held');assert sched.select(c,'rev-1',NOW) is None

def test_invalid_owner_insert_rejected(c):
 name=add(c,'A',1)
 c.execute("INSERT INTO jobs VALUES('bad','B','verified','pending','direct',0)")
 with pytest.raises(sqlite3.IntegrityError):
  c.execute("INSERT INTO scheduler_job_intents VALUES('bad','B',?,'model-1','standard','eligible',NULL,'2026')",(f'comp-{name}',))
 c.rollback()

def test_deleted_user_not_scheduled(c):
 add(c,'A',1);c.execute("UPDATE users SET status='suspended' WHERE id='A'");c.commit()
 assert sched.select(c,'rev-1',NOW) is None

def test_round_robin_no_starvation(c):
 for i in range(12):add(c,'A',i)
 for i in range(3):add(c,'B',i)
 selections=[]
 for idx in range(4):
  iid=f'inst-new-{idx}'
  c.execute("INSERT INTO scheduler_instances VALUES(?,'rev-1',?,'ready',1,1,0,?,?)",
     (iid,f'provider-new-{idx}',NOW,NOW));c.commit()
  p=sched.reserve_plan(c,'rev-1',iid,now=NOW+idx)
  selections.append(p['owner_user_id'])
  c.execute("UPDATE instance_allocations SET state='released',released_at=? WHERE id=?",(NOW+idx+0.1,p['allocation_id']))
  c.execute("UPDATE jobs SET state='succeeded' WHERE id=?",(p['job_id'],));c.commit()
 assert selections[:4]==['A','B','A','B']

def test_concurrency_limit(c):
 add(c,'A',1);add(c,'A',2);add(c,'B',1)
 first=sched.reserve_plan(c,'rev-1','inst-1',now=NOW)
 c.execute("INSERT INTO scheduler_instances VALUES('inst-other','rev-1','provider-other','ready',1,1,0,?,?)",(NOW,NOW));c.commit()
 second=sched.reserve_plan(c,'rev-1','inst-other',now=NOW)
 assert first['owner_user_id']=='A' and second['owner_user_id']=='B'

def test_duplicate_allocation_blocked(c):
 add(c,'A',1);sched.reserve_plan(c,'rev-1','inst-1',now=NOW)
 with pytest.raises(sched.Blocked):sched.reserve_plan(c,'rev-1','inst-1',now=NOW)

def test_allocation_foreign_owner_rejected(c):
 j=add(c,'A',1)
 with pytest.raises(sqlite3.IntegrityError):
  c.execute("INSERT INTO instance_allocations(id,job_id,owner_user_id,instance_id,revision_id,lease_until,allocated_at) VALUES('x',?,'B','inst-1','rev-1',?,?)",(j,NOW+120,NOW))
 c.rollback()

def test_stale_worker_blocks_reservation(c):
 add(c,'A',1)
 c.execute("UPDATE scheduler_instances SET worker_observed_at=? WHERE id='inst-1'",(NOW-200,));c.commit()
 with pytest.raises(sched.Blocked):sched.reserve_plan(c,'rev-1','inst-1',now=NOW)

def test_unknown_readiness_blocks_reservation(c):
 add(c,'A',1)
 c.execute("UPDATE scheduler_instances SET model_ready=NULL WHERE id='inst-1'");c.commit()
 with pytest.raises(sched.Blocked):sched.reserve_plan(c,'rev-1','inst-1',now=NOW)

def test_scale_start_exactly_one_unsubmitted(c):
 add(c,'A',1)
 c.execute("UPDATE scheduler_instances SET provider_state='stopped',provider_pending_change=0 WHERE id='inst-1'");c.commit()
 one=sched.proposed_scale(c,'rev-1','start','ADMIN',now=NOW)
 two=sched.proposed_scale(c,'rev-1','start','ADMIN',now=NOW)
 assert one['id']==two['id'] and not one['submitted_to_provider'] and two['idempotent']
 assert c.execute("SELECT COUNT(*) FROM scheduler_scale_intents").fetchone()[0]==1

def test_scale_start_no_demand(c):
 c.execute("UPDATE scheduler_instances SET provider_state='stopped',provider_pending_change=0 WHERE id='inst-1'");c.commit()
 with pytest.raises(sched.Blocked):sched.proposed_scale(c,'rev-1','start','ADMIN',now=NOW)

def test_stop_blocked_pending(c):
 add(c,'A',1)
 with pytest.raises(sched.Blocked):sched.proposed_scale(c,'rev-1','stop','ADMIN',now=NOW)

@pytest.mark.parametrize('state',['running','finalizing','stalled','cancel_requested','unknown'])
def test_stop_blocked_active_uncertain(c,state):
 add(c,'A',1);c.execute('UPDATE jobs SET state=?',(state,));c.commit()
 with pytest.raises(sched.Blocked):sched.proposed_scale(c,'rev-1','stop','ADMIN',now=NOW)

def test_stop_blocks_cross_profile_pending(c):
 add(c,'B',1,model='model-2')
 with pytest.raises(sched.Blocked):sched.proposed_scale(c,'rev-1','stop','ADMIN',now=NOW)

def test_stop_unknown_provider(c):
 c.execute("UPDATE scheduler_instances SET provider_state='unknown' WHERE id='inst-1'");c.commit()
 with pytest.raises(sched.Blocked):sched.proposed_scale(c,'rev-1','stop','ADMIN',now=NOW)

def test_stop_idle_still_not_provider_confirmation(c):
 r=sched.proposed_scale(c,'rev-1','stop','ADMIN',now=NOW)
 assert r['state']=='requested' and r['submitted_to_provider'] is False
 assert c.execute('SELECT confirmed_at FROM scheduler_scale_intents').fetchone()[0] is None

def test_pending_provider_change_blocks_stop(c):
 c.execute("UPDATE scheduler_instances SET provider_pending_change=1");c.commit()
 with pytest.raises(sched.Blocked):sched.proposed_scale(c,'rev-1','stop','ADMIN',now=NOW)

def test_conflicting_pending_operation_rejected(c):
 sched.proposed_scale(c,'rev-1','stop','ADMIN',now=NOW)
 with pytest.raises(sched.Blocked):sched.proposed_scale(c,'rev-1','start','ADMIN',now=NOW)

def test_usage_estimate_distinct_from_invoice(c):
 add(c,'A',1)
 allocation=sched.reserve_plan(c,'rev-1','inst-1',now=NOW)
 c.execute("UPDATE instance_allocations SET state='released',released_at=? WHERE id=?",(NOW+120,allocation['allocation_id']));c.commit()
 u=sched.own_usage(c,'A',now=NOW+140)
 assert u['allocated_seconds_estimate']==120
 assert u['cost_estimates_minor']=={'CAD':10} and u['provider_actual_minor'] is None
 assert sched.own_usage(c,'B')['provider_actual_minor'] is None

def test_usage_provider_receipt_separate(c):
 add(c,'A',1);a=sched.reserve_plan(c,'rev-1','inst-1',now=NOW)
 c.execute("INSERT INTO scheduler_usage_ledger VALUES('ledger','A',?,'provider_actual',3600,999,'CAD','provider_invoice_verified','invoice-12345','2026-10-11')",(a['allocation_id'],));c.commit()
 assert sched.own_usage(c,'A')['provider_actual_minor']=={'CAD':999}
 assert sched.own_usage(c,'B')['provider_actual_minor'] is None

def test_bad_ledger_owner_is_rejected(c):
 add(c,'A',1);a=sched.reserve_plan(c,'rev-1','inst-1',now=NOW)
 with pytest.raises(sqlite3.IntegrityError):
  c.execute("INSERT INTO scheduler_usage_ledger VALUES('ledger','B',?,'provider_actual',3600,999,'CAD','provider_invoice_verified','invoice-12345','2026-10-11')",(a['allocation_id'],))
 c.rollback()

def test_dedicated_disabled_by_default(c):
 assert not hasattr(sched,'create_dedicated_session')

def test_user_queue_never_leaks_other_user_data(c):
 add(c,'A',1);add(c,'B',1)
 q=sched.own_queue(c,'A')
 assert q['eligible']==1 and 'B' not in str(q) and q['eta_seconds'] is None

def test_scale_when_policy_disabled(c):
 add(c,'A',1);c.execute("UPDATE scheduler_profile_policy SET enabled=0 WHERE revision_id='rev-1'");c.commit()
 with pytest.raises(sched.Blocked):sched.proposed_scale(c,'rev-1','start','ADMIN',now=NOW)
