#!/usr/bin/env python3
"""Read-only operator preflight (no model approval, GPU startup or DB writes)."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    backend=root/'backend'
    if backend.is_dir():sys.path.insert(0,str(backend))


def main():
    from app import direct_queue, settings_store
    from app.owner_direct_bridge import workflow_catalog
    report=workflow_catalog({'user_id':'operator-preflight','roles':['admin']})
    active=settings_store.active()
    seen=direct_queue.load_setting('direct_worker_seen', None)
    # Never output worker credentials, environment variables or raw job inputs.
    summary={
        'active_image':active.get('image'),
        'active_group':active.get('group_name'),
        'direct_queue_enabled':direct_queue.enabled(),
        'worker_seen_observed':bool(seen),
        'runtime_ready':seen.get('runtime_ready') if isinstance(seen,dict) else None,
        'legacy_workflow_count':len(report['items']),
        'allowlist_candidates':[{'name':w['name'], 'model_files':w['model_files'],
                                 'allowlist_value':w['id']+'@'+w['graph_sha256'],
                                 'can_submit':w['can_submit']} for w in report['items']],
        'safety':'These are graph metadata and operator allowlist candidates, NOT verified inference-ready models.',
    }
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('PREFLIGHT FAILED: '+type(exc).__name__+': '+str(exc),file=sys.stderr)
        raise SystemExit(2)
