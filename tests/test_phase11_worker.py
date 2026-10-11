from __future__ import annotations
import hashlib,io,importlib.util,os,sqlite3,sys,time
from pathlib import Path
import pytest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'salad-worker'))

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

contract=load('phase11_contract_backend',ROOT/'backend/app/worker_v11_contract.py')
worker_contract=load('v11_contract',ROOT/'salad-worker/v11_contract.py')
execution=load('v11_execution',ROOT/'salad-worker/v11_execution.py')
cache=load('v11_cache',ROOT/'salad-worker/v11_cache.py')
media=load('worker_v11_media',ROOT/'backend/app/worker_v11_media.py')
migration=load('phase11_migration',ROOT/'backend/app/migrations/phase11.py')
state=load('phase11_state',ROOT/'backend/app/worker_v11_state.py')
SECRET='s'*45; TOKEN='x'*48
DIGEST='ghcr.io/company/qwen-edit@sha256:'+'a'*64

def image_data():
    img=Image.new('RGB',(8,12),color=(20,30,40));out=io.BytesIO();img.save(out,format='PNG');return out.getvalue()

DATA=image_data()

def body():
    graph={'txt':{'class_type':'TextEncoder','inputs':{'prompt':'A palace'}},
           'image':{'class_type':'LoadImage','inputs':{'image':{'asset_slot':'identity'}}},
           'sampler':{'class_type':'Sampler','inputs':{'conditioning':['txt','TEXT'],'image':['image','IMAGE']}}}
    return dict(version=11,job_id='job-one',attempt_id='attempt-one',lease_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
         worker_image_digest=DIGEST,model_version_id='qwen-model-v1',workflow_version_id='workflow-v1',
         deployment_revision_id='deploy-v1',compiled_graph=graph,compiled_graph_sha256=contract.digest(graph),
         inputs=[dict(asset_id='asset-one',slot='identity',role='identity',key='inputs/user1/asset-1.png',
                      sha256=hashlib.sha256(DATA).hexdigest(),size_bytes=len(DATA),mime_type='image/png')],
         loras=[],output_prefix='outputs/job-one/attempt-one/',issued_at=1000,expires_at=1450)

def check(e,now=1100,which=worker_contract):
    return which.verify(e,SECRET,lease_token=TOKEN,worker_image_digest=DIGEST,ready_models={'qwen-model-v1'},
                        ready_loras=set(),node_inventory={'TextEncoder','LoadImage','Sampler'},now=now)

class R2:
    def __init__(self,objects):self.objects=objects
    def get_object(self,*,Bucket,Key):return {'Body':io.BytesIO(self.objects[Key])}
    def head_object(self,*,Bucket,Key):
        return {'ContentLength':len(self.objects[Key]),'ContentType':'image/png'}

def test_protocol_exact_copy():assert (ROOT/'salad-worker/v11_contract.py').read_bytes()==(ROOT/'backend/app/worker_v11_contract.py').read_bytes()
def test_valid_signed():assert check(contract.sign(body(),SECRET))['job_id']=='job-one'
def test_mutated_signature():
    e=contract.sign(body(),SECRET);e['payload']['compiled_graph']['txt']['inputs']['prompt']='hacked'
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation)):check(e)
def test_lease_fence():
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation)):worker_contract.verify(contract.sign(body(),SECRET),SECRET,lease_token='y'*48,worker_image_digest=DIGEST,ready_models={'qwen-model-v1'},ready_loras=set(),node_inventory={'TextEncoder','LoadImage','Sampler'},now=1100)
def test_expired():
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='expired'):check(contract.sign(body(),SECRET),now=1500)
def test_image_downgrade():
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='wrong_worker_image'):
        worker_contract.verify(contract.sign(body(),SECRET),SECRET,lease_token=TOKEN,worker_image_digest=DIGEST.replace('a'*64,'b'*64),ready_models={'qwen-model-v1'},ready_loras=set(),node_inventory={'TextEncoder','LoadImage','Sampler'},now=1100)
