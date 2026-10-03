from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any
from uuid import uuid4
from pathlib import Path
import hmac
import os
import re
import httpx

from .config import settings
from . import db, storage, salad, salad_control, job_lifecycle, settings_store, direct_queue
from .template import render_template

app = FastAPI(title=settings.app_name, version="1.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


def stale_minutes():
    # The value is optional so existing server .env files remain compatible.
    try:
        return max(10, min(7 * 24 * 60, int(os.getenv("JOB_STALE_MINUTES", "180"))))
    except ValueError:
        return 180


@app.on_event("startup")
def startup():
    db.init_db()
    settings_store.seed()  # One-time migration of the original PRIVATE .env.
    if direct_queue.enabled():
        if not settings.internal_token:
            raise RuntimeError("APP_INTERNAL_TOKEN is required in direct queue mode")
        if len(os.getenv("DIRECT_WORKER_TOKEN", "")) < 32:
            raise RuntimeError("DIRECT_WORKER_TOKEN must contain at least 32 characters")


def check_internal_token(x_internal_token: str | None):
    if settings.internal_token and not hmac.compare_digest(
        x_internal_token or "", settings.internal_token
    ):
        raise HTTPException(status_code=401, detail="invalid internal token")


def check_admin_token(x_internal_token: str | None):
    if not settings.internal_token:
        raise HTTPException(503, "Set APP_INTERNAL_TOKEN in the private server .env before enabling administrative actions")
    check_internal_token(x_internal_token)


def check_worker_token(x_worker_token: str | None):
    if not direct_queue.enabled():
        raise HTTPException(503, "Direct worker mode is disabled")
    expected = os.getenv("DIRECT_WORKER_TOKEN", "")
    if len(expected) < 32 or not hmac.compare_digest(x_worker_token or "", expected):
        raise HTTPException(401, "invalid worker token")


def safe_name(name: str):
    name = Path(name or "upload.bin").name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def salad_error(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return HTTPException(502, f"Salad API rejected the operation (HTTP {exc.response.status_code})")
    if isinstance(exc, ValueError):
        return HTTPException(409, str(exc))
    return HTTPException(502, f"Salad API unavailable: {type(exc).__name__}")


class WorkflowIn(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=200)
    api_prompt: dict[str, Any]
    ui_workflow: dict[str, Any] | None = None


class JobIn(BaseModel):
    workflow_id: str
    variables: dict[str, Any] = Field(default_factory=dict)
    priority: str | None = None


class RetryIn(BaseModel):
    allow_duplicate: bool = False


class SaladSettingsIn(BaseModel):
    # Image can be a versioned GHCR image; never accept arbitrary shell syntax.
    image: str = Field(min_length=10, max_length=255, pattern=r"^ghcr\.io/[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$")
    group_name: str = Field(min_length=2, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    display_name: str = Field(min_length=2, max_length=63, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.-]*$")


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": settings.app_name,
        "default_priority": settings.salad_priority,
        "gpu_name": settings.salad_gpu_name,
        "queue_name": "direct" if direct_queue.enabled() else settings.salad_queue_name(),
        "queue_mode": "direct" if direct_queue.enabled() else "salad_queue",
        "admin_configured": bool(settings.internal_token),
    }


@app.get("/api/workflows")
def workflows():
    return db.list_workflows()


@app.get("/api/workflows/{workflow_id}")
def workflow(workflow_id: str):
    item = db.get_workflow(workflow_id)
    if not item:
        raise HTTPException(404, "workflow not found")
    return item


@app.put("/api/workflows/{workflow_id}")
def put_workflow(workflow_id: str, body: WorkflowIn, x_internal_token: str | None = Header(default=None)):
    check_internal_token(x_internal_token)
    if workflow_id != body.id:
        raise HTTPException(400, "path id and body id must match")
    if "nodes" in body.api_prompt or "last_node_id" in body.api_prompt:
        raise HTTPException(400, "api_prompt looks like ComfyUI UI workflow format. Export API Format first.")
    return db.save_workflow(body.id, body.name, body.api_prompt, body.ui_workflow)


@app.delete("/api/workflows/{workflow_id}", status_code=204)
def remove_workflow(workflow_id: str, x_internal_token: str | None = Header(default=None)):
    check_internal_token(x_internal_token)
    db.delete_workflow(workflow_id)


@app.post("/api/uploads")
def upload(file: UploadFile = File(...), x_internal_token: str | None = Header(default=None)):
    check_internal_token(x_internal_token)
    upload_id = str(uuid4())
    filename = safe_name(file.filename)
    key = f"inputs/{upload_id}/{filename}"
    f = file.file
    current = f.tell()
    f.seek(0, 2)
    size = f.tell()
    f.seek(current)
    if size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"file exceeds {settings.max_upload_mb} MB")
    f.seek(0)
    storage.upload_fileobj(f, key, file.content_type)
    return {
        "upload_id": upload_id,
        "bucket": settings.r2_bucket,
        "key": key,
        "url": storage.presign_get(key),
        "s3_uri": f"s3://{settings.r2_bucket}/{key}",
    }


def submit_job(workflow_id, variables, priority=None):
    selected_priority = (priority or settings.salad_priority).strip().lower()
    if selected_priority != settings.salad_priority:
        raise HTTPException(400, f"Only priority {settings.salad_priority!r} is available")
    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    if not isinstance(variables, dict):
        raise HTTPException(400, "variables must be an object")
    try:
        # Store durable s3:// references; renew signed URLs for EVERY attempt.
        runtime_variables = storage.sign_s3_values(variables)
        rendered = render_template(wf["api_prompt"], runtime_variables)
    except KeyError as exc:
        raise HTTPException(400, str(exc))
    local_id = str(uuid4())
    selected_queue = "direct" if direct_queue.enabled() else salad.queue_name_for_priority(selected_priority)
    prompt_request = {
        "id": local_id,
        "prompt": rendered,
        "s3": {
            "bucket": settings.r2_bucket,
            "prefix": f"outputs/{local_id}/",
            "async": False,
        },
    }
    if direct_queue.enabled():
        # Persist S3 URIs, not pre-signed URLs that expire in the local queue.
        # Convert only URLs pointing to our own input bucket.
        def durable(value):
            if isinstance(value, dict):
                return {k: durable(v) for k, v in value.items()}
            if isinstance(value, list):
                return [durable(v) for v in value]
            if isinstance(value, str):
                recovered = job_lifecycle.recover_image_ref(value)
                return recovered if recovered else value
            return value
        prompt_request["prompt"] = durable(render_template(wf["api_prompt"], variables))
        db.create_job(
            local_id, workflow_id, prompt_request, priority=selected_priority,
            salad_queue="direct", variables=variables, execution_mode="direct",
        )
        return db.get_job(local_id)
    db.create_job(
        local_id, workflow_id, prompt_request,
        priority=selected_priority,
        salad_queue=selected_queue,
        variables=variables,
    )
    try:
        response, _, _ = salad.submit_job(
            prompt_request,
            priority=selected_priority,
            metadata={"controller_job_id": local_id, "workflow_id": workflow_id},
        )
        salad_id = response.get("id") or response.get("job_id")
        if not salad_id:
            raise RuntimeError("Salad response has no job id")
        state = response.get("status") or response.get("state") or "pending"
        db.update_job(local_id, salad_job_id=str(salad_id), state=state, output=response)
    except Exception as exc:
        # The remote service could have accepted a request despite a network
        # exception: do not assert that retrying cannot produce a duplicate.
        db.update_job(local_id, state="submit_failed", error=str(exc))
        raise HTTPException(502, f"Salad job submission failed (local job {local_id}): {type(exc).__name__}")
    return db.get_job(local_id)


@app.post("/api/jobs")
def create_job(body: JobIn, x_internal_token: str | None = Header(default=None)):
    check_internal_token(x_internal_token)
    return public_job(submit_job(body.workflow_id, body.variables, body.priority))


def note_stale(item):
    if item and item.get("execution_mode") == "direct":
        return item
    if item and item.get("state") not in job_lifecycle.TERMINAL and \
            item.get("state") != "stalled" and \
            job_lifecycle.age_minutes(item.get("created_at")) >= stale_minutes():
        db.mark_stalled(item["id"], stale_minutes())
        return db.get_job(item["id"])
    return item


def public_job(item: dict):
    if not item:
        return item
    data = dict(item)
    # This hash is internal lease bookkeeping, never an API field.
    data.pop("lease_token_hash", None)
    data.pop("worker_id", None)
    # Do not advertise an expired signed URL as a valid editable input.
    data["output"] = storage.sign_s3_values(data.get("output"))
    return data


@app.get("/api/jobs")
def jobs(limit: int = 50):
    return [public_job(note_stale(item)) for item in db.list_jobs(limit)]


@app.get("/api/jobs/{local_id}")
def job(local_id: str):
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    salad_id = item.get("salad_job_id")
    if salad_id and item.get("execution_mode") != "direct" and item.get("state") not in job_lifecycle.TERMINAL:
        try:
            queue_name = item.get("salad_queue") or settings.salad_legacy_queue
            if not queue_name:
                raise RuntimeError("Historic job has no queue; configure SALAD_LEGACY_QUEUE")
            remote = salad.get_job(salad_id, queue_name)
            state = remote.get("status") or remote.get("state") or item["state"]
            output = remote.get("output")
            if output is None:
                output = remote
            db.update_job(local_id, state=state, output=output,
                          error="" if state in job_lifecycle.TERMINAL else None)
            item = db.get_job(local_id)
        except Exception as exc:
            item["poll_warning"] = f"Salad poll failed: {type(exc).__name__}"
    item = note_stale(item)
    return public_job(item)


@app.get("/api/jobs/{local_id}/draft")
def job_draft(local_id: str):
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    wf = db.get_workflow(item["workflow_id"])
    if not wf:
        raise HTTPException(409, "Original workflow was removed")
    if item.get("variables") is not None:
        return {"workflow_id": wf["id"], "variables": item["variables"], "legacy": False}
    rendered = (item.get("request") or {}).get("prompt")
    extracted = job_lifecycle.legacy_draft(wf.get("api_prompt"), rendered)
    return {
        "workflow_id": wf["id"], "variables": extracted, "legacy": True,
        "warning": "Legacy job: edit fields and re-upload any image that cannot be recovered."
    }


@app.post("/api/jobs/{local_id}/retry")
def retry_job(local_id: str, body: RetryIn, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    if item.get("state") not in job_lifecycle.RETRYABLE | {"stalled"}:
        raise HTTPException(409, "This job is not retryable while it is active or succeeded")
    if item.get("state") == "stalled" and item.get("execution_mode") != "direct" and not body.allow_duplicate:
        raise HTTPException(409, "Remote job may still run; explicitly confirm a duplicate attempt")
    if item.get("variables") is None:
        raise HTTPException(409, "Legacy job has no saved variables. Use Edit & Run instead")
    return public_job(submit_job(item["workflow_id"], item["variables"], item.get("priority")))


@app.delete("/api/jobs/{local_id}", status_code=204)
def hide_job(local_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    # Hide never cancels a running task. For pending direct tasks, cancel it
    # first so it cannot be dispatched after being hidden.
    if item.get("execution_mode") == "direct" and item.get("state") == "pending":
        direct_queue.cancel_pending(local_id)
    db.hide_job(local_id)


@app.get("/api/jobs/{local_id}/images")
def images(local_id: str):
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    try:
        images = storage.job_images(local_id, item.get("output"), include_storage=True)
        return {"images": images}
    except Exception as exc:
        raise HTTPException(502, f"Cannot list output images: {type(exc).__name__}")


@app.get("/api/salad/settings")
def get_salad_settings(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    return settings_store.snapshot()


@app.put("/api/salad/settings")
def update_salad_settings(body: SaladSettingsIn,
                          x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    return settings_store.save_draft(body.model_dump())


@app.post("/api/salad/settings/deploy")
def deploy_salad_settings(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    try:
        return salad_control.deploy_draft()
    except Exception as exc:
        raise salad_error(exc)


@app.get("/api/salad/instances")
def salad_instances():
    try:
        return salad_control.status()
    except Exception as exc:
        raise salad_error(exc)


@app.post("/api/salad/keep-warm")
def enable_keep_warm(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    try:
        return salad_control.set_keep_warm(True)
    except Exception as exc:
        raise salad_error(exc)


@app.post("/api/salad/auto-scale")
def enable_auto_scale(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    try:
        return salad_control.set_keep_warm(False)
    except Exception as exc:
        raise salad_error(exc)


@app.post("/api/salad/stop")
def stop_worker(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    try:
        return salad_control.stop()
    except Exception as exc:
        raise salad_error(exc)


@app.post("/api/salad/start")
def start_worker(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    try:
        return salad_control.start()
    except Exception as exc:
        raise salad_error(exc)


@app.post("/api/salad/replica")
def request_worker(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    try:
        return salad_control.request_one_replica()
    except Exception as exc:
        raise salad_error(exc)


# ───── Direct pull-worker API. All routes require a separate strong token. ─────
class WorkerHello(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)


class WorkerLease(BaseModel):
    lease_token: str = Field(min_length=32, max_length=256)


class WorkerComplete(WorkerLease):
    output: dict[str, Any]


class WorkerFailure(WorkerLease):
    error: str = Field(min_length=1, max_length=600)
    retryable: bool = False


@app.post("/api/worker/hello")
def worker_hello(body: WorkerHello, x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    direct_queue.worker_seen(body.worker_id)
    return {"accepted": True}


@app.post("/api/worker/claim")
def worker_claim(body: WorkerHello, x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    if direct_queue.load_setting("direct_hold", False):
        raise HTTPException(409, "GPU controller is on HOLD; reset it before claiming jobs")
    return direct_queue.claim(body.worker_id)


@app.post("/api/worker/heartbeat/{local_id}")
def worker_heartbeat(local_id: str, body: WorkerLease,
                     x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    if not direct_queue.heartbeat(local_id, body.lease_token):
        raise HTTPException(409, "lease expired or is no longer owned by this worker")
    return {"accepted": True}


@app.post("/api/worker/complete/{local_id}")
def worker_complete(local_id: str, body: WorkerComplete,
                    x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    if not direct_queue.finish(local_id, body.lease_token, body.output):
        raise HTTPException(409, "lease expired or result already committed")
    return {"accepted": True}


@app.post("/api/worker/fail/{local_id}")
def worker_fail(local_id: str, body: WorkerFailure,
                x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    if not direct_queue.fail(local_id, body.lease_token, body.error, body.retryable):
        raise HTTPException(409, "lease expired or failure already recorded")
    return {"accepted": True}


@app.get("/api/direct/status")
def direct_status(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    return {
        "enabled": direct_queue.enabled(),
        "gpu_auto_control": os.getenv("DIRECT_GPU_AUTO_CONTROL", "false").lower() == "true",
        "jobs": direct_queue.counters(),
        "hold": direct_queue.load_setting("direct_hold", False),
        "keep_warm": bool(direct_queue.load_setting("direct_keep_warm", False)),
        "worker_seen": direct_queue.load_setting("direct_worker_seen", None),
    }


@app.post("/api/direct/reset-hold")
def direct_reset_hold(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    if not direct_queue.enabled():
        raise HTTPException(409, "Direct mode is disabled")
    direct_queue.save_setting("direct_hold", False)
    direct_queue.save_setting("direct_boot_started", 0)
    return {"accepted": True, "message": "GPU controller HOLD cleared"}
