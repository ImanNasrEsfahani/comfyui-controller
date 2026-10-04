#!/usr/bin/env python3
"""Pull jobs from our Google VM; no Salad Queue SDK and no IMDS token.

Only short control requests traverse Cloudflare. Long image/video processing
is a localhost call to comfyui-api while a separate thread renews the lease.
"""
import json
import os
import re
import signal
import socket
import threading
import time
import urllib.error
import urllib.request
from uuid import uuid4
from urllib.parse import quote

try:
    import websocket
except ImportError:  # Progress remains explicitly unknown when WebSocket support is absent.
    websocket = None

BACKEND = os.environ.get("DIRECT_BACKEND_URL", "").rstrip("/")
TOKEN = os.environ.get("DIRECT_WORKER_TOKEN", "")
COMFY = f"http://127.0.0.1:{os.environ.get('PORT', '3000')}/prompt"
COMFY_BASE = COMFY.rsplit("/prompt", 1)[0]
WORKER_ID = (socket.gethostname() + "-" + uuid4().hex[:8])[:128]
POLL_SECONDS = max(3, int(os.environ.get("DIRECT_WORKER_POLL_SECONDS", "10")))
HEARTBEAT_SECONDS = max(5, int(os.environ.get("DIRECT_WORKER_HEARTBEAT_SECONDS", "15")))
JOB_TIMEOUT = max(60, int(os.environ.get("DIRECT_WORKER_JOB_TIMEOUT_SECONDS", "3600")))
STOP = threading.Event()
UNRESOLVED_BINDING = re.compile(r"\{\{(?:input|prompt|generation|output|lora)\.[A-Za-z0-9_.:-]+\}\}")


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


def build_comfy_payload(job):
    """Pass the backend-rendered API graph through without rewriting it."""
    request_data = job.get("request") if isinstance(job, dict) else None
    prompt = request_data.get("prompt") if isinstance(request_data, dict) else None
    if not isinstance(prompt, dict) or not prompt:
        raise RuntimeError("Controller job has no rendered ComfyUI graph")

    def check(value):
        if isinstance(value, dict):
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif isinstance(value, str) and UNRESOLVED_BINDING.search(value):
            raise RuntimeError("Controller job contains an unresolved Workflow binding")

    check(prompt)
    return request_data


