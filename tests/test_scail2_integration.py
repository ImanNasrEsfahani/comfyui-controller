"""Controller API integration tests with fake authentication/R2, real SQLite/FFmpeg.

No external storage, GPU, Docker or network. Inference is intentionally mocked.
"""
from contextlib import contextmanager
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
from unittest import TestCase
from unittest.mock import patch
import shutil

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


class FakeR2:
    def __init__(self):self.objects={}
    def upload_fileobj(self, source, key, mime):
        self.objects[key]=(source.read(),mime)
    def head_object(self,*,Bucket,Key):
        if Key not in self.objects:raise KeyError(Key)
        b,m=self.objects[Key]
        return {'ContentLength':len(b),'ContentType':m}
    def get_object(self,*,Bucket,Key,Range=None):
        b,m=self.objects[Key]
        if Range:
            a,z=Range[6:].split('-');b=b[int(a):int(z)+1]
        return {'Body':FakeBody(b),'ContentType':m}
    def generate_presigned_url(self,*args,**kwargs):return 'https://r2.example.invalid/signed-object'


class FakeBody:
    def __init__(self,b):self.buf=io.BytesIO(b)
    def iter_chunks(self,chunk_size):
        while (part:=self.buf.read(chunk_size)):yield part
    def close(self):self.buf.close()


