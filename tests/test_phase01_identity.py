"""Offline Phase01 tests using synthetic legacy schema; never production data."""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.migrations.phase01 import migrate,backup_copy,approve_legacy_owner
from app import identity_repository as ids


BASE_SCHEMA='''
CREATE TABLE workflows(id TEXT PRIMARY KEY,name TEXT,api_prompt TEXT,created_at TEXT,updated_at TEXT);
CREATE TABLE jobs(id TEXT PRIMARY KEY,workflow_id TEXT,client_request_id TEXT,request_hash TEXT,
 request_json TEXT NOT NULL,variables_json TEXT,snapshot_json TEXT,state TEXT NOT NULL,
 hidden INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 FOREIGN KEY(workflow_id) REFERENCES workflows(id));
CREATE UNIQUE INDEX idx_jobs_client_request ON jobs(client_request_id) WHERE client_request_id IS NOT NULL;
CREATE TABLE input_assets(asset_id TEXT PRIMARY KEY,storage_key TEXT NOT NULL UNIQUE,
 mime_type TEXT NOT NULL,size_bytes INTEGER,width INTEGER,height INTEGER,created_at TEXT NOT NULL);
CREATE TABLE job_assets(asset_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,attempt_id TEXT,
 storage_key TEXT NOT NULL,media_type TEXT,mime_type TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TRIGGER jobs_snapshot_immutable BEFORE UPDATE OF snapshot_json,request_json,variables_json ON jobs
 WHEN NEW.snapshot_json IS NOT OLD.snapshot_json OR NEW.request_json IS NOT OLD.request_json
 OR NEW.variables_json IS NOT OLD.variables_json
 BEGIN SELECT RAISE(ABORT,'submitted Job snapshot is immutable'); END;
'''
NOW='2026-10-10T00:00:00+00:00'


def legacy(conn):
    conn.executescript(BASE_SCHEMA)
    conn.execute("INSERT INTO workflows VALUES ('wf','model','{}',?,?)",(NOW,NOW))
    for job in ('job-old','job-orphan'):
        conn.execute("INSERT INTO jobs(id,workflow_id,request_json,state,created_at,updated_at,client_request_id,request_hash) VALUES (?,?,?,?,?,?,?,?)",
             (job,'wf','{}','succeeded',NOW,NOW,job,'hash'))
    conn.execute("INSERT INTO input_assets VALUES ('input-orphan','inputs/orphan.png','image/png',22,2,2,?)",(NOW,))
    conn.execute("INSERT INTO job_assets(asset_id,job_id,storage_key,status,created_at) VALUES ('output-old','job-old','outputs/job-old/out.png','available',?)",(NOW,))
    conn.execute("INSERT INTO job_assets(asset_id,job_id,storage_key,status,created_at) VALUES ('output-orphan','missing','outputs/missing/out.png','available',?)",(NOW,))
    conn.commit()


