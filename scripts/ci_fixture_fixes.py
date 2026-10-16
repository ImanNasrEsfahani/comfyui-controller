#!/usr/bin/env python3
"""SHA-guarded historical CI fixture validator/repairer.

The two original repairs remain strictly SHA-locked. A later, reviewed
regression-test-only update adds the async Salad provider operation mock.
Never silently modify application code or relax authentication checks.
"""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile

BASE_BLOBS = {
    'tests/test_axis_04.py': 'fedc4ed639ff0be94b375b72d1816b2964763b2f',
    'tests/check_frontend_backend_upgrade.py': 'afcceb5944eb731f37e676b4ae4db9ac6c6df013',
}
AXIS_ANCHOR = '    "SALAD_LEGACY_QUEUE": "legacy-queue", "R2_ENDPOINT_URL": "https://storage.invalid",'
AXIS_EXTRA = ('    "SALAD_IMAGE": "ghcr.io/test/worker:offline-fixture",\n'
              '    "SALAD_CONTAINER_GROUP_NAME": "test-group",\n'
              '    "SALAD_CONTAINER_GROUP_DISPLAY_NAME": "Test Group",\n')
UPGRADE_REPLACEMENTS = {
    'self.client.get(f"/api/jobs/{local_id}/images")':
        'self.client.get(f"/api/jobs/{local_id}/images", headers=ADMIN)',
    'self.client.get(f"/api/jobs/{job[\'id\']}/draft")':
        'self.client.get(f"/api/jobs/{job[\'id\']}/draft", headers=ADMIN)',
    'self.client.get("/api/jobs")': 'self.client.get("/api/jobs", headers=ADMIN)',
    'self.client.get(f"/api/jobs/{local_id}")':
        'self.client.get(f"/api/jobs/{local_id}", headers=ADMIN)',
    'self.client.get("/api/salad/instances")':
        'self.client.get("/api/salad/instances", headers=ADMIN)',
}

# SHA256 of a fully reviewed replacement regression fixture. Exact bytes only.
# This new accepted state is TEST-ONLY and cannot be used to authorize changes
# to credentials, GitHub build instructions, or the Salad control plane.
REVIEWED_STOP_TEST_SHA256 = "14ab8d5f452547fead35069cf4e4e788a136e157c6b6b311f3c4e19515e2e66a"
UPGRADE_PATH = 'tests/check_frontend_backend_upgrade.py'


def blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def is_reviewed_stop_test(data: bytes) -> bool:
    if hashlib.sha256(data).hexdigest() != REVIEWED_STOP_TEST_SHA256:
        return False
    # An additional human-readable assertion documents what the new mock means.
    text = data.decode('utf-8')
    return ("provider.assert_called_once_with(\"POST\", \"/stop\", json_body=None)" in text
            and 'self.assertEqual(self.client.post("/api/salad/stop").status_code, 401)' in text
            and '"awaiting_confirmation"' in text)


def change_axis(source: str) -> str:
    if source.count(AXIS_ANCHOR) != 1:
        raise RuntimeError('Phase04 test fixture anchor missing/duplicated')
    return source.replace(AXIS_ANCHOR, AXIS_EXTRA + AXIS_ANCHOR, 1)


def change_upgrade(source: str) -> str:
    for old, new in UPGRADE_REPLACEMENTS.items():
        if source.count(old) < 1:
            raise RuntimeError('Legacy auth fixture anchor missing: ' + old)
        source = source.replace(old, new)
    return source


def expected_changes(data: dict[str, bytes]) -> dict[str, bytes]:
    result = {}
    for path, old in data.items():
        text = old.decode('utf-8')
        new = change_axis(text) if path.endswith('test_axis_04.py') else change_upgrade(text)
        compile(new, path, 'exec')
        result[path] = new.encode('utf-8')
    return result


def prepare(root: Path) -> tuple[dict[str, bytes], list[str]]:
    root = root.resolve()
    paths = {p: root / p for p in BASE_BLOBS}
    if any(not f.is_file() for f in paths.values()):
        raise RuntimeError('Complete checkout with both original tests is required')
    before = {p: f.read_bytes() for p, f in paths.items()}
    already, originals, reviewed = [], {}, {}
    for p, raw in before.items():
        if p == UPGRADE_PATH and is_reviewed_stop_test(raw):
            compile(raw, p, 'exec')
            already.append(p)
            reviewed[p] = raw
            continue
        if blob(raw) == BASE_BLOBS[p]:
            originals[p] = raw
        else:
            if p.endswith('test_axis_04.py'):
                if raw.count(AXIS_EXTRA.encode()) != 1:
                    raise RuntimeError('Unexpected test changes; refuse: ' + p)
                back = raw.replace(AXIS_EXTRA.encode(), b'', 1)
            else:
                back = raw
                for old, new in UPGRADE_REPLACEMENTS.items():
                    back = back.replace(new.encode(), old.encode())
            if blob(back) != BASE_BLOBS[p]:
                raise RuntimeError('Unexpected test changes; refuse: ' + p)
            already.append(p)
            originals[p] = back
    changed = expected_changes(originals)
    for p in already:
        if p not in reviewed and before[p] != changed[p]:
            raise RuntimeError('Patched content diverged: ' + p)
    changed.update(reviewed)
    return changed, already


def run(root: Path, *, apply: bool = False, check: bool = False) -> int:
    if check and apply:
        raise RuntimeError('--check and --apply are mutually exclusive')
    changed, already = prepare(root)
    required = set(BASE_BLOBS)
    if check:
        if set(already) != required:
            raise RuntimeError('Historical CI fixtures are not yet patched: ' + str(sorted(required-set(already))))
        print('CI FIXTURE CHECK PASS: two precisely reviewed test fixtures installed')
        return 0
    if not apply:
        print('DRY RUN OK: historical CI fixture changes prepared; originals unchanged')
        return 0
    for p, data in changed.items():
        target = root / p
        if target.read_bytes() == data:
            continue
        fd, name = tempfile.mkstemp(prefix='.ci-fixture-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    print('PATCHED historical test fixtures; no application code changed.')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true')
    group.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    try:
        return run(args.repo.resolve(), apply=args.apply, check=args.check)
    except (OSError, RuntimeError, SyntaxError, UnicodeError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
