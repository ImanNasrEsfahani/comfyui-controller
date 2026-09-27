from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Literal
from uuid import uuid4
from pathlib import Path
import re

from .config import settings
from . import db, storage, salad
from .template import render_template

app = FastAPI(title="Qwen ComfyUI Controller", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db.init_db()


def check_internal_token(x_internal_token: str | None):
    if settings.internal_token and x_internal_token != settings.internal_token:
        raise HTTPException(status_code=401, detail="invalid internal token")


def safe_name(name: str):
    name = Path(name or "upload.bin").name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


class WorkflowIn(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=200)
    api_prompt: dict[str, Any]
    ui_workflow: dict[str, Any] | None = None


class JobIn(BaseModel):
    workflow_id: str
    variables: dict[str, Any] = Field(default_factory=dict)
    priority: Literal["high", "medium", "low", "batch"] = "medium"


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": settings.app_name,
        "default_priority": settings.salad_default_priority,
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
        raise HTTPException(
            400,
            "api_prompt looks like ComfyUI UI workflow format. Export API Format first.",
        )
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


@app.post("/api/jobs")
def create_job(body: JobIn, x_internal_token: str | None = Header(default=None)):
    check_internal_token(x_internal_token)

    wf = db.get_workflow(body.workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")

    try:
        rendered = render_template(wf["api_prompt"], body.variables)
    except KeyError as exc:
        raise HTTPException(400, str(exc))

    local_id = str(uuid4())
    selected_priority = body.priority or "medium"
    selected_queue = salad.queue_name_for_priority(selected_priority)

    prompt_request = {
        "id": local_id,
        "prompt": rendered,
        "s3": {
            "bucket": settings.r2_bucket,
            "prefix": f"outputs/{local_id}/",
            "async": False,
        },
    }

    db.create_job(
        local_id,
        body.workflow_id,
        prompt_request,
        priority=selected_priority,
        salad_queue=selected_queue,
    )

    try:
        response, queue_name, normalized_priority = salad.submit_job(
            prompt_request,
            priority=selected_priority,
            metadata={
                "controller_job_id": local_id,
                "workflow_id": body.workflow_id,
            },
        )

        salad_id = response.get("id") or response.get("job_id")
        if not salad_id:
            raise RuntimeError("Salad response has no job id")

        state = response.get("status") or response.get("state") or "pending"
        db.update_job(
            local_id,
            salad_job_id=str(salad_id),
            state=state,
            output=response,
        )

    except Exception as exc:
        db.update_job(local_id, state="submit_failed", error=str(exc))
        raise HTTPException(502, f"Salad job submission failed: {exc}")

    return db.get_job(local_id)


@app.get("/api/jobs")
def jobs(limit: int = 50):
    return [public_job(item) for item in db.list_jobs(limit)]


def public_job(item: dict):
    if not item:
        return item
    data = dict(item)
    data["output"] = storage.sign_s3_values(data.get("output"))
    return data


@app.get("/api/jobs/{local_id}")
def job(local_id: str):
    item = db.get_job(local_id)
    if not item:
        raise HTTPException(404, "job not found")

    salad_id = item.get("salad_job_id")

    if salad_id and item.get("state") not in {
        "succeeded", "failed", "cancelled", "submit_failed"
    }:
        try:
            queue_name = item.get("salad_queue") or settings.salad_legacy_queue
            remote = salad.get_job(salad_id, queue_name)

            state = remote.get("status") or remote.get("state") or item["state"]
            output = remote.get("output")
            if output is None:
                output = remote

            db.update_job(local_id, state=state, output=output)
            item = db.get_job(local_id)

        except Exception as exc:
            item["poll_warning"] = str(exc)

    return public_job(item)
