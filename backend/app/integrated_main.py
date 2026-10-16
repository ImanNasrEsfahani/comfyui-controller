"""Production integrated entrypoint; owner-scoped APIs take precedence.

Legacy unscoped jobs and assets APIs remain inaccessible from browser sessions.
The authenticated self-service GPU router is intentionally enabled for every
active account; underlying single-group operations still enforce job safety.
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
from .gpu_self_service import router as gpu_self_service_router

# Auth first; media and owner-scoped routes before old legacy API routes.
ROUTERS = (
    auth_router,
    media_router,
    owner_router,
    account_router,
    gpu_self_service_router,
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

    for router in ROUTERS:
        app.include_router(router)
    appended = tuple(app.router.routes[len(previous):])
    if not appended:
        raise RuntimeError('Router integration produced no routes')

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

    def keep_legacy(route):
        path = getattr(route, 'path', '')
        if not path.startswith('/api/'):
            return True
        return any(path.startswith(prefix) for prefix in (
            '/api/worker/',   # dedicated Worker credential
            '/api/direct/',   # dedicated internal credential
            '/api/salad/',    # dedicated internal credential
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
        ('/api/self-service/gpu', 'GET'),
        ('/api/self-service/gpu/{action}', 'POST'),
        ('/api/legacy-direct/workflows', 'GET'),
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
