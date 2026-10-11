"""Phase12 read-only user visibility and Admin-only *offline* scale intents.

No direct Salad, billing settlement or Worker Claim operation is exposed.
"""
from __future__ import annotations
import os
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field
from . import db,security,scheduler_v12 as scheduler
router=APIRouter(prefix='/api/v2/scheduling',tags=['Stage12 GPU scheduling / offline only'])

def ready():
 if os.getenv('SCHEDULER_V12_UI_ENABLED','false').lower()!='true':
  raise HTTPException(503,'GPU scheduling v12 preview disabled')
 security.policy()
 with db.connect() as c:
  try:scheduler.tables(c)
  except scheduler.Blocked:raise HTTPException(503,'Phase12 migration required')

def current(user=Depends(security.require_active_user),_=Depends(ready)):
 return user

def admin(user=Depends(current)):
 if not {'admin','superadmin','operator'}.intersection(user.get('roles',[])):
  raise HTTPException(403,'Administrative permission required')
 return user

def change(request:Request,user=Depends(admin)):
 security.require_csrf(request)
 return user

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class ScaleDraft(Strict):
 revision_id:str=Field(min_length=1,max_length=96)
 action:str=Field(pattern='^(start|stop|drain|hold)$')
 reason_code:str=Field(min_length=3,max_length=60,pattern=r'^[a-z][a-z0-9_]{2,59}$')
 acknowledge_non_executing_preview:bool

@router.get('/me/queue-summary')
def my_queue(user=Depends(current)):
 with db.connect() as c:
  return scheduler.own_queue(c,user['id'])

@router.get('/me/usage')
def my_usage(user=Depends(current)):
 with db.connect() as c:
  return scheduler.own_usage(c,user['id'])

@router.get('/admin/infrastructure')
def admin_infrastructure(user=Depends(admin)):
 with db.connect() as c:
  # Provider observations in this table cannot prove runtime model readiness:
  # they are internal preview state until a provider-signed reconciler exists.
  rows=[dict(r) for r in c.execute('''SELECT s.revision_id,s.provider_state,s.provider_ready,
   s.provider_pending_change,s.provider_observed_at,s.worker_observed_at,
   (SELECT COUNT(*) FROM instance_allocations a WHERE a.instance_id=s.id
    AND a.state IN ('planned','active','uncertain')) AS active_allocations
   FROM scheduler_instances s ORDER BY s.revision_id LIMIT 100''')]
  for row in rows:
   row['readiness']='unverified';row['model_ready']=None
  return {'instances':rows,'source':'scheduler_preview_only','provider_operations_enabled':False}

@router.get('/admin/allocations')
def admin_allocations(user=Depends(admin)):
 with db.connect() as c:
  # Metadata only; no raw prompt, filename, storage key or user identity.
  return {'allocations':[dict(r) for r in c.execute('''SELECT id,revision_id,state,allocation_type,
   allocated_at,released_at,lease_until FROM instance_allocations
   ORDER BY allocated_at DESC LIMIT 100''')]}

@router.get('/admin/decisions')
def admin_decisions(user=Depends(admin)):
 with db.connect() as c:
  return {'scale_intents':[dict(r) for r in c.execute('''SELECT id,revision_id,action,state,
     requested_at,confirmed_at,reason_code FROM scheduler_scale_intents
     ORDER BY requested_at DESC LIMIT 100''')],
    'submitted_to_provider':False}

@router.post('/admin/scale-intents',status_code=202)
def scale_intent(data:ScaleDraft,user=Depends(change)):
 if not data.acknowledge_non_executing_preview:
  raise HTTPException(422,'Preview acknowledgement required')
 with db.connect() as c:
  try:return scheduler.proposed_scale(c,data.revision_id,data.action,user['id'],reason=data.reason_code)
  except scheduler.Blocked as exc:raise HTTPException(409,str(exc))
  except ValueError:raise HTTPException(422,'Invalid scale intent')
