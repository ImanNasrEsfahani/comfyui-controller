"""Authenticated self-service Salad controls for the current single shared GPU group.

All signed-in, active accounts can start/stop/scale. No admin approval is needed.
Operations are constrained to the *configured* group, with the existing
provider reconciliation, active-job safety guards, and CSRF protection.
A group is SHARED: this module deliberately does not claim per-user isolation.
"""
from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from . import db, direct_queue, salad_control, security

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/self-service/gpu', tags=['Self-service GPU'])
authenticated = Depends(security.require_active_user)


def queue_summary():
    """Only aggregate counts, never other users' job IDs or prompt data."""
    with db.connect() as c:
        rows = c.execute("""SELECT state,COUNT(*) AS n FROM jobs
            WHERE execution_mode='direct' AND state IN
              ('pending','running','finalizing','cancel_requested','stalled')
            GROUP BY state""").fetchall()
    counts = {r['state']: r['n'] for r in rows}
    return {
        'waiting': counts.get('pending', 0),
        'active': sum(counts.get(key, 0) for key in ('running', 'finalizing', 'cancel_requested')),
        'uncertain': counts.get('stalled', 0),
    }


def fail(exc):
    if isinstance(exc, (ValueError, RuntimeError)):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, httpx.HTTPStatusError):
        raise HTTPException(502, f'Salad rejected the operation (HTTP {exc.response.status_code})') from exc
    logger.warning('GPU control provider error: %s', type(exc).__name__)
    raise HTTPException(502, 'Salad connection is unavailable') from exc


@router.get('')
def status(user=authenticated):
    # No privileged token is returned to the browser, nor are identifiers for
    # the owners of other jobs.
    if not direct_queue.enabled():
        return {'enabled': False, 'status': 'disabled', 'replicas': 0,
                'pending_change': False, 'instances': [], 'queue': queue_summary(),
                'shared': True, 'note': 'Direct Queue is not configured'}
    try:
        provider = salad_control.status()
    except Exception as exc:
        fail(exc)
    instances = provider.get('instances', [])
    return {
        'enabled': True,
        'status': provider.get('status') or 'unknown',
        'replicas': provider.get('replicas') or 0,
        'pending_change': bool(provider.get('pending_change')),
        'instances': [{'state': a.get('state'), 'ready': a.get('ready'),
                       'pulling_progress': a.get('pulling_progress')} for a in instances],
        'queue': queue_summary(),
        'shared': True,
        'keep_warm': bool(provider.get('keep_warm')),
        'auto_gpu_control': bool(provider.get('auto_gpu_control')),
        'note': 'This is one shared Salad GPU group, not a dedicated GPU for each user',
    }


@router.post('/{action}')
def control(action: Literal['start', 'one', 'zero', 'stop'], request: Request,
            user=authenticated):
    security.require_csrf(request)
    if not direct_queue.enabled():
        raise HTTPException(503, 'Direct Queue is not enabled')
    # Prevent a user from switching off a GPU while *any* user's work is queued
    # or could still be running. Existing salad_control also fences uncertain
    # provider operations, active leases, Keep Warm, and concurrent changes.
    if action in ('stop', 'zero'):
        counts = queue_summary()
        if counts['waiting'] or counts['active'] or counts['uncertain']:
            raise HTTPException(409, 'Cannot shut down a shared GPU while jobs are queued, active, or uncertain')
    try:
        if action == 'start':
            result = salad_control.start(source='self_service')
        elif action == 'one':
            result = salad_control.request_one_replica(source='self_service')
        elif action == 'zero':
            result = salad_control.set_replicas(0, source='self_service')
        else:
            result = salad_control.stop(source='self_service')
    except Exception as exc:
        fail(exc)
    return {'action': action, 'result': result,
            'message': 'Provider operation requested; refresh to confirm actual state'}
