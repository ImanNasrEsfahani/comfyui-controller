#!/usr/bin/env python3
"""Read-only Salad cold-start audit; OPTIONAL explicitly gated idle cache PATCH.

No secrets, prompt text, raw JSON or environment variables are printed.
An operator must provide the EXACT active group name; stale .env defaults are
never silently used. The default operation is always read-only.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote
import urllib.error
import urllib.request

LOG_RE = re.compile(r'^\[coldstart\] event=([a-z_]+) utc=([0-9TZ:.-]+) elapsed_s=(\d+)\s*$')
EVENTS = (
    'container_entry', 'model_restore_start', 'model_restore_done', 'api_start',
    'api_ready', 'runtime_verification_start', 'runtime_verified',
    'direct_worker_spawned',
)


def extract_timeline(text: str) -> dict:
    timeline = {}
    for line in text.splitlines():
        match = LOG_RE.match(line.strip())
        if not match:
            continue
        event, utc, seconds = match.groups()
        # A fresh container boot starts a fresh interval.
        if event == 'container_entry':
            timeline = {}
        if event in EVENTS:
            timeline[event] = {'utc': utc, 'elapsed_s': int(seconds)}
    phase_pairs = {
        'reassemble_and_hash_models': ('model_restore_start', 'model_restore_done'),
        'comfyui_api_ready_wait': ('api_start', 'api_ready'),
        'runtime_validation': ('runtime_verification_start', 'runtime_verified'),
        'entry_to_worker_spawn': ('container_entry', 'direct_worker_spawned'),
    }
    durations = {}
    for label, (start, end) in phase_pairs.items():
        if start in timeline and end in timeline:
            duration = timeline[end]['elapsed_s'] - timeline[start]['elapsed_s']
            if duration >= 0:
                durations[label] = duration
    return {'events': timeline, 'durations_seconds': durations}


def instance_observation(group: dict, instances: list) -> dict:
    counts = (group.get('current_state') or {}).get('instance_status_counts') or {}
    out = {
        'group_name': group.get('name'),
        'image': (group.get('container') or {}).get('image'),
        'image_caching': (group.get('container') or {}).get('image_caching'),
        'provider_status': (group.get('current_state') or {}).get('status'),
        'pending_change': group.get('pending_change'),
        'requested_replicas': group.get('replicas'),
        'instance_counts': counts,
        'instances': [],
    }
    for item in instances:
        if not isinstance(item, dict):
            continue
        obs = {'state': item.get('state'), 'ready': item.get('ready'),
               'updated_at': item.get('update_time')}
        raw = item.get('pulling_progress')
        unit = item.get('pulling_progress_unit')
        total = item.get('pulling_progress_total')
        percentage = None
        if isinstance(raw, (float, int)) and not isinstance(raw, bool):
            if unit in ('fraction', 'ratio') and 0 <= raw <= 1:
                percentage = round(raw * 100, 2)
            elif unit in ('percent', '%') and 0 <= raw <= 100:
                percentage = round(raw, 2)
            elif unit in ('bytes', 'byte') and isinstance(total, (int, float)) and total > 0 and 0 <= raw <= total:
                percentage = round(raw / total * 100, 2)
        obs['pull_percent'] = percentage  # null means not provable; not 0%.
        out['instances'].append(obs)
    return out


def _read_json(path: Path):
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, (dict, list)):
        raise ValueError(f'{path.name}: expected a JSON object or array')
    return obj


def _instances(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get('instances'), list):
        return value['instances']
    raise ValueError('Unrecognized Salad instances response; refusing to guess')


def _slug(value: str, label: str) -> str:
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,62}', value or ''):
        raise ValueError(f'Invalid {label}; use the exact Salad resource slug')
    return value


class SaladClient:
    def __init__(self, base: str, org: str, project: str, group: str, key: str):
        if not base.startswith('https://'):
            raise ValueError('SALAD_API_BASE_URL must use HTTPS')
        if not key:
            raise ValueError('SALAD_API_KEY is missing')
        self.base = base.rstrip('/')
        self.path = ('/organizations/' + _slug(org, 'org') + '/projects/' +
                     _slug(project, 'project') + '/containers/' + _slug(group, 'group'))
        self.key = key

    def request(self, method: str, suffix: str = '', data: dict | None = None):
        if method not in ('GET', 'PATCH'):
            raise ValueError('Only GET and explicitly approved PATCH supported')
        blob = None if data is None else json.dumps(data).encode()
        headers = {'Salad-Api-Key': self.key, 'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/merge-patch+json'
        url = self.base + self.path + suffix
        request = urllib.request.Request(url, headers=headers, data=blob, method=method)
        with urllib.request.urlopen(request, timeout=30) as reply:
            content = reply.read()
            return json.loads(content) if content else {}


def assert_safe_for_cache_update(group: dict, instances: list):
    if group.get('pending_change') is not False:
        raise ValueError('A provider change is pending/unknown; cache update refused')
    replicas = group.get('replicas')
    if type(replicas) is not int or replicas != 0:
        raise ValueError('Requested replicas must be exactly 0; cache update refused')
    if instances:
        raise ValueError('Salad still reports instance records; verify zero live instances before updating')
    counts = (group.get('current_state') or {}).get('instance_status_counts') or {}
    if not isinstance(counts, dict) or any(not isinstance(v, int) or v != 0 for v in counts.values()):
        raise ValueError('Instance state counts not zero; cache update refused')
    autoscaler = group.get('queue_autoscaler') or {}
    if autoscaler.get('min_replicas', 0) != 0:
        raise ValueError('Keep Warm/queue min replicas is not zero; cache update refused')


def run(args, client=None):
    if args.group_json:
        if args.apply:
            raise ValueError('--apply cannot be used with offline JSON')
        group = _read_json(args.group_json)
        if not isinstance(group, dict):
            raise ValueError('Group JSON must be an object')
        instances = _instances(_read_json(args.instances_json)) if args.instances_json else []
    else:
        if not args.group:
            raise ValueError('--group is required for live inspection (active name, not old .env default)')
        if client is None:
            client = SaladClient(
                os.environ.get('SALAD_API_BASE_URL', 'https://api.salad.com/api/public'),
                os.environ.get('SALAD_ORG', ''), os.environ.get('SALAD_PROJECT', ''),
                args.group, os.environ.get('SALAD_API_KEY', ''))
        group = client.request('GET')
        instances = _instances(client.request('GET', '/instances'))
    output = {'salad': instance_observation(group, instances)}
    if args.worker_log:
        output['worker_boot'] = extract_timeline(args.worker_log.read_text(encoding='utf-8'))
    # Never print provider raw data: env variables and keys can be embedded.
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if not args.apply:
        return 0
    if not args.confirm_idle_cache_update:
        raise ValueError('Required: --confirm-idle-cache-update (never implicit)')
    assert_safe_for_cache_update(group, instances)
    if (group.get('container') or {}).get('image_caching') is True:
        print('Image caching is already true. No PATCH needed.')
        return 0
    client.request('PATCH', data={'container': {'image_caching': True}})
    # Do not claim success until the provider reports it.
    after = client.request('GET')
    if (after.get('container') or {}).get('image_caching') is True and after.get('pending_change') is False:
        print('CONFIRMED: Salad reports image_caching=true for the idle group.')
    else:
        print('PATCH accepted; provider confirmation is pending. Re-run read-only audit.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', help='exact active Salad Container Group name')
    parser.add_argument('--group-json', type=Path, help='offline JSON from GET group API')
    parser.add_argument('--instances-json', type=Path, help='offline JSON from GET /instances')
    parser.add_argument('--worker-log', type=Path, help='worker startup stdout log')
    parser.add_argument('--apply', action='store_true', help='PATCH image_caching=true only if fully idle')
    parser.add_argument('--confirm-idle-cache-update', action='store_true',
                        help='explicitly authorize the idle Container Group configuration update')
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print('AUDIT REFUSED: ' + type(exc).__name__ + ': ' +
              (str(exc) if not isinstance(exc, urllib.error.HTTPError) else
               'Salad HTTP ' + str(exc.code)), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
