"""Phase11 signed execution adapter; opt-in, fail closed until controller issues v11 claims.

No browser session, raw user graph, arbitrary public URLs, external shell or
runtime downloads. Staging copies *controller-authorized* objects into the
ComfyUI input directory and only rewrites exact typed asset_slot references.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import v11_contract as contract

class StageError(ValueError):pass


def stage_inputs(body, *, s3, bucket, directory):
    root=Path(directory).resolve()
    if not root.is_dir() or root.is_symlink():raise StageError('invalid_staging_directory')
    names={}
    created=[]
    try:
        for a in body['inputs']:
            if a['slot'] in names:raise StageError('duplicate_slot')
            ext={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[a['mime_type']]
            filename=f"v11_{body['attempt_id']}_{a['slot']}{ext}"
            target=root/filename
            if target.is_symlink() or target.exists():raise StageError('existing_staging_file')
            # The DB-bound manifest was authenticated by HMAC before here.
            stream=s3.get_object(Bucket=bucket,Key=a['key'])['Body']
            try: data=stream.read(a['size_bytes']+1)
            finally:
                if hasattr(stream,'close'):stream.close()
            if len(data)!=a['size_bytes'] or hashlib.sha256(data).hexdigest()!=a['sha256']:
                raise StageError('input_integrity_mismatch')
            if a['mime_type']=='image/png' and not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise StageError('input_mime_mismatch')
            if a['mime_type']=='image/jpeg' and not data.startswith(b'\xff\xd8\xff'):
                raise StageError('input_mime_mismatch')
            if a['mime_type']=='image/webp' and not (data[:4]==b'RIFF' and data[8:12]==b'WEBP'):
                raise StageError('input_mime_mismatch')
            # exclusive create; do not allow path traversal or overwrite.
            with target.open('xb') as f:
                os.chmod(target,0o600)
                f.write(data)
            created.append(target)
            names[a['slot']]=filename
        return names, created
    except BaseException:
        for p in created:p.unlink(missing_ok=True)
        raise


def graph_with_inputs(body,names):
    import copy
    graph=copy.deepcopy(body['compiled_graph'])
    for node in graph.values():
        for key,value in list(node['inputs'].items()):
            if isinstance(value,dict) and set(value)=={'asset_slot'}:
                slot=value['asset_slot']
                if slot not in names:raise StageError('missing_staged_slot')
                node['inputs'][key]=names[slot]
    return graph


def verify_claim(job, *,secret,worker_image_digest,ready_models,ready_loras,node_inventory,
                 s3,bucket,input_dir,now=None):
    if not isinstance(job,dict) or 'signed_execution' not in job:
        raise StageError('unsigned_job_not_allowed_in_v11')
    body=contract.verify(job['signed_execution'],secret,lease_token=job.get('lease_token',''),
            worker_image_digest=worker_image_digest,ready_models=ready_models,
            ready_loras=ready_loras,node_inventory=node_inventory,now=now)
    if body['job_id']!=job.get('job_id') or body['attempt_id']!=job.get('attempt_id'):
        raise StageError('claim_job_mismatch')
    names,created=stage_inputs(body,s3=s3,bucket=bucket,directory=input_dir)
    try:
        graph=graph_with_inputs(body,names)
        # The checked graph hash applies to source graph; only typed asset slots change.
        return {'prompt':graph,'s3':{'bucket':bucket,'prefix':body['output_prefix']}}, created
    except BaseException:
        cleanup(created)
        raise


def cleanup(created):
    for p in created:p.unlink(missing_ok=True)
