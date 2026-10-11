"""Phase05 isolated HTTP tests. Real auth, sqlite schema and no network/GPU."""
from __future__ import annotations
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from test_phase02_auth import Phase02HTTP
from app import account_api,db
from app.migrations.phase05 import migrate as phase05

class Phase05HTTP(unittest.TestCase):
    def setUp(self):
        Phase02HTTP.setUp(self)
        with sqlite3.connect(self.path) as c:
            c.execute("ALTER TABLE jobs ADD COLUMN active_attempt_id TEXT")
            assert phase05(c)
            assert not phase05(c)
        self.app.include_router(account_api.router)
        self.env2=patch.dict(os.environ,{'ACCOUNT_UI_ENABLED':'true','ACCOUNT_REQUESTS_ENABLED':'false'})
        self.env2.start()
        self.a=self.client
        Phase02HTTP.enroll(self,'a@example.com')
        Phase02HTTP.log_in(self,'a@example.com')
        self.b=TestClient(self.app,base_url='https://testserver')
        self.b.headers.update({'Origin':'https://testserver'})
        Phase02HTTP.enroll(self,'b@example.com')
        self.assertEqual(self.b.post('/api/auth/login',json={'email':'b@example.com','password':'A-secure-password-019'}).status_code,200)
        self.c=TestClient(self.app,base_url='https://testserver')
        self.c.headers.update({'Origin':'https://testserver'})
        Phase02HTTP.enroll(self,'admin@example.com')
        with db.connect() as conn:
            row=conn.execute("SELECT id FROM users WHERE email='admin@example.com'").fetchone()
            self.adminid=row['id']
            conn.execute('INSERT INTO user_roles(user_id,role_id,granted_at) VALUES (?,?,?)',
                         (self.adminid,'admin','2026-10-10T00:00:00+00:00'))
        self.assertEqual(self.c.post('/api/auth/login',json={'email':'admin@example.com','password':'A-secure-password-019'}).status_code,200)
        with db.connect() as conn:
            self.aid=conn.execute("SELECT id FROM users WHERE email='a@example.com'").fetchone()[0]
            self.bid=conn.execute("SELECT id FROM users WHERE email='b@example.com'").fetchone()[0]
    def tearDown(self):
        self.b.close();self.c.close();self.env2.stop();Phase02HTTP.tearDown(self)
    def call(self,*a,**kw):
        return Phase02HTTP.call(self,*a,**kw)
    def csrf(self,client):
        return client.get('/api/auth/csrf').json()['csrf_token']
    def patchme(self,client,url,data):
        return client.patch(url,json=data,headers={'X-CSRF-Token':self.csrf(client)})
    def post(self,client,url,data):
        return client.post(url,json=data,headers={'X-CSRF-Token':self.csrf(client)})

    def test_01_dashboard_sql_owner_and_aggregate_privacy(self):
        from app import security
        now=security.iso()
        with db.connect() as c:
            c.execute('INSERT INTO workflows(id,name,api_prompt,created_at,updated_at) VALUES (?,?,?,?,?)',('wf','Model','{}',now,now))
            for uid,jid,state in [(self.aid,'ja','succeeded'),(self.bid,'jb','failed')]:
                c.execute('''INSERT INTO jobs(id,workflow_id,state,request_json,created_at,updated_at,owner_user_id,ownership_state)
                             VALUES (?,?,?,?,?,?,?,?)''',(jid,'wf',state,'{}',now,now,uid,'verified'))
                c.execute('''INSERT INTO job_assets(asset_id,job_id,storage_key,status,created_at,owner_user_id,ownership_state)
                             VALUES (?,?,?,?,?,?,?)''',('asset'+jid,jid,'outputs/'+jid+'/private.png','available',now,uid,'verified'))
        da=self.a.get('/api/dashboard/summary');dbb=self.b.get('/api/dashboard/summary')
        self.assertEqual((da.status_code,dbb.status_code),(200,200))
        self.assertEqual(da.json()['counts']['succeeded'],1)
        self.assertEqual(da.json()['counts']['outputs'],1)
        self.assertEqual(dbb.json()['counts']['succeeded'],0)
        self.assertEqual(dbb.json()['counts']['failed'],1)
        self.assertNotIn('jb',str(da.json()));self.assertNotIn('assetjb',str(da.json()))
        self.assertNotIn('ja',str(dbb.json()))
        self.assertEqual(da.json()['quota']['status'],'unavailable')
        self.assertEqual(self.a.get('/api/admin/summary').status_code,403)
        self.assertEqual(self.a.get('/api/admin/users').status_code,403)
        self.assertEqual(self.a.get('/api/admin/audit-logs').status_code,403)
        self.assertEqual(self.c.get('/api/admin/summary').status_code,200)
        self.assertNotIn('request_json',str(self.c.get('/api/admin/summary').json()))

    def test_02_preferences_across_two_clients_and_csrf(self):
        payload={'theme':'dark','locale':'fa','timezone':'America/Vancouver','default_model_id':None,'default_ratio':'16:9'}
        self.assertEqual(self.a.patch('/api/users/me/preferences',json=payload).status_code,403)
        self.assertEqual(self.patchme(self.a,'/api/users/me/preferences',payload).status_code,200)
        self.assertEqual(self.a.get('/api/users/me/preferences').json()['theme'],'dark')
        self.assertEqual(self.b.get('/api/users/me/preferences').json()['theme'],'system')
        self.assertEqual(self.patchme(self.b,'/api/users/me/preferences',{'theme':'invalid','locale':'en','timezone':'UTC'}).status_code,422)
        self.assertEqual(self.patchme(self.a,'/api/users/me/preferences',{'theme':'light','locale':'en','timezone':'Mars/Here'}).status_code,422)
        self.assertEqual(self.patchme(self.a,'/api/users/me',{'display_name':'Updated A'}).status_code,200)
        self.assertEqual(self.b.get('/api/users/me').json()['display_name'],'Test user')

    def test_03_admin_suspend_revokes_and_audit_immutable(self):
        target=self.b.get('/api/auth/me');self.assertEqual(target.status_code,200)
        csrf=self.csrf(self.c)
        self.assertEqual(self.c.patch('/api/admin/users/'+self.bid,json={'status':'suspended','reason':'manual test action'},headers={'X-CSRF-Token':'wrong'}).status_code,403)
        response=self.c.patch('/api/admin/users/'+self.bid,json={'status':'suspended','reason':'manual test action'},headers={'X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['sessions_revoked'])
        self.assertEqual(self.b.get('/api/auth/me').status_code,401)
        self.assertEqual(self.b.get('/api/dashboard/summary').status_code,401)
        self.assertEqual(self.b.post('/api/auth/login',json={'email':'b@example.com','password':'A-secure-password-019'}).status_code,401)
        history=self.c.get('/api/admin/audit-logs').json()['items']
        self.assertTrue(any(x['action']=='user.status_suspended' and x['subject_id']==self.bid for x in history))
        with db.connect() as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('DELETE FROM account_audit_logs')
                c.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE account_audit_logs SET action='tampered'")
                c.rollback()
        self.assertEqual(self.c.patch('/api/admin/users/'+self.adminid,json={'status':'suspended','reason':'manual test action'},headers={'X-CSRF-Token':csrf}).status_code,409)

    def test_04_roles_stepup_password_and_no_impersonation(self):
        self.assertEqual(self.post(self.c,'/api/admin/users/'+self.aid+'/role',{'role':'admin','action':'grant','reason':'testing role elevation','current_password':'A-secure-password-019'}).status_code,403)
        with db.connect() as c:
            c.execute('INSERT INTO user_roles(user_id,role_id,granted_at) VALUES (?,?,?)',(self.adminid,'superadmin','2026-10-10T00:00:00+00:00'))
        self.assertEqual(self.post(self.c,'/api/admin/users/'+self.aid+'/role',{'role':'admin','action':'grant','reason':'testing role elevation','current_password':'wrong'}).status_code,401)
        ok=self.post(self.c,'/api/admin/users/'+self.aid+'/role',{'role':'admin','action':'grant','reason':'testing role elevation','current_password':'A-secure-password-019'})
        self.assertEqual(ok.status_code,200,ok.text)
        self.assertEqual(self.a.get('/api/auth/me').status_code,401)
        self.assertEqual(set(self.c.get('/api/admin/users/'+self.aid).json()['roles']),{'user','admin'})
        self.assertEqual(self.a.get('/api/admin/users').status_code,401)

    def test_05_email_change_token_one_time_and_no_premature_change(self):
        original=self.a.get('/api/users/me').json()['email']
        res=self.post(self.a,'/api/users/me/email-change',{'new_email':'new@example.com','current_password':'A-secure-password-019'})
        self.assertEqual(res.status_code,202,res.text)
        self.assertEqual(self.a.get('/api/users/me').json()['email'],original)
        message=self.mail.sent[-1][-1]
        self.assertIn('#email-change-token=',message)
        token=message.rsplit('#email-change-token=',1)[1]
        self.assertEqual(self.post(self.b,'/api/users/me/verify-email-change',{'token':token}).status_code,409)
        self.assertEqual(self.post(self.a,'/api/users/me/verify-email-change',{'token':token}).status_code,200)
        self.assertEqual(self.a.get('/api/users/me').json()['email'],'new@example.com')
        self.assertEqual(self.post(self.a,'/api/users/me/verify-email-change',{'token':token}).status_code,409)
        self.assertEqual(self.post(self.a,'/api/users/me/email-change',{'new_email':'other@example.com','current_password':'wrong'}).status_code,401)

    def test_06_user_data_requests_feature_gated(self):
        self.assertEqual(self.a.get('/api/account/data-summary').status_code,200)
        self.assertEqual(self.post(self.a,'/api/account/export-request',None).status_code,503)
        self.assertEqual(self.post(self.a,'/api/account/delete-request',None).status_code,503)
        with patch.dict(os.environ,{'ACCOUNT_REQUESTS_ENABLED':'true'}):
            res=self.post(self.a,'/api/account/export-request',None)
            self.assertEqual(res.status_code,202,res.text)
            self.assertEqual(res.json()['status'],'pending_review')
            self.assertNotIn(res.json()['id'],str(self.b.get('/api/account/data-summary').json()))
        self.assertEqual(self.a.get('/api/account/data-summary').json()['requests'][0]['status'],'pending_review')

    def test_07_audit_admin_cursor_and_email_list_denied(self):
        self.assertEqual(self.a.get('/api/admin/users?limit=100').status_code,403)
        self.assertEqual(self.c.get('/api/admin/users?limit=1').status_code,200)
        self.assertIn('next_cursor',self.c.get('/api/admin/users?limit=1').json())
        self.assertEqual(self.c.get('/api/admin/audit-logs?cursor=invalid').status_code,422)
        with patch.dict(os.environ,{'ACCOUNT_UI_ENABLED':'false'}):
            self.assertEqual(self.a.get('/api/dashboard/summary').status_code,503)
            self.assertEqual(self.c.get('/api/admin/users').status_code,503)

if __name__=='__main__':unittest.main()
