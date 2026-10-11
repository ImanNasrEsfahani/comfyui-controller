"""Phase11 mutually authenticated, lease-bound *offline* worker envelope contract.

This module does not issue dispatches on its own. Only the trusted controller
may sign after confirming an authenticated owner, immutable compilation, an
approved image/profile and an active lease. The browser never receives keys.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import re
import time
from copy import deepcopy

class ContractViolation(ValueError):
    def __init__(self, code):
        self.code=code
        super().__init__(code)

HEX64=re.compile(r'^[a-f0-9]{64}$')
OPAQUE=re.compile(r'^[A-Za-z0-9_-]{1,96}$')
IMAGE_REF=re.compile(r'^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_./-]+@sha256:([a-f0-9]{64})$')
SAFE_NODE=re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,95}$')


def canonical(value):
    try: return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    except (ValueError,TypeError,OverflowError) as exc:raise ContractViolation('invalid_json') from exc


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def verify_graph(graph, inventory):
    if not isinstance(graph,dict) or not 1<=len(graph)<=160 or not isinstance(inventory,(list,tuple,set)):
        raise ContractViolation('invalid_graph')
    trusted=set(inventory)
    if not trusted or len(trusted)>512 or any(not isinstance(c,str) or not SAFE_NODE.fullmatch(c) for c in trusted):
        raise ContractViolation('invalid_node_inventory')
    for node_id,node in graph.items():
        if not isinstance(node_id,str) or not OPAQUE.fullmatch(node_id) or not isinstance(node,dict) or set(node)!={'class_type','inputs'}:
            raise ContractViolation('invalid_graph_node')
        if node['class_type'] not in trusted or not SAFE_NODE.fullmatch(node['class_type']):
            raise ContractViolation('unapproved_node')
        if not isinstance(node['inputs'],dict) or len(node['inputs'])>40:
            raise ContractViolation('invalid_node_inputs')
        for k,v in node['inputs'].items():
            if not isinstance(k,str) or not SAFE_NODE.fullmatch(k):raise ContractViolation('invalid_input_key')
            if isinstance(v,str):
                if len(v)>16000 or '{{' in v or '}}' in v or re.search(r'(?:https?://|file://|\x00|\n|\r)',v,re.I):
                    raise ContractViolation('unsafe_input')
            elif isinstance(v,(int,float,bool)) or v is None:pass
            elif isinstance(v,list) and len(v)==2 and all(isinstance(q,str) for q in v):
                if v[0] not in graph or not OPAQUE.fullmatch(v[1]):raise ContractViolation('bad_graph_reference')
            elif isinstance(v,dict) and set(v)=={'asset_slot'} and isinstance(v['asset_slot'],str) and OPAQUE.fullmatch(v['asset_slot']):pass
            else:raise ContractViolation('unsafe_input')
    if len(canonical(graph))>262144:raise ContractViolation('graph_too_large')
    return True


def validate_body(body, *, worker_image_digest, ready_models, ready_loras, node_inventory, now=None):
    now=time.time() if now is None else now
    if not isinstance(body,dict):raise ContractViolation('invalid_body')
    expected={'version','job_id','attempt_id','lease_hash','worker_image_digest','model_version_id',
              'workflow_version_id','deployment_revision_id','compiled_graph','compiled_graph_sha256',
              'inputs','loras','output_prefix','issued_at','expires_at'}
    if set(body)!=expected or body['version']!=11:raise ContractViolation('invalid_envelope_version')
    for key in ('job_id','attempt_id','model_version_id','workflow_version_id','deployment_revision_id'):
        if not isinstance(body[key],str) or not OPAQUE.fullmatch(body[key]):raise ContractViolation('invalid_identifier')
    if not isinstance(body['worker_image_digest'],str) or not IMAGE_REF.fullmatch(body['worker_image_digest']):
        raise ContractViolation('invalid_image_digest')
    if body['worker_image_digest']!=worker_image_digest:raise ContractViolation('wrong_worker_image')
    if body['model_version_id'] not in ready_models:raise ContractViolation('model_not_verified_ready')
    if not isinstance(body['lease_hash'],str) or not HEX64.fullmatch(body['lease_hash']):raise ContractViolation('invalid_lease_hash')
    if not isinstance(body['issued_at'],int) or not isinstance(body['expires_at'],int):raise ContractViolation('invalid_expiry')
    if body['issued_at']>now+30 or not now<body['expires_at']<=body['issued_at']+600:
        raise ContractViolation('envelope_expired')
    if body['output_prefix']!=f"outputs/{body['job_id']}/{body['attempt_id']}/":
        raise ContractViolation('invalid_output_prefix')
    if not HEX64.fullmatch(str(body['compiled_graph_sha256'])) or digest(body['compiled_graph'])!=body['compiled_graph_sha256']:
        raise ContractViolation('graph_hash_mismatch')
    verify_graph(body['compiled_graph'],node_inventory)
    if not isinstance(body['inputs'],list) or len(body['inputs'])>16:raise ContractViolation('invalid_assets')
    slots=set()
    for a in body['inputs']:
        if not isinstance(a,dict) or set(a)!={'asset_id','slot','role','key','sha256','size_bytes','mime_type'}:
            raise ContractViolation('invalid_assets')
        if any(not isinstance(a[k],str) or not OPAQUE.fullmatch(a[k]) for k in ('asset_id','slot','role')):
            raise ContractViolation('invalid_assets')
        if a['slot'] in slots:raise ContractViolation('duplicate_slot')
        slots.add(a['slot'])
        if not isinstance(a['key'],str) or not re.fullmatch(r'(?:inputs|outputs)/[A-Za-z0-9_./-]{8,260}',a['key']) or any(p in {'..','.'} for p in a['key'].split('/')):
            raise ContractViolation('unsafe_storage_key')
        if not HEX64.fullmatch(str(a['sha256'])) or type(a['size_bytes']) is not int or not 0<a['size_bytes']<=1024**3:
            raise ContractViolation('invalid_asset_integrity')
        if a['mime_type'] not in ('image/png','image/jpeg','image/webp'):
            raise ContractViolation('unsupported_asset_type')
    if not isinstance(body['loras'],list) or len(body['loras'])>8:raise ContractViolation('invalid_loras')
    seen=set()
    for l in body['loras']:
        if not isinstance(l,dict) or set(l)!={'id','sha256','enabled','model_strength','clip_strength','order'}:
            raise ContractViolation('invalid_lora')
        if not isinstance(l['id'],str) or not OPAQUE.fullmatch(l['id']) or l['id'] in seen:raise ContractViolation('invalid_lora')
        seen.add(l['id'])
        if l['enabled'] is not True:raise ContractViolation('disabled_lora_in_effective_graph')
        if not HEX64.fullmatch(str(l['sha256'])) or (l['id'],l['sha256']) not in ready_loras:raise ContractViolation('unready_lora')
        if type(l['order']) is not int or l['order']<0 or l['order']>=8:raise ContractViolation('invalid_lora_order')
        for strength in ('model_strength','clip_strength'):
            if type(l[strength]) not in (int,float) or not -2<=l[strength]<=2:
                raise ContractViolation('invalid_lora_strength')
    if sorted(l['order'] for l in body['loras'])!=list(range(len(body['loras']))):
        raise ContractViolation('invalid_lora_order')
    for n in body['compiled_graph'].values():
        for v in n['inputs'].values():
            if isinstance(v,dict) and v['asset_slot'] not in slots:raise ContractViolation('unbound_asset_slot')
    return True


def sign(body, secret):
    if not isinstance(secret,(str,bytes)) or len(secret)<32:raise ContractViolation('weak_signing_key')
    key=secret.encode() if isinstance(secret,str) else secret
    return {'payload':deepcopy(body),'signature':hmac.new(key,canonical(body),hashlib.sha256).hexdigest()}


def verify(envelope, secret, *, lease_token, worker_image_digest, ready_models, ready_loras, node_inventory, now=None):
    if not isinstance(envelope,dict) or set(envelope)!={'payload','signature'}:
        raise ContractViolation('invalid_envelope')
    if not isinstance(secret,(str,bytes)) or len(secret)<32 or not isinstance(lease_token,str) or len(lease_token)<32:
        raise ContractViolation('invalid_credentials')
    key=secret.encode() if isinstance(secret,str) else secret
    expected=hmac.new(key,canonical(envelope['payload']),hashlib.sha256).hexdigest()
    if not isinstance(envelope['signature'],str) or not hmac.compare_digest(envelope['signature'],expected):
        raise ContractViolation('bad_signature')
    body=envelope['payload']
    if not hmac.compare_digest(body.get('lease_hash',''),hashlib.sha256(lease_token.encode()).hexdigest()):
        raise ContractViolation('lease_mismatch')
    validate_body(body,worker_image_digest=worker_image_digest,ready_models=ready_models,
                  ready_loras=ready_loras,node_inventory=node_inventory,now=now)
    return deepcopy(body)