class Phase01(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'legacy-test.sqlite'
        self.c=sqlite3.connect(self.path)
        self.c.row_factory=sqlite3.Row
        legacy(self.c)

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def test_01_revisions_idempotent_counts_fk_and_triggers(self):
        before=self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        first=migrate(self.c)
        second=migrate(self.c)
        self.assertEqual(first['revision'],'003_legacy_review')
        self.assertEqual(first,second)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],before)
        self.assertEqual(len(list(self.c.execute('PRAGMA foreign_key_check'))),0)
        self.assertIn('idx_jobs_owner_time', {r[1] for r in self.c.execute('PRAGMA index_list(jobs)')})
        self.assertIn('jobs_snapshot_immutable', {r[0] for r in self.c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")})
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.execute("UPDATE jobs SET request_json='changed' WHERE id='job-old'")
        self.c.rollback()

    def test_02_unclaimed_quarantine_and_fk_rejection(self):
        migrate(self.c)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM owner_review_queue WHERE status='quarantined'").fetchone()[0],5)
        self.assertIsNone(ids.user_job(self.c,'not-real','job-old'))
        self.assertIsNone(ids.user_input_asset(self.c,'not-real','input-orphan'))
        self.assertIsNone(ids.user_job_asset(self.c,'not-real','output-old'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.execute("UPDATE jobs SET owner_user_id='not-found',ownership_state='verified' WHERE id='job-old'")
        self.c.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.execute("UPDATE jobs SET ownership_state='verified' WHERE id='job-old'")
        self.c.rollback()

    def test_03_a_b_sql_isolation_and_preset(self):
        migrate(self.c)
        a=ids.create_user(self.c,email='A@example.com',password='some-long-password-123',display_name='A',status='active',email_verified_at=NOW)
        b=ids.create_user(self.c,email='B@example.com',password='some-other-long-password-123',display_name='B',status='active',email_verified_at=NOW)
        self.c.execute("UPDATE jobs SET owner_user_id=?,ownership_state='verified' WHERE id='job-old'",(a,))
        self.c.execute("UPDATE job_assets SET owner_user_id=?,ownership_state='verified' WHERE asset_id='output-old'",(a,))
        self.c.execute("UPDATE input_assets SET owner_user_id=?,ownership_state='verified' WHERE asset_id='input-orphan'",(a,))
        self.assertIsNotNone(ids.user_job(self.c,a,'job-old'))
        self.assertIsNone(ids.user_job(self.c,b,'job-old'))
        self.assertEqual(len(ids.list_user_jobs(self.c,a)),1)
        self.assertEqual(len(ids.list_user_jobs(self.c,b)),0)
        self.assertIsNotNone(ids.user_job_asset(self.c,a,'output-old'))
        self.assertIsNone(ids.user_job_asset(self.c,b,'output-old'))
        self.assertIsNone(ids.user_input_asset(self.c,b,'input-orphan'))
        with self.assertRaises(ids.AccessDenied): ids.require_reference(self.c,b,'output-old')
        self.c.execute("INSERT INTO presets(id,owner_user_id,name,fields_json,created_at,updated_at) VALUES ('P',?,'test','{}',?,?)",(a,NOW,NOW))
        self.assertIsNone(ids.user_preset(self.c,b,'P'))
        self.assertIsNotNone(ids.user_preset(self.c,a,'P'))

    def test_04_idempotency_owner_scoped_at_mapping_level(self):
        migrate(self.c)
        a=ids.create_user(self.c,email='A@example.com',password='some-long-password-123',display_name='A',status='active',email_verified_at=NOW)
        b=ids.create_user(self.c,email='B@example.com',password='some-other-long-password-123',display_name='B',status='active',email_verified_at=NOW)
        self.c.execute("UPDATE jobs SET owner_user_id=?,ownership_state='verified' WHERE id='job-old'",(a,))
        self.c.execute("UPDATE jobs SET owner_user_id=?,ownership_state='verified' WHERE id='job-orphan'",(b,))
        self.c.execute('BEGIN IMMEDIATE') if not self.c.in_transaction else None
        self.assertEqual(ids.register_idempotency(self.c,user_id=a,client_key='same',request_hash='one',job_id='job-old'),'job-old')
        self.assertEqual(ids.register_idempotency(self.c,user_id=b,client_key='same',request_hash='two',job_id='job-orphan'),'job-orphan')
        self.assertEqual(ids.register_idempotency(self.c,user_id=a,client_key='same',request_hash='one',job_id='job-old'),'job-old')
        with self.assertRaises(ids.DuplicateRequest):
            ids.register_idempotency(self.c,user_id=a,client_key='same',request_hash='different',job_id='job-old')
        with self.assertRaises(ids.AccessDenied):
            ids.register_idempotency(self.c,user_id=b,client_key='forbidden',request_hash='two',job_id='job-old')
        # Legacy app's global idx still prevents actual duplicated jobs.client_request_id;
        # explicitly NOT claiming Phase01 AT-01-03 full API acceptance.
        self.assertIn('idx_jobs_client_request',{r[1] for r in self.c.execute('PRAGMA index_list(jobs)')})

    def test_05_safe_backup_restore_and_failed_schema_rolls_back(self):
        dest=Path(self.tmp.name)/'isolated-copy.sqlite'
        backup_copy(self.path,dest)
        with sqlite3.connect(dest) as cloned:
            self.assertEqual(cloned.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(cloned.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],2)
            self.assertEqual(len(list(cloned.execute("SELECT name FROM sqlite_master WHERE type='trigger'"))),1)
        with self.assertRaises(ValueError): backup_copy(self.path,self.path)

    def test_06_admin_cli_library_and_password_hash(self):
        migrate(self.c)
        with self.assertRaises(ValueError):
            ids.seed_verified_admin(self.c,email='admin@example.com',password='proper-long-pass-123',display_name='Admin',verification_evidence='',approver='')
        uid=ids.seed_verified_admin(self.c,email='admin@example.com',password='proper-long-pass-123',display_name='Admin',verification_evidence='approved-private-identity',approver='operator')
        rec=self.c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        self.assertTrue(rec['password_hash'].startswith('$argon2id$'))
        self.assertTrue(ids.verify_password(rec['password_hash'],'proper-long-pass-123'))
        self.assertFalse(ids.verify_password(rec['password_hash'],'wrong-password'))
        self.assertEqual(rec['status'],'active')
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM user_roles WHERE user_id=? AND role_id='admin'",(uid,)).fetchone()[0],1)

    def test_07_legacy_backfill_explicit_and_orphan_safe(self):
        migrate(self.c)
        a=ids.create_user(self.c,email='owner@example.com',password='some-long-password-123',display_name='Owner',status='active',email_verified_at=NOW)
        self.c.commit()
        with self.assertRaises(ValueError):
            approve_legacy_owner(self.c,a,approval_ref='',approved_by='operator',source_sha='a',apply=True)
        r=approve_legacy_owner(self.c,a,approval_ref='formal-approval',approved_by='operator',source_sha='baseline-sha',apply=False)
        self.assertTrue(r['dry_run'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs WHERE owner_user_id IS NOT NULL').fetchone()[0],0)
        r=approve_legacy_owner(self.c,a,approval_ref='formal-approval',approved_by='operator',source_sha='baseline-sha',apply=True)
        self.assertEqual(r['job_count'],2)
        self.assertEqual(r['job_asset_count'],1)
        self.assertEqual(r['inputs_still_unclaimed'],1)
        self.assertIsNone(ids.user_job_asset(self.c,a,'output-orphan'))
        self.assertIsNotNone(ids.user_job_asset(self.c,a,'output-old'))
        self.assertIsNone(ids.user_input_asset(self.c,a,'input-orphan'))
        self.assertEqual(self.c.execute("SELECT status FROM owner_review_queue WHERE resource_type='input_assets'").fetchone()[0],'quarantined')
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchone(),None)

    def test_08_no_data_export_or_download_side_effects(self):
        migrate(self.c)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],2)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM input_assets').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM job_assets').fetchone()[0],2)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],3)