class ProgressReporter:
    def __init__(self, job, lease_lost):
        self.job = job
        self.lease_lost = lease_lost
        self.sequence = 0
        self.lock = threading.Lock()

    def emit(self, phase, label, *, value=None, total=None, unit=None, source="worker"):
        with self.lock:
            self.sequence += 1
            data = {"lease_token": self.job["lease_token"],
                    "attempt_id": self.job.get("attempt_id"), "sequence": self.sequence,
                    "phase": phase, "label": label, "value": value, "total": total,
                    "unit": unit, "scope": "stage", "source": source}
        try:
            response = request("/api/worker/progress/" + self.job["job_id"], data)
            return bool(response and response.get("accepted"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 409):
                self.lease_lost.set()
            log("Progress update rejected with HTTP " + str(exc.code))
        except (OSError, ValueError) as exc:
            log("Progress update unavailable: " + type(exc).__name__)
        return False


def _node_label(node_type):
    kind = str(node_type or "").lower()
    if "ksampler" in kind or "sampler" in kind:
        return "Sampling"
    if "save" in kind or "preview" in kind:
        return "Saving generated output"
    if "load" in kind or "checkpoint" in kind or "vae" in kind:
        return "Preparing model and inputs"
    return "Processing Workflow"


class ComfyMonitor:
    """Listen for ComfyUI's real per-client progress events when available."""
    def __init__(self, client_id, nodes, reporter):
        self.client_id = client_id
        self.nodes = nodes
        self.reporter = reporter
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.interrupted = threading.Event()
        self.thread = None
        self.socket = None
        self.prompt_id = None
        self.last_progress_at = 0.0
        self.last_progress_value = None
        self.completed = threading.Event()
        self.succeeded = threading.Event()
        self.execution_error = None

    def start(self):
        if websocket is None:
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(1.5)

    def _run(self):
        base = COMFY_BASE.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        url = base + "/ws?clientId=" + quote(self.client_id, safe="")
        try:
            self.socket = websocket.create_connection(url, timeout=5, enable_multithread=True)
            self.socket.settimeout(1)
            self.ready.set()
            while not self.stopped.is_set() and not STOP.is_set():
                try:
                    raw = self.socket.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not isinstance(raw, str):
                    continue
                try:
                    event = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                self.consume(event)
        except Exception as exc:
            if not self.stopped.is_set():
                log("ComfyUI progress channel unavailable: " + type(exc).__name__)
        finally:
            self.ready.set()
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass

    def consume(self, event):
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if data.get("prompt_id"):
            self.prompt_id = str(data["prompt_id"])
        node = data.get("node")
        label = _node_label(self.nodes.get(str(node)))
        if event_type == "progress":
            value, total = data.get("value"), data.get("max")
            if (isinstance(value, (int, float)) and not isinstance(value, bool) and
                    isinstance(total, (int, float)) and not isinstance(total, bool) and
                    total > 0 and 0 <= value <= total):
                now = time.monotonic()
                if (value != total and value == self.last_progress_value and
                        now - self.last_progress_at < 0.75) or (value != total and now - self.last_progress_at < 0.45):
                    return
                self.last_progress_at = now
                self.last_progress_value = value
                sampling = label == "Sampling"
                self.reporter.emit("sampling" if sampling else "node_progress", label,
                    value=value, total=total, unit="steps" if sampling else "nodes", source="comfyui")
        elif event_type == "executing":
            if data.get("node") is None:
                self.reporter.emit("finalizing", "Finishing the Workflow", source="comfyui")
            else:
                self.reporter.emit("processing", label, source="comfyui")
        elif event_type == "executed":
            output = data.get("output") if isinstance(data.get("output"), dict) else {}
            if label == "Saving generated output" or output.get("images"):
                self.reporter.emit("collecting_outputs", "Collecting generated outputs", source="comfyui")
        elif event_type == "execution_success":
            self.succeeded.set()
            self.completed.set()
            self.reporter.emit("finalizing", "Verifying generated outputs", source="comfyui")
        elif event_type == "execution_interrupted":
            self.interrupted.set()
            self.completed.set()
        elif event_type == "execution_error":
            self.execution_error = data
            self.completed.set()

    def close(self):
        self.stopped.set()
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=2)


def execute(job, reporter=None, api_started=None, monitor_holder=None):
    request_payload = build_comfy_payload(job)
    client_id = uuid4().hex
    monitor = None
    if reporter:
        nodes = {str(key): value.get("class_type") for key, value in request_payload["prompt"].items()
                 if isinstance(value, dict)}
        monitor = ComfyMonitor(client_id, nodes, reporter)
        monitor.start()
        if monitor_holder is not None:
            monitor_holder["monitor"] = monitor
        reporter.emit("processing", "Running Workflow on ComfyUI")
    # ComfyUI scopes WebSocket progress to the same client_id used for submit.
    request_payload = dict(request_payload)
    request_payload["client_id"] = client_id
    payload = json.dumps(request_payload).encode()
    req = urllib.request.Request(
        COMFY, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if api_started is not None:
        api_started.set()
    try:
        with urllib.request.urlopen(req, timeout=JOB_TIMEOUT) as response:
            raw = response.read()
            body = json.loads(raw) if raw else {}
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"ComfyUI unexpected HTTP {response.status}")
            if not isinstance(body, dict):
                raise RuntimeError("ComfyUI returned an unexpected non-object response")
            if str(body.get("status", "")).lower() in ("failed", "error"):
                raise RuntimeError("ComfyUI reported a failed processing status")
            prompt_id = body.get("prompt_id")
            if prompt_id:
                if monitor:
                    monitor.prompt_id = str(prompt_id)
                return wait_for_comfy_result(prompt_id, monitor, reporter)
            # Some compatible gateways return completed output directly.
            if reporter:
                reporter.emit("finalizing", "Saving and verifying generated outputs")
            return body
    finally:
        if monitor:
            monitor.close()


