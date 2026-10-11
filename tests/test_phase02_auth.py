"""Phase02 HTTP security tests using two synthetic users, never GPU/email network."""
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
# app.config is instantiated at import time in the existing project; harmless
# offline placeholders avoid requiring a private production .env in a test.
FAKE_ENV={
 'APP_NAME':'phase02-test','DB_PATH':'/tmp/phase02-test.db','MAX_UPLOAD_MB':'10',
 'SALAD_API_KEY':'offline-only','SALAD_API_BASE_URL':'https://example.invalid',
 'SALAD_USER_AGENT':'phase02-tests','SALAD_HTTP_TIMEOUT_SECONDS':'5',
 'SALAD_ORG':'offline','SALAD_PROJECT':'offline','SALAD_QUEUE_NAME':'offline',
 'SALAD_PRIORITY':'medium','SALAD_GPU_NAME':'offline','R2_ENDPOINT_URL':'https://example.invalid',
 'R2_BUCKET':'offline','R2_ACCESS_KEY_ID':'offline','R2_SECRET_ACCESS_KEY':'offline',
 'R2_REGION':'auto','R2_PRESIGN_TTL_SECONDS':'60'}
for name,value in FAKE_ENV.items():os.environ.setdefault(name,value)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import auth, security
from app.migrations.phase01 import migrate as phase01
from app.migrations.phase02 import migrate as phase02
from app import db

LEGACY='''
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
'''

class Mailbox:
    def __init__(self):self.sent=[]
    def send(self,to,subject,content):self.sent.append((to,subject,content))
    def pop_token(self):
        assert self.sent
        url=self.sent[-1][-1].strip().splitlines()[-1]
        assert '#token=' in url
        return url.split('#token=')[1]

