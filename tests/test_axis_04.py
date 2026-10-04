"""Axis 4 API, progress, timing, cancellation, history and comparison tests."""
import importlib.util
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_ENV = {
    "APP_NAME": "axis4-test", "DB_PATH": "/tmp/axis4-unused.db", "MAX_UPLOAD_MB": "10",
    "APP_INTERNAL_TOKEN": "axis4-admin-token", "SALAD_API_KEY": "not-a-real-key",
    "SALAD_API_BASE_URL": "https://provider.invalid", "SALAD_USER_AGENT": "axis4-tests",
    "SALAD_HTTP_TIMEOUT_SECONDS": "1", "SALAD_ORG": "test-org", "SALAD_PROJECT": "test-project",
    "SALAD_QUEUE_NAME": "test-queue", "SALAD_PRIORITY": "medium", "SALAD_GPU_NAME": "test-gpu",
    "SALAD_LEGACY_QUEUE": "legacy-queue", "R2_ENDPOINT_URL": "https://storage.invalid",
    "R2_BUCKET": "test-bucket", "R2_ACCESS_KEY_ID": "fake-access",
    "R2_SECRET_ACCESS_KEY": "fake-storage-secret", "R2_REGION": "auto",
    "R2_PRESIGN_TTL_SECONDS": "60", "DIRECT_QUEUE_ENABLED": "true",
    "DIRECT_GPU_AUTO_CONTROL": "false", "DIRECT_WORKER_TOKEN": "w" * 48,
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)

from app import db, direct_queue as queue, main as controller, storage
from app.config import settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    object.__setattr__(settings, "db_path", str(tmp_path / "axis4.sqlite"))
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "true")
    monkeypatch.setenv("DIRECT_WORKER_TOKEN", "w" * 48)
    monkeypatch.setattr(storage, "sign_s3_values", lambda value: value)
    monkeypatch.setattr(storage, "presign_get", lambda key: "https://signed.invalid/" + key)
    db.init_db()
    yield


def new_job(job_id, *, prompt="A test image", snapshot=None, variables=None):
    variables = variables if variables is not None else {"prompt.positive": prompt}
    return db.create_job(job_id, "test-tool", {
        "id": job_id, "prompt": {"1": {"class_type": "KSampler", "inputs": {"text": prompt}}},
        "s3": {"bucket": settings.r2_bucket, "prefix": f"outputs/{job_id}/"},
    }, execution_mode="direct", salad_queue="direct", variables=variables, snapshot=snapshot)


def worker_headers():
    return {"X-Worker-Token": "w" * 48}


def admin_headers():
    return {"X-Internal-Token": settings.internal_token}


def test_real_progress_is_attempt_fenced_ordered_and_not_job_completion():
    new_job("progress-job")
    claim = queue.claim("worker-one")
    event = {"lease_token": claim["lease_token"], "attempt_id": claim["attempt_id"],
             "sequence": 4, "phase": "sampling", "label": "Sampling",
             "value": 12, "total": 30, "unit": "steps", "scope": "stage", "source": "comfyui"}
    with TestClient(controller.app) as api:
        assert api.post("/api/worker/progress/progress-job", json=event, headers=worker_headers()).status_code == 200
        older = {**event, "sequence": 3, "value": 9}
        assert api.post("/api/worker/progress/progress-job", json=older, headers=worker_headers()).status_code == 409
        invalid = {**event, "sequence": 5, "value": 31}
        assert api.post("/api/worker/progress/progress-job", json=invalid, headers=worker_headers()).status_code == 409
        current = api.get("/api/jobs/progress-job").json()
    assert current["state"] == "running"
    assert current["progress"]["value"] == 12
    assert current["progress"]["total"] == 30
    assert current["progress"]["scope"] == "stage"
    assert current["progress"]["attempt_id"] == claim["attempt_id"]
    assert [event["sequence"] for event in current["progress_history"]] == [4]

    assert queue.fail("progress-job", claim["lease_token"], "controlled test failure", retryable=False,
                      attempt_id=claim["attempt_id"])
    assert queue.retry("progress-job")
    next_attempt = queue.claim("worker-two")
    assert next_attempt["attempt_id"] != claim["attempt_id"]
    assert not queue.record_progress("progress-job", claim["lease_token"], claim["attempt_id"], event)
    assert queue.record_progress("progress-job", next_attempt["lease_token"], next_attempt["attempt_id"],
        {**event, "sequence": 1, "value": None, "total": None, "unit": None,
         "phase": "finalizing", "label": "Verifying output", "source": "worker"})
    latest = db.get_job("progress-job")
    assert latest["progress"]["attempt_id"] == next_attempt["attempt_id"]
    assert latest["progress"]["value"] is None
    assert len(latest["attempt_history"]) == 2


def test_queued_cancel_is_final_and_active_cancel_waits_for_worker_confirmation():
    new_job("queued-cancel")
    new_job("active-cancel")
    with TestClient(controller.app) as api:
        queued = api.post("/api/jobs/queued-cancel/cancel", headers=admin_headers())
        assert queued.status_code == 200
        assert queued.json()["state"] == "cancelled"
        assert api.post("/api/jobs/queued-cancel/cancel", headers=admin_headers()).json()["state"] == "cancelled"
        claim = api.post("/api/worker/claim", json={"worker_id": "worker"}, headers=worker_headers()).json()
        assert claim["job_id"] == "active-cancel"
        active = api.post("/api/jobs/active-cancel/cancel", headers=admin_headers())
        assert active.status_code == 200
        assert active.json()["state"] == "cancel_requested"
        assert api.post("/api/worker/heartbeat/active-cancel",
            json={"lease_token": claim["lease_token"], "attempt_id": claim["attempt_id"]},
            headers=worker_headers()).json()["cancel_requested"] is True
        assert api.post("/api/worker/claim", json={"worker_id": "other"}, headers=worker_headers()).json() is None
        confirmed = api.post("/api/worker/cancelled/active-cancel",
            json={"lease_token": claim["lease_token"], "attempt_id": claim["attempt_id"]},
            headers=worker_headers())
        assert confirmed.status_code == 200
        assert api.get("/api/jobs/active-cancel").json()["state"] == "cancelled"


