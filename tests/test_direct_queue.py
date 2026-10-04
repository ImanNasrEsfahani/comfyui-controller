"""GPU-free regression tests: no Salad API calls and no R2 network access."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Set only harmless defaults; tests never use production Salad/R2 credentials.
TEST_ENV = {
    "APP_NAME": "controller-test", "DB_PATH": "/tmp/direct-queue-test.db",
    "MAX_UPLOAD_MB": "100", "APP_INTERNAL_TOKEN": "test-admin",
    "SALAD_API_KEY": "not-a-real-key", "SALAD_API_BASE_URL": "https://api.salad.com/api/public",
    "SALAD_USER_AGENT": "controller-unit-test", "SALAD_HTTP_TIMEOUT_SECONDS": "10",
    "SALAD_ORG": "imanprojects", "SALAD_PROJECT": "comfy",
    "SALAD_QUEUE_NAME": "qwen-comfyui-medium", "SALAD_PRIORITY": "medium",
    "SALAD_GPU_NAME": "RTX 5090 (32 GB)", "SALAD_LEGACY_QUEUE": "qwen-comfyui",
    "R2_ENDPOINT_URL": "https://example.r2.cloudflarestorage.com",
    "R2_BUCKET": "comfy", "R2_ACCESS_KEY_ID": "test-id",
    "R2_SECRET_ACCESS_KEY": "test-secret", "R2_REGION": "auto",
    "R2_PRESIGN_TTL_SECONDS": "21600", "DIRECT_BACKEND_URL": "https://example.test",
    "DIRECT_WORKER_TOKEN": "x" * 48,
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)

from app import db, direct_queue as dq, direct_scheduler, salad_control, storage
from app.config import settings


@pytest.fixture(autouse=True)
def local_queue(tmp_path, monkeypatch):
    object.__setattr__(settings, "db_path", str(tmp_path / "controller.sqlite"))
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "true")
    monkeypatch.setenv("DIRECT_GPU_AUTO_CONTROL", "false")
    monkeypatch.setenv("DIRECT_WORKER_TOKEN", "x" * 48)
    monkeypatch.setattr(storage, "sign_s3_values", lambda x: x)
    db.init_db()
    dq.save_setting("salad_active", {"image": "ghcr.io/test/worker:direct", "group_name": "test-direct", "display_name": "Test"})
    dq.save_setting("salad_draft", {"image": "ghcr.io/test/worker:direct", "group_name": "test-direct", "display_name": "Test"})
    yield


def new_job(job_id="j1", *, priority="medium"):
    db.create_job(job_id, "wf", {"id": job_id, "prompt": {"1": {"inputs": {"image": "s3://comfy/inputs/a/a.png"}}}},
                  execution_mode="direct", salad_queue="direct", priority=priority)


def test_atomic_single_claim_and_idempotent_result():
    new_job("j1")
    new_job("j2")
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda i: dq.claim("worker-" + str(i)), range(6)))
    winners = [x for x in claims if x]
    assert len(winners) == 1
    job = winners[0]
    assert dq.heartbeat(job["job_id"], "invalid") is False
    assert dq.heartbeat(job["job_id"], job["lease_token"]) is True
    assert dq.finish(job["job_id"], job["lease_token"], {"output": {"ok": True}})
    assert not dq.finish(job["job_id"], job["lease_token"], {"output": {"overwrite": True}})
    assert db.get_job(job["job_id"])["output"] == {"output": {"ok": True}}
    assert dq.claim("worker-next")["job_id"] != job["job_id"]


def test_expired_attempt_is_fenced_and_retry_bounded(monkeypatch):
    new_job()
    first = dq.claim("w1")
    original_clock = dq._time()
    monkeypatch.setattr(dq, "_time", lambda: original_clock + 200)
    assert dq.recover_expired() == 1
    assert not dq.heartbeat("j1", first["lease_token"])
    assert not dq.finish("j1", first["lease_token"], {"wrong": True})
    monkeypatch.setattr(dq, "_time", lambda: original_clock + 400)
    second = dq.claim("w2")
    assert second["attempt"] == 2
    assert second["lease_token"] != first["lease_token"]
    assert dq.fail("j1", second["lease_token"], "bad workflow", retryable=False)
    assert db.get_job("j1")["state"] == "failed"
    assert dq.claim("w3") is None


def test_retry_limit_on_missing_heartbeats(monkeypatch):
    monkeypatch.setenv("DIRECT_MAX_ATTEMPTS", "2")
    new_job()
    t0 = dq._time()
    a = dq.claim("w1")
    monkeypatch.setattr(dq, "_time", lambda: t0 + 300)
    dq.recover_expired()
    monkeypatch.setattr(dq, "_time", lambda: t0 + 500)
    b = dq.claim("w2")
    assert b["attempt"] == 2
    monkeypatch.setattr(dq, "_time", lambda: t0 + 800)
    dq.recover_expired()
    assert db.get_job("j1")["state"] == "failed"
    assert dq.claim("w3") is None


def test_worker_endpoint_auth_and_local_submit(monkeypatch):
    from app.main import app
    db.save_workflow("wf", "Basic", {"1": {"class_type": "LoadImage", "inputs": {"image": "{{input.image_1}}"}}})
    with TestClient(app) as api:
        assert api.post("/api/worker/claim", json={"worker_id": "w"}).status_code == 401
        assert api.post("/api/worker/claim", json={"worker_id": "w"},
                        headers={"X-Worker-Token": "bad"}).status_code == 401
        job_response = api.post("/api/jobs", json={"workflow_id": "wf", "variables": {
            "input.image_1": f"s3://{settings.r2_bucket}/inputs/a/a.png"}},
            headers={"X-Internal-Token": settings.internal_token})
        assert job_response.status_code == 200, job_response.text
        result = job_response.json()
        assert result["execution_mode"] == "direct"
        assert result["salad_job_id"] is None
        assert result["state"] == "pending"
        assert "lease_token_hash" not in result
        headers = {"X-Worker-Token": "x" * 48}
        claimed = api.post("/api/worker/claim", json={"worker_id": "test"}, headers=headers)
        assert claimed.status_code == 200
        attempt = claimed.json()
        assert attempt["request"]["prompt"]["1"]["inputs"]["image"] == f"s3://{settings.r2_bucket}/inputs/a/a.png"
        class OutputStore:
            def head_object(self, **kwargs):
                return {"ContentLength": 128, "ContentType": "image/png"}
        monkeypatch.setattr(storage, "client", lambda: OutputStore())
        monkeypatch.setattr(storage, "presign_get", lambda key: "https://example.invalid/" + key)
        output_uri = f"s3://{settings.r2_bucket}/{attempt['request']['s3']['prefix']}result.png"
        done = api.post(f"/api/worker/complete/{result['id']}",
                        json={"lease_token": attempt["lease_token"], "attempt_id": attempt["attempt_id"], "output": {"images": [output_uri]}}, headers=headers)
        assert done.status_code == 200
        job_status = api.get(
            f"/api/jobs/{result['id']}",
            headers={"X-Internal-Token": settings.internal_token},
        )
        assert job_status.status_code == 200, job_status.text
        assert job_status.json()["state"] == "succeeded"


def test_worker_failure_is_not_automatically_retried():
    new_job()
    claim = dq.claim("w")
    assert dq.fail("j1", claim["lease_token"], "unknown processing outcome", retryable=False)
    assert db.get_job("j1")["state"] == "failed"


def test_scheduler_off_never_calls_salad(monkeypatch):
    new_job()
    monkeypatch.setattr(direct_scheduler.salad_control, "_get_group", lambda _: (_ for _ in ()).throw(
        AssertionError("GPU must never start in manual mode")))
    direct_scheduler.tick()
    assert db.get_job("j1")["state"] == "pending"


def test_group_payload_has_no_queue_or_sdk(monkeypatch):
    values = {
        "SALAD_MANIFEST_PATH": "/opt/qvr-salad/manifest.yaml",
        "SALAD_WORKER_PORT": "3000", "SALAD_LRU_CACHE_SIZE_GB": "40",
        "SALAD_LOG_LEVEL": "info", "SALAD_READY_TIMEOUT_SECONDS": "1800",
        "SALAD_STARTUP_CHECK_MAX_TRIES": "360", "SALAD_STARTUP_CHECK_INTERVAL_S": "5",
        "SALAD_MAX_REPLICAS": "1", "SALAD_MIN_REPLICAS": "0", "SALAD_CPU": "4",
        "SALAD_MEMORY_MB": "30720", "SALAD_SHM_MB": "2048", "SALAD_STORAGE_GB": "100",
        "SALAD_WORKER_SCHEME": "http", "SALAD_READINESS_PATH": "/ready",
        "SALAD_STARTUP_PATH": "/health",
    }
    for prefix in ("SALAD_READINESS", "SALAD_STARTUP"):
        values.update({f"{prefix}_INITIAL_DELAY_SECONDS": "10", f"{prefix}_PERIOD_SECONDS": "30",
                       f"{prefix}_TIMEOUT_SECONDS": "5", f"{prefix}_SUCCESS_THRESHOLD": "1",
                       f"{prefix}_FAILURE_THRESHOLD": "20"})
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    payload = salad_control._new_group_payload({"group_name": "test-direct", "display_name": "Test direct",
                                                "image": "ghcr.io/test/worker:direct"}, "gpu-id")
    assert "queue_connection" not in payload
    assert "queue_autoscaler" not in payload
    assert payload["restart_policy"] == "never"
    assert payload["autostart_policy"] is False
    assert payload["replicas"] == 0
    assert payload["container"]["environment_variables"]["DIRECT_WORKER_TOKEN"] == "x" * 48


def test_original_gpu_runtime_dependencies_are_preserved():
    root = Path(__file__).resolve().parents[1]
    docker = (root / "salad-worker/Dockerfile").read_text()
    assert "python3-dev" in docker and "build-essential" in docker
    assert "libgl1" in docker and "libglib2.0-0t64" in docker
    assert "onnxruntime-gpu" in docker
    assert "model_parts.py verify fp8" in docker
    assert "salad-http-job-queue-worker" not in docker
    assert "pull_worker.py" in docker


def test_scheduler_cold_start_is_single_request(monkeypatch):
    new_job()
    monkeypatch.setenv("DIRECT_GPU_AUTO_CONTROL", "true")
    provider_calls = []
    group = {
        "container": {"image": "ghcr.io/test/worker:direct", "command": []},
        "queue_connection": None, "queue_autoscaler": None,
        "restart_policy": "never", "replicas": 0, "pending_change": False,
        "current_state": {"status": "stopped"},
    }

    def fake_request(method, suffix="", **kwargs):
        if method == "GET" and suffix == "":
            return group
        if method == "GET" and suffix == "/instances":
            return {"instances": []}
        raise AssertionError(f"Unexpected Salad read: {method} {suffix}")

    def fake_provider_call(method, suffix="", *, json_body=None):
        provider_calls.append((method, suffix, {"json_body": json_body} if json_body is not None else {}))
        return 202

    monkeypatch.setattr(salad_control, "_get_group", lambda _: group)
    monkeypatch.setattr(salad_control, "request", fake_request)
    monkeypatch.setattr(salad_control, "_provider_call", fake_provider_call)
    direct_scheduler.tick()
    assert provider_calls == [("POST", "/start", {})]
    group["current_state"]["status"] = "running"
    direct_scheduler.tick()
    assert provider_calls[-1] == ("PATCH", "", {"json_body": {"replicas": 1}})
    assert len(provider_calls) == 2
    group["replicas"] = 1
    direct_scheduler.tick()
    assert len(provider_calls) == 2  # no endless start/scale calls


def test_forced_hold_shutdown_allows_pending_but_blocks_active_jobs(monkeypatch):
    activity = {"pending": 1, "running": 0, "finalizing": 0, "uncertain": 0, "stop_blocked": True}
    monkeypatch.setattr(db, "activity_counts", lambda: activity)

    assert salad_control._activity_stop_guard(allow_pending=True) == activity
    with pytest.raises(ValueError, match="Jobs are pending"):
        salad_control._activity_stop_guard()

    for key in ("running", "finalizing", "uncertain"):
        unsafe_activity = {**activity, key: 1}
        monkeypatch.setattr(db, "activity_counts", lambda value=unsafe_activity: value)
        with pytest.raises(ValueError):
            salad_control._activity_stop_guard(allow_pending=True)


def test_scheduler_holds_and_stops_after_boot_timeout(monkeypatch):
    new_job()
    monkeypatch.setenv("DIRECT_GPU_AUTO_CONTROL", "true")
    monkeypatch.setenv("DIRECT_STARTUP_TIMEOUT_SECONDS", "600")
    now = time.time()
    dq.save_setting("direct_boot_started", now - 1000)
    provider_calls = []
    group = {
        "container": {"image": "ghcr.io/test/worker:direct", "command": []},
        "queue_connection": None, "queue_autoscaler": None,
        "restart_policy": "never", "replicas": 1, "pending_change": False,
        "current_state": {"status": "running"},
    }

    def fake_request(method, suffix="", **kwargs):
        if method == "GET" and suffix == "":
            return group
        if method == "GET" and suffix == "/instances":
            return {"instances": []}
        raise AssertionError(f"Unexpected Salad read: {method} {suffix}")

    def fake_provider_call(method, suffix="", *, json_body=None):
        provider_calls.append((method, suffix, {"json_body": json_body} if json_body is not None else {}))
        return 202

    monkeypatch.setattr(salad_control, "_get_group", lambda _: group)
    monkeypatch.setattr(salad_control, "request", fake_request)
    monkeypatch.setattr(salad_control, "_provider_call", fake_provider_call)
    direct_scheduler.tick()
    assert provider_calls == [("POST", "/stop", {})]
    assert dq.load_setting("direct_hold")
    direct_scheduler.tick()
    assert provider_calls == [("POST", "/stop", {})]  # do not repeat an unconfirmed operation


def test_presigned_inputs_are_renewed_at_claim(monkeypatch):
    new_job()
    original_request = db.get_job("j1")["request"]
    assert original_request["prompt"]["1"]["inputs"]["image"].startswith("s3://")
    monkeypatch.setattr(storage, "sign_s3_values", lambda value: {
        **value,
        "prompt": {"1": {"inputs": {"image": "https://signed-now.invalid/a.png"}}},
    })
    item = dq.claim("worker")
    assert item["request"]["prompt"]["1"]["inputs"]["image"] == "https://signed-now.invalid/a.png"
    assert db.get_job("j1")["request"] == original_request


def test_gpu_worker_posts_exact_comfy_request(monkeypatch):
    import importlib.util
    module_path = Path(__file__).resolve().parents[1] / "salad-worker" / "pull_worker.py"
    spec = importlib.util.spec_from_file_location("direct_worker_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sent = {}

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"status":"succeeded","output":{"images":[]}}'

    def fake_urlopen(req, timeout):
        sent["url"] = req.full_url
        sent["body"] = __import__("json").loads(req.data)
        sent["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    job = {"request": {"id": "j", "prompt": {"node": {"class_type": "Test"}},
                       "s3": {"bucket": "comfy", "prefix": "outputs/j/", "async": False}}}
    out = module.execute(job)
    assert sent["url"].endswith("/prompt")
    assert sent["body"]["id"] == job["request"]["id"]
    assert sent["body"]["prompt"] == job["request"]["prompt"]
    assert sent["body"]["s3"] == job["request"]["s3"]
    assert isinstance(sent["body"].get("client_id"), str)
    assert len(sent["body"]["client_id"]) == 32
    assert "client_id" not in job["request"]  # adding WebSocket routing must not mutate the stored Job
    assert out["status"] == "succeeded"
    assert sent["timeout"] >= 60


def test_existing_salad_queue_rows_survive_sqlite_migration(tmp_path):
    import sqlite3
    old_path = tmp_path / "old-controller.db"
    with sqlite3.connect(old_path) as conn:
        conn.executescript("""
        CREATE TABLE workflows (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, api_prompt TEXT NOT NULL,
          ui_workflow TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
          id TEXT PRIMARY KEY, salad_job_id TEXT, workflow_id TEXT,
          state TEXT NOT NULL, request_json TEXT NOT NULL,
          output_json TEXT, error_text TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO jobs (id,salad_job_id,workflow_id,state,request_json,created_at,updated_at)
          VALUES ('legacy','remote-123','wf','pending','{}','2026-01-01','2026-01-01');
        """)
    object.__setattr__(settings, "db_path", str(old_path))
    db.init_db()
    row = db.get_job("legacy")
    assert row["salad_job_id"] == "remote-123"
    assert row["state"] == "pending"
    assert row["execution_mode"] == "salad_queue"
    assert row["salad_queue"] == settings.salad_legacy_queue
    assert row["attempts"] == 0
