"""Owner-bound private gallery SQL. All reads filter owner in SQLite, never in memory."""
from __future__ import annotations
import sqlite3
from . import owner_repository as owners

class NotReady(RuntimeError):pass

def require_schema(c):
 owners.require_schema(c)
 names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 if not {'asset_variants','asset_deletions','job_input_assets'} <= names:raise NotReady('Phase06 migration is not applied')

def available_asset(c,uid,aid):
 a=owners.asset(c,uid,aid)
 if a is None:return None
 if c.execute('SELECT 1 FROM asset_deletions WHERE asset_id=? AND owner_user_id=?',(aid,uid)).fetchone():return None
 return a

def asset_page(c,uid,*,limit=24,cursor=None,kind=None,after=None,before=None,status=None,model=None,project=None):
 if not 1<=limit<=100:raise ValueError('Page limit')
 if project:raise ValueError('Project-scoped asset mapping not available in current schema')
 if model:raise ValueError('Model-scoped asset registry not available in current schema')
 if kind not in (None,'image','video','input','output'):raise ValueError('Invalid kind')
 if status not in (None,'available'):raise ValueError('Invalid status')
 # Two SQL branches, each enforcing owner and referencing job state/active attempt for outputs.
 common=' AND NOT EXISTS(SELECT 1 FROM asset_deletions d WHERE d.asset_id=a.asset_id AND d.owner_user_id=?)'
 statements=[('''SELECT a.asset_id,a.mime_type,a.width,a.height,a.size_bytes,a.created_at,
 'input' kind,NULL job_id FROM input_assets a WHERE a.owner_user_id=? AND a.ownership_state='verified' '''+common,'input'),
 ('''SELECT a.asset_id,a.mime_type,a.width,a.height,a.size_bytes,a.created_at,
 'output' kind,a.job_id FROM job_assets a JOIN jobs j ON j.id=a.job_id
 WHERE a.owner_user_id=? AND a.ownership_state='verified' AND a.status='available'
 AND j.owner_user_id=? AND j.ownership_state='verified' AND j.hidden=0
 AND (j.active_attempt_id IS NULL OR a.attempt_id=j.active_attempt_id) '''+common,'output')]
 parts=[];args=[]
 for template,k in statements:
  if kind in ('input','output') and kind!=k:continue
  pred=template;par=[uid,uid] if k=='input' else [uid,uid,uid]
  if kind in ('image','video'):
   pred+=' AND a.mime_type LIKE ?';par.append(kind+'/%')
  if after:pred+=' AND a.created_at>=?';par.append(after)
  if before:pred+=' AND a.created_at<=?';par.append(before)
  if cursor:pred+=' AND (a.created_at<? OR (a.created_at=? AND a.asset_id<?))';par.extend([cursor[0],cursor[0],cursor[1]])
  parts.append(pred);args+=par
 if not parts:return [],None
 query='SELECT * FROM ('+' UNION ALL '.join(parts)+') ORDER BY created_at DESC,asset_id DESC LIMIT ?'
 rows=[dict(row) for row in c.execute(query,args+[limit+1]).fetchall()]
 return rows[:limit], ((rows[limit-1]['created_at'],rows[limit-1]['asset_id']) if len(rows)>limit else None)

def variant(c,uid,aid,kind='thumbnail'):
 a=available_asset(c,uid,aid)
 if a is None:return None
 row=c.execute('''SELECT storage_key,mime_type,width,height,size_bytes FROM asset_variants
 WHERE asset_id=? AND owner_user_id=? AND kind=?''',(aid,uid,kind)).fetchone()
 return dict(row) if row else None

def is_referenced(c,uid,aid):
 return bool(c.execute('''SELECT 1 FROM job_input_assets WHERE owner_user_id=? AND asset_id=? LIMIT 1''',(uid,aid)).fetchone())

def soft_delete(c,uid,aid,instant):
 # Must be invoked inside BEGIN IMMEDIATE to serialize with reference creation.
 a=available_asset(c,uid,aid)
 if a is None:return 'missing'
 if is_referenced(c,uid,aid):return 'referenced'
 # Historic pre-Phase06 references are unindexed: fail closed when ambiguous.
 # Only output assets that have never been references can be soft-hidden.
 # No R2 objects are ever physically deleted.
 c.execute('INSERT INTO asset_deletions(asset_id,owner_user_id,deleted_at) VALUES(?,?,?)',(aid,uid,instant))
 return 'deleted'

def lineage(c,uid,aid):
 if available_asset(c,uid,aid) is None:return None
 return [dict(r) for r in c.execute('''SELECT r.job_id,r.slot_key,r.role,r.position,r.source_job_id,r.bound_at
 FROM job_input_assets r JOIN jobs j ON j.id=r.job_id
 WHERE r.owner_user_id=? AND r.asset_id=? AND j.owner_user_id=?
 AND j.ownership_state='verified' ORDER BY r.bound_at DESC LIMIT 100''',(uid,aid,uid))]
