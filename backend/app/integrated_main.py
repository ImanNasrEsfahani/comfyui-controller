"""Production entrypoint for the integrated, owner-scoped UI (Phase 02–13).

Preserve the original app.main for the legacy scheduler/worker implementation,
but do NOT expose its global, unscoped user/job APIs under the new multi-user UI.
No GPU feature is implicitly activated; all new routers retain their own gates.

Use: uvicorn app.integrated_main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from fastapi.routing import APIRoute

from .main import app
from .auth import router as auth_router
from .media_api import router as media_router
from .owner_api import router as owner_router
from .account_api import router as account_router
from .registry_api import router as registry_router
from .parameters_api import router as parameters_router
from .workflow_api import router as workflow_router
from .worker_v11_api import router as worker_v11_router
from .scheduler_v12_api import router as scheduler_v12_router
from .video_api import router as video_v13_router

# ORDER IS SECURITY-RELEVANT: auth first; Phase06 media before Phase03 owner.
# Legacy /api/jobs, /api/assets, /api/uploads etc. MUST NOT remain reachable:
# they are single-operator APIs, not owner-bound. Preserve token-guarded legacy
# Worker, Direct Queue and Salad control endpoints for compatibility only.
ROUTERS = (
    auth_router,
    media_router,
    owner_router,
    account_router,
    registry_router,
    parameters_router,
    workflow_router,
    worker_v11_router,
    scheduler_v12_router,
    video_v13_router,
)


def _route_methods(route):
    return frozenset(getattr(route, 'methods', ()) or ())


def _route_identity(route):
    return (getattr(route, 'path', ''), _route_methods(route))


def _install_once():
    if getattr(app.state, 'integrated_owner_api', False):
        return

    previous = tuple(app.router.routes)
    if not any(getattr(route, 'path', '') == '/health' for route in previous):
        raise RuntimeError('Expected Controller app.main baseline is unavailable')

    # Importing modules should not start workers or alter the provider.
    for router in ROUTERS:
        app.include_router(router)
    appended = tuple(app.router.routes[len(previous):])
    if not appended:
        raise RuntimeError('Router integration produced no routes')

    # Skip only exact duplicate methods. A new router must not leave an old
    # endpoint silently shadowing a session-bound endpoint.
    new_routes = []
    keys = set()
    duplicates = []
    for route in appended:
        identity = _route_identity(route)
        if identity in keys:
            duplicates.append(identity[0])
            continue
        keys.add(identity)
        new_routes.append(route)

    # Legacy API paths not on this explicit allowlist are not safe to expose
    # to a multi-user frontend. The original legacy app remains importable,
    # but its global jobs/assets/workflow endpoints are no longer HTTP routes.
    def keep_legacy(route):
        path = getattr(route, 'path', '')
        if not path.startswith('/api/'):
            return True
        return any(path.startswith(prefix) for prefix in (
            '/api/worker/',   # separate worker credential
            '/api/direct/',   # separate admin/worker credentials
            '/api/salad/',    # separate internal admin credential
        ))

    legacy_routes = []
    for route in previous:
        if not keep_legacy(route):
            continue
        identity = _route_identity(route)
        if identity in keys:
            continue
        keys.add(identity)
        legacy_routes.append(route)

    app.router.routes[:] = [*new_routes, *legacy_routes]
    required = {
        ('/api/auth/session', 'GET'),
        ('/api/auth/login', 'POST'),
        ('/api/jobs', 'GET'),
        ('/api/jobs', 'POST'),
        ('/api/users/me', 'GET'),
        ('/api/v2/semantic-workflows', 'GET'),
        ('/api/v2/worker/claim', 'POST'),
        ('/api/v2/video/models', 'GET'),
    }
    actual = {(r.path, method) for r in app.router.routes
              if isinstance(r, APIRoute) for method in r.methods}
    missing = required - actual
    if missing:
        raise RuntimeError('Router integration missing required route(s): '+str(sorted(missing)))

    app.state.integrated_owner_api = True
    app.state.integrated_routes = len(new_routes)
    app.state.excluded_legacy_api_routes = sum(
        1 for route in previous if not keep_legacy(route)
    )
    app.state.overlapping_new_routes = tuple(duplicates)


_install_once()