def test_model_unready():
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='model_not_verified_ready'):
        worker_contract.verify(contract.sign(body(),SECRET),SECRET,lease_token=TOKEN,worker_image_digest=DIGEST,ready_models=set(),ready_loras=set(),node_inventory={'TextEncoder','LoadImage','Sampler'},now=1100)
def test_untrusted_node():
    b=body();b['compiled_graph']['image']['class_type']='ShellScript';b['compiled_graph_sha256']=contract.digest(b['compiled_graph'])
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='unapproved_node'):check(contract.sign(b,SECRET))
def test_cross_slot():
    b=body();b['compiled_graph']['image']['inputs']['image']={'asset_slot':'other'};b['compiled_graph_sha256']=contract.digest(b['compiled_graph'])
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='unbound_asset_slot'):check(contract.sign(b,SECRET))
def test_storage_escape():
    b=body();b['inputs'][0]['key']='inputs/user1/../../other.png'
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='storage'):check(contract.sign(b,SECRET))
def test_secret_url_not_allowed():
    b=body();b['compiled_graph']['txt']['inputs']['prompt']='https://malicious.example/secret';b['compiled_graph_sha256']=contract.digest(b['compiled_graph'])
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='unsafe_input'):check(contract.sign(b,SECRET))
def test_lora_not_attested():
    b=body();b['loras']=[{'id':'lora-one','sha256':'b'*64,'enabled':True,'model_strength':1.2,'clip_strength':0.7,'order':0}]
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='unready_lora'):check(contract.sign(b,SECRET))
def test_disabled_lora_cannot_execute():
    b=body();b['loras']=[{'id':'lora-one','sha256':'b'*64,'enabled':False,'model_strength':1,'clip_strength':1,'order':0}]
    with pytest.raises((contract.ContractViolation,worker_contract.ContractViolation),match='disabled_lora'):worker_contract.verify(contract.sign(b,SECRET),SECRET,lease_token=TOKEN,worker_image_digest=DIGEST,ready_models={'qwen-model-v1'},ready_loras={('lora-one','b'*64)},node_inventory={'TextEncoder','LoadImage','Sampler'},now=1100)
def test_valid_lora():
    b=body();b['loras']=[{'id':'lora-one','sha256':'b'*64,'enabled':True,'model_strength':0.6,'clip_strength':0.7,'order':0}]
    assert worker_contract.verify(contract.sign(b,SECRET),SECRET,lease_token=TOKEN,worker_image_digest=DIGEST,ready_models={'qwen-model-v1'},ready_loras={('lora-one','b'*64)},node_inventory={'TextEncoder','LoadImage','Sampler'},now=1100)['loras'][0]['model_strength']==0.6

def test_worker_stages_owned_bytes(tmp_path):
    claim=dict(job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,signed_execution=contract.sign(body(),SECRET))
    payload,created=execution.verify_claim(claim,secret=SECRET,worker_image_digest=DIGEST,ready_models={'qwen-model-v1'},ready_loras=set(),node_inventory={'TextEncoder','LoadImage','Sampler'},s3=R2({'inputs/user1/asset-1.png':DATA}),bucket='comfy',input_dir=tmp_path,now=1100)
    assert payload['prompt']['image']['inputs']['image'].startswith('v11_attempt-one_identity')
    assert (tmp_path/payload['prompt']['image']['inputs']['image']).read_bytes()==DATA
    assert payload['s3']['prefix']=='outputs/job-one/attempt-one/'
    execution.cleanup(created);assert list(tmp_path.iterdir())==[]
def test_worker_rejects_modified_r2(tmp_path):
    claim=dict(job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,signed_execution=contract.sign(body(),SECRET))
    with pytest.raises(execution.StageError,match='integrity'):execution.verify_claim(claim,secret=SECRET,worker_image_digest=DIGEST,ready_models={'qwen-model-v1'},ready_loras=set(),node_inventory={'TextEncoder','LoadImage','Sampler'},s3=R2({'inputs/user1/asset-1.png':b'fake'}),bucket='comfy',input_dir=tmp_path,now=1100)
    assert list(tmp_path.iterdir())==[]
