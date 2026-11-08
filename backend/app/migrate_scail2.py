#!/usr/bin/env python3
"""Create the SCAIL2 private lane tables; always back up SQLite first.
Run from the project root: python3 scripts/migrate_scail2.py
"""
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone


def main():
    path = Path(os.environ.get('DB_PATH', './data/controller.db')).resolve()
    if not path.exists():
        sys.exit(f'Existing Controller database not found: {path}; set DB_PATH')
    if path.is_symlink():
        sys.exit('Refusing symlink database path')
    backup = path.with_name(path.name + '.pre-scail2-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.bak')
    src = sqlite3.connect(f'file:{path}?mode=rw', uri=True, timeout=30)
    try:
        dest = sqlite3.connect(backup)
        try:src.backup(dest)
        finally: dest.close()
        src.execute('BEGIN IMMEDIATE')
        src.execute('''CREATE TABLE IF NOT EXISTS cr_assets(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('video','reference')),
            r2_key TEXT NOT NULL UNIQUE, mime TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL, duration REAL, fps REAL,
            created_at TEXT NOT NULL)''')
        src.execute('''CREATE TABLE IF NOT EXISTS cr_jobs(
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, source_video_id TEXT NOT NULL,
            reference_image_id TEXT NOT NULL, client_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
            prompt TEXT NOT NULL, detect_prompt TEXT NOT NULL, quality TEXT NOT NULL,
            steps INTEGER NOT NULL, seed INTEGER NOT NULL, preserve_audio INTEGER NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            lease_hash TEXT, lease_until REAL, worker_id TEXT, output_key TEXT, output_size INTEGER,
            error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            started_at TEXT, finished_at TEXT,
            UNIQUE(owner_id, client_key), FOREIGN KEY(source_video_id) REFERENCES cr_assets(id),
            FOREIGN KEY(reference_image_id) REFERENCES cr_assets(id))''')
        src.execute('''CREATE TABLE IF NOT EXISTS cr_runtime(
            id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL, ready INTEGER NOT NULL,
            seen_at REAL NOT NULL)''')
        src.execute('CREATE INDEX IF NOT EXISTS cr_jobs_owner_created ON cr_jobs(owner_id,created_at)')
        src.execute('CREATE INDEX IF NOT EXISTS cr_jobs_state_created ON cr_jobs(state,created_at)')
        src.commit()
        print('Migration complete. Backed up DB to:', backup)
    except Exception:
        src.rollback()
        print('Migration failed; backup:', backup, file=sys.stderr)
        raise
    finally:src.close()

if __name__=='__main__':main()