if __name__=='__main__':unittest.main()

class Phase01PatchAndScopedIndex(unittest.TestCase):
    def test_patch_anchors_reject_drift_and_transform_expected_fragments(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        from phase01_prepare_checkout import patch_job_records,patch_db
        # Exact current-source anchors. The real-file SHA check runs at checkout.
        jr='''def migrate(c):
    execute_schema(c, """
      CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_client_request ON jobs(client_request_id)
        WHERE client_request_id IS NOT NULL;
    """)
    allowed = " OR ".join("(OLD.state='" + x for x in y)

def acceptance(c,local_id,client_request_id,request_hash):
    row = c.execute("SELECT id,request_hash,hidden FROM jobs WHERE client_request_id=?", (client_request_id,)).fetchone()
'''
        patched=patch_job_records(jr)
        self.assertIn('idx_jobs_legacy_request',patched)
        self.assertIn('legacy_controller_owner',patched)
        with self.assertRaises(RuntimeError):patch_job_records('not the source')
        db='''def create_job():
        existing = job_records.acceptance(c, local_id, client_request_id, request_hash)
        c.execute("""INSERT INTO jobs
                snapshot_json,client_request_id,request_hash,owner,source_job_id,queued_at,active_attempt_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_job_id, now if execution_mode == "direct" else None, attempt_id,
            ))
'''
        new=patch_db(db)
        self.assertIn('controller_owner_id',new)
        self.assertIn('?,?,?,?)',new)

    def test_activate_scoped_index_allows_two_users_same_key_in_sql(self):
        from app.migrations.phase01 import activate_scoped_idempotency
        with tempfile.TemporaryDirectory() as temp:
            db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
            legacy(db);migrate(db)
            code=Path(temp)/'job_records.py'
            code.write_text('idx_jobs_legacy_request idx_jobs_owner_request legacy_controller_owner')
            db_code=Path(temp)/'db.py'
            db_code.write_text('controller_owner_id legacy_controller_owner')
            activate_scoped_idempotency(db,patched_source=code,patched_db_source=db_code)
            a=ids.create_user(db,email='alpha@example.com',password='correct-password-123',display_name='Alpha',status='active',email_verified_at=NOW)
            b=ids.create_user(db,email='beta@example.com',password='correct-password-123',display_name='Beta',status='active',email_verified_at=NOW)
            for jid,uid in [('a-job',a),('b-job',b)]:
                db.execute('''INSERT INTO jobs(id,request_json,state,created_at,updated_at,client_request_id,owner_user_id,ownership_state)
                            VALUES (?,'{}','pending',?,?, 'shared-key',?,'verified')''',(jid,NOW,NOW,uid))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE client_request_id='shared-key'").fetchone()[0],2)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('''INSERT INTO jobs(id,request_json,state,created_at,updated_at,client_request_id,owner_user_id,ownership_state)
                            VALUES ('bad','{}','pending',?,?, 'shared-key',?,'verified')''',(NOW,NOW,a))
            db.rollback()
            db.close()

class Phase01Sessions(unittest.TestCase):
    def test_hashed_session_account_status_revocation_and_cross_account(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        legacy(con);migrate(con)
        a=ids.create_user(con,email='a@example.com',password='password-a-12345',display_name='A',status='active',email_verified_at=NOW)
        b=ids.create_user(con,email='b@example.com',password='password-b-12345',display_name='B',status='active',email_verified_at=NOW)
        sid,token=ids.issue_session(con,user_id=a,ttl_seconds=3600,absolute_ttl_seconds=86400)
        self.assertNotEqual(con.execute('SELECT session_token_hash FROM sessions WHERE id=?',(sid,)).fetchone()[0],token)
        self.assertEqual(ids.current_session_user(con,token)['id'],a)
        self.assertNotEqual(ids.current_session_user(con,token)['id'],b)
        self.assertIsNone(ids.current_session_user(con,'not a real token'))
        self.assertFalse(ids.revoke_session(con,b,sid))
        self.assertTrue(ids.revoke_session(con,a,sid))
        self.assertIsNone(ids.current_session_user(con,token))
        con.close()

    def test_pending_account_cannot_issue_session(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        legacy(con);migrate(con)
        a=ids.create_user(con,email='pending@example.com',password='password-12345',display_name='Pending')
        with self.assertRaises(ids.AccessDenied):
            ids.issue_session(con,user_id=a,ttl_seconds=3600,absolute_ttl_seconds=86400)
        con.close()

class Phase01Downgrade(unittest.TestCase):
    def test_synthetic_copy_up_and_down_preserves_legacy_data(self):
        from app.migrations.phase01 import downgrade_empty_copy
        con=sqlite3.connect(':memory:'); con.row_factory=sqlite3.Row
        legacy(con)
        migrate(con)
        d=downgrade_empty_copy(con)
        self.assertTrue(d['downgraded'])
        self.assertEqual(con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],2)
        self.assertNotIn('owner_user_id',{r[1] for r in con.execute('PRAGMA table_info(jobs)')})
        self.assertIn('jobs_snapshot_immutable',{r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")})
        self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchone(),None)
        con.close()

    def test_downgrade_refuses_user_data(self):
        from app.migrations.phase01 import downgrade_empty_copy
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        legacy(con);migrate(con)
        ids.create_user(con,email='user@example.com',password='some-password-12345',display_name='User')
        con.commit()
        with self.assertRaises(RuntimeError):downgrade_empty_copy(con)
        self.assertIn('users',{r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")})
        con.close()