def test_unsigned_worker_claim(tmp_path):
    with pytest.raises(execution.StageError,match='unsigned'):execution.verify_claim({'lease_token':TOKEN},secret=SECRET,worker_image_digest=DIGEST,ready_models=set(),ready_loras=set(),node_inventory={'TextEncoder'},s3=R2({}),bucket='comfy',input_dir=tmp_path)

def test_cache_verified_reuse(tmp_path):
    calls=[]
    def download(item,out):calls.append(item['id']);out.write(DATA)
    c=cache.ArtifactCache(tmp_path,trusted_hosts={'huggingface.co'},fetcher=download)
    item={'id':'model-a','sha256':hashlib.sha256(DATA).hexdigest(),'size_bytes':len(DATA),'url':'https://huggingface.co/approved/path'}
    assert c.ensure(item)==c.ensure(item)
    assert len(calls)==1
def test_cache_bad_digest_never_published(tmp_path):
    c=cache.ArtifactCache(tmp_path,trusted_hosts={'huggingface.co'},fetcher=lambda item,out:out.write(b'bad'))
    item={'id':'model-a','sha256':hashlib.sha256(DATA).hexdigest(),'size_bytes':len(DATA),'url':'https://huggingface.co/safe'}
    with pytest.raises(cache.ArtifactError):c.ensure(item)
    assert not list(tmp_path.iterdir())
def test_cache_external_url_blocked(tmp_path):
    c=cache.ArtifactCache(tmp_path,trusted_hosts={'huggingface.co'},fetcher=lambda item,out:None)
    with pytest.raises(cache.ArtifactError):c.ensure({'id':'a','sha256':'b'*64,'size_bytes':12,'url':'https://evil.example/model'})

def test_png_real_decode():
    m=media.verify_media_bytes(DATA,'png',claimed_mime='image/png')
    assert (m['width'],m['height'],m['size_bytes'])==(8,12,len(DATA))
def test_mime_spoof_rejected():
    with pytest.raises(media.MediaViolation):media.verify_media_bytes(b'not a png','png',claimed_mime='image/png')
def test_truncated_png_rejected():
    with pytest.raises(media.MediaViolation):media.verify_media_bytes(DATA[:36],'png')
def test_mime_conflict_rejected():
    with pytest.raises(media.MediaViolation,match='mime'):media.verify_media_bytes(DATA,'png',claimed_mime='video/mp4')
def test_video_needs_probe():
    with pytest.raises(media.MediaViolation,match='video_probe'):media.verify_media_bytes(b'\x00\x00\x00\x20ftyp'+b' '*40,'mp4')
def test_mixed_partial_output(tmp_path):
    key1='outputs/job-one/attempt-one/01.png'; key2='outputs/job-one/attempt-one/02.png'
    result=media.verify_output_objects(R2({key1:DATA,key2:b'bad'}),'comfy',job_id='job-one',attempt_id='attempt-one',keys=[key1,key2])
    assert [x['status'] for x in result]==['available','unavailable']
def test_cross_attempt_output():
    with pytest.raises(media.MediaViolation,match='prefix'):
        media.verify_output_objects(R2({}),'comfy',job_id='job-one',attempt_id='attempt-one',keys=['outputs/job-one/old-attempt/01.png'])

@pytest.fixture
def conn():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
    c.execute('''CREATE TABLE jobs(id TEXT PRIMARY KEY,owner_user_id TEXT,ownership_state TEXT,hidden INTEGER,
      active_attempt_id TEXT,lease_token_hash TEXT,lease_deadline REAL,state TEXT)''')
    c.execute('CREATE TABLE job_attempts(id TEXT PRIMARY KEY,job_id TEXT REFERENCES jobs(id))')
    c.execute('CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT)')
    c.execute("INSERT INTO jobs VALUES('job-one','user-a','verified',0,'attempt-one',? ,1300,'running')",(hashlib.sha256(TOKEN.encode()).hexdigest(),))
    c.execute("INSERT INTO job_attempts VALUES('attempt-one','job-one')")
    c.commit()
    assert migration.migrate(c)
    return c

