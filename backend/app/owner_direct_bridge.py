"""Owner-transactional, explicitly allowlisted legacy Direct Queue bridge.

NOT a Phase07 verified-model catalog or a replacement for signed v11 claims.
Operator must separately establish compatibility with the deployed Worker.
Never exposed to non-admin users. No network calls during admission.
"""
from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import urlparse
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import HTTPException
from . import db, contracts, direct_queue, owner_repository, settings_store
from .config import settings
from .template import render_template

ALLOWED = re.compile(r'^[A-Za-z0-9_.:-]{1,80}@[a-f0-9]{64}$')
SHA = re.compile(r'^[a-f0-9]{64}$')
REFERENCE = re.compile(r'^input\.image_[0-9]+$')
NUMBER = re.compile(r'(seed|steps|width|height|count)$', re.I)
DECIMAL = re.compile(r'(cfg|denoise|strength(?:_(?:model|clip))?|(?:model|clip)_strength)$', re.I)
LOADER_KEYS = ('ckpt_name', 'unet_name', 'vae_name', 'clip_name')


def require_operator(actor):
    if not ({'admin', 'superadmin'} & set(actor.get('roles', ()) or ())):
        raise HTTPException(403, 'Administrator role required for legacy Direct Queue')


def allowlist():
    raw = os.environ.get('OWNER_DIRECT_ALLOWLIST', '').strip()
    if not raw:
        return {}
    parts = [p.strip() for p in raw.split(',')]
    if len(parts) > 32 or any(not ALLOWED.fullmatch(part) for part in parts):
        raise HTTPException(503, 'Invalid OWNER_DIRECT_ALLOWLIST configuration')
    mapping = {}
    for part in parts:
        ident, checksum = part.rsplit('@', 1)
        if ident in mapping and mapping[ident] != checksum:
            raise HTTPException(503, 'Conflicting workflow pins')
        mapping[ident] = checksum
    return mapping


def configured():
    return os.environ.get('OWNER_DIRECT_JOB_ENABLED', 'false').lower() == 'true'


def ready_for_admission():
    if not configured() or not direct_queue.enabled():
        return False
    # The deployment identity is an explicit operator policy, not proof that
    # model weights inside the Worker are loaded or compatible.
    expected_image = os.environ.get('OWNER_DIRECT_IMAGE', '').strip()
    if not expected_image:
        return False
    try:
        return settings_store.active().get('image') == expected_image
    except Exception:
        return False


def filename(value):
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    if any(x in value.lower() for x in ('{{', '://', '?', '#', 'token', 'secret')):
        return None
    value = value.replace('\\', '/').split('/')[-1]
    return value if re.fullmatch(r'[\w .()+-]{1,150}', value) else None


def observed_models(graph):
    found = set()
    for node in graph.values():
        if isinstance(node, dict) and isinstance(node.get('inputs'), dict):
            for key in LOADER_KEYS:
                value = filename(node['inputs'].get(key))
                if value:
                    found.add(value)
    return sorted(found)


def field_type(key):
    if NUMBER.search(key):
        return 'integer'
    if DECIMAL.search(key):
        return 'number'
    if key.endswith('.enabled'):
        return 'boolean'
    if REFERENCE.fullmatch(key):
        return 'reference'
    return 'text'


def workflow_catalog(actor):
    require_operator(actor)
    pinned = allowlist()
    permitted = ready_for_admission()
    with db.connect() as c:
        rows = c.execute('SELECT id,name,api_prompt FROM workflows ORDER BY updated_at DESC LIMIT 100').fetchall()
    items = []
    for row in rows:
        try:
            graph = json.loads(row['api_prompt'])
            if not isinstance(graph, dict) or len(graph) > 1000:
                continue
            revision = contracts.digest(graph)
            names = observed_models(graph)
            fields = [{'key':key, 'type':field_type(key)} for key in contracts.placeholders(graph)]
            allowed = pinned.get(row['id']) == revision and permitted
            items.append({'id':row['id'], 'name':row['name'], 'graph_sha256':revision,
                          'model_files':names, 'fields':fields, 'can_submit':allowed,
                          'readiness':'unverified', 'model_approval':'not_asserted'})
        except (ValueError, TypeError):
            continue
    return {'items':items, 'operator_enabled':permitted,
            'note':'Legacy workflow metadata only; not a verified model registry. Pin workflow SHA and deploy image explicitly before submission.'}


def _reference_owner(c, uid, key):
    # Reuse the central owner repository's deletion and parent-job guards.
    # Never trust an S3 key merely because it exists in an unclaimed row.
    for table in ('input_assets', 'job_assets'):
        for row in c.execute(f'SELECT asset_id FROM {table} WHERE storage_key=? LIMIT 5', (key,)):
            owned = owner_repository.asset(c, uid, row['asset_id'])
            if owned and owned.get('storage_key') == key:
                return True
    return False


def resolve_references(c, uid, values):
    """Accept only asset:<uuid> or exact private S3 URI, never browser URLs."""
    result = dict(values)
    for key, value in values.items():
        if not REFERENCE.fullmatch(key):
            continue
        if value == '':
            continue  # optional reference validity is checked by contracts
        if not isinstance(value, str):
            raise HTTPException(422, 'Reference must be a stored private asset')
        if value.startswith('asset:'):
            aid = value[6:]
            if not re.fullmatch(r'[0-9a-fA-F-]{36}', aid):
                raise HTTPException(422, 'Invalid reference asset ID')
            asset = owner_repository.asset(c, uid, aid)
            if not asset:
                raise HTTPException(404, 'Reference asset was not found')
            result[key] = f's3://{settings.r2_bucket}/{asset["storage_key"]}'
        else:
            u = urlparse(value)
            if u.scheme != 's3' or u.netloc != settings.r2_bucket or u.query or u.fragment or u.username or u.password:
                raise HTTPException(422, 'Reference must be stored in the private bucket')
            if not _reference_owner(c, uid, u.path.lstrip('/')):
                raise HTTPException(404, 'Reference asset was not found')
    return result