def test_completion_that_wins_cancel_race_keeps_verified_job_result():
    new_job("cancel-race")
    claim = queue.claim("worker")
    assert queue.request_cancel("cancel-race")["state"] == "cancel_requested"
    assert queue.finish("cancel-race", claim["lease_token"], {"images": []}, claim["attempt_id"])
    assert db.get_job("cancel-race")["state"] == "succeeded"


def test_cancel_without_worker_confirmation_becomes_uncertain_not_cancelled(monkeypatch):
    new_job("lost-cancel")
    claim = queue.claim("worker")
    assert queue.request_cancel("lost-cancel")["state"] == "cancel_requested"
    start = queue._time()
    monkeypatch.setattr(queue, "_time", lambda: start + queue.lease_seconds() + 1)
    assert queue.recover_expired() == 1
    item = db.get_job("lost-cancel")
    assert item["state"] == "stalled"
    assert "not confirmed" in item["error_text"].lower()
    assert queue.claim("other-worker") is None


def test_history_paginates_with_stable_cursor_and_exact_failed_filter():
    new_job("history-a", prompt="portrait of a mountain")
    new_job("history-b", prompt="portrait of a river")
    new_job("history-c", prompt="city skyline")
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET created_at='2026-10-01T00:00:00+00:00' WHERE id='history-a'")
        conn.execute("UPDATE jobs SET created_at='2026-10-02T00:00:00+00:00' WHERE id='history-b'")
        conn.execute("UPDATE jobs SET created_at='2026-10-03T00:00:00+00:00' WHERE id='history-c'")
        conn.execute("UPDATE jobs SET state='failed' WHERE id='history-a'")
        conn.execute("UPDATE jobs SET state='submit_failed' WHERE id='history-b'")
    with TestClient(controller.app) as api:
        first = api.get("/api/jobs/history", params={"limit": 1}).json()
        second = api.get("/api/jobs/history", params={"limit": 1, "cursor": first["next_cursor"]}).json()
        failed = api.get("/api/jobs/history", params={"state": "failed"}).json()
        searched = api.get("/api/jobs/history", params={"q": "mountain"}).json()
        wrong_cursor = api.get("/api/jobs/history", params={"state": "failed", "cursor": first["next_cursor"]})
    assert [item["id"] for item in first["items"] + second["items"]] == ["history-c", "history-b"]
    assert [item["id"] for item in failed["items"]] == ["history-a"]
    assert [item["id"] for item in searched["items"]] == ["history-a"]
    assert wrong_cursor.status_code == 400


def test_comparison_uses_saved_snapshot_and_omits_reference_uris():
    first_snapshot = {"workflow_id": "tool", "workflow_version": "v1", "operation": "image_edit",
        "model": {"name": "Model A"}, "positive_prompt": "first", "negative_prompt": "",
        "output_spec": {"width": 512, "height": 512}, "seed": 7, "seed_mode": "fixed",
        "parameters": {"generation.steps": 8}, "loras": [],
        "references": [{"label": "Identity", "role": "identity", "order": 0, "uri": "s3://private/input.png"}]}
    second_snapshot = {**first_snapshot, "workflow_version": "v2", "positive_prompt": "second",
        "parameters": {"generation.steps": 12}, "references": []}
    new_job("compare-a", snapshot=first_snapshot)
    new_job("compare-b", snapshot=second_snapshot)
    with TestClient(controller.app) as api:
        response = api.get("/api/job-comparison", params={"first_id": "compare-a", "second_id": "compare-b"})
    assert response.status_code == 200
    data = response.json()
    changed = {item["field"] for item in data["differences"]}
    assert {"workflow_version", "positive_prompt", "parameters", "references"} <= changed
    assert "uri" not in response.text


def test_worker_waits_for_comfy_terminal_result_after_prompt_acceptance(monkeypatch):
    worker_path = Path(__file__).resolve().parents[1] / "salad-worker" / "pull_worker.py"
    spec = importlib.util.spec_from_file_location("axis4_pull_worker", worker_path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)

    class Reporter:
        def __init__(self):
            self.events = []

        def emit(self, *args, **kwargs):
            self.events.append((args, kwargs))

    class Accepted:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"prompt_id":"comfy-prompt-1"}'

    monkeypatch.setattr(worker.ComfyMonitor, "start", lambda self: None)
    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *_args, **_kwargs: Accepted())
    monkeypatch.setattr(worker, "comfy_history", lambda prompt_id: {
        prompt_id: {"status": {"completed": True, "status_str": "success"},
                    "outputs": {"8": {"images": [{"filename": "result.png"}]}}}
    })
    reporter = Reporter()
    monitor_holder = {}
    result = worker.execute({"request": {"prompt": {"8": {"class_type": "SaveImage"}}}},
                            reporter, monitor_holder=monitor_holder)
    assert result["status"] == "success"
    assert result["outputs"]["8"]["images"][0]["filename"] == "result.png"
    assert monitor_holder["monitor"].prompt_id == "comfy-prompt-1"
