"""Offline worker/ComfyUI integration checks; no GPU or Salad credentials used."""
import importlib.util
import json
import threading
from pathlib import Path
import unittest
from unittest.mock import patch

WORKER_PATH = Path(__file__).resolve().parents[1] / "salad-worker" / "pull_worker.py"
spec = importlib.util.spec_from_file_location("controller_pull_worker", WORKER_PATH)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class Reporter:
    def __init__(self):
        self.events = []
    def emit(self, *args, **kwargs):
        self.events.append((args, kwargs))


class WorkerRuntimeTests(unittest.TestCase):
    def test_worker_correlates_comfy_progress_to_the_submitted_client_id(self):
        created = []
        payloads = []

        class Monitor:
            def __init__(self, client_id, nodes, reporter):
                self.client_id, self.nodes, self.reporter = client_id, nodes, reporter
                self.prompt_id = None
                created.append(self)
            def start(self): pass
            def close(self): pass

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"prompt_id":"prompt-1"}'

        reporter = Reporter()
        payload = {"prompt": {
            "1": {"class_type": "LoadImage", "inputs": {"image": "s3://bucket/inputs/a.png"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "s3://bucket/inputs/b.png"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 7, "image_a": ["1", 0], "image_b": ["2", 0]}},
        }, "extra_data": {"references": ["image-a", "image-b"]}}
        started = threading.Event()
        holder = {}

        def fake_urlopen(req, timeout):
            payloads.append((req, timeout))
            return Response()

        with patch.object(worker, "COMFY", "http://127.0.0.1:3000/prompt"), \
             patch.object(worker, "COMFY_BASE", "http://127.0.0.1:3000"), \
             patch.object(worker, "ComfyMonitor", Monitor), \
             patch.object(worker.urllib.request, "urlopen", fake_urlopen), \
             patch.object(worker, "wait_for_comfy_result", lambda prompt_id, monitor, progress:
                 {"prompt_id": prompt_id, "status": "success", "outputs": {"images": []}}):
            result = worker.execute({"request": payload}, reporter, started, holder)

        submitted = json.loads(payloads[0][0].data)
        self.assertEqual(submitted["client_id"], created[0].client_id)
        self.assertEqual(submitted["prompt"], payload["prompt"])
        self.assertEqual(submitted["extra_data"], payload["extra_data"])
        self.assertEqual(submitted["prompt"]["1"]["inputs"]["image"], "s3://bucket/inputs/a.png")
        self.assertEqual(submitted["prompt"]["2"]["inputs"]["image"], "s3://bucket/inputs/b.png")
        self.assertTrue(started.is_set())
        self.assertIs(holder["monitor"], created[0])
        self.assertEqual(result["prompt_id"], "prompt-1")

    def test_comfy_progress_is_real_stage_data_and_interruption_is_explicit(self):
        reporter = Reporter()
        monitor = worker.ComfyMonitor("client-1", {"10": "KSampler"}, reporter)

        monitor.consume({"type": "progress", "data": {"prompt_id": "p-1", "node": "10", "value": 12, "max": 30}})
        self.assertEqual(reporter.events[-1][0], ("sampling", "Sampling"))
        self.assertEqual(reporter.events[-1][1], {"value": 12, "total": 30, "unit": "steps", "source": "comfyui"})
        event_count = len(reporter.events)
        monitor.consume({"type": "progress", "data": {"node": "10", "value": 5, "max": 0}})
        self.assertEqual(len(reporter.events), event_count, "missing totals must not create a synthetic percent")
        monitor.consume({"type": "executing", "data": {"node": None, "prompt_id": "p-1"}})
        self.assertEqual(reporter.events[-1][0], ("finalizing", "Finishing the Workflow"))
        monitor.consume({"type": "execution_interrupted", "data": {"prompt_id": "p-1"}})
        self.assertTrue(monitor.interrupted.is_set() and monitor.completed.is_set())

    def test_worker_requires_an_active_prompt_before_sending_interrupt(self):
        with self.assertRaisesRegex(RuntimeError, "has not reported"):
            worker.interrupt_comfy(None)

        captured = []
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(worker, "COMFY_BASE", "http://127.0.0.1:3000"), \
             patch.object(worker.urllib.request, "urlopen", lambda req, timeout: (captured.append((req, timeout)) or Response())):
            worker.interrupt_comfy("prompt-2")
        req, timeout = captured[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:3000/interrupt")
        self.assertEqual(json.loads(req.data), {"prompt_id": "prompt-2"})
        self.assertEqual(timeout, 10)


if __name__ == "__main__":
    unittest.main()
