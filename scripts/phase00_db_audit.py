#!/usr/bin/env python3
"""Phase 00: offline SQLite copy inspection and non-destructive backup/restore drill.

Never connect this script to the production SQLite volume. Provide an isolated
copy, made with SQLite's online backup API by a trusted operator, not a raw
file-only copy of a live WAL database. Reports contain schema and counts only.
"""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

EXPECTED_TABLES = (
    'workflows', 'jobs', 'controller_settings', 'job_attempts', 'job_assets',
    'input_assets', 'job_events', 'job_progress', 'job_progress_events',
    'instance_observations', 'instance_sessions', 'instance_cost_periods',
    'instance_stage_events', 'instance_operations',
)


def qident(s):
    return '"' + s.replace('"', '""') + '"'


def open_read_only(db_file):
    db_file = Path(db_file).expanduser().resolve(strict=True)
    if not db_file.is_file():
        raise ValueError('SQLite copy must be a regular file')
    uri = db_file.as_uri() + '?mode=ro'
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def snapshot(db):
    objects = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    tables = [row['name'] for row in objects if row['type'] == 'table']
    columns, indexes, foreign_keys, counts = {}, {}, {}, {}
    for table in tables:
        columns[table] = [dict(r) for r in db.execute('PRAGMA table_info(' + qident(table) + ')')]
        indexes[table] = [dict(r) for r in db.execute('PRAGMA index_list(' + qident(table) + ')')]
        foreign_keys[table] = [dict(r) for r in db.execute('PRAGMA foreign_key_list(' + qident(table) + ')')]
        counts[table] = db.execute('SELECT count(*) FROM ' + qident(table)).fetchone()[0]
    owner_gaps = {}
    for name in ('jobs', 'input_assets', 'job_assets', 'workflows'):
        if name not in tables:
            owner_gaps[name] = 'table absent'
            continue
        fields = {c['name'] for c in columns[name]}
        owner_gaps[name] = {}
        for f in ('owner_user_id', 'owner'):
            if f in fields:
                owner_gaps[name][f] = db.execute('SELECT count(*) FROM '+qident(name)+' WHERE '+qident(f)+' IS NULL OR TRIM('+qident(f)+")=''" ).fetchone()[0]
            else:
                owner_gaps[name][f] = 'column absent'
    schema_objects = [dict(row) for row in objects]
    schema_str = json.dumps(schema_objects, ensure_ascii=False, sort_keys=True)
    return {
        'schema_sha256': hashlib.sha256(schema_str.encode('utf-8')).hexdigest(),
        'schema_objects': schema_objects, 'table_counts': counts,
        'columns': columns, 'indexes': indexes, 'foreign_keys': foreign_keys,
        'owner_gaps': owner_gaps,
        'unexpected_or_missing_tables': sorted(set(EXPECTED_TABLES) - set(tables)),
        'pragmas': {'user_version': db.execute('PRAGMA user_version').fetchone()[0],
                    'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0],
                    'foreign_keys': db.execute('PRAGMA foreign_keys').fetchone()[0]},
        'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0],
    }


def restore_drill(copy_db):
    """Back up isolated DB COPY into memory, restore into temporary second file."""
    with closing(open_read_only(copy_db)) as original:
        with closing(sqlite3.connect(':memory:')) as ephemeral:
            ephemeral.row_factory = sqlite3.Row
            original.backup(ephemeral)
            a = snapshot(ephemeral)
            with TemporaryDirectory(prefix='phase00-restore-') as directory:
                restored_path = Path(directory)/'restored.sqlite3'
                with closing(sqlite3.connect(str(restored_path))) as restored:
                    ephemeral.backup(restored)
                with closing(open_read_only(restored_path)) as restored_ro:
                    b = snapshot(restored_ro)
    checks = {
        'schema_sha256_equal': a['schema_sha256'] == b['schema_sha256'],
        'table_counts_equal': a['table_counts'] == b['table_counts'],
        'columns_equal': a['columns'] == b['columns'],
        'indexes_equal': a['indexes'] == b['indexes'],
        'triggers_equal': [x for x in a['schema_objects'] if x['type']=='trigger'] ==
                          [x for x in b['schema_objects'] if x['type']=='trigger'],
        'restored_integrity_ok': b['integrity_check'] == 'ok',
    }
    return {'outcome': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
            'table_counts': b['table_counts'], 'schema_sha256': b['schema_sha256'],
            'scope': 'isolated SQLite COPY only (NOT production restore)'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database-copy', required=True, help='Path to a trusted isolated SQLite COPY, never the live volume')
    p.add_argument('--out', required=True, help='JSON evidence file path')
    p.add_argument('--restore-drill', action='store_true')
    p.add_argument('--acknowledge-isolated-copy', action='store_true', required=True)
    args = p.parse_args()
    source=Path(args.database_copy).expanduser().resolve(strict=True)
    if any(part in source.parts for part in ('docker', 'overlay2', 'containers', 'volumes')):
        p.error('Refusing a path resembling Docker-managed production storage; use an offline staging COPY')
    with closing(open_read_only(source)) as db:
        data = snapshot(db)
    if args.restore_drill:
        data['restore_drill'] = restore_drill(source)
    target=Path(args.out).resolve()
    if target == source:
        p.error('Output must not replace source database')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'database': 'isolated copy', 'tables': len(data['table_counts']),
                      'integrity_check': data['integrity_check'],
                      'restore_outcome': data.get('restore_drill',{}).get('outcome','NOT RUN'),
                      'report': str(target)},ensure_ascii=False))


if __name__ == '__main__':
    main()
