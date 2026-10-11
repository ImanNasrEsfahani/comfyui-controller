"""Feature-gated service-only worker capabilities intake. Not a dispatch endpoint.

No browser auth, no client-side role, no actual model-ready assertion. A future
approved allocator must join verified runtime evidence to a pinned registry
revision and immutable job snapshot before emitting v11 signed claims.
"""
from __future__ import annotations
import hmac
import json
import os
import re
from uuid import uuid4
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from . import db

router=APIRouter(prefix='/api/v2/worker',tags=['v11 worker private'])
DIGEST=re.compile(r'^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_./-]+@sha256:[a-f0-9]{64}$')

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Artifact(Strict):
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,96}$')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    verified:bool=False
class Worker(Strict):
    worker_id:str=Field(min_length=1,max_length=128)
    generation:str=Field(min_length=8,max_length=128)
    worker_image_digest:str=Field(min_length=78,max_length=300)
    deployment_revision_id:str=Field(min_length=1,max_length=96)
    comfyui_api_ready:bool
    model_versions:list[Artifact]=Field(default_factory=list,max_length=64)
    lora_versions:list[Artifact]=Field(default_factory=list,max_length=128)
    node_inventory:list[str]=Field(default_factory=list,max_length=256)

def gate(token):
    if os.getenv('WORKER_V11_CAPABILITIES_ENABLED','false').lower()!='true':
        raise HTTPException(503,'Worker v11 capabilities are disabled')
    expected=os.getenv('DIRECT_WORKER_TOKEN','')
    if not expected or len(expected)<32 or not token or not hmac.compare_digest(token,expected):
        raise HTTPException(401,'Invalid worker credential')

@router.post('/hello')
def hello(body:Worker,x_worker_token:str|None=Header(default=None)):
    gate(x_worker_token)
    if not DIGEST.fullmatch(body.worker_image_digest) or len(body.node_inventory)!=len(set(body.node_inventory)):
        raise HTTPException(422,'Invalid pinned runtime inventory')
    for node in body.node_inventory:
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,95}',node):
            raise HTTPException(422,'Invalid node inventory')
    # A service's self-report is observation only, not test-confirmed readiness.
    with db.connect() as c:
        needed={'worker_v11_observations','schema_migrations'}
        if not needed<={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            raise HTTPException(503,'Phase11 migration required')
        c.execute('BEGIN IMMEDIATE')
        c.execute('''INSERT INTO worker_v11_observations(id,worker_id,generation,image_digest,
          deployment_revision_id,api_ready,models_json,loras_json,nodes_json,observed_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)''',
          (str(uuid4()),body.worker_id,body.generation,body.worker_image_digest,
          body.deployment_revision_id,int(body.comfyui_api_ready),
          json.dumps([a.model_dump() for a in body.model_versions]),
          json.dumps([a.model_dump() for a in body.lora_versions]),
          json.dumps(body.node_inventory),db.utcnow()))
    return {'accepted':True,'compatibility':'unverified','model_ready':'unknown',
            'dispatch_enabled':False}

@router.post('/claim')
def claim(x_worker_token:str|None=Header(default=None)):
    gate(x_worker_token)
    # Existing owner-scoped Job submission and runtime compatibility are not
    # DONE_VERIFIED. Do not claim old queue work just to 'test' the new adapter.
    raise HTTPException(503,'Signed worker claim disabled pending verified job allocator')
