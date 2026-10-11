"""OPT-IN bootstrap of signed v11 claims; old Worker remains the default.

Attestation JSON is a controlled, checksum-pinned local file. It is NOT proof
of a successful GPU inference. The backend still refuses v11 dispatch until
Phase03/07/09/10 owner, compatibility and compiled-job gates are complete.
"""
from __future__ import annotations
import hashlib,json,os,threading
from pathlib import Path
from v11_execution import verify_claim,cleanup

_STAGED={}
_LOCK=threading.Lock()


def load_manifest():
    raw_path=os.environ.get('WORKER_V11_ATTESTATION_FILE','')
    expected=os.environ.get('WORKER_V11_ATTESTATION_SHA256','')
    if not raw_path or not expected or len(expected)!=64:
        raise RuntimeError('Trusted Worker v11 attestation not configured')
    path=Path(raw_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
        raise RuntimeError('Worker attestation file invalid')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise RuntimeError('Worker attestation checksum mismatch')
    obj=json.loads(raw)
    if set(obj)!={'worker_image_digest','model_versions_ready','lora_versions_ready','node_inventory'}:
        raise RuntimeError('Invalid Worker attestation schema')
    return obj


def build_payload(job):
    attested=load_manifest()
    secret=os.environ.get('WORKER_V11_SIGNING_KEY','')
    bucket=os.environ.get('R2_BUCKET','')
    if not secret or not bucket or len(secret)<32:
        raise RuntimeError('Worker v11 secrets not provisioned')
    # boto3 is intentionally imported only in opt-in mode; container image
    # must separately prove that its pinned build contains this dependency.
    import boto3
    client=boto3.client('s3',endpoint_url=os.environ['R2_ENDPOINT_URL'],
                        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
                        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
                        region_name=os.environ.get('R2_REGION','auto'))
    payload,paths=verify_claim(job,secret=secret,worker_image_digest=attested['worker_image_digest'],
       ready_models=set(attested['model_versions_ready']),
       ready_loras={tuple(x) for x in attested['lora_versions_ready']},
       node_inventory=set(attested['node_inventory']),s3=client,bucket=bucket,
       input_dir=os.environ.get('COMFYUI_INPUT_DIR','/opt/ComfyUI/input'))
    with _LOCK:_STAGED[job['attempt_id']]=paths
    return payload


def cleanup_attempt(job):
    with _LOCK: paths=_STAGED.pop(job.get('attempt_id'),[])
    cleanup(paths)


def capability_report(worker_id,generation):
    a=load_manifest()
    return {'worker_id':worker_id,'generation':generation,
            'worker_image_digest':a['worker_image_digest'],
            'deployment_revision_id':os.environ['WORKER_V11_DEPLOYMENT_REVISION'],
            'comfyui_api_ready':False, # never assert actual model inference readiness
            # No model/lora is announced as installed without independent GPU
            # inventory + exact artifact hashes. Do not fabricate checksum fields.
            'model_versions':[],
            'lora_versions':[],
            'node_inventory':a['node_inventory']}