class Integration(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox=tempfile.TemporaryDirectory()
        cls.dbfile=Path(cls.sandbox.name)/'controller.db'
        cls.dbfile.touch()
        env={**os.environ,'DB_PATH':str(cls.dbfile)}
        subprocess.run([sys.executable,str(ROOT/'scripts/migrate_scail2.py')],env=env,check=True,capture_output=True)
        pkg=types.ModuleType('cr_audit_pkg');pkg.__path__=[str(ROOT/'backend/app')]
        cls.modules={'cr_audit_pkg':pkg}
        db=types.ModuleType('cr_audit_pkg.db')
        @contextmanager
        def connect():
            c=sqlite3.connect(cls.dbfile)
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA busy_timeout=5000')
            try:
                with c:yield c
            finally:c.close()
        db.connect=connect
        security=types.ModuleType('cr_audit_pkg.security')
        def actor(req:Request):
            return {'user_id':req.headers.get('X-Test-User','u1'),
                    'roles':[req.headers.get('X-Test-Role','user')]}
        def csrf(req):
            if req.headers.get('X-CSRF-Token')!='unit-test-csrf':raise HTTPException(403,'Invalid CSRF')
        security.require_active_user=actor
        security.require_csrf=csrf
        cls.r2=FakeR2()
        storage=types.ModuleType('cr_audit_pkg.storage')
        storage.upload_fileobj=cls.r2.upload_fileobj
        storage.client=lambda:cls.r2
        storage.get_object=lambda key:cls.r2.get_object(Bucket='comfy',Key=key)
        storage.presign_get=lambda key,ttl=3600: 'https://r2.example.invalid/signed-get'
        config=types.ModuleType('cr_audit_pkg.config')
        config.settings=types.SimpleNamespace(r2_bucket='comfy')
        cls.modules.update({'cr_audit_pkg.db':db,'cr_audit_pkg.security':security,
                            'cr_audit_pkg.storage':storage,'cr_audit_pkg.config':config})
        cls.previous={key:sys.modules.get(key) for key in cls.modules}
        sys.modules.update(cls.modules)
        spec=importlib.util.spec_from_file_location('cr_audit_pkg.character_replace_api',ROOT/'backend/app/character_replace_api.py')
        cls.api=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=cls.api
        spec.loader.exec_module(cls.api)
        cls.app=FastAPI();cls.app.include_router(cls.api.router)
        cls.client=TestClient(cls.app)
        cls.env=patch.dict(os.environ,{'CHARACTER_REPLACE_ENABLED':'true',
                        'CHARACTER_REPLACE_WORKER_TOKEN':'test-token-'+('a'*55)})
        cls.env.start()
        cls.wtoken='test-token-'+('a'*55)
        # Real short H.264 clip, not arbitrary fake bytes.
        cls.video=Path(cls.sandbox.name)/'sample.mp4'
        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-f','lavfi','-i',
                        'testsrc=size=320x240:rate=16:duration=1','-c:v','libx264',
                        '-pix_fmt','yuv420p',str(cls.video)],check=True,timeout=15)
        img=Image.new('RGB',(256,256),(10,20,30))
        b=io.BytesIO();img.save(b,format='PNG');cls.reference=b.getvalue()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        for key,previous in cls.previous.items():
            if previous is None:sys.modules.pop(key,None)
            else:sys.modules[key]=previous
        sys.modules.pop('cr_audit_pkg.character_replace_api',None)
        cls.client.close()
        cls.sandbox.cleanup()

    def post(self,endpoint,body=None,actor='u1',role='user'):
        return self.client.post('/api/v2/character-replace'+endpoint,json=body,headers={
            'X-CSRF-Token':'unit-test-csrf','X-Test-User':actor,'X-Test-Role':role})

    def worker(self,endpoint,body=None):
        return self.client.post('/api/v2/character-replace/worker'+endpoint,json=body or {},headers={
            'X-Character-Worker-Token':self.wtoken})

    def upload_asset(self,kind,payload,filename):
        return self.client.post('/api/v2/character-replace/assets/'+kind,
            files={'file':(filename,payload,'application/octet-stream')},
            headers={'X-CSRF-Token':'unit-test-csrf'})

    def make_job(self,tag,mode='quality'):
        video=self.upload_asset('video',self.video.read_bytes(),'sample.mp4')
        self.assertEqual(video.status_code,201,video.text)
        image=self.upload_asset('reference',self.reference,'ref.png')
        self.assertEqual(image.status_code,201,image.text)
        req={'source_video_id':video.json()['asset_id'],
             'reference_image_id':image.json()['asset_id'],
             'client_request_id':'test-'+tag+'-1234',
             'confirmed_rights':True,'quality':mode,'steps':24 if mode=='quality' else 4}
        response=self.post('/jobs',req)
        self.assertEqual(response.status_code,202,response.text)
        return response.json()['id'],req

    def test_01_private_upload_validation_idempotency(self):
        bad=self.upload_asset('video',b'broken'*10,'x.mp4')
        self.assertEqual(bad.status_code,422)
        job,req=self.make_job('privacy')
        again=self.post('/jobs',req)
        self.assertEqual(again.status_code,202)
        self.assertEqual(again.json()['id'],job)
        changed=self.post('/jobs',{**req,'prompt':'new'})
        self.assertEqual(changed.status_code,409)
        private=self.client.get('/api/v2/character-replace/jobs/'+job,headers={'X-Test-User':'u2'})
        self.assertEqual(private.status_code,404)
        no_csrf=self.client.post('/api/v2/character-replace/jobs',json=req)
        self.assertEqual(no_csrf.status_code,403)

    def test_02_claim_lease_success_and_range(self):
        # Clear old queued test jobs to keep claim deterministic.
        with self.api.db.connect() as c:c.execute("UPDATE cr_jobs SET state='cancelled' WHERE state='queued'")
        job_id,_=self.make_job('success')
        self.assertEqual(self.worker('/hello',{'generation':'A'*32,'ready':True}).status_code,200)
        status=self.client.get('/api/v2/character-replace/config')
        self.assertTrue(status.json()['worker_ready'])
        claim=self.worker('/claim')
        self.assertEqual(claim.status_code,200,claim.text)
        job=claim.json()['job'];self.assertEqual(job['id'],job_id)
        self.assertFalse('lease_token' in str(self.client.get('/api/v2/character-replace/jobs/'+job_id).json()))
        self.assertTrue(job['source_url'].startswith('https://'))
        event={'job_id':job_id,'lease_token':job['lease_token']}
        self.assertEqual(self.worker('/event',{**event,'state':'running'}).status_code,200)
        self.assertEqual(self.worker('/heartbeat',event).json()['cancel_requested'],False)
        self.assertEqual(self.worker('/event',{**event,'state':'uploading'}).status_code,200)
        output=(b'\0'*4096)
        self.r2.objects[job['output_key']]=(output,'video/mp4')
        self.assertEqual(self.worker('/event',{**event,'state':'succeeded'}).status_code,200)
        result=self.client.get('/api/v2/character-replace/jobs/'+job_id+'/preview',headers={'Range':'bytes=12-31'})
        self.assertEqual(result.status_code,206,result.text)
        self.assertEqual(result.content,output[12:32]);self.assertEqual(result.headers['Content-Range'],'bytes 12-31/4096')
        self.assertEqual(self.client.get('/api/v2/character-replace/jobs/'+job_id+'/result').status_code,200)
        deny=self.client.get('/api/v2/character-replace/jobs/'+job_id+'/result',headers={'X-Test-User':'u2'})
        self.assertEqual(deny.status_code,404)

    def test_03_cancel_and_invalid_token(self):
        with self.api.db.connect() as c:c.execute("UPDATE cr_jobs SET state='cancelled' WHERE state='queued'")
        job_id,_=self.make_job('cancel')
        claimed=self.worker('/claim').json()['job'];event={'job_id':job_id,'lease_token':claimed['lease_token']}
        self.assertEqual(self.post('/jobs/'+job_id+'/cancel').json()['state'],'cancel_requested')
        self.assertTrue(self.worker('/heartbeat',event).json()['cancel_requested'])
        self.assertEqual(self.worker('/event',{**event,'state':'succeeded'}).status_code,409)
        self.assertEqual(self.worker('/event',{**event,'state':'cancelled'}).status_code,200)
        self.assertEqual(self.client.get('/api/v2/character-replace/jobs/'+job_id).json()['state'],'cancelled')
        self.assertEqual(self.worker('/event',{**event,'state':'cancelled'}).status_code,409)
        token=self.client.post('/api/v2/character-replace/worker/claim',json={},headers={
            'X-Character-Worker-Token':'BAD'})
        self.assertEqual(token.status_code,401)

    def test_04_expired_requires_admin_ack(self):
        with self.api.db.connect() as c:c.execute("UPDATE cr_jobs SET state='cancelled' WHERE state='queued'")
        job_id,_=self.make_job('stalled')
        claimed=self.worker('/claim').json()['job']
        with self.api.db.connect() as c:c.execute('UPDATE cr_jobs SET lease_until=0 WHERE id=?',(job_id,))
        status=self.client.get('/api/v2/character-replace/jobs/'+job_id)
        self.assertEqual(status.json()['state'],'stalled')
        self.assertEqual(self.worker('/claim').json()['blocked'],'operator_recovery_required')
        self.assertEqual(self.post('/jobs/'+job_id+'/retry').status_code,409)
        self.assertEqual(self.post('/jobs/'+job_id+'/recover',{'confirm_worker_stopped':True}).status_code,403)
        self.assertEqual(self.post('/jobs/'+job_id+'/recover',{'confirm_worker_stopped':True},role='admin').status_code,200)
        self.assertEqual(self.post('/jobs/'+job_id+'/retry').status_code,200)
        c=self.worker('/claim');self.assertEqual(c.json()['job']['id'],job_id)
        self.assertNotEqual(c.json()['job']['lease_token'],claimed['lease_token'])
        self.worker('/event',{'job_id':job_id,'lease_token':c.json()['job']['lease_token'],'state':'failed'})
    def test_05_mock_worker_end_to_end_mp4(self):
        """Real API+SQLite+FFmpeg; replace actual ComfyUI+R2 network with fakes."""
        sys.path.insert(0,str(ROOT/'salad-worker/scail2'))
        import worker
        with self.api.db.connect() as c:
            c.execute("UPDATE cr_jobs SET state='cancelled' WHERE state='queued'")
        job_id,_=self.make_job('full-pipeline',mode='fast')
        claimed=self.worker('/claim').json()['job']
        self.assertEqual(claimed['id'],job_id)
        with tempfile.TemporaryDirectory() as tempdir:
            folder=Path(tempdir)
            generated=folder/'gpu-mocked-output.mp4'
            shutil.copyfile(self.video,generated)
            captured=[]
            def fake_backend(path,data=None):
                r=self.worker('/'+path,data)
                if r.status_code>=400:raise RuntimeError('Simulated HTTP '+str(r.status_code)+': '+r.text)
                return r.json()
            def fake_download(url,path,limit):
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(self.reference if 'reference' in path.name else self.video.read_bytes())
            def fake_post_graph(graph):
                captured.append(graph)
                return 'simulated-gpu-prompt-id'
            def fake_upload(url,path):
                self.assertTrue(url.startswith('https://'))
                self.r2.objects[claimed['output_key']]=(path.read_bytes(),'video/mp4')
            with patch.object(worker,'BACKEND','https://fake.example'), \
                 patch.object(worker,'INPUT_DIR',folder), \
                 patch.object(worker,'OUTPUT_DIR',folder), \
                 patch.object(worker,'backend',side_effect=fake_backend), \
                 patch.object(worker,'download',side_effect=fake_download), \
                 patch.object(worker,'runtime_ready',return_value=[]), \
                 patch.object(worker,'make_graph',return_value=({'1':{'inputs':{},'class_type':'GPU_SIMULATION'}},
                                                               {'width':320,'height':240})), \
                 patch.object(worker,'post_graph',side_effect=fake_post_graph), \
                 patch.object(worker,'wait_graph',return_value=generated), \
                 patch.object(worker,'upload_file',side_effect=fake_upload):
                worker.handle(claimed)
            self.assertEqual(len(captured),1)
            stored=self.client.get('/api/v2/character-replace/jobs/'+job_id).json()
            self.assertEqual(stored['state'],'succeeded',stored)
            file=self.client.get('/api/v2/character-replace/jobs/'+job_id+'/result')
            self.assertEqual(file.status_code,200,file.text)
            self.assertGreater(len(file.content),1024)
            out=folder/'returned.mp4';out.write_bytes(file.content)
            info=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                                 '-of','csv=p=0',str(out)],capture_output=True,text=True,check=True)
            self.assertTrue(0<float(info.stdout)<2)

    def test_06_presign_error_must_not_claim(self):
        with self.api.db.connect() as c:c.execute("UPDATE cr_jobs SET state='cancelled' WHERE state='queued'")
        job_id,_=self.make_job('presign-rollback')
        with patch.object(self.r2,'generate_presigned_url',side_effect=RuntimeError('signer failure')):
            with self.assertRaises(RuntimeError):self.worker('/claim')
        current=self.client.get('/api/v2/character-replace/jobs/'+job_id).json()
        self.assertEqual(current['state'],'queued')

if __name__=='__main__':
    from unittest import main
    main()
