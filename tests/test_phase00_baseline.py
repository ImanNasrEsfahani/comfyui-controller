"""Offline-only Phase 00 test harness. No access to production or GPU."""
import importlib.util
import sqlite3
from pathlib import Path
from contextlib import closing
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]

def load(name, file):
    spec=importlib.util.spec_from_file_location(name, file)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

audit=load('phase00_db_audit', ROOT/'scripts'/'phase00_db_audit.py')
r2=load('phase00_r2_count', ROOT/'scripts'/'phase00_r2_count.py') if importlib.util.find_spec('boto3') else None


def synthetic_fixture(path):
    """A deliberately SMALL fixture: it does not stand in for the production schema."""
    with closing(sqlite3.connect(path)) as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE workflows (id TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE jobs (id TEXT PRIMARY KEY, owner TEXT, workflow_id TEXT,
                            FOREIGN KEY(workflow_id) REFERENCES workflows(id));
        CREATE TABLE input_assets (asset_id TEXT PRIMARY KEY, storage_key TEXT NOT NULL UNIQUE);
        CREATE TABLE job_assets (asset_id TEXT PRIMARY KEY, job_id TEXT NOT NULL);
        CREATE INDEX idx_jobs_owner ON jobs(owner);
        CREATE TRIGGER jobs_no_empty_id BEFORE INSERT ON jobs WHEN NEW.id=''
        BEGIN SELECT RAISE(ABORT,'empty id'); END;
        INSERT INTO workflows VALUES ('wf-test', 'Synthetic Workflow');
        INSERT INTO jobs VALUES ('j-a',NULL,'wf-test');
        INSERT INTO jobs VALUES ('j-b','legacy','wf-test');
        INSERT INTO input_assets VALUES ('a-1','inputs/dummy/image.png');
        ''')

class BaselineTests(unittest.TestCase):
    def test_sqlite_restore_exact_schema_counts_indexes_triggers(self):
        with TemporaryDirectory(prefix='phase00-fixture-') as tmp:
            p=Path(tmp)/'synthetic.sqlite3'
            synthetic_fixture(p)
            result=audit.restore_drill(p)
            self.assertEqual(result['outcome'],'PASS',result)
            with closing(audit.open_read_only(p)) as c:
                data=audit.snapshot(c)
                self.assertEqual(data['owner_gaps']['jobs']['owner'],1)
                self.assertEqual(data['integrity_check'],'ok')
                self.assertIn('jobs',data['table_counts'])
                self.assertEqual(data['unexpected_or_missing_tables'] != [], True)

    def test_read_only_connection_rejects_writes(self):
        with TemporaryDirectory(prefix='phase00-fixture-') as tmp:
            p=Path(tmp)/'synthetic.sqlite3';synthetic_fixture(p)
            with closing(audit.open_read_only(p)) as c:
                with self.assertRaises(sqlite3.OperationalError):
                    c.execute("INSERT INTO jobs(id) VALUES ('unapproved')")

    def test_r2_count_pagination_without_reading_objects(self):
        class FakePaginator:
            def paginate(self, **kwargs):
                return [{'Contents':[{'Key':'inputs/x'},{'Key':'outputs/a'}]},
                        {'Contents':[{'Key':'misc/y'}]}]
        class FakeClient:
            def get_paginator(self, op):
                if op!='list_objects_v2':raise AssertionError('Unexpected S3 operation')
                return FakePaginator()
        if r2 is None:
            self.skipTest('boto3 absent in offline harness')
        result=r2.count_prefixes(FakeClient(),'mock-bucket')
        self.assertEqual(result['total_objects'],3)
        self.assertEqual(result['prefix_counts'],{'inputs/':1,'outputs/':1,'other':1})

if __name__=='__main__':
    unittest.main()