def test_migration_reentrant(conn):assert not migration.migrate(conn)
def test_migration_immutable_observations(conn):
    conn.execute("INSERT INTO worker_v11_observations VALUES('id1','worker','g','d','r',0,'[]','[]','[]','date')")
    with pytest.raises(sqlite3.IntegrityError):conn.execute("DELETE FROM worker_v11_observations")
def test_migration_requires_job_schema():
    c=sqlite3.connect(':memory:');c.execute('CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT)')
    with pytest.raises(RuntimeError):migration.migrate(c)
def test_state_fenced_progress_and_complete(conn):
    state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
    state.progress(conn,'job-one','attempt-one',TOKEN,1,'sampling',now=1100)
    with pytest.raises(state.StaleLease):state.progress(conn,'job-one','attempt-one',TOKEN,1,'sampling',now=1100)
    receipt=[{'key':'outputs/job-one/attempt-one/image.png','status':'available','sha256':'a'*64,'size_bytes':len(DATA)}]
    assert state.finish(conn,'job-one','attempt-one',TOKEN,receipt,now=1100)
    assert state.finish(conn,'job-one','attempt-one',TOKEN,receipt,now=1100)
    assert not state.finish(conn,'job-one','attempt-one',TOKEN,receipt+[receipt[0]],now=1100)
    assert conn.execute('SELECT count(*) FROM worker_v11_verified_outputs').fetchone()[0]==1
def test_state_partial_refused(conn):
    state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
    with pytest.raises(state.StaleLease):state.finish(conn,'job-one','attempt-one',TOKEN,[{'status':'unavailable'}],now=1100)
def test_state_cancel_is_not_instant(conn):
    state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
    state.cancel_requested(conn,'job-one','attempt-one',TOKEN,now=1100)
    assert conn.execute('SELECT state FROM worker_v11_attempts').fetchone()[0]=='cancel_requested'
    with pytest.raises(state.StaleLease):state.finish(conn,'job-one','attempt-one',TOKEN,[{'status':'available','key':'outputs/job-one/attempt-one/x.png','sha256':'a'*64,'size_bytes':5}],now=1100)
    assert state.cancel_confirmed(conn,'job-one','attempt-one',TOKEN,now=1100)
def test_expired_lease_rejected(conn):
    state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
    with pytest.raises(state.StaleLease):state.progress(conn,'job-one','attempt-one',TOKEN,1,'sampling',now=1400)
def test_late_attempt_fenced(conn):
    conn.execute("INSERT INTO job_attempts VALUES('attempt-two','job-one')")
    state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
    conn.execute("UPDATE jobs SET active_attempt_id='attempt-two',lease_token_hash=? WHERE id='job-one'",(hashlib.sha256(('y'*48).encode()).hexdigest(),))
    state.begin(conn,job_id='job-one',attempt_id='attempt-two',lease_token='y'*48,worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
    with pytest.raises(state.StaleLease):state.progress(conn,'job-one','attempt-one',TOKEN,1,'sampling',now=1100)
    state.progress(conn,'job-one','attempt-two','y'*48,1,'sampling',now=1100)
def test_unowned_job_refused(conn):
    conn.execute("UPDATE jobs SET owner_user_id=NULL WHERE id='job-one'")
    with pytest.raises(state.StaleLease):state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)

def test_cache_symlink_root_refused(tmp_path):
    other=tmp_path/'real';other.mkdir();link=tmp_path/'link';link.symlink_to(other,target_is_directory=True)
    with pytest.raises(cache.ArtifactError,match='symlink'):
        cache.ArtifactCache(link,trusted_hosts={'huggingface.co'})

