"""FastAPI + SQLite + mocked R2 S3 multipart API; tests owners/CSRF/validation."""
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]

class R2:
    def __init__(self):self.uploads={};self.objects={};self.seq=0
    def create_multipart_upload(self,*,Bucket,Key,ContentType):
        self.seq+=1
        uploadid=f'up-{self.seq}'
        self.uploads[uploadid]={'key':Key,'type':ContentType,'parts':{}}
        return {'UploadId':uploadid}
    def generate_presigned_url(self,action,*,Params,ExpiresIn):
        if action=='upload_part':
            assert Params['UploadId'] in self.uploads
            return f'https://example.invalid/upload/{Params["PartNumber"]}'
        return 'https://example.invalid/signed'
    def complete_multipart_upload(self,*,Bucket,Key,UploadId,MultipartUpload):
        sess=self.uploads[UploadId]
        size=0
        for part in MultipartUpload['Parts']:
            size+=sess['parts'][part['PartNumber']]
        self.objects[Key]={'ContentLength':size,'ContentType':sess['type']}
        return {}
    def head_object(self,*,Bucket,Key):return self.objects[Key]
    def abort_multipart_upload(self,*,Bucket,Key,UploadId):self.uploads.pop(UploadId,None)
    def delete_object(self,*,Bucket,Key):self.objects.pop(Key,None)

class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox=tempfile.TemporaryDirectory();cls.dbfile=Path(cls.sandbox.name)/'test.sqlite'
        con=sqlite3.connect(cls.dbfile);con.execute('CREATE TABLE baseline(a INTEGER)');con.commit();con.close()
        subprocess.run([sys.executable,str(ROOT/'scripts/migrate_scail2.py')],check=True,capture_output=True,
                       env={**os.environ,'DB_PATH':str(cls.dbfile)})
        package='cr_longform_pkg';pkg=types.ModuleType(package);pkg.__path__=[str(ROOT/'backend/app')]
        cls.mods={package:pkg}
        db=types.ModuleType(package+'.db')
        @contextmanager
        def connect():
            c=sqlite3.connect(cls.dbfile);c.row_factory=sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        db.connect=connect
        security=types.ModuleType(package+'.security')
        def actor(req:Request):return {'user_id':req.headers.get('X-Test-User','u1'),'roles':['user']}
        def csrf(req):
            if req.headers.get('X-CSRF-Token')!='fake-csrf':raise HTTPException(403,'CSRF')
        security.require_active_user=actor;security.require_csrf=csrf
        cls.r2=R2();storage=types.ModuleType(package+'.storage');storage.client=lambda:cls.r2
        config=types.ModuleType(package+'.config')
        config.settings=types.SimpleNamespace(r2_bucket='comfy')
        cls.mods.update({db.__name__:db,security.__name__:security,
                         storage.__name__:storage,config.__name__:config})
        cls.previous={name:sys.modules.get(name) for name in cls.mods}
        sys.modules.update(cls.mods)
        for module in ('character_replace_api','character_replace_large_uploads'):
            name=package+'.'+module
            spec=importlib.util.spec_from_file_location(name,ROOT/'backend/app'/(module+'.py'))
            mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod
            spec.loader.exec_module(mod)
            cls.mods[name]=mod
        cls.app=FastAPI()
        cls.app.include_router(sys.modules[package+'.character_replace_large_uploads'].router)
        cls.client=TestClient(cls.app)
        cls.env=patch.dict(os.environ,{'CHARACTER_REPLACE_ENABLED':'true',
                                        'CHARACTER_REPLACE_MAX_VIDEO_GIB':'20'})
        cls.env.start()
    @classmethod
    def tearDownClass(cls):
        cls.env.stop();cls.client.close()
        for name in cls.mods:
            if name in cls.previous and cls.previous[name] is not None:
                sys.modules[name]=cls.previous[name]
            else:sys.modules.pop(name,None)
        cls.sandbox.cleanup()
    def post(self,path,body,user='u1',csrf=True):
        headers={'X-Test-User':user}
        if csrf:headers['X-CSRF-Token']='fake-csrf'
        return self.client.post('/api/v2/character-replace/uploads'+path,json=body,headers=headers)
    def test_direct_upload_and_private_completion(self):
        size=25*1024*1024
        start=self.post('/start',{'filename':'travel_video.MOV','size_bytes':size})
        self.assertEqual(start.status_code,201,start.text)
        data=start.json();sid=data['session_id'];self.assertEqual(data['part_count'],2)
        self.assertEqual(self.post(f'/{sid}/part-url',{'number':1},user='stranger').status_code,404)
        self.assertEqual(self.post(f'/{sid}/part-url',{'number':1},csrf=False).status_code,403)
        invalid=self.post(f'/{sid}/complete',{'parts':[{'number':1,'etag':'bad'}]})
        self.assertEqual(invalid.status_code,422)
        self.assertEqual(self.post(f'/{sid}/part-url',{'number':3}).status_code,422)
        for n in (1,2):self.assertEqual(self.post(f'/{sid}/part-url',{'number':n}).status_code,200)
        remote=list(self.r2.uploads.values())[-1]
        remote['parts']={1:16*1024*1024,2:9*1024*1024}
        etags=[{'number':n,'etag':'"'+'a'*32+'"'} for n in (1,2)]
        done=self.post(f'/{sid}/complete',{'parts':etags})
        self.assertEqual(done.status_code,200,done.text)
        self.assertEqual(done.json()['size_bytes'],size)
        self.assertIsNone(done.json()['duration'])
        self.assertEqual(self.post(f'/{sid}/complete',{'parts':etags}).status_code,200)
    def test_limits_and_invalid_file_name_not_trusted(self):
        too_large=self.post('/start',{'filename':'big.mov','size_bytes':30*1024**3})
        self.assertEqual(too_large.status_code,413)
        other=self.post('/start',{'filename':'../payload.exe','size_bytes':1234567},user='u2')
        self.assertEqual(other.status_code,201,other.text)
        key=list(self.r2.uploads.values())[-1]['key']
        self.assertTrue(key.endswith('.bin'))
        self.assertNotIn('..',key)
        self.assertEqual(self.post(f'/{other.json()["session_id"]}/abort',{},user='u2').status_code,200)

if __name__=='__main__':unittest.main()