def interrupt_comfy(prompt_id):
    if not prompt_id:
        raise RuntimeError("ComfyUI has not reported the active prompt ID")
    body = json.dumps({"prompt_id": str(prompt_id)}).encode()
    req = urllib.request.Request(COMFY_BASE + "/interrupt", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError("ComfyUI did not accept the interrupt request")


def comfy_history(prompt_id):
    """Read ComfyUI's durable execution result after /prompt accepts a graph."""
    url = COMFY_BASE + "/history/" + quote(str(prompt_id), safe="")
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        # ComfyUI may not have written history yet while the graph is running.
        if exc.code == 404:
            return {}
        raise


def _comfy_error_text(data):
    if not isinstance(data, dict):
        return "ComfyUI reported a Workflow execution error"
    parts = [str(data.get(key, "")).strip() for key in
             ("exception_message", "message", "node_type") if data.get(key)]
    return ("ComfyUI execution error: " + "; ".join(parts))[:600] if parts else \
        "ComfyUI reported a Workflow execution error"


def wait_for_comfy_result(prompt_id, monitor, reporter):
    """Wait for the real ComfyUI terminal event/history, not just queue acceptance."""
    deadline = time.monotonic() + JOB_TIMEOUT
    while not STOP.is_set():
        if monitor and monitor.execution_error is not None:
            raise RuntimeError(_comfy_error_text(monitor.execution_error))
        if monitor and monitor.interrupted.is_set():
            return {"prompt_id": prompt_id, "status": "interrupted", "outputs": {}}

        try:
            history = comfy_history(prompt_id)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log("ComfyUI history temporarily unavailable: " + type(exc).__name__)
            history = {}
        record = history.get(str(prompt_id)) if isinstance(history, dict) else None
        if isinstance(record, dict):
            status = record.get("status") if isinstance(record.get("status"), dict) else {}
            status_name = str(status.get("status_str", "")).lower()
            messages = status.get("messages") if isinstance(status.get("messages"), list) else []
            if status_name in {"error", "failed"}:
                details = next((entry[1] for entry in messages
                                if isinstance(entry, (list, tuple)) and len(entry) > 1 and
                                entry[0] == "execution_error" and isinstance(entry[1], dict)), None)
                raise RuntimeError(_comfy_error_text(details))
            if status.get("completed"):
                if status_name in {"interrupted", "cancelled", "canceled"}:
                    return {"prompt_id": prompt_id, "status": status_name,
                            "outputs": record.get("outputs", {})}
                if status_name == "success":
                    if reporter:
                        reporter.emit("finalizing", "Saving and verifying generated outputs")
                    return {"prompt_id": prompt_id, "status": "success",
                            "outputs": record.get("outputs", {})}

        if monitor and monitor.completed.is_set():
            if monitor.interrupted.is_set():
                return {"prompt_id": prompt_id, "status": "interrupted", "outputs": {}}
            if monitor.execution_error is not None:
                raise RuntimeError(_comfy_error_text(monitor.execution_error))
            if monitor.succeeded.is_set():
                if reporter:
                    reporter.emit("finalizing", "Saving and verifying generated outputs")
                return {"prompt_id": prompt_id, "status": "success",
                        "outputs": record.get("outputs", {}) if isinstance(record, dict) else {}}

        if time.monotonic() >= deadline:
            raise TimeoutError("ComfyUI Workflow did not reach a terminal state before the Worker timeout")
        STOP.wait(1)
    raise RuntimeError("Worker is shutting down before ComfyUI completed the Workflow")


def keep_lease(job, done, lease_lost, cancel_requested, interrupt_sent, api_started, monitor_holder):
    path = "/api/worker/heartbeat/" + job["job_id"]
    while not done.wait(HEARTBEAT_SECONDS):
        try:
            result = request(path, {"lease_token": job["lease_token"], "attempt_id": job.get("attempt_id")})
            if not result or not result.get("accepted"):
                lease_lost.set()
                log("Lease rejected for job " + job["job_id"])
                return
            if result.get("cancel_requested"):
                cancel_requested.set()
                if api_started.is_set() and not interrupt_sent.is_set():
                    try:
                        monitor = monitor_holder.get("monitor")
                        prompt_id = getattr(monitor, "prompt_id", None)
                        interrupt_comfy(prompt_id)
                        interrupt_sent.set()
                        log("ComfyUI accepted per-Job interrupt for " + job["job_id"])
                    except Exception as exc:
                        log("ComfyUI interrupt not confirmed: " + type(exc).__name__)
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
    cancel_requested = threading.Event()
    interrupt_sent = threading.Event()
    api_started = threading.Event()
    monitor_holder = {}
    reporter = ProgressReporter(job, lost)
    thread = threading.Thread(target=keep_lease,
        args=(job, done, lost, cancel_requested, interrupt_sent, api_started, monitor_holder), daemon=True)
    thread.start()
    response = None
    error = None
    try:
        reporter.emit("preparing", "Preparing Worker execution")
        response = execute(job, reporter, api_started, monitor_holder)
    except urllib.error.HTTPError as exc:
        error = f"ComfyUI returned HTTP {exc.code}"
    except Exception as exc:
        # A timeout may happen *after* ComfyUI accepted a job. Do not silently
        # retry an ambiguous execution and incur duplicated GPU/R2 costs.
        error = "ComfyUI execution error: " + type(exc).__name__ + ": " + str(exc)[:250]
    try:
        monitor = monitor_holder.get("monitor")
        status = str((response or {}).get("status", "")).lower()
        confirmed_by_comfy = bool(getattr(monitor, "interrupted", None) and monitor.interrupted.is_set())
        was_interrupted = bool(cancel_requested.is_set() and interrupt_sent.is_set() and
            (confirmed_by_comfy or status in {"cancelled", "canceled", "interrupted"}))
        if status in {"cancelled", "canceled", "interrupted"} and not was_interrupted:
            error = "ComfyUI Workflow was interrupted without a confirmed cancellation request"
        if was_interrupted and not lost.is_set():
            try:
                result = request("/api/worker/cancelled/" + job_id,
                    {"lease_token": job["lease_token"], "attempt_id": job.get("attempt_id")})
                if result and result.get("accepted"):
                    log("Cancellation confirmed for job " + job_id)
                else:
                    log("Cancellation confirmation rejected for job " + job_id)
            except Exception as exc:
                log("Cancellation acknowledgement unavailable: " + type(exc).__name__)
        else:
            deliver_result(job, response, error, lost)
    finally:
        # Output validation is part of the active attempt. Renew the lease
        # until the controller acknowledges finalization, not just compute.
        done.set()
        thread.join(timeout=3)


def deliver_result(job, response, error, lost):
    job_id = job["job_id"]
    if lost.is_set():
        log("Lease expired/revoked; refusing to commit stale job " + job_id)
        return
    path = "/api/worker/" + ("fail/" if error else "complete/") + job_id
    data = {"lease_token": job["lease_token"], "attempt_id": job.get("attempt_id")}
    if error:
        data.update({"error": error, "retryable": False})
    else:
        data["output"] = response
    for attempt in range(3):
        try:
            result = request(path, data)
            if result and result.get("accepted"):
                log("Job " + job_id + (" failed: " + error if error else " result committed: " + result.get("state", "accepted")))
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
