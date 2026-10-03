#!/usr/bin/env python3
"""Pull jobs from our Google VM; no Salad Queue SDK and no IMDS token.

Only short control requests traverse Cloudflare. Long image/video processing
is a localhost call to comfyui-api while a separate thread renews the lease.
"""
import json
import os
import signal
import socket
import threading
import time
import urllib.error
import urllib.request
from uuid import uuid4

BACKEND = os.environ.get("DIRECT_BACKEND_URL", "").rstrip("/")
TOKEN = os.environ.get("DIRECT_WORKER_TOKEN", "")
COMFY = f"http://127.0.0.1:{os.environ.get('PORT', '3000')}/prompt"
WORKER_ID = (socket.gethostname() + "-" + uuid4().hex[:8])[:128]
POLL_SECONDS = max(3, int(os.environ.get("DIRECT_WORKER_POLL_SECONDS", "10")))
HEARTBEAT_SECONDS = max(5, int(os.environ.get("DIRECT_WORKER_HEARTBEAT_SECONDS", "15")))
JOB_TIMEOUT = max(60, int(os.environ.get("DIRECT_WORKER_JOB_TIMEOUT_SECONDS", "3600")))
STOP = threading.Event()


def log(message):
    print("[direct-worker] " + message, flush=True)


def request(path, data=None, *, timeout=20):
    payload = json.dumps(data).encode() if data is not None else None
    headers = {"X-Worker-Token": TOKEN, "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BACKEND + path, data=payload,
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def execute(job):
    payload = json.dumps(job["request"]).encode()
    req = urllib.request.Request(
        COMFY, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=JOB_TIMEOUT) as response:
        raw = response.read()
        body = json.loads(raw) if raw else {}
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"ComfyUI unexpected HTTP {response.status}")
        if not isinstance(body, dict):
            raise RuntimeError("ComfyUI returned an unexpected non-object response")
        if str(body.get("status", "")).lower() in ("failed", "error"):
            raise RuntimeError("ComfyUI reported a failed processing status")
        return body


def keep_lease(job, done, lease_lost):
    path = "/api/worker/heartbeat/" + job["job_id"]
    while not done.wait(HEARTBEAT_SECONDS):
        try:
            result = request(path, {"lease_token": job["lease_token"]})
            if not result or not result.get("accepted"):
                lease_lost.set()
                log("Lease rejected for job " + job["job_id"])
                return
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 409):
                lease_lost.set()
                log("Lease rejected with HTTP " + str(exc.code))
                return
            log("Heartbeat HTTP " + str(exc.code) + "; retrying")
        except (OSError, ValueError) as exc:
            log("Heartbeat temporarily unavailable: " + type(exc).__name__)


def work(job):
    job_id = job["job_id"]
    log(f"Claimed job {job_id}, attempt {job['attempt']}")
    done = threading.Event()
    lost = threading.Event()
    thread = threading.Thread(target=keep_lease, args=(job, done, lost), daemon=True)
    thread.start()
    response = None
    error = None
    try:
        response = execute(job)
    except urllib.error.HTTPError as exc:
        error = f"ComfyUI returned HTTP {exc.code}"
    except Exception as exc:
        # A timeout may happen *after* ComfyUI accepted a job. Do not silently
        # retry an ambiguous execution and incur duplicated GPU/R2 costs.
        error = "ComfyUI execution error: " + type(exc).__name__ + ": " + str(exc)[:250]
    finally:
        done.set()
        thread.join(timeout=3)
    if lost.is_set():
        log("Lease expired/revoked; refusing to commit stale job " + job_id)
        return
    path = "/api/worker/" + ("fail/" if error else "complete/") + job_id
    data = {"lease_token": job["lease_token"]}
    if error:
        data.update({"error": error, "retryable": False})
    else:
        data["output"] = response
    for attempt in range(3):
        try:
            result = request(path, data)
            if result and result.get("accepted"):
                log("Job " + job_id + (" failed: " + error if error else " succeeded"))
            else:
                log("Completion rejected for job " + job_id)
            return
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 409):
                log("Completion rejected HTTP " + str(exc.code))
                return
            log("Completion HTTP " + str(exc.code))
        except (OSError, ValueError) as exc:
            log("Completion delivery error: " + type(exc).__name__)
        time.sleep(3)
    log("Completion acknowledgement unavailable; lease recovery will handle job " + job_id)


def main():
    if not BACKEND.startswith("https://") or not TOKEN or len(TOKEN) < 32:
        raise SystemExit("DIRECT_BACKEND_URL must be HTTPS and DIRECT_WORKER_TOKEN at least 32 characters")
    log("Started; local ComfyUI gateway=" + COMFY)
    last_hello = 0
    errors = 0
    while not STOP.is_set():
        try:
            if time.time() - last_hello >= 30:
                request("/api/worker/hello", {"worker_id": WORKER_ID})
                last_hello = time.time()
            item = request("/api/worker/claim", {"worker_id": WORKER_ID})
            errors = 0
            if item:
                work(item)
                last_hello = 0
            else:
                STOP.wait(POLL_SECONDS)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                log("Authentication rejected (HTTP " + str(exc.code) + "); stopping")
                return 2
            errors += 1
            log("Backend HTTP " + str(exc.code) + "; retrying")
            STOP.wait(min(60, 5 * errors))
        except (OSError, ValueError) as exc:
            errors += 1
            log("Backend temporarily unavailable: " + type(exc).__name__)
            STOP.wait(min(60, 5 * errors))
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    raise SystemExit(main())
