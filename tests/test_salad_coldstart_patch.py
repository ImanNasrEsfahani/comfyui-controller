"""Offline safety and compatibility checks for Salad cold-start patch.

Run: python3 -m unittest discover -s tests -p 'test_salad_coldstart_patch.py' -v
"""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent.parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load_module('apply_salad_coldstart', HERE / 'scripts' / 'apply_salad_coldstart.py')
A = load_module('salad_cold_start_audit', HERE / 'scripts' / 'salad_cold_start_audit.py')

LEGACY = '''import os
IMAGE = 'example:fixed'
def validate_configuration():
    return True
def group_payload(gpu_id):
    return {'container': {
        "image": IMAGE,
        "priority": 'medium',
    }}
def config_drift(group, gpu_id):
    drift = []
    container = group.get("container") or {}
    if container.get("image") != IMAGE:
        drift.append("image")
    return drift
def patch_group(gpu_id):
    desired = {'container': {
                "image": IMAGE,
                "priority": 'medium',
    }}
    return desired
'''

BACKEND = '''import os
def status(group, configured_group):
    result = {
        "name": group.get("name") or configured_group,
        "status": 'started',
    }
    return result
def _new_group_payload(config, gpu_id):
    if config.get('direct'):
        return {'container': {
                "image": config["image"],
                "priority": 'medium'
        }}
    return {'container': {
            "image": config["image"],
            "priority": 'medium'
    }}
def deploy_draft(old_group, desired, current):
    if True:
            if (old_group.get("container") or {}).get("image") != desired["image"]:
                _api("PATCH", _group_path(current["group_name"]),
                     payload={"container": {"image": desired["image"]}})
'''

CONTRACT = '''def record(data, version, observed_at):
    group_name = data['name']
    result = {
        "hold": data.get("hold"), "name": group_name, "group_name": group_name,
        "status": 'started',
    }
    return result
'''

ENV = 'SALAD_PRIORITY=medium\nSALAD_GPU_NAME="RTX 5090 (32 GB)"\nSALAD_CPU=4\n'


