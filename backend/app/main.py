from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Any
from uuid import uuid4
from pathlib import Path
from datetime import datetime, timezone
import base64
import hmac
import json
import os
import re
import secrets
import httpx
import io
import warnings
from PIL import Image, UnidentifiedImageError

from .config import settings
from . import db, storage, salad, salad_control, job_lifecycle, settings_store, direct_queue, contracts
from .contracts import JobIn, ContractError
from .template import render_template

app = FastAPI(title=settings.app_name, version="1.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.exception_handler(ContractError)
async def contract_error_handler(request, exc):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc),
        "error": {"code": exc.code, "message": str(exc), "path": exc.path}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    # Never echo Pydantic's input/context: it can contain credentials.
    errors = [{"code": "unsupported_contract_version" if e["loc"][-1] == "contract_version" else e["type"],
               "message": e["msg"], "path": ".".join(str(x) for x in e["loc"] if x != "body")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Request validation failed", "error": errors[0], "errors": errors})


@app.exception_handler(HTTPException)
async def http_error_handler(request, exc):
    codes = {401: "authentication_required", 403: "access_denied", 404: "not_found",
             409: "conflict", 413: "payload_too_large", 429: "capacity_exceeded",
             502: "upstream_unavailable", 503: "service_unavailable"}
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail,
        "error": {"code": codes.get(exc.status_code, "invalid_request"), "message": str(exc.detail), "path": ""}}, headers=exc.headers)


def stale_minutes():
    # The value is optional so existing server .env files remain compatible.
    try:
        return max(10, min(7 * 24 * 60, int(os.getenv("JOB_STALE_MINUTES", "180"))))
    except ValueError:
        return 180


def random_seed(minimum: int, maximum: int) -> int:
    """Choose one inclusive seed without changing the global PRNG module."""
    return minimum + secrets.randbelow(maximum - minimum + 1)


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
        raise HTTPException(503, "Set APP_INTERNAL_TOKEN in the private server .env before enabling controller data or administrative access")
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
    capability_spec: dict[str, Any] | None = None


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


@app.get("/api/catalog")
def workflow_catalog():
    items = []
    for row in db.list_workflows():
        wf = db.get_workflow(row["id"])
        if not wf:
            continue
        items.append({"id": wf["id"], "name": wf["name"], **contracts.workflow_contract(wf)})
    return {"schema_version": 1, "workflows": items}


