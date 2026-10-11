#!/usr/bin/env python3
"""Deterministic, fail-closed, per-module Python regression runner.

This is the whole repository's historical *unit regression* suite, not proof of
cross-module integration or production readiness. It runs ALL discovered tests
in fresh Python processes, preserves pytest exit codes, records JUnit counts,
and produces an optional JSON manifest for review. No test file is silently
excluded, and missing/empty/invalid JUnit is failure, not a PASS.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


def cases(root: Path) -> list[Path]:
    testdir = root / 'tests'
    return sorted(testdir.glob('test_*.py')) + sorted(testdir.glob('check_*.py'))


def junit_totals(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    if root.tag == 'testsuite':
        suites = [root]
    elif root.tag == 'testsuites':
        suites = list(root.findall('testsuite'))
    else:
        raise ValueError('Unexpected JUnit XML root')
    if not suites:
        raise ValueError('No JUnit test suites reported')
    counts = {key: sum(int(s.get(key, '0')) for s in suites)
              for key in ('tests', 'failures', 'errors', 'skipped')}
    if counts['tests'] <= 0:
        raise ValueError('An empty pytest collection is not a successful test run')
    if counts['failures'] + counts['errors'] + counts['skipped'] > counts['tests']:
        raise ValueError('Inconsistent JUnit totals')
    return counts


def run(root: Path, *, files: list[Path] | None = None,
        python: str = sys.executable, report: Path | None = None,
        timeout: int = 180) -> int:
    root = root.resolve()
    chosen = files if files is not None else cases(root)
    if not chosen:
        print('ERROR: no Python test modules found', file=sys.stderr)
        return 2
    labels: list[str] = []
    for file in chosen:
        p = ((root / file) if not file.is_absolute() else file).resolve()
        try:
            label = str(p.relative_to(root))
        except ValueError:
            print('ERROR: test path outside checkout', file=sys.stderr)
            return 2
        if not p.is_file() or not label.startswith('tests/') or not label.endswith('.py'):
            print('ERROR: missing/unexpected Python test path: ' + label, file=sys.stderr)
            return 2
        if label in labels:
            print('ERROR: duplicate Python test file: ' + label, file=sys.stderr)
            return 2
        labels.append(label)
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [
        str(root / 'backend'), str(root / 'tests'), env.get('PYTHONPATH', '')]))
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    summary: list[dict] = []
    with tempfile.TemporaryDirectory(prefix='comfy-ci-junit-') as tmp:
        for i, label in enumerate(labels):
            xml = Path(tmp) / f'module-{i:03}.xml'
            command = [python, '-m', 'pytest', '-q', '--tb=short',
                       '--show-capture=no', '--junitxml', str(xml), label]
            print('=== START ' + label + ' ===', flush=True)
            start = time.monotonic()
            try:
                completed = subprocess.run(command, cwd=root, env=env,
                                           check=False, timeout=timeout)
                code = completed.returncode
            except subprocess.TimeoutExpired:
                print('ERROR: test timed out: ' + label, flush=True)
                code = 124
            counts = None
            if xml.is_file():
                try:
                    counts = junit_totals(xml)
                except (ET.ParseError, ValueError, OSError) as exc:
                    print('ERROR: invalid JUnit for ' + label + ': ' + str(exc), flush=True)
            passed = code == 0 and counts is not None and not (counts['errors'] or counts['failures'])
            duration = round(time.monotonic() - start, 3)
            summary.append({'file': label, 'status': 'PASS' if passed else 'FAIL',
                            'exit_code': code, 'seconds': duration,
                            'counts': counts})
            print(f'=== {"PASS" if passed else "FAIL"} {label} (exit {code}, {duration}s) ===', flush=True)
    failures = [s['file'] for s in summary if s['status'] != 'PASS']
    totals = {key: sum((s['counts'] or {}).get(key, 0) for s in summary)
              for key in ('tests', 'failures', 'errors', 'skipped')}
    output = {'format': 'comfyui-ci-python-v2', 'isolation': 'per-test-file',
              'environment': 'offline', 'status': 'PASS' if not failures else 'FAIL',
              'discovered_files': len(labels), 'executed_files': len(summary),
              'successful_files': len(summary) - len(failures),
              'failed_files': failures, 'totals': totals, 'files': summary,
              'warning': 'Per-file tests do NOT verify live Router, R2, provider or GPU integration.'}
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'PYTHON FILE SUMMARY: passed={len(labels)-len(failures)} failed={len(failures)} total={len(labels)}')
    print(f'PYTHON TEST TOTALS: {json.dumps(totals, sort_keys=True)}')
    for label in failures:
        print('FAILED FILE: ' + label)
    if totals['skipped']:
        print('WARNING: skipped tests are recorded, not misreported as executed')
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--test-file', action='append', default=[],
                        help='Repo-relative test file for focused checks')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    return run(args.repo, files=[Path(x) for x in args.test_file] if args.test_file else None,
               report=args.report, timeout=args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())
