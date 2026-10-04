"""Axis 5 infrastructure lifecycle, readiness, session and estimate tests.

All provider and Worker observations in this file are local fakes. These tests
never call Salad, ComfyUI, production databases, or GPU infrastructure.
"""
import os
import time

import pytest

TEST_ENV = {
    "APP_NAME": "axis5-test", "DB_PATH": "/tmp/axis5-unused.db", "MAX_UPLOAD_MB": "10",
    "APP_INTERNAL_TOKEN": "axis5-fake-admin-token", "SALAD_API_KEY": "axis5-fake-provider-key",
    "SALAD_API_BASE_URL": "https://provider.invalid", "SALAD_USER_AGENT": "axis5-tests",
    "SALAD_HTTP_TIMEOUT_SECONDS": "1", "SALAD_ORG": "test-org", "SALAD_PROJECT": "test-project",
    "SALAD_QUEUE_NAME": "test-queue", "SALAD_PRIORITY": "medium", "SALAD_GPU_NAME": "test-gpu",
    "SALAD_CONTAINER_GROUP_NAME": "axis5-test-group", "SALAD_CONTAINER_GROUP_DISPLAY_NAME": "Axis 5 test",
    "SALAD_IMAGE": "ghcr.io/example/controller:test", "SALAD_LEGACY_QUEUE": "legacy-queue",
    "R2_ENDPOINT_URL": "https://storage.invalid", "R2_BUCKET": "test-bucket",
    "R2_ACCESS_KEY_ID": "fake-access", "R2_SECRET_ACCESS_KEY": "fake-storage-secret",
    "R2_REGION": "auto", "R2_PRESIGN_TTL_SECONDS": "60",
    "DIRECT_QUEUE_ENABLED": "true", "DIRECT_GPU_AUTO_CONTROL": "false",
    "DIRECT_WORKER_TOKEN": "w" * 48,
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)

from app import db, direct_queue, instance_contract, salad_control, settings_store
from app.config import settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, request):
    previous_db_path = settings.db_path
    previous_rate = settings.salad_gpu_hourly_rate
    previous_currency = settings.salad_gpu_rate_currency
    def restore_settings():
        object.__setattr__(settings, "db_path", previous_db_path)
        object.__setattr__(settings, "salad_gpu_hourly_rate", previous_rate)
        object.__setattr__(settings, "salad_gpu_rate_currency", previous_currency)
    request.addfinalizer(restore_settings)
    object.__setattr__(settings, "db_path", str(tmp_path / "axis5.sqlite"))
    object.__setattr__(settings, "salad_gpu_hourly_rate", "")
    object.__setattr__(settings, "salad_gpu_rate_currency", "")
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "true")
    monkeypatch.setenv("DIRECT_WORKER_STATUS_STALE_SECONDS", "90")
    db.init_db()
    settings_store.activate({
        "image": "ghcr.io/example/controller:test",
        "group_name": "axis5-test-group",
        "display_name": "Axis 5 test",
    })
    yield


def observation(*, status="running", instances=None):
    return {
        "name": "axis5-test-group", "queue_mode": "direct", "auto_gpu_control": False,
        "hold": False, "status": status, "pending_change": False, "replicas": len(instances or []),
        "counts": {}, "autoscaler_enabled": False, "keep_warm": False,
        "min_replicas": 0, "max_replicas": 1, "instances": instances or [],
    }


def test_pull_percent_requires_a_known_unit_and_valid_bounds():
    assert instance_contract.normalize_pull_progress(0.4)["percent"] is None
    assert instance_contract.normalize_pull_progress(0.4, unit="fraction")["percent"] == 40
    assert instance_contract.normalize_pull_progress(40, unit="percent")["percent"] == 40
    assert instance_contract.normalize_pull_progress(50, unit="bytes", total=200)["percent"] == 25
    assert instance_contract.normalize_pull_progress(201, unit="bytes", total=200)["percent"] is None


