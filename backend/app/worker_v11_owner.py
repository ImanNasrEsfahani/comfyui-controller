"""Controller-only validation of immutable slot bindings before signing a claim.

No trust in asset IDs supplied by a Worker or browser. Requires Phase03/06
verified owner and immutable job_input_assets rows. This function does NOT
allocate/dispatch a job or mark a model compatible.
"""
from __future__ import annotations
import hashlib,re

class OwnershipViolation(ValueError):pass


def authorize_inputs(c,job_id,bindings,*,r2,bucket,limit_bytes=40*1024**2):
    if not isinstance(bindings,list) or not 0<=len(bindings)<=16:
        raise OwnershipViolation('invalid_bindings')
    job=c.execute("SELECT owner_user_id,ownership_state,hidden FROM jobs WHERE id=?",(job_id,)).fetchone()
    if not job or not job['owner_user_id'] or job['ownership_state']!='verified' or job['hidden']:
        raise OwnershipViolation('unverified_job_owner')
    owner=job['owner_user_id'];manifest=[];seen=set()
    for b in bindings:
        if not isinstance(b,dict) or set(b)!={'asset_id','slot','role','position'}:
            raise OwnershipViolation('invalid_binding_shape')
        aid,slot,role,pos=b['asset_id'],b['slot'],b['role'],b['position']
        if any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}',v) for v in (aid,slot,role)) or type(pos) is not int or pos<0:
            raise OwnershipViolation('invalid_binding')
        if slot in seen:raise OwnershipViolation('duplicate_slot')
        seen.add(slot)
        rel=c.execute("""SELECT 1 FROM job_input_assets WHERE job_id=? AND owner_user_id=?
          AND asset_id=? AND slot_key=? AND role=? AND position=?""",(job_id,owner,aid,slot,role,pos)).fetchone()
        if not rel:raise OwnershipViolation('missing_immutable_binding')
        if c.execute('SELECT 1 FROM asset_deletions WHERE owner_user_id=? AND asset_id=?',(owner,aid)).fetchone():
            raise OwnershipViolation('deleted_asset')
        asset=c.execute("""SELECT storage_key,mime_type,size_bytes FROM input_assets
          WHERE asset_id=? AND owner_user_id=? AND ownership_state='verified'""",(aid,owner)).fetchone()
        if not asset:
            asset=c.execute("""SELECT a.storage_key,a.mime_type,a.size_bytes FROM job_assets a
              JOIN jobs source ON source.id=a.job_id WHERE a.asset_id=? AND a.owner_user_id=?
              AND a.ownership_state='verified' AND a.status='available'
              AND source.owner_user_id=? AND source.ownership_state='verified' AND source.hidden=0
              AND (source.active_attempt_id IS NULL OR a.attempt_id=source.active_attempt_id)""",(aid,owner,owner)).fetchone()
        if not asset:raise OwnershipViolation('asset_not_owned_or_available')
        key,mime,size=asset['storage_key'],asset['mime_type'],asset['size_bytes']
        if mime not in ('image/png','image/jpeg','image/webp') or not isinstance(size,int) or not 0<size<=limit_bytes:
            raise OwnershipViolation('invalid_input_media')
        if not isinstance(key,str) or not re.fullmatch(r'(?:inputs|outputs)/[A-Za-z0-9_./-]{8,260}',key) or any(x in {'.','..',''} for x in key.split('/')):
            raise OwnershipViolation('unsafe_storage_key')
        # Verify R2 content outside an SQLite write transaction in the caller.
        stream=r2.get_object(Bucket=bucket,Key=key)['Body']
        try:content=stream.read(size+1)
        finally:
            if hasattr(stream,'close'):stream.close()
        if len(content)!=size:raise OwnershipViolation('r2_object_mismatch')
        manifest.append({'asset_id':aid,'slot':slot,'role':role,'key':key,
                         'mime_type':mime,'size_bytes':size,'sha256':hashlib.sha256(content).hexdigest()})
    return manifest
