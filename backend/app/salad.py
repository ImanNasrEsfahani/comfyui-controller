"""New jobs always go to SALAD_QUEUE_NAME from the root .env."""
import httpx
from .config import settings


def headers():
    settings.validate_salad()
    return {
        "Salad-Api-Key": settings.salad_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": settings.salad_user_agent,
    }


def normalize_priority(priority: str | None) -> str:
    selected = (priority or settings.salad_priority).strip().lower()
    if selected != settings.salad_priority:
        raise ValueError(f"Only priority {settings.salad_priority!r} is configured")
    return selected


def queue_name_for_priority(priority: str | None) -> str:
    return settings.salad_queue_name(normalize_priority(priority))


def queue_base(queue_name: str):
    return (
        f"{settings.salad_api_base_url}/organizations/{settings.salad_org}"
        f"/projects/{settings.salad_project}/queues/{queue_name}"
    )


def submit_job(input_payload: dict, *, priority: str | None = None, metadata: dict | None = None):
    selected_priority = normalize_priority(priority)
    queue_name = queue_name_for_priority(selected_priority)

    body = {"input": input_payload}
    metadata_payload = dict(metadata or {})
    metadata_payload["priority"] = selected_priority
    metadata_payload["queue"] = queue_name
    body["metadata"] = metadata_payload

    with httpx.Client(timeout=settings.salad_http_timeout_seconds) as client:
        response = client.post(
            f"{queue_base(queue_name)}/jobs", headers=headers(), json=body
        )
        response.raise_for_status()
        return response.json(), queue_name, selected_priority


def get_job(job_id: str, queue_name: str):
    # Historic jobs may have a different saved Queue; do not rewrite it.
    with httpx.Client(timeout=settings.salad_http_timeout_seconds) as client:
        response = client.get(
            f"{queue_base(queue_name)}/jobs/{job_id}", headers=headers()
        )
        response.raise_for_status()
        return response.json()