class PatchTests(unittest.TestCase):
    def test_patch_idempotent_and_valid_syntax(self):
        for func, src in ((P.patch_legacy, LEGACY), (P.patch_backend, BACKEND)):
            result = func(src)
            self.assertGreaterEqual(result.count('"image_caching": image_caching_enabled()'), 2)
            self.assertEqual(func(result), result)
            compile(result, '<patched-module>', 'exec')
        self.assertIn('container.image_caching', P.patch_legacy(LEGACY))
        patched_contract = P.patch_instance_contract(CONTRACT)
        self.assertIn('\"image_caching\": data.get(\"image_caching\")', patched_contract)
        self.assertEqual(patched_contract, P.patch_instance_contract(patched_contract))
        compile(patched_contract, '<contract>', 'exec')
        self.assertIn('"image_caching": (group.get("container")', P.patch_backend(BACKEND))

    def test_patch_legacy_calculates_drift_and_payload(self):
        scope = {'os': __import__('os')}
        exec(compile(P.patch_legacy(LEGACY), 'legacy', 'exec'), scope)
        with mock.patch.dict('os.environ', {'SALAD_IMAGE_CACHING': 'true'}):
            self.assertIs(True, scope['group_payload']('id')['container']['image_caching'])
            self.assertEqual(scope['config_drift']({'container': {'image': 'example:fixed', 'image_caching': False}}, 'id'), ['container.image_caching'])
        with mock.patch.dict('os.environ', {'SALAD_IMAGE_CACHING': 'false'}):
            self.assertIs(False, scope['patch_group']('id')['container']['image_caching'])

    def test_backend_sets_cache_both_paths(self):
        scope = {'os': __import__('os')}
        exec(compile(P.patch_backend(BACKEND), 'backend', 'exec'), scope)
        with mock.patch.dict('os.environ', {'SALAD_IMAGE_CACHING': 'true'}):
            for direct in (True, False):
                payload = scope['_new_group_payload']({'image':'image:test', 'direct':direct}, 'id')
                self.assertEqual(payload['container']['image_caching'], True)

    def test_patch_refuses_unknown_source_and_is_idempotent(self):
        with self.assertRaises(ValueError):
            P.patch_legacy(LEGACY.replace('"image": IMAGE,', '"image": "unknown",', 1))
        with self.assertRaises(ValueError):
            P.patch_backend(BACKEND.replace('"image": config["image"],', '"image": config["image_new"],', 1))
        result = P.patch_env(ENV)
        self.assertIn('SALAD_IMAGE_CACHING=true', result)
        self.assertEqual(P.patch_env(result), result)

    def test_all_or_nothing_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'salad-worker').mkdir()
            (root / 'backend/app').mkdir(parents=True)
            (root / 'salad-worker/deploy_salad.py').write_text(LEGACY)
            (root / 'backend/app/salad_control.py').write_text('unrecognized')
            (root / 'backend/app/instance_contract.py').write_text(CONTRACT)
            (root / '.env.example').write_text(ENV)
            with self.assertRaises(ValueError):
                P.apply(root)
            self.assertEqual((root / 'salad-worker/deploy_salad.py').read_text(), LEGACY)
            (root / 'backend/app/salad_control.py').write_text(BACKEND)
            self.assertEqual(len(P.apply(root)), 4)
            self.assertEqual(set(P.apply(root).values()), {'already-applied'})


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.group = {'name': 'qwen-test', 'pending_change': False,
                      'replicas': 0,
                      'container': {'image': 'ghcr.io/example/tag', 'image_caching': False},
                      'current_state': {'status': 'started', 'instance_status_counts': {}}}

    def test_log_durations(self):
        sample = '''[coldstart] event=container_entry utc=2026-10-16T10:00:00Z elapsed_s=0
[coldstart] event=model_restore_start utc=2026-10-16T10:00:00Z elapsed_s=0
[coldstart] event=model_restore_done utc=2026-10-16T10:02:00Z elapsed_s=120
[coldstart] event=api_start utc=2026-10-16T10:02:01Z elapsed_s=121
[coldstart] event=api_ready utc=2026-10-16T10:05:01Z elapsed_s=301
[coldstart] event=direct_worker_spawned utc=2026-10-16T10:05:04Z elapsed_s=304
'''
        metrics = A.extract_timeline(sample)['durations_seconds']
        self.assertEqual(metrics['reassemble_and_hash_models'], 120)
        self.assertEqual(metrics['comfyui_api_ready_wait'], 180)
        self.assertEqual(metrics['entry_to_worker_spawn'], 304)

    def test_unproven_progress_remains_unknown(self):
        results = A.instance_observation(self.group, [
            {'state': 'pulling', 'pulling_progress': 0.43},
            {'state': 'pulling', 'pulling_progress': 0.43, 'pulling_progress_unit': 'fraction'},
            {'state': 'pulling', 'pulling_progress': 43, 'pulling_progress_unit': 'percent'},
        ])
        self.assertEqual([i['pull_percent'] for i in results['instances']], [None, 43.0, 43])
        self.assertNotIn('environment_variables', str(results))

    def test_patch_requires_strictly_idle_group(self):
        A.assert_safe_for_cache_update(self.group, [])
        for change in ({'replicas': 1}, {'pending_change': True},
                       {'current_state': {'instance_status_counts': {'running': 1}}},
                       {'queue_autoscaler': {'min_replicas': 1}}):
            group = dict(self.group, **change)
            with self.assertRaises(ValueError):
                A.assert_safe_for_cache_update(group, [])
        with self.assertRaises(ValueError):
            A.assert_safe_for_cache_update(self.group, [{'id': 'existing'}])

    def test_audit_does_not_patch_without_explicit_confirmation(self):
        class FakeClient:
            def __init__(self, group): self.group=group; self.calls=[]
            def request(self, method, suffix='', data=None):
                self.calls.append((method, suffix, data))
                if method == 'PATCH':
                    self.group['container']['image_caching'] = True
                    return {}
                if suffix == '/instances': return {'instances': []}
                return self.group
        class Args:
            group_json=None
            instances_json=None
            worker_log=None
            group='qwen-test'
            apply=False
            confirm_idle_cache_update=False
        fake = FakeClient(self.group)
        with contextlib.redirect_stdout(io.StringIO()):
            A.run(Args, fake)
        self.assertTrue(all(method=='GET' for method, _, _ in fake.calls))
        Args.apply = True
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(io.StringIO()):
                A.run(Args, fake)
        self.assertTrue(all(method=='GET' for method, _, _ in fake.calls))
        Args.confirm_idle_cache_update=True
        with contextlib.redirect_stdout(io.StringIO()):
            A.run(Args, fake)
        self.assertEqual(len([x for x in fake.calls if x[0]=='PATCH']), 1)
        self.assertTrue(self.group['container']['image_caching'])


if __name__ == '__main__':
    unittest.main()
