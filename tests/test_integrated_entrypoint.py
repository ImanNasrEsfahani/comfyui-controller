"""Pure regression test for integrating router modules without a live provider.

Uses the checked-in Phase02-13 router modules in the checkout when pytest is run
from the repo root. No DB migrations, provider or secrets are required.
"""
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_runs_new_entrypoint():
    body = (ROOT / 'docker-compose.yml').read_text()
    assert 'app.integrated_main:app' in body
    assert 'controller_data:/app/data' in body
    assert 'DIRECT_GPU_AUTO_CONTROL=true' not in body


def test_frontend_flags_enable_new_ui_at_build():
    body = (ROOT / 'frontend/Dockerfile').read_text()
    assert 'ARG VITE_AUTH_UI_ENABLED=true' in body
    assert 'ARG VITE_WORKFLOW_STUDIO_ENABLED=true' in body
    assert body.index('ENV VITE_AUTH_UI_ENABLED=') < body.index('RUN npm run build')


def test_main_integrator_filters_legacy_global_paths():
    body = (ROOT / 'backend/app/integrated_main.py').read_text()
    ast.parse(body)
    for name in ('auth_router', 'media_router', 'owner_router', 'account_router',
                 'registry_router', 'parameters_router', 'workflow_router',
                 'worker_v11_router', 'scheduler_v12_router', 'video_v13_router'):
        assert name in body
    assert "if not path.startswith('/api/')" in body
    assert "'/api/worker/'" in body
    assert "'/api/direct/'" in body
    assert "'/api/salad/'" in body


def test_migration_is_offline_and_backs_up_sqlite():
    body = (ROOT / 'backend/app/migrate_offline.py').read_text()
    ast.parse(body)
    assert 'backup_copy(live, saved)' in body
    assert "PHASES = ('01', '02', '05'" in body
    assert "for action in" not in body


def test_admin_credentials_not_cli_arguments():
    body = (ROOT / 'backend/app/create_admin.py').read_text()
    ast.parse(body)
    assert 'getpass.getpass' in body
    assert 'sqlite3.connect' in body