def _validate(body, graph, values, contract):
    if body.priority is not None and body.priority != settings.salad_priority:
        raise HTTPException(422, 'Unsupported Direct Queue priority')
    if body.source_job_id is not None:
        raise HTTPException(422, 'Use the owner-scoped Retry endpoint for historical Jobs')
    if body.workflow_version and body.workflow_version != contract['workflow_version']:
        raise HTTPException(409, 'Workflow changed. Reload the form.')
    if body.capability_version and body.capability_version != contract['capability_version']:
        raise HTTPException(409, 'Capabilities changed. Reload the form.')
    if body.seed_mode not in (None, 'fixed'):
        raise HTTPException(422, 'Random seed must be chosen explicitly as a value in this pilot')
    if body.reference_order is not None:
        raise HTTPException(422, 'Reference reorder is unavailable in this pilot')
    return contracts.validate_variables(graph, values)


def _owner_key(uid, key):
    return str(uuid5(NAMESPACE_URL, 'comfy-owner-direct:v1:' + uid + ':' + key))


def submit(actor, body):
    require_operator(actor)
    if not ready_for_admission():
        raise HTTPException(503, 'Owner Direct Queue is disabled or deployed Image does not match operator pin')
    if not body.client_request_id:
        raise HTTPException(422, 'client_request_id is required for idempotency')
    pinned = allowlist()
    if body.workflow_id not in pinned:
        raise HTTPException(403, 'Workflow is not explicitly allowlisted')
    if len(json.dumps(body.variables)) > 30000:
        raise HTTPException(413, 'Input payload too large')
    uid = actor['user_id']
    # Validate request fingerprint BEFORE generating a Job ID or retrying; this
    # prevents duplicate GPU Jobs for timed-out HTTP responses.
    fingerprint = contracts.digest(body.model_dump(exclude={'client_request_id'}))
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        owner_repository.require_schema(c)
        prior = c.execute('''SELECT request_hash,job_id FROM idempotency_keys
            WHERE owner_user_id=? AND client_key=?''', (uid, body.client_request_id)).fetchone()
        if prior:
            if prior['request_hash'] != fingerprint:
                raise HTTPException(409, 'Request key was already used with different inputs')
            row = owner_repository.job(c, uid, prior['job_id'])
            if not row:
                raise HTTPException(409, 'Previously accepted Job is not available')
            return {'id':row['id'], 'state':row['state'], 'duplicate':True}
        wf = c.execute('SELECT * FROM workflows WHERE id=?', (body.workflow_id,)).fetchone()
        if not wf:
            raise HTTPException(404, 'Workflow does not exist')
        graph = json.loads(wf['api_prompt'])
        if not isinstance(graph, dict) or len(graph) > 1000 or contracts.digest(graph) != pinned[body.workflow_id]:
            raise HTTPException(409, 'Workflow graph changed; re-approve exact SHA256')
        workflow = {'id': wf['id'], 'name': wf['name'], 'api_prompt':graph,
                    'ui_workflow':None,
                    'capability_spec':json.loads(wf['capabilities_json']) if wf['capabilities_json'] else None}
        contract = contracts.workflow_contract(workflow)
        values = resolve_references(c, uid, body.variables)
        values = _validate(body, graph, values, contract)
        optional = {item['variable_key'] for item in contract['capabilities'].get('references', [])
                    if not item.get('required', True)}
        values = contracts.validate_image_references(values, optional)
        snapshot = contracts.effective_snapshot(workflow, values, settings.salad_priority,
                                                client_request_id=body.client_request_id, seed_mode='fixed')
        contracts.ensure_no_credentials(snapshot['prompt'], 'workflow')
        job_id = str(uuid4())
        prompt = {'id':job_id, 'prompt':render_template(graph, values),
                  's3':{'bucket':settings.r2_bucket,'prefix':f'outputs/{job_id}/','async':False}}
        timestamp = db.utcnow()
        safe_key = _owner_key(uid, body.client_request_id)
        c.execute('''INSERT INTO jobs
            (id,salad_job_id,workflow_id,state,request_json,priority,salad_queue,
             variables_json,created_at,updated_at,execution_mode,snapshot_json,
             client_request_id,request_hash,owner,source_job_id,queued_at,
             active_attempt_id,owner_user_id,ownership_state)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (job_id,None,body.workflow_id,'pending',json.dumps(prompt,separators=(',',':')),
             settings.salad_priority,'direct',json.dumps(values,separators=(',',':')),
             timestamp,timestamp,'direct',json.dumps(snapshot,separators=(',',':')),
             safe_key,fingerprint,'controller',None,timestamp,None,uid,'verified'))
        c.execute('''INSERT INTO idempotency_keys
            (owner_user_id,client_key,request_hash,job_id,created_at,expires_at)
            VALUES (?,?,?,?,?,?)''',
            (uid,body.client_request_id,fingerprint,job_id,timestamp,None))
    return {'id':job_id, 'state':'pending', 'duplicate':False}


def lookup_by_client_key(uid, key):
    if not key or len(key)>128:
        raise HTTPException(422, 'Invalid client request key')
    with db.connect() as c:
        row = c.execute('''SELECT j.* FROM idempotency_keys i JOIN jobs j ON j.id=i.job_id
            WHERE i.owner_user_id=? AND i.client_key=? AND j.owner_user_id=?
            AND j.ownership_state='verified' AND j.hidden=0 LIMIT 1''',(uid,key,uid)).fetchone()
        return row
