import httpx
from .config import settings

BASE = "https://api.salad.com/api/public"

def headers():
    settings.validate_runtime()
    return {
        "Salad-Api-Key": settings.salad_api_key,
        "Content-Type": "application/json",
    }

def queue_base():
    return (
        f"{BASE}/organizations/{settings.salad_org}"
        f"/projects/{settings.salad_project}"
        f"/queues/{settings.salad_queue}"
    )

def submit_job(input_payload: dict, metadata: dict | None = None):
    body = {"input": input_payload}
    if metadata:
        body["metadata"] = metadata
    with httpx.Client(timeout=30.0) as c:
        r = c.post(f"{queue_base()}/jobs", headers=headers(), json=body)
        r.raise_for_status()
        return r.json()

def get_job(job_id: str):
    with httpx.Client(timeout=30.0) as c:
        r = c.get(f"{queue_base()}/jobs/{job_id}", headers=headers())
        r.raise_for_status()
        return r.json()
