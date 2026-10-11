"""Phase12 staged shared-GPU scheduler: only DB plans; NEVER sends provider or Worker commands.

Calls that change SQLite require a caller-held BEGIN IMMEDIATE. Active dispatch
remains disabled until Phase03/07/09/11 safety gates pass. Runtime provider
observations must enter through a future authenticated reconciler.
"""
from __future__ import annotations
import math, sqlite3, time
from uuid import uuid4
from datetime import datetime, timezone

class Blocked(RuntimeError):pass

REQUIRED={'scheduler_profile_policy','scheduler_job_intents','scheduler_instances',
 'instance_allocations','scheduler_owner_turns','scheduler_scale_intents','scheduler_usage_ledger'}
BLOCKING_STATES=('accepted','queued','pending','submitting','waiting','preparing','processing','running',
 'finalizing','cancel_requested','stalled','unknown')

def tables(c):
 found={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 if not REQUIRED<=found:raise Blocked('Phase12 migration not applied')

def policy(c,revision):
 tables(c)
 p=c.execute('''SELECT p.*,r.image_id,r.gpu_id,r.status AS revision_status,
 d.active_revision_id,wi.signature_status,wi.status AS image_status,wi.digest
 FROM scheduler_profile_policy p JOIN deployment_profile_revisions r ON r.id=p.revision_id
 JOIN deployment_profiles d ON d.id=r.profile_id JOIN worker_images wi ON wi.id=r.image_id
 WHERE p.revision_id=?''',(revision,)).fetchone()
 if p is None:raise Blocked('Profile policy missing')
 p=dict(p)
 if not (p['enabled']==1 and p['revision_status']=='active' and p['active_revision_id']==revision and
    p['signature_status']=='verified' and p['image_status']=='approved'):
  raise Blocked('Active signed worker image and enabled profile required')
 return p

def eligible(c,revision,*,now=None):
 """Snapshot-linked candidates, tested compatibility, age/fairness and per-owner concurrency.

 Uses a SQL owner join rather than trusting owner/user/model in client-supplied JSON.
 No Worker allocation or Job transition occurs here.
 """
 p=policy(c,revision); now=now if now is not None else time.time()
 if not math.isfinite(now):raise ValueError('Invalid time')
 rows=[dict(r) for r in c.execute('''
 SELECT j.id AS job_id,j.owner_user_id,i.model_version_id,i.priority_class,i.created_at,
 COALESCE(t.served,0) AS served,COALESCE(t.last_served_at,0) AS last_served_at,
 (SELECT COUNT(*) FROM instance_allocations a WHERE a.owner_user_id=j.owner_user_id
 AND a.state IN ('planned','active','uncertain')) AS owner_running
 FROM scheduler_job_intents i JOIN jobs j ON j.id=i.job_id
 JOIN users u ON u.id=j.owner_user_id
 JOIN workflow_compilations w ON w.id=i.compilation_id
 JOIN workflow_versions v ON v.id=w.workflow_version_id
 JOIN model_versions m ON m.id=i.model_version_id
 JOIN deployment_profile_revisions pr ON pr.id=?
 JOIN image_model_compatibility im ON im.model_id=i.model_version_id AND im.image_id=pr.image_id
 JOIN model_deployment_compatibility dc ON dc.model_id=i.model_version_id AND dc.revision_id=pr.id
 WHERE i.disposition='eligible' AND j.owner_user_id=i.owner_user_id AND j.ownership_state='verified'
 AND j.execution_mode='direct' AND j.state='pending' AND j.next_attempt_at<=?
 AND u.status='active' AND u.email_verified_at IS NOT NULL
 AND w.owner_user_id=i.owner_user_id AND w.model_version_id=i.model_version_id
 AND v.status='published' AND m.status='ready'
 AND im.state='tested_pass' AND dc.state='tested_pass'
 '''.replace('JOIN deployment_profile_revisions pr ON pr.id=?',
  'LEFT JOIN scheduler_owner_turns t ON t.revision_id=? AND t.owner_user_id=j.owner_user_id\n JOIN deployment_profile_revisions pr ON pr.id=?'),(revision,revision,now)).fetchall()]
 # Limit each owner's eligible *view*; excess remain held for later consideration,
 # not deleted or rewritten. Sorted by user fair share, then age/entitlement.
 oldest={}
 for row in rows:
  oldest.setdefault(row['owner_user_id'],[]).append(row)
 results=[]
 for uid,items in oldest.items():
  items.sort(key=lambda q:(q['created_at'],q['job_id']))
  if items[0]['owner_running']>=p['max_owner_running']:continue
  results.extend(items[:p['max_owner_queued']])
 def priority(row):
  try:wait=max(0,now-datetime.fromisoformat(row['created_at'].replace('Z','+00:00')).timestamp())
  except (ValueError,TypeError):wait=0
  # Fair share dominates an entitlement boost, while aging prevents old jobs
  # from staying behind newly arriving work from the same owner.
  served=float(row['served']) / (1.5 if row['priority_class']=='entitled_high' else 1.0)
  return (served,row['last_served_at'], -(min(wait/p['aging_seconds'],1000)),row['created_at'],row['job_id'])
 return sorted(results,key=priority)

def select(c,revision,now=None):
 jobs=eligible(c,revision,now=now)
 return jobs[0] if jobs else None

def reserve_plan(c,revision,instance_id,*,now=None,ttl=120):
 """Atomic *planning* allocation. Not a job lease, and never a Worker claim."""
 if not 30<=ttl<=3600:raise ValueError('Planning TTL outside bounds')
 now=time.time() if now is None else now
 if not math.isfinite(now) or now<=0:raise ValueError('Invalid clock')
 c.execute('BEGIN IMMEDIATE')
 try:
  p=policy(c,revision)
  s=c.execute('SELECT * FROM scheduler_instances WHERE id=? AND revision_id=?',(instance_id,revision)).fetchone()
  if s is None or s['provider_pending_change'] or s['provider_state']!='ready' or s['provider_ready']!=1 or s['model_ready']!=1:
   raise Blocked('No provider-confirmed, model-ready instance')
  # Worker heartbeat is not model attestation; freshness is necessary but not sufficient.
  if s['provider_observed_at'] is None or s['worker_observed_at'] is None or now-s['provider_observed_at']>90 or now-s['worker_observed_at']>90:
   raise Blocked('Provider or Worker observation is stale')
  if c.execute("SELECT 1 FROM instance_allocations WHERE instance_id=? AND state IN ('planned','active','uncertain')",(instance_id,)).fetchone():
   raise Blocked('Instance already allocated or uncertain')
  choice=select(c,revision,now)
  if choice is None:
   c.commit();return None
  uid=choice['owner_user_id'];aid=str(uuid4())
  c.execute('''INSERT INTO instance_allocations(id,job_id,owner_user_id,instance_id,revision_id,
   allocation_type,state,lease_until,allocated_at,quoted_rate_minor_per_hour,currency)
   VALUES(?,?,?,?,?,'shared_job','planned',?,?,?,?)''',
   (aid,choice['job_id'],uid,instance_id,revision,now+ttl,now,p['rate_minor_per_hour'],p['currency']))
  c.execute('''INSERT INTO scheduler_owner_turns(revision_id,owner_user_id,served,last_served_at)
  VALUES(?,?,1,?) ON CONFLICT(revision_id,owner_user_id) DO UPDATE SET
  served=served+1,last_served_at=excluded.last_served_at''',(revision,uid,now))
  c.commit();return {'allocation_id':aid,'job_id':choice['job_id'],'owner_user_id':uid,
    'revision_id':revision,'state':'planned','dispatch_enabled':False}
 except BaseException:c.rollback();raise

def global_busy(c):
 """All execution modes block stop; uncertain/stalled is NOT idle."""
 table=','.join('?' for _ in BLOCKING_STATES)
 count=c.execute(f"SELECT COUNT(*) FROM jobs WHERE state IN ({table})",BLOCKING_STATES).fetchone()[0]
 allocated=c.execute("SELECT COUNT(*) FROM instance_allocations WHERE state IN ('planned','active','uncertain')").fetchone()[0]
 return int(count)+int(allocated)

def proposed_scale(c,revision,action,actor,*,reason='operator_review',now=None):
 """Idempotent LOCAL intent only; DOES NOT invoke Salad or certify action."""
 if action not in ('start','stop','drain','hold'):raise ValueError('Invalid scale action')
 if not actor or not isinstance(actor,str):raise ValueError('Actor must be authenticated')
 now=time.time() if now is None else now
 c.execute('BEGIN IMMEDIATE')
 try:
  policy(c,revision)
  previous=c.execute("SELECT * FROM scheduler_scale_intents WHERE revision_id=? AND state IN ('requested','unconfirmed')",(revision,)).fetchone()
  if previous:
   if previous['action']!=action:raise Blocked('Another provider operation is pending')
   c.commit();return {'id':previous['id'],'state':previous['state'],'submitted_to_provider':False,'idempotent':True}
  instances=[dict(r) for r in c.execute('SELECT * FROM scheduler_instances WHERE revision_id=?',(revision,))]
  if action=='start':
   if select(c,revision,now) is None:raise Blocked('No eligible compatible demand')
   if not instances or any(x['provider_pending_change'] or x['provider_state']!='stopped' or
      x['provider_observed_at'] is None or now-x['provider_observed_at']>90 for x in instances):
    raise Blocked('Provider has not confirmed zero/stopped; start requires fresh observation')
  if action in ('stop','drain'):
   if global_busy(c):raise Blocked('Pending, running, finalizing or uncertain Job exists')
   if not instances or any(x['provider_pending_change'] or x['provider_state'] not in ('idle','ready','stopped') or
      x['provider_observed_at'] is None or now-x['provider_observed_at']>90 for x in instances):
    raise Blocked('Provider has not confirmed idle/stopped instance state')
  op=str(uuid4())
  c.execute('''INSERT INTO scheduler_scale_intents(id,revision_id,action,state,requested_at,reason_code,requested_by)
    VALUES(?,?,?,'requested',?,?,?)''',(op,revision,action,now,reason[:60],actor))
  c.commit();return {'id':op,'state':'requested','submitted_to_provider':False,'idempotent':False}
 except BaseException:c.rollback();raise

def own_queue(c,uid):
 tables(c)
 n=c.execute('''SELECT disposition,COUNT(*) n FROM scheduler_job_intents i
 JOIN jobs j ON j.id=i.job_id WHERE i.owner_user_id=? AND j.owner_user_id=?
 AND j.ownership_state='verified' AND j.state='pending' GROUP BY disposition''',(uid,uid)).fetchall()
 return {'eligible':next((r['n'] for r in n if r['disposition']=='eligible'),0),
   'held':next((r['n'] for r in n if r['disposition']=='held'),0),
   'queue_position':None,'eta_seconds':None,'ready': 'unknown'}

def own_usage(c,uid,now=None):
 tables(c);now=time.time() if now is None else now
 allocations=[dict(r) for r in c.execute('''SELECT allocated_at,released_at,quoted_rate_minor_per_hour,currency
 FROM instance_allocations WHERE owner_user_id=? AND state IN ('released','active','uncertain')''',(uid,))]
 seconds=0.; estimated={}
 for a in allocations:
  start=float(a['allocated_at']);stop=now if a['released_at'] is None else float(a['released_at'])
  elapsed=max(0,stop-start);seconds+=elapsed
  if a['quoted_rate_minor_per_hour'] is not None:
   key=a['currency'];estimated[key]=estimated.get(key,0)+round(elapsed*int(a['quoted_rate_minor_per_hour'])/3600)
 actual={}
 for r in c.execute('''SELECT currency,SUM(amount_minor) n FROM scheduler_usage_ledger
 WHERE owner_user_id=? AND kind='provider_actual' GROUP BY currency''',(uid,)):
  actual[r['currency']]=r['n']
 return {'allocated_seconds_estimate':round(seconds,3),'cost_estimates_minor':estimated or None,
    'provider_actual_minor':actual or None,'invoice_status':'unavailable' if not actual else 'provider_source_recorded_unattested',
    'note':'Allocated time/cost are estimates; not a balance or provider invoice'}