def test_worker_generation_fences_late_heartbeats(monkeypatch):
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "true")
    accepted = direct_queue.worker_seen("worker-new", generation="generation-new", started_at=200,
                                        runtime_ready=True)
    stale = direct_queue.worker_seen("worker-old", generation="generation-old", started_at=100,
                                     runtime_ready=True)
    assert accepted["accepted"] is True
    assert stale["accepted"] is False
    assert direct_queue.load_setting("direct_worker_seen")["worker_id"] == "worker-new"


def test_readiness_sessions_and_cost_are_separate_from_model_readiness(monkeypatch):
    worker = {"worker_id": "worker-a", "generation": "gen-a", "at": time.time(),
              "started_at": time.time() - 30, "runtime_ready": True}
    monkeypatch.setattr(direct_queue, "enabled", lambda: True)
    monkeypatch.setattr(direct_queue, "load_setting", lambda key, default=None: worker if key == "direct_worker_seen" else default)
    object.__setattr__(settings, "salad_gpu_hourly_rate", "0.50")
    object.__setattr__(settings, "salad_gpu_rate_currency", "USD")
    first_at = "2026-10-04T10:00:00+00:00"
    first = instance_contract.record(observation(instances=[{
        "id": "instance-a", "state": "running", "ready": True,
        "pulling_progress": 0.25, "pulling_progress_unit": "fraction",
    }]), 1, first_at)
    assert first["readiness"] == "ready"
    assert first["model_readiness"] == "unknown"
    assert first["instances"][0]["pull_progress"]["percent"] == 25
    assert first["financial"]["balance"] is None
    object.__setattr__(settings, "salad_gpu_hourly_rate", "0.75")
    second = instance_contract.record(observation(instances=[{
        "id": "instance-a", "state": "running", "ready": True,
    }]), 2, "2026-10-04T11:00:00+00:00")
    assert second["financial"]["estimated_cost"] == 0.5
    stopped = instance_contract.record(observation(status="stopped"), 3, "2026-10-04T12:00:00+00:00")
    assert stopped["sessions"][0]["stopped_at"] == "2026-10-04T12:00:00+00:00"
    assert stopped["financial"]["estimated_cost"] == 1.25
    assert stopped["financial"]["estimate_scope"] == "latest_observed_session"
    with db.connect() as conn:
        rates = [row["hourly_rate"] for row in conn.execute("SELECT hourly_rate FROM instance_cost_periods ORDER BY started_at")]
    assert rates == [0.5, 0.75]


def test_start_is_idempotent_until_provider_state_confirms(monkeypatch):
    monkeypatch.setattr(salad_control, "request", lambda method, suffix="", **kwargs: {
        "current_state": {"status": "stopped"}, "pending_change": False,
    })
    provider_calls = []
    monkeypatch.setattr(salad_control, "_provider_call", lambda *args, **kwargs: provider_calls.append(args) or 202)
    first = salad_control.start()
    second = salad_control.start()
    assert first["accepted"] is True and first["pending"] is True
    assert second["accepted"] is False and second["operation_id"] == first["operation_id"]
    assert len(provider_calls) == 1
    pending = instance_contract.record(observation(status="stopped"), 1, "2026-10-04T10:00:00+00:00")
    assert pending["pending_operation"]["status"] == "awaiting_confirmation"
    confirmed = instance_contract.record(observation(status="running"), 2, "2026-10-04T10:00:30+00:00")
    assert confirmed["operation"]["status"] == "confirmed"


def test_stop_guard_blocks_queued_work_in_any_execution_mode(monkeypatch):
    monkeypatch.setattr(direct_queue, "enabled", lambda: False)
    db.create_job("queue-pending", "tool", {"prompt": {}}, execution_mode="salad_queue")
    monkeypatch.setattr(salad_control, "request", lambda method, suffix="", **kwargs: {
        "current_state": {"status": "running"}, "pending_change": False,
        "queue_autoscaler": {"min_replicas": 0},
    })
    calls = []
    monkeypatch.setattr(salad_control, "_provider_call", lambda *args, **kwargs: calls.append(args) or 202)
    with pytest.raises(ValueError, match="pending"):
        salad_control.stop()
    assert calls == []
    assert db.activity_counts()["stop_blocked"] is True
