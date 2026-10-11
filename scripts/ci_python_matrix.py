#!/usr/bin/env python3
"""Run every repository Python test file in a separate interpreter process.

Historical phases modify sys.modules/app.db at import time. A shared interpreter
can leak their fixtures into unrelated phases and conceal the real first failure.
This runner NEVER skips or suppresses tests; exit code nonzero if any file fails.
It is not a replacement for an integrated, single-process suite, which remains
an independent release gate once the historical fixtures are repaired.
"""
from __future__ import annotations
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def cases(root: Path) -> list[Path]:
    testdir = root / 'tests'
    return sorted(testdir.glob('test_*.py')) + sorted(testdir.glob('check_*.py'))


def run(root: Path, *, files: list[Path] | None = None, python: str = sys.executable) -> int:
    root = root.resolve()
    chosen = files if files is not None else cases(root)
    if not chosen:
        print('ERROR: no Python test modules found', file=sys.stderr)
        return 2
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root / 'backend') + os.pathsep + str(root / 'tests') + (
        os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    bad: list[str] = []
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
        print('=== START ' + label + ' ===', flush=True)
        cp = subprocess.run([python, '-m', 'pytest', '-q', '--tb=short', '--show-capture=no', label],
                            cwd=root, env=env, check=False)
        print('=== ' + ('PASS' if cp.returncode == 0 else 'FAIL') + ' ' + label +
              f' (exit {cp.returncode}) ===', flush=True)
        if cp.returncode:
            bad.append(label)
    print(f'PYTHON FILE SUMMARY: passed={len(chosen)-len(bad)} failed={len(bad)} total={len(chosen)}',flush=True)
    for p in bad:
        print('FAILED FILE: ' + p,flush=True)
    return 1 if bad else 0


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path('.'))
    parser.add_argument('--test-file',action='append',default=[],help='Repo-relative test file for focused checks')
    args=parser.parse_args(argv)
    return run(args.repo,files=[Path(x) for x in args.test_file] if args.test_file else None)

if __name__ == '__main__':
    raise SystemExit(main())