@app.get("/api/workflows/{workflow_id}")
def workflow(workflow_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    item = db.get_workflow(workflow_id)
    if not item:
        raise HTTPException(404, "workflow not found")
    return {**item, **contracts.workflow_contract(item)}


@app.put("/api/workflows/{workflow_id}")
def put_workflow(workflow_id: str, body: WorkflowIn, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    if workflow_id != body.id:
        raise HTTPException(400, "path id and body id must match")
    if "nodes" in body.api_prompt or "last_node_id" in body.api_prompt:
        raise HTTPException(400, "api_prompt looks like ComfyUI UI workflow format. Export API Format first.")
    try:
        contracts.ensure_no_credentials(body.capability_spec, "capability_spec")
        capability_spec = contracts.validate_capability_spec(body.api_prompt, body.capability_spec)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "path"):
            raise ContractError(exc.code, str(exc), exc.path)
        raise
    return db.save_workflow(body.id, body.name, body.api_prompt, body.ui_workflow, capability_spec)


@app.delete("/api/workflows/{workflow_id}", status_code=204)
def remove_workflow(workflow_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    db.delete_workflow(workflow_id)


@app.post("/api/uploads")
def upload(file: UploadFile = File(...), x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    upload_id = str(uuid4())
    filename = safe_name(file.filename)
    key = f"inputs/{upload_id}/{filename}"
    limit = settings.max_upload_mb * 1024 * 1024
    content = file.file.read(limit + 1)
    size = len(content)
    if size > limit:
        raise HTTPException(413, f"file exceeds {settings.max_upload_mb} MB")
    if not content:
        raise HTTPException(422, "Choose a non-empty image file")
    declared = (file.content_type or "").lower().split(";", 1)[0].strip()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                detected_format = (probe.format or "").upper()
                width, height = probe.size
                if width <= 0 or height <= 0 or width * height > 40_000_000:
                    raise ValueError("image dimensions exceed the 40 megapixel limit")
                if detected_format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                    raise ValueError("unsupported image format")
                probe.verify()
            with Image.open(io.BytesIO(content)) as decoded:
                decoded.load()
                width, height = decoded.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise HTTPException(422, "The uploaded file is not a valid, supported image") from exc
    mime_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}[detected_format]
    if declared and declared not in {"application/octet-stream", mime_type}:
        raise HTTPException(422, "Image content does not match the declared file type")
    storage.upload_fileobj(io.BytesIO(content), key, mime_type)
    created_at = db.utcnow()
    db.save_input_asset({"asset_id": upload_id, "storage_key": key, "mime_type": mime_type,
        "size_bytes": size, "width": width, "height": height, "created_at": created_at})
    return {
        "asset_id": upload_id,
        "upload_id": upload_id,
        "bucket": settings.r2_bucket,
        "key": key,
        "url": storage.presign_get(key),
        "mime_type": mime_type,
        "size_bytes": size,
        "width": width,
        "height": height,
        "s3_uri": f"s3://{settings.r2_bucket}/{key}",
    }


@app.get("/api/jobs/{local_id}/assets/{asset_id}/download")
def download_asset(local_id: str, asset_id: str, x_internal_token: str | None = Header(default=None)):
    """Stream this Job's verified output after controller authentication."""
    check_admin_token(x_internal_token)
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    asset = next((a for a in item.get("assets", []) if a.get("asset_id") == asset_id and a.get("status") == "available"), None)
    if not asset:
        raise HTTPException(404, "verified asset not found")
    key = asset.get("storage_key") or ""
    if not key.startswith(f"outputs/{local_id}/") or ".." in key.split("/"):
        raise HTTPException(404, "verified asset not found")
    try:
        stored = storage.get_object(key)
        body = stored["Body"]
    except Exception as exc:
        # Keep provider details and object keys out of the public error.
        raise HTTPException(404, "verified output is no longer available") from exc

    name = key.rsplit("/", 1)[-1]
    safe_name = re.sub(r"[\r\n\"\\]", "_", name)[:180] or "output"
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", safe_name) or "output"
    from urllib.parse import quote
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(safe_name)}"

    def chunks():
        try:
            yield from body.iter_chunks(chunk_size=1024 * 1024)
        finally:
            body.close()

    headers = {
        "Content-Disposition": disposition,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    content_length = stored.get("ContentLength")
    if isinstance(content_length, int) and content_length >= 0:
        headers["Content-Length"] = str(content_length)
    return StreamingResponse(chunks(), media_type=asset.get("mime_type") or "application/octet-stream",
                             headers=headers)


def submit_job(workflow_id, variables, priority=None, *, client_request_id=None, workflow_version=None,
               capability_version=None, seed_mode=None, reference_order=None, source_job_id=None):
    selected_priority = (priority or settings.salad_priority).strip().lower()
    if selected_priority != settings.salad_priority:
        raise HTTPException(400, f"Only priority {settings.salad_priority!r} is available")
    try:
        request_hash = contracts.digest({"workflow_id": workflow_id, "workflow_version": workflow_version,
            "capability_version": capability_version, "seed_mode": seed_mode,
            "reference_order": reference_order, "variables": variables,
            "priority": selected_priority, "source_job_id": source_job_id})
    except (ValueError, TypeError):
        raise ContractError("invalid_variables", "Variables must contain valid finite JSON values", "variables")
    if client_request_id:
        accepted = db.job_for_request(client_request_id, request_hash)
        if accepted:
            return accepted
    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    if not isinstance(variables, dict):
        raise HTTPException(400, "variables must be an object")
    if workflow_version and workflow_version != contracts.digest(wf["api_prompt"]):
        raise ContractError("workflow_changed", "The saved workflow changed; reload it before submitting", "workflow_version", 409)
    wf_contract = contracts.workflow_contract(wf)
    if capability_version and capability_version != wf_contract["capability_version"]:
        raise ContractError("capability_changed", "Workflow capabilities changed; reload the form before submitting", "capability_version", 409)
    capabilities = wf_contract["capabilities"]
    variables = contracts.validate_variables(wf["api_prompt"], variables, wf.get("capability_spec"))
    seed_variable = capabilities.get("seed_variable")
    if seed_mode not in (None, "fixed", "random"):
        raise ContractError("invalid_seed_mode", "Seed mode must be fixed or random", "seed_mode")
    if seed_mode is not None and not seed_variable:
        raise ContractError("unsupported_seed_mode", "This Workflow does not bind a seed to a sampler", "seed_mode")
    effective_seed_mode = seed_mode or "fixed"
    if effective_seed_mode == "random":
        seed_limits = capabilities.get("seed_range") or {"minimum": 0, "maximum": contracts.JS_SAFE_INTEGER}
        minimum = max(0, int(seed_limits.get("minimum", 0)))
        maximum = min(contracts.JS_SAFE_INTEGER, int(seed_limits.get("maximum", contracts.JS_SAFE_INTEGER)))
        if maximum < minimum:
            raise ContractError("invalid_seed_range", "Workflow seed range is invalid", "seed_mode")
        variables[seed_variable] = random_seed(minimum, maximum)
        variables = contracts.validate_variables(wf["api_prompt"], variables, wf.get("capability_spec"))
    variables = contracts.reorder_reference_values(variables, capabilities, reference_order)
    if source_job_id:
        source = db.get_job(source_job_id)
        if not source or source.get("hidden"):
            raise ContractError("invalid_source_job", "The source Job is not available", "source_job_id", 404)
    def durable(value):
        if isinstance(value, dict):
            return {k: durable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [durable(v) for v in value]
        if isinstance(value, str):
            recovered = job_lifecycle.recover_image_ref(value)
            return recovered if recovered else value
        return value
    variables = durable(variables)
    optional_images = {item["variable_key"] for item in capabilities.get("references", []) if not item.get("required", True)}
    variables = contracts.validate_image_references(variables, optional_images)
    snapshot = contracts.effective_snapshot(wf, variables, selected_priority,
        client_request_id=client_request_id, seed_mode=effective_seed_mode, reference_order=reference_order)
    contracts.ensure_no_credentials(snapshot["prompt"], "workflow")
    try:
        # Store durable s3:// references; renew signed URLs for EVERY attempt.
        runtime_variables = variables if direct_queue.enabled() else storage.sign_s3_values(variables)
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
        prompt_request["prompt"] = durable(render_template(wf["api_prompt"], variables))
        accepted_id = db.create_job(
            local_id, workflow_id, prompt_request, priority=selected_priority,
            salad_queue="direct", variables=variables, execution_mode="direct",
            snapshot=snapshot, client_request_id=client_request_id, request_hash=request_hash, source_job_id=source_job_id,
        )
        return db.get_job(accepted_id)
    accepted_id = db.create_job(
        local_id, workflow_id, prompt_request,
        priority=selected_priority,
        salad_queue=selected_queue,
        variables=variables,
        snapshot=snapshot, client_request_id=client_request_id, request_hash=request_hash, source_job_id=source_job_id,
    )
    if accepted_id != local_id:
        return db.get_job(accepted_id)
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
        db.update_job(local_id, salad_job_id=str(salad_id))
        apply_provider_result(db.get_job(local_id), state, response.get("output", response))
    except Exception as exc:
        if db.get_job(local_id).get("salad_job_id"):
            # The provider acknowledged acceptance. A validation outage must
            # not change that to a submission failure or dispatch another job.
            db.update_job(local_id, error="Provider result update deferred: " + type(exc).__name__)
            return db.get_job(local_id)
        # The remote service could have accepted a request despite a network
        # exception: do not assert that retrying cannot produce a duplicate.
        db.update_job(local_id, state="submit_failed", error=str(exc))
        raise HTTPException(502, f"Salad job submission failed (local job {local_id}): {type(exc).__name__}")
    return db.get_job(local_id)


def apply_provider_result(item, state, output):
    state = str(state).lower()
    if state == "succeeded" and item.get("snapshot"):
        if not db.update_job(item["id"], state="finalizing", output=output, expected_version=item["version"]):
            return False
        finalizing = db.get_job(item["id"])
        prefix = db.attempt_output_prefix(finalizing["active_attempt_id"]) or (finalizing.get("request", {}).get("s3") or {}).get("prefix")
        assets = storage.validate_outputs(item["id"], finalizing["active_attempt_id"], output, storage_prefix=prefix)
        success = any(asset["status"] == "available" for asset in assets)
        return db.update_job(item["id"], state="succeeded" if success else "failed", output=output,
            error="" if success else "No output file could be verified in storage", assets=assets, expected_version=finalizing["version"])
    return db.update_job(item["id"], state=state, output=output, expected_version=item["version"],
                         error="" if state in job_lifecycle.TERMINAL else None)


@app.post("/api/jobs")
def create_job(body: JobIn, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    return public_job(submit_job(body.workflow_id, body.variables, body.priority,
        client_request_id=body.client_request_id, workflow_version=body.workflow_version,
        capability_version=body.capability_version, seed_mode=body.seed_mode,
        reference_order=body.reference_order, source_job_id=body.source_job_id))


@app.get("/api/job-requests/{client_request_id}")
def accepted_request(client_request_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    item = db.job_for_request(client_request_id)
    if not item:
        raise HTTPException(404, "No accepted Job was found for this request key")
    return public_job(item)


def note_stale(item):
    if item and item.get("execution_mode") == "direct":
        return item
    attempt_history = (item or {}).get("attempt_history") or []
    wait_since = attempt_history[-1]["created_at"] if attempt_history else (item or {}).get("created_at")
    if item and item.get("state") not in job_lifecycle.TERMINAL and \
            item.get("state") != "stalled" and \
            job_lifecycle.age_minutes(wait_since) >= stale_minutes():
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
    data.pop("request_hash", None)
    data["contract_version"] = (data.get("snapshot") or {}).get("contract_version", 1) if data.get("snapshot") else 0
    data["last_updated_at"] = data["updated_at"]
    data["error_category"] = classify_error(data.get("state"), data.get("error_text"))
    heartbeat_at = data.get("last_heartbeat")
    data["communication"] = {"source": "controller", "worker_last_heartbeat_at": datetime.fromtimestamp(heartbeat_at, timezone.utc).isoformat() if heartbeat_at else None,
                             "overdue": data.get("state") == "stalled"}
    scoped_assets = data.get("assets", [])
    if data.get("active_attempt_id"):
        scoped_assets = [a for a in scoped_assets if a.get("attempt_id") == data["active_attempt_id"]]
    available = [a for a in scoped_assets if a["status"] == "available"]
    unavailable = len(scoped_assets) - len(available)
    expected = ((data.get("snapshot") or {}).get("output_spec") or {}).get("count")
    data["output_summary"] = {"available": len(available), "unavailable": unavailable, "expected_count": expected,
        "partial_success": bool(available and (unavailable or isinstance(expected, int) and len(available) < expected)), "verification": "storage_head" if data.get("snapshot") else "legacy_unverified"}
    for asset in data.get("assets", []):
        asset["preview"] = None
        asset["url"] = storage.presign_get(asset["storage_key"]) if asset["status"] == "available" else None
        asset["s3_uri"] = f"s3://{settings.r2_bucket}/{asset['storage_key']}" if asset["status"] == "available" else None
    # Do not advertise an expired signed URL as a valid editable input.
    data["output"] = storage.sign_s3_values(data.get("output"))
    return data


def classify_error(state, error):
    if not error:
        return None
    message = str(error).lower()
    if any(word in message for word in ("invalid variable", "missing required", "workflow changed", "input image")):
        return "input"
    if any(word in message for word in ("output file", "output validation", "r2", "storage", "upload", "presign")):
        return "output_transfer"
    if any(word in message for word in ("timeout", "temporarily unavailable", "connection", "heartbeat", "lease")):
        return "communication"
    if any(word in message for word in ("capacity", "replica", "queue is full", "gpu unavailable", "http 429", "insufficient capacity")):
        return "capacity"
    if state == "submit_failed":
        return "preparation"
    return "worker"


@app.get("/api/jobs")
def jobs(limit: int = 50, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    return [public_job(note_stale(item)) for item in db.list_jobs(limit)]


def _history_time(value, name):
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(400, f"{name} must be an ISO-8601 date or timestamp")


def _cursor_encode(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def _cursor_decode(value, filters):
    if not value:
        return None
    if len(value) > 2048:
        raise HTTPException(400, "Invalid history cursor")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = json.loads(raw)
        if (not isinstance(decoded, dict) or not isinstance(decoded.get("created_at"), str) or
                not isinstance(decoded.get("id"), str) or
                decoded.get("filters") != contracts.digest(filters)):
            raise ValueError
        return decoded
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(400, "Invalid history cursor or filter set changed")


@app.get("/api/jobs/history")
def job_history(limit: int = 24, state: str | None = None, workflow_id: str | None = None,
                created_after: str | None = None, created_before: str | None = None,
                q: str | None = None, cursor: str | None = None,
                x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    states = {"submitting", "pending", "queued", "waiting", "preparing", "processing", "running",
              "finalizing", "cancel_requested", "stalled", "succeeded", "failed", "cancelled", "submit_failed"}
    if not 1 <= limit <= 100:
        raise HTTPException(400, "limit must be between 1 and 100")
    if state and state not in states:
        raise HTTPException(400, "Unknown Job state filter")
    if workflow_id and (len(workflow_id) > 80 or not re.fullmatch(r"[A-Za-z0-9._-]+", workflow_id)):
        raise HTTPException(400, "Invalid Workflow filter")
    search = (q or "").strip()
    if len(search) > 160:
        raise HTTPException(400, "Search text must be 160 characters or fewer")
    after = _history_time(created_after, "created_after")
    before = _history_time(created_before, "created_before")
    if after and before and after > before:
        raise HTTPException(400, "created_after must not be later than created_before")
    filters = {"state": state, "workflow_id": workflow_id, "created_after": after,
               "created_before": before, "q": search}
    decoded = _cursor_decode(cursor, filters)
    page = db.history_page(limit=limit, state=state, workflow_id=workflow_id,
        created_after=after, created_before=before, query=search or None,
        cursor_created_at=decoded["created_at"] if decoded else None,
        cursor_id=decoded["id"] if decoded else None)
    next_cursor = None
    if page["has_more"] and page["items"]:
        last = page["items"][-1]
        next_cursor = _cursor_encode({"created_at": last["created_at"], "id": last["id"],
                                      "filters": contracts.digest(filters)})
    items = [public_job(note_stale(item)) for item in page["items"]]
    return {"items": items, "count": len(items), "total": page["total"], "next_cursor": next_cursor}


def _comparison_snapshot(item):
    snapshot = item.get("snapshot") or {}
    references = [{"role": ref.get("role"), "label": ref.get("label"),
                   "slot": ref.get("order"), "recorded": True}
                  for ref in snapshot.get("references", []) if isinstance(ref, dict)]
    return {
        "workflow_id": snapshot.get("workflow_id") or item.get("workflow_id"),
        "workflow_version": snapshot.get("workflow_version"),
        "operation": snapshot.get("operation"),
        "model": snapshot.get("model"),
        "positive_prompt": snapshot.get("positive_prompt"),
        "negative_prompt": snapshot.get("negative_prompt"),
        "output_spec": snapshot.get("output_spec"),
        "seed": snapshot.get("seed"),
        "seed_mode": snapshot.get("seed_mode"),
        "parameters": snapshot.get("parameters"),
        "loras": snapshot.get("loras"),
        "references": references if snapshot else None,
        "worker_seconds": item.get("timing", {}).get("worker_seconds"),
        "outputs": item.get("output_summary", {}).get("available"),
    }


@app.get("/api/job-comparison")
def compare_jobs(first_id: str, second_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    if first_id == second_id:
        raise HTTPException(400, "Choose two different Jobs to compare")
    first, second = db.get_job(first_id), db.get_job(second_id)
    if not first or first.get("hidden") or not second or second.get("hidden"):
        raise HTTPException(404, "One or both Jobs are not available")
    left, right = _comparison_snapshot(public_job(first)), _comparison_snapshot(public_job(second))
    differences = [{"field": key, "first": left[key], "second": right[key]}
                   for key in left if left[key] != right[key]]
    return {"first_id": first_id, "second_id": second_id,
            "first": left, "second": right, "differences": differences}


@app.get("/api/jobs/{local_id}")
def job(local_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
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
            apply_provider_result(item, state, output)
            item = db.get_job(local_id)
        except Exception as exc:
            item["poll_warning"] = f"Salad poll failed: {type(exc).__name__}"
    item = note_stale(item)
    return public_job(item)


@app.get("/api/jobs/{local_id}/draft")
def job_draft(local_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    wf = db.get_workflow(item["workflow_id"])
    if not wf:
        raise HTTPException(409, "Original workflow was removed")
    if item.get("variables") is not None:
        snapshot = item.get("snapshot") or {}
        return {"workflow_id": wf["id"], "variables": item["variables"],
                "seed_mode": snapshot.get("seed_mode", "fixed"), "legacy": False}
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
    if item.get("state") in {"stalled", "submit_failed"} and item.get("execution_mode") != "direct" and not body.allow_duplicate:
        raise HTTPException(409, "Remote job may still run; explicitly confirm a duplicate attempt")
    if item.get("variables") is None:
        raise HTTPException(409, "Legacy job has no saved variables. Use Edit & Run instead")
    if item.get("execution_mode") == "direct":
        if not direct_queue.retry(local_id):
            raise HTTPException(409, "Job state changed; refresh before retrying")
        return public_job(db.get_job(local_id))
    if item.get("snapshot"):
        attempt_id = db.begin_provider_retry(local_id, item["version"])
        if not attempt_id:
            raise HTTPException(409, "Job state changed; refresh before retrying")
        try:
            payload = {**item["request"], "id": attempt_id, "prompt": storage.sign_s3_values(item["snapshot"]["prompt"]),
                       "s3": {**item["request"]["s3"], "prefix": db.attempt_output_prefix(attempt_id)}}
            response, _, _ = salad.submit_job(payload, priority=item.get("priority"),
                metadata={"controller_job_id": local_id, "attempt_id": attempt_id, "workflow_id": item["workflow_id"]})
            remote_id = response.get("id") or response.get("job_id")
            if not remote_id: raise RuntimeError("Salad response has no Job ID")
            db.update_job(local_id, salad_job_id=str(remote_id))
            apply_provider_result(db.get_job(local_id), response.get("status") or response.get("state") or "pending", response.get("output", response))
        except Exception as exc:
            if db.get_job(local_id).get("salad_job_id"):
                db.update_job(local_id, error="Provider result update deferred: " + type(exc).__name__)
            else:
                db.update_job(local_id, state="submit_failed", error="Retry submission outcome is unknown: " + type(exc).__name__)
        return public_job(db.get_job(local_id))
    return public_job(submit_job(item["workflow_id"], item["variables"], item.get("priority"), source_job_id=local_id))


@app.post("/api/jobs/{local_id}/cancel")
def cancel_job(local_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    if item.get("execution_mode") != "direct":
        raise HTTPException(409, "Per-Job cancellation is not available for this legacy Salad Queue Job")
    result = direct_queue.request_cancel(local_id)
    if result is None:
        raise HTTPException(404, "job not found")
    if result.get("unavailable"):
        if result["state"] == "finalizing":
            raise HTTPException(409, "The Worker has finished processing and is validating outputs; cancellation is no longer available")
        raise HTTPException(409, "Cancellation cannot be confirmed for this Job state; refresh the Job before acting")
    return public_job(db.get_job(local_id))


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
def images(local_id: str, x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    item = db.get_job(local_id)
    if not item or item.get("hidden"):
        raise HTTPException(404, "job not found")
    try:
        if item.get("snapshot"):
            assets = public_job(item)["assets"]
            return {"images": [{**a, "key": a["storage_key"]} for a in assets if a["status"] == "available" and a["media_type"] == "image"], "assets": assets}
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
def salad_instances(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
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
    generation: str | None = Field(default=None, min_length=1, max_length=128)
    started_at: float | None = Field(default=None, gt=0)
    runtime_ready: bool | None = None


class WorkerLease(BaseModel):
    lease_token: str = Field(min_length=32, max_length=256)
    attempt_id: str | None = Field(default=None, max_length=80)


class WorkerComplete(WorkerLease):
    output: dict[str, Any]


class WorkerFailure(WorkerLease):
    error: str = Field(min_length=1, max_length=600)
    retryable: bool = False


class WorkerProgress(WorkerLease):
    sequence: int = Field(ge=1, le=2147483647)
    phase: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=120)
    value: float | None = Field(default=None, ge=0)
    total: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=16)
    scope: str = "stage"
    source: str = "worker"


@app.post("/api/worker/hello")
def worker_hello(body: WorkerHello, x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    result = direct_queue.worker_seen(body.worker_id, generation=body.generation,
        started_at=body.started_at, runtime_ready=body.runtime_ready)
    if not result.get("accepted"):
        raise HTTPException(409, "stale Worker generation; this container process cannot reclaim readiness")
    return result


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
    result = direct_queue.heartbeat_control(local_id, body.lease_token, body.attempt_id)
    if not result:
        raise HTTPException(409, "lease expired or is no longer owned by this worker")
    return result


@app.post("/api/worker/progress/{local_id}")
def worker_progress(local_id: str, body: WorkerProgress,
                    x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    event = body.model_dump(exclude={"lease_token", "attempt_id"})
    if not direct_queue.record_progress(local_id, body.lease_token, body.attempt_id, event):
        raise HTTPException(409, "progress event is stale, invalid, or outside the active attempt")
    return {"accepted": True}


@app.post("/api/worker/cancelled/{local_id}")
def worker_cancelled(local_id: str, body: WorkerLease,
                     x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    if not direct_queue.confirm_cancel(local_id, body.lease_token, body.attempt_id):
        raise HTTPException(409, "cancellation confirmation does not match the active requested attempt")
    return {"accepted": True, "state": "cancelled"}


@app.post("/api/worker/complete/{local_id}")
def worker_complete(local_id: str, body: WorkerComplete,
                    x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    try:
        accepted = direct_queue.finish(local_id, body.lease_token, body.output, body.attempt_id)
    except ValueError:
        raise ContractError("invalid_result", "Worker result must contain finite JSON values", "output")
    except Exception as exc:
        raise HTTPException(502, f"Output validation temporarily unavailable: {type(exc).__name__}")
    if not accepted:
        raise HTTPException(409, "lease expired or result already committed")
    return {"accepted": True, "state": db.get_job(local_id)["state"]}


@app.post("/api/worker/fail/{local_id}")
def worker_fail(local_id: str, body: WorkerFailure,
                x_worker_token: str | None = Header(default=None)):
    check_worker_token(x_worker_token)
    if not direct_queue.fail(local_id, body.lease_token, body.error, body.retryable, body.attempt_id):
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
