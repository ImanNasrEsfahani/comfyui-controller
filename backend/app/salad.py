import httpx
from .config import settings, VALID_SALAD_PRIORITIES

BASE = "https://api.salad.com/api/public"
USER_AGENT = "comfyui-controller/1.1"


def headers():
    settings.validate_salad()
    return {
        "Salad-Api-Key": settings.salad_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def normalize_priority(priority: str | None) -> str:
    value = (priority or settings.salad_default_priority).strip().lower()
    if value not in VALID_SALAD_PRIORITIES:
        raise ValueError("priority must be one of: " + ", ".join(VALID_SALAD_PRIORITIES))
    return value


def queue_name_for_priority(priority: str | None) -> str:
    return settings.salad_queue_name(normalize_priority(priority))


def queue_base(queue_name: str):
    return (
        f"{BASE}/organizations/{settings.salad_org}"
        f"/projects/{settings.salad_project}"
        f"/queues/{queue_name}"
    )


def submit_job(input_payload: dict, *, priority: str | None = None, metadata: dict | None = None):
    selected_priority = normalize_priority(priority)
    queue_name = queue_name_for_priority(selected_priority)

    body = {"input": input_payload}
    metadata_payload = dict(metadata or {})
    metadata_payload["priority"] = selected_priority
    metadata_payload["queue"] = queue_name
    body["metadata"] = metadata_payload

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{queue_base(queue_name)}/jobs",
            headers=headers(),
            json=body,
        )
        response.raise_for_status()
        return response.json(), queue_name, selected_priority


def get_job(job_id: str, queue_name: str):
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{queue_base(queue_name)}/jobs/{job_id}",
            headers=headers(),
        )
        response.raise_for_status()
        return response.json()
