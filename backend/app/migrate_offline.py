#!/usr/bin/env python3
"""Controlled production SQLite snapshot, isolated schema migration, activation, and restore.

This script runs INSIDE a one-shot Backend container while app services are stopped.
The backup folder is mounted as /backup; the live SQLite volume as /app/data.
It must never perform network operations.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid

PHASES = ('01', '02', '05', '06', '07', '08', '09', '10', '11', '12', '13')
TABLES = ('jobs', 'input_assets', 'job_assets')
BACKUP = Path('/backup')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def counts(conn):
    return {name: conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in TABLES}


def verify(conn):
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    fk = list(conn.execute('PRAGMA foreign_key_check'))
    if integrity != 'ok' or fk:
        raise RuntimeError(f'SQLite validation failed: integrity={integrity!r}, foreign_keys={len(fk)}')
    return counts(conn)


def backup_copy(src: Path, dest: Path):
    if dest.exists():
        raise RuntimeError(f'Refusing to overwrite existing backup: {dest}')
    from urllib.parse import quote
    uri = 'file:' + quote(src.as_posix(), safe='/') + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as input_db:
        with sqlite3.connect(dest) as output_db:
            input_db.backup(output_db)
    dest.chmod(0o600)
    with sqlite3.connect(dest) as v:
        return verify(v)


def ensure_env():
    if os.environ.get('DB_PATH') != '/app/data/controller.db':
        raise RuntimeError('DB_PATH must be the expected mounted SQLite volume: /app/data/controller.db')
    if not BACKUP.is_dir():
        raise RuntimeError('Expected /backup bind mount')
    live = Path(os.environ['DB_PATH'])
    if not live.is_file():
        raise RuntimeError('Production SQLite does not exist; refusing to initialize a new one')
    return live


def snapshot():
    live = ensure_env()
    saved = BACKUP / 'controller-original.sqlite3'
    result = backup_copy(live, saved)
    print('OFFLINE SNAPSHOT PASS; counts:', result, 'sha256:', sha256(saved), flush=True)


def migrate():
    ensure_env()
    original = BACKUP / 'controller-original.sqlite3'
    target = BACKUP / 'controller-migrated.sqlite3'
    if not original.is_file() or target.exists():
        raise RuntimeError('Expected original backup and absent migrated target')
    baseline_hash = sha256(original)
    shutil.copyfile(original, target)
    target.chmod(0o600)
    try:
        with sqlite3.connect(target) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            before = verify(conn)
            for phase in PHASES:
                mod = importlib.import_module(f'app.migrations.phase{phase}')
                value = mod.migrate(conn)
                print('MIGRATION', phase, 'PASS', type(value).__name__, flush=True)
            after = verify(conn)
            if before != after:
                raise RuntimeError(f'Existing record count changed: {before} -> {after}')
            if conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()[0] != 1:
                raise RuntimeError('Schema migration tracking missing')
            rows = [v[0] for v in conn.execute('SELECT revision FROM schema_migrations ORDER BY revision')]
            for tab in ('jobs','input_assets','job_assets'):
                count = conn.execute(f'SELECT COUNT(*) FROM {tab} WHERE owner_user_id IS NULL').fetchone()[0]
                print('UNCLAIMED',tab,count,flush=True)
            print('REVISIONS', len(rows), rows, flush=True)
        if sha256(original) != baseline_hash:
            raise RuntimeError('Backup was modified during migration')
        print('OFFLINE MIGRATION PASS; unchanged row counts:', after, 'migrated SHA256:', sha256(target), flush=True)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def atomic_swap(candidate: Path):
    live = ensure_env()
    if not candidate.is_file():
        raise RuntimeError(f'Candidate DB file missing: {candidate}')
    with sqlite3.connect(candidate) as check:
        expected = verify(check)
    original = BACKUP / 'controller-original.sqlite3'
    if not original.is_file():
        raise RuntimeError('Original verified backup missing')
    if candidate != original:
        with sqlite3.connect(original) as check:
            before = verify(check)
        if expected != before:
            raise RuntimeError('Data count mismatch; refusing database activation')
    if not live.parent.is_dir():
        raise RuntimeError('Database volume mount not found')
    tmp = live.parent / ('.controller-deploy-' + str(uuid.uuid4()))
    try:
        with candidate.open('rb') as fin, tmp.open('xb') as fout:
            shutil.copyfileobj(fin, fout)
            fout.flush()
            os.fsync(fout.fileno())
        tmp.chmod(0o600)
        with sqlite3.connect(tmp) as check:
            verify(check)
        # Save the physical legacy database and any WAL/SHM sidecars in addition to the
        # earlier normalized SQLite snapshot. No process may be attached at this point.
        if candidate != original:
            for suffix in ('', '-wal', '-shm'):
                p = Path(str(live) + suffix)
                if p.exists():
                    physical_backup = BACKUP / ('controller-physical-before' + suffix)
                    if physical_backup.exists():
                        raise RuntimeError('Physical rollback backup already exists: '+str(physical_backup))
                    shutil.copy2(p, physical_backup)
        for suffix in ('-wal', '-shm'):
            Path(str(live) + suffix).unlink(missing_ok=True)
        os.replace(tmp, live)
        dirfd = os.open(str(live.parent), os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        tmp.unlink(missing_ok=True)
    with sqlite3.connect(live) as check:
        result = verify(check)
    print('DATABASE ACTIVATED PASS; row counts:', result, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['snapshot','migrate','install','restore'])
    args = parser.parse_args()
    if args.action == 'snapshot': snapshot()
    elif args.action == 'migrate': migrate()
    elif args.action == 'install': atomic_swap(BACKUP/'controller-migrated.sqlite3')
    else: atomic_swap(BACKUP/'controller-original.sqlite3')

if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        print('DATABASE DEPLOYMENT STOP:', type(exc).__name__, str(exc), file=sys.stderr)
        raise