def test_wrong_receipt_stale_token(conn):
    state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
    with pytest.raises(state.StaleLease):state.progress(conn,'job-one','attempt-one','z'*48,1,'sampling',now=1100)
    assert conn.execute('SELECT last_sequence FROM worker_v11_attempts').fetchone()[0]==0

owner=load('phase11_owner',ROOT/'backend/app/worker_v11_owner.py')

def test_controller_verifies_asset_owner_and_slot_before_signing():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,owner_user_id TEXT,ownership_state TEXT,hidden INT,active_attempt_id TEXT)')
    c.execute('CREATE TABLE job_input_assets(job_id TEXT,owner_user_id TEXT,asset_id TEXT,slot_key TEXT,role TEXT,position INT)')
    c.execute('CREATE TABLE asset_deletions(asset_id TEXT,owner_user_id TEXT)')
    c.execute('CREATE TABLE input_assets(asset_id TEXT,owner_user_id TEXT,ownership_state TEXT,storage_key TEXT,mime_type TEXT,size_bytes INT)')
    c.execute('CREATE TABLE job_assets(asset_id TEXT,owner_user_id TEXT,ownership_state TEXT,status TEXT,job_id TEXT,attempt_id TEXT,storage_key TEXT,mime_type TEXT,size_bytes INT)')
    c.execute("INSERT INTO jobs VALUES('job-one','user-a','verified',0,NULL)")
    c.execute("INSERT INTO jobs VALUES('job-two','user-b','verified',0,NULL)")
    c.execute("INSERT INTO input_assets VALUES('asset-one','user-a','verified','inputs/user1/asset-1.png','image/png',?)",(len(DATA),))
    c.execute("INSERT INTO input_assets VALUES('asset-two','user-b','verified','inputs/user2/asset-2.png','image/png',?)",(len(DATA),))
    c.execute("INSERT INTO job_input_assets VALUES('job-one','user-a','asset-one','identity','identity',0)")
    manifest=owner.authorize_inputs(c,'job-one',[dict(asset_id='asset-one',slot='identity',role='identity',position=0)],r2=R2({'inputs/user1/asset-1.png':DATA}),bucket='comfy')
    assert manifest[0]['sha256']==hashlib.sha256(DATA).hexdigest()
    with pytest.raises(owner.OwnershipViolation):
        owner.authorize_inputs(c,'job-one',[dict(asset_id='asset-two',slot='identity',role='identity',position=0)],r2=R2({'inputs/user2/asset-2.png':DATA}),bucket='comfy')
    with pytest.raises(owner.OwnershipViolation):
        owner.authorize_inputs(c,'job-one',[dict(asset_id='asset-one',slot='pose',role='pose',position=0)],r2=R2({'inputs/user1/asset-1.png':DATA}),bucket='comfy')
    c.execute("INSERT INTO asset_deletions VALUES('asset-one','user-a')")
    with pytest.raises(owner.OwnershipViolation):
        owner.authorize_inputs(c,'job-one',[dict(asset_id='asset-one',slot='identity',role='identity',position=0)],r2=R2({'inputs/user1/asset-1.png':DATA}),bucket='comfy')

def test_old_attempt_rejected_after_controller_pointer_changes(conn):
    state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,
        worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
    conn.execute("UPDATE jobs SET active_attempt_id='some-new-attempt' WHERE id='job-one'")
    with pytest.raises(state.StaleLease,match='controller_lease_changed'):
        state.progress(conn,'job-one','attempt-one',TOKEN,1,'sampling',now=1100)

def test_not_ownership_verified_cannot_start_v11(conn):
    conn.execute("UPDATE jobs SET ownership_state='unclaimed' WHERE id='job-one'")
    with pytest.raises(state.StaleLease,match='unowned'):
        state.begin(conn,job_id='job-one',attempt_id='attempt-one',lease_token=TOKEN,
            worker_image_digest=DIGEST,compiled_graph_sha256='c'*64,deadline=1300,now=1100)