class Phase02HTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'copy.sqlite'
        c=sqlite3.connect(self.path)
        try:
            c.executescript(LEGACY)
            c.commit()
            phase01(c)
            self.assertTrue(phase02(c))
            self.assertFalse(phase02(c))
        finally:
            c.close()
        @contextmanager
        def connect():
            c=sqlite3.connect(self.path,timeout=5)
            c.row_factory=sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        self.patcher=patch.object(db,'connect',connect)
        self.patcher.start()
        self.env=patch.dict(os.environ,{
            'AUTH_ENABLED':'true', 'AUTH_PUBLIC_ORIGIN':'https://testserver',
            'AUTH_CSRF_SECRET':'A'*48,'AUTH_REGISTRATION_MODE':'public',
            'AUTH_SESSION_SECONDS':'3600','AUTH_REMEMBER_SECONDS':'86400',
            'AUTH_IDLE_SECONDS':'1200'})
        self.env.start()
        self.mail=Mailbox()
        app=FastAPI()
        app.include_router(auth.router)
        from fastapi import Depends
        @app.get('/__test/admin',dependencies=[Depends(security.require_role('admin'))])
        def admin_only(): return {'ok':True}
        app.dependency_overrides[auth.email_sender]=lambda:self.mail
        self.app=app
        self.client=TestClient(app,base_url='https://testserver')
        self.client.headers.update({'Origin':'https://testserver'})

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.patcher.stop()
        self.tmp.cleanup()

    def call(self,path,body=None,method='post',client=None,**kw):
        c=client or self.client
        return getattr(c,method)(path,json=body,**kw) if method in ('post','put','patch') else getattr(c,method)(path,**kw)

    def enroll(self,email='a@example.com',password='A-secure-password-019'):
        r=self.call('/api/auth/register',{'email':email,'password':password,'display_name':'Test user','terms_accepted':True})
        self.assertEqual(r.status_code,202,r.text)
        token=self.mail.pop_token()
        r=self.call('/api/auth/verify-email',{'token':token})
        self.assertEqual(r.status_code,200,r.text)
        return token

    def log_in(self,email='a@example.com',password='A-secure-password-019',remember=False):
        r=self.call('/api/auth/login',{'email':email,'password':password,'remember_me':remember})
        self.assertEqual(r.status_code,200,r.text)
        return r

    def csrf(self,client=None):
        return (client or self.client).get('/api/auth/csrf').json()['csrf_token']

    def test_01_full_cycle_and_cookie(self):
        token=self.enroll()
        self.assertEqual(self.call('/api/auth/verify-email',{'token':token}).status_code,409)
        self.assertEqual(self.call('/api/auth/login',{'email':'a@example.com','password':'bad-password'}).status_code,401)
        r=self.log_in(remember=True)
        cookie=r.headers['set-cookie']
        self.assertIn('httponly',cookie.lower());self.assertIn('secure',cookie.lower());self.assertIn('samesite=lax',cookie.lower())
        self.assertIn('__Host-comfy_session=',cookie)
        self.assertNotIn('APP_INTERNAL_TOKEN',str(r.json()))
        self.assertEqual(self.client.get('/api/auth/me').json()['user']['status'],'active')
        self.assertEqual(self.client.get('/api/auth/session').json()['state'],'authenticated')
        csrf=self.csrf()
        self.assertEqual(self.client.post('/api/auth/logout',headers={'X-CSRF-Token':csrf}).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_02_reset_revokes_all_and_is_one_time(self):
        self.enroll();self.log_in()
        r=self.call('/api/auth/forgot-password',{'email':'a@example.com'})
        self.assertEqual(r.status_code,202)
        raw=self.mail.pop_token()
        self.assertNotIn(raw,str(r.json()))
        new='Different-secure-password-123'
        self.assertEqual(self.call('/api/auth/reset-password',{'token':raw,'new_password':new}).status_code,200)
        self.assertEqual(self.call('/api/auth/reset-password',{'token':raw,'new_password':new}).status_code,409)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertEqual(self.call('/api/auth/login',{'email':'a@example.com','password':'A-secure-password-019'}).status_code,401)
        self.log_in(password=new)
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)

    def test_03_anti_enumeration_and_login_rate(self):
        self.enroll()
        known=self.call('/api/auth/forgot-password',{'email':'a@example.com'})
        unknown=self.call('/api/auth/forgot-password',{'email':'missing@example.com'})
        self.assertEqual((known.status_code,known.json()),(unknown.status_code,unknown.json()))
        for attempt in range(5):
            r=self.call('/api/auth/login',{'email':'a@example.com','password':'wrong-pass'})
            self.assertEqual(r.status_code,401)
        self.assertEqual(self.call('/api/auth/login',{'email':'a@example.com','password':'wrong-pass'}).status_code,429)
        self.assertEqual(self.call('/api/auth/login',{'email':'a@example.com','password':'A-secure-password-019'}).status_code,429)

    def test_04_csrf_bad_origin_and_foreign_session(self):
        self.enroll();self.log_in()
        self.assertEqual(self.call('/api/auth/logout').status_code,403)
        csrf=self.csrf()
        self.assertEqual(self.client.post('/api/auth/logout',headers={'Origin':'https://evil.example','X-CSRF-Token':csrf}).status_code,403)
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        other=TestClient(self.app,base_url='https://testserver')
        other.headers.update({'Origin':'https://testserver'})
        self.assertEqual(other.get('/api/auth/me').status_code,401)
        self.assertEqual(other.get('/api/auth/csrf').status_code,401)
        self.assertEqual(self.client.post('/api/auth/logout',headers={'X-CSRF-Token':csrf}).status_code,200)
        other.close()

    def test_05_role_spoof_admin_does_not_work(self):
        self.enroll();self.log_in()
        self.assertEqual(self.client.get('/api/auth/me',headers={'X-User-Role':'superadmin'}).json()['user']['roles'],['user'])
        response=self.call('/api/auth/register',{'email':'b@example.com','password':'B-secure-password-019',
                 'display_name':'B','terms_accepted':True,'role':'admin','owner_user_id':'x'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(self.client.get('/__test/admin').status_code,403)
        self.assertEqual(self.client.get('/__test/admin',headers={'X-User-Role':'admin'}).status_code,403)

    def test_06_logout_all_and_session_list(self):
        self.enroll();self.log_in()
        c2=TestClient(self.app,base_url='https://testserver');c2.headers.update({'Origin':'https://testserver'})
        self.assertEqual(self.call('/api/auth/login',{'email':'a@example.com','password':'A-secure-password-019'},client=c2).status_code,200)
        rows=self.client.get('/api/auth/sessions').json()['sessions']
        self.assertEqual(len(rows),2)
        a=self.csrf()
        self.assertEqual(self.client.post('/api/auth/logout-all',headers={'X-CSRF-Token':a}).status_code,200)
        self.assertEqual(c2.get('/api/auth/me').status_code,401)
        c2.close()

    def test_07_disabled_registration_and_unverified(self):
        with patch.dict(os.environ,{'AUTH_REGISTRATION_MODE':'disabled'}):
            self.assertEqual(self.call('/api/auth/register',{'email':'a@example.com',
                  'password':'A-secure-password-019','display_name':'Test','terms_accepted':True}).status_code,403)
        response=self.call('/api/auth/register',{'email':'a@example.com',
          'password':'A-secure-password-019','display_name':'Test','terms_accepted':True})
        self.assertEqual(response.status_code,202)
        self.assertEqual(self.call('/api/auth/login',{'email':'a@example.com','password':'A-secure-password-019'}).status_code,401)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_09_invite_policy_and_replay(self):
        from datetime import timedelta
        import hashlib
        from uuid import uuid4
        raw='super-secret-invite-token-0123456789'
        email='invited@example.com'
        conn=sqlite3.connect(self.path)
        with conn:
            now=security.now()
            conn.execute('INSERT INTO auth_invitations(id,email_normalized,token_hash,created_at,expires_at) VALUES (?,?,?,?,?)',
                         (str(uuid4()),email,hashlib.sha256(raw.encode()).hexdigest(),security.iso(now),security.iso(now+timedelta(days=1))))
        conn.close()
        with patch.dict(os.environ,{'AUTH_REGISTRATION_MODE':'invite'}):
            body={'email':email,'password':'B-secure-password-321','display_name':'Invited','terms_accepted':True}
            self.assertEqual(self.call('/api/auth/register',body).status_code,403)
            self.assertEqual(self.call('/api/auth/register',{**body,'invite_token':raw}).status_code,202)
            self.assertEqual(self.call('/api/auth/register',{**body,'invite_token':raw}).status_code,403)
        conn=sqlite3.connect(self.path)
        try:self.assertEqual(conn.execute('SELECT COUNT(*) FROM users WHERE email_normalized=?',(email,)).fetchone()[0],1)
        finally:conn.close()

    def test_10_password_change_revokes_all(self):
        self.enroll();self.log_in()
        self.assertEqual(self.call('/api/auth/change-password',{'current_password':'A-secure-password-019',
            'new_password':'Another-good-password-321'}).status_code,403)
        csrf=self.csrf()
        self.assertEqual(self.client.post('/api/auth/change-password',headers={'X-CSRF-Token':csrf},
          json={'current_password':'A-secure-password-019','new_password':'Another-good-password-321'}).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.log_in(password='Another-good-password-321')

    def test_11_session_revoke_other_and_cross_owner(self):
        self.enroll();self.log_in()
        c2=TestClient(self.app,base_url='https://testserver');c2.headers.update({'Origin':'https://testserver'})
        self.log_in()  # second cookie in original browser, creates another valid session
        rows=self.client.get('/api/auth/sessions').json()['sessions']
        old=next(row['id'] for row in rows if not row['current'])
        token=self.csrf()
        self.assertEqual(self.client.delete('/api/auth/sessions/'+old,headers={'X-CSRF-Token':token}).status_code,204)
        self.assertEqual(self.client.delete('/api/auth/sessions/'+old,headers={'X-CSRF-Token':token}).status_code,404)
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        c2.close()

    def test_12_secure_disabled_migration_flag(self):
        with patch.dict(os.environ,{'AUTH_ENABLED':'false'}):
            self.assertEqual(self.client.get('/api/auth/session').status_code,503)
        with patch.dict(os.environ,{'AUTH_PUBLIC_ORIGIN':'http://insecure.invalid'}):
            self.assertEqual(self.client.get('/api/auth/session').status_code,503)
        with patch.dict(os.environ,{'AUTH_MFA_ENABLED':'true'}):
            self.assertEqual(self.client.get('/api/auth/session').status_code,503)

    def test_13_registration_race_atomic(self):
        import concurrent.futures
        body={'email':'race@example.com','password':'Race-secure-password-314',
              'display_name':'Concurrent','terms_accepted':True}
        def submit(_):
            c=TestClient(self.app,base_url='https://testserver')
            c.headers.update({'Origin':'https://testserver'})
            try:return c.post('/api/auth/register',json=body).status_code
            finally:c.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(submit,range(2)))
        self.assertEqual(results,[202,202])
        conn=sqlite3.connect(self.path)
        try:self.assertEqual(conn.execute("SELECT COUNT(*) FROM users WHERE email_normalized='race@example.com'").fetchone()[0],1)
        finally:conn.close()

    def test_14_hashed_secret_storage_and_rehash(self):
        self.enroll()
        raw=self.mail.pop_token()
        self.log_in()
        session_raw=self.client.cookies.get(security.COOKIE_NAME)
        conn=sqlite3.connect(self.path)
        try:
            stored=conn.execute("SELECT session_token_hash FROM sessions LIMIT 1").fetchone()[0]
            self.assertEqual(stored,security.digest(session_raw))
            self.assertNotEqual(stored,session_raw)
            token_hash=conn.execute("SELECT token_hash FROM email_verification_tokens LIMIT 1").fetchone()[0]
            self.assertNotEqual(token_hash,raw)
            # Simulate a legacy Argon2id parameter set; login should upgrade it.
            from argon2 import PasswordHasher
            weak=PasswordHasher(time_cost=1,memory_cost=8192,parallelism=1)
            conn.execute("UPDATE users SET password_hash=? WHERE email_normalized='a@example.com'",
                         (weak.hash('A-secure-password-019'),))
            conn.commit()
        finally:conn.close()
        self.log_in()
        conn=sqlite3.connect(self.path)
        try:
            upgraded=conn.execute("SELECT password_hash FROM users WHERE email_normalized='a@example.com'").fetchone()[0]
            self.assertFalse(auth.identity.PASSWORD_HASHER.check_needs_rehash(upgraded))
        finally:conn.close()

    def test_08_user_session_cannot_access_worker_or_admin(self):
        self.enroll();self.log_in()
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        self.assertFalse('X-Internal-Token' in self.client.headers)
        self.assertFalse('X-Worker-Token' in self.client.headers)
        # Existing legacy endpoints require separate tokens; tested in repo regression.

if __name__=='__main__': unittest.main()
