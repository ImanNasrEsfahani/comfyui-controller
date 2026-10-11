"""Phase11 transactional receipt journal. Trusted controller-side functions only.

Not a replacement for Phase03's unresolved atomic job creation. These records
cannot dispatch GPU work and never modify old jobs/job_attempts by themselves.
"""
from __future__ import annotations
import hashlib,time,json

class StaleLease(ValueError):pass

def lease_digest(token):
    if not isinstance(token,str) or len(token)<32:raise StaleLease('invalid_token')
    return hashlib.sha256(token.encode()).hexdigest()

def begin(c,*,job_id,attempt_id,lease_token,worker_image_digest,compiled_graph_sha256,deadline,now=None):
    now=time.time() if now is None else now
    if not now<deadline<=now+3600:raise StaleLease('bad_deadline')
    # Never issue a lease to an anonymous/legacy job or unknown attempt.
    job=c.execute('''SELECT owner_user_id,ownership_state,hidden,active_attempt_id,
      lease_token_hash,lease_deadline,state FROM jobs WHERE id=?''',(job_id,)).fetchone()
    attempt=c.execute('SELECT job_id FROM job_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not job or not job['owner_user_id'] or job['ownership_state']!='verified' or job['hidden'] or not attempt or attempt[0]!=job_id:
        raise StaleLease('unowned_or_missing_job')
    if job['active_attempt_id']!=attempt_id or job['lease_token_hash']!=lease_digest(lease_token) or job['state']!='running' or not job['lease_deadline']>=now:
        raise StaleLease('noncurrent_controller_lease')
    c.execute("UPDATE worker_v11_attempts SET state='superseded' WHERE job_id=? AND state IN ('running','cancel_requested')",(job_id,))
    c.execute('''INSERT INTO worker_v11_attempts(job_id,attempt_id,lease_hash,image_digest,graph_hash,
      deadline,state,last_sequence,result_hash) VALUES(?,?,?,?,?,?,?,?,NULL)''',
      (job_id,attempt_id,lease_digest(lease_token),worker_image_digest,compiled_graph_sha256,
       deadline,'running',0))

def fenced(c,job_id,attempt_id,lease_token,*,now=None):
    now=time.time() if now is None else now
    row=c.execute('SELECT * FROM worker_v11_attempts WHERE job_id=? AND attempt_id=?',(job_id,attempt_id)).fetchone()
    if not row or row['lease_hash']!=lease_digest(lease_token) or not row['deadline']>=now:
        raise StaleLease('lease_expired_or_stale')
    controller=c.execute('SELECT active_attempt_id,lease_token_hash,lease_deadline,state FROM jobs WHERE id=?',(job_id,)).fetchone()
    if (not controller or controller['active_attempt_id']!=attempt_id or
          controller['lease_token_hash']!=lease_digest(lease_token) or
          controller['state'] not in ('running','finalizing','cancel_requested') or
          not controller['lease_deadline']>=now):
        raise StaleLease('controller_lease_changed')
    if c.execute('SELECT attempt_id FROM worker_v11_attempts WHERE job_id=? AND state IN (\'running\',\'cancel_requested\') AND attempt_id<>? LIMIT 1',(job_id,attempt_id)).fetchone():
        raise StaleLease('superseded_attempt')
    return row

def progress(c,job_id,attempt_id,lease_token,sequence,phase,*,now=None):
    row=fenced(c,job_id,attempt_id,lease_token,now=now)
    if row['state']!='running' or type(sequence) is not int or sequence<=row['last_sequence'] or not phase in ('preparing','model_loading','sampling','finalizing','transferring'):
        raise StaleLease('stale_or_invalid_progress')
    c.execute('UPDATE worker_v11_attempts SET last_sequence=? WHERE attempt_id=? AND state=\'running\'',(sequence,attempt_id))

def cancel_requested(c,job_id,attempt_id,lease_token,*,now=None):
    row=fenced(c,job_id,attempt_id,lease_token,now=now)
    if row['state']!='running':raise StaleLease('not_running')
    c.execute("UPDATE worker_v11_attempts SET state='cancel_requested' WHERE attempt_id=?",(attempt_id,))

def finish(c,job_id,attempt_id,lease_token,assets,*,now=None):
    row=fenced(c,job_id,attempt_id,lease_token,now=now)
    if row['state']=='succeeded':return row['result_hash']==hashlib.sha256(json.dumps(assets,sort_keys=True).encode()).hexdigest()
    if row['state']!='running':raise StaleLease('attempt_not_running')
    if not isinstance(assets,list) or not assets or len(assets)>16:raise StaleLease('output_missing')
    if any(not isinstance(x,dict) or x.get('status')!='available' or not x.get('sha256') or not x.get('size_bytes') or
           not isinstance(x.get('key'),str) or not x['key'].startswith(f'outputs/{job_id}/{attempt_id}/') for x in assets):
        raise StaleLease('unverified_or_partial_output')
    keys=[x['key'] for x in assets]
    if len(set(keys))!=len(keys):raise StaleLease('duplicate_output')
    result_hash=hashlib.sha256(json.dumps(assets,sort_keys=True).encode()).hexdigest()
    for x in assets:
        c.execute('''INSERT INTO worker_v11_verified_outputs(job_id,attempt_id,storage_key,sha256,size_bytes)
          VALUES(?,?,?,?,?)''',(job_id,attempt_id,x['key'],x['sha256'],x['size_bytes']))
    c.execute("UPDATE worker_v11_attempts SET state='succeeded',result_hash=? WHERE attempt_id=? AND state='running'",(result_hash,attempt_id))
    return True

def cancel_confirmed(c,job_id,attempt_id,lease_token,*,now=None):
    row=fenced(c,job_id,attempt_id,lease_token,now=now)
    if row['state']!='cancel_requested':raise StaleLease('cancel_not_requested')
    c.execute("UPDATE worker_v11_attempts SET state='cancelled' WHERE attempt_id=?",(attempt_id,))
    return True
