from pathlib import Path
import hashlib,io,importlib.util,subprocess,tempfile
import pytest,types,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app import video_storage as module
from app.video_pipeline import VideoError
@pytest.fixture(scope='module')
def sample():
 with tempfile.TemporaryDirectory() as d:
  path=Path(d)/'video.mp4'
  subprocess.run(['ffmpeg','-loglevel','error','-f','lavfi','-i','color=blue:size=128x128:rate=12',
    '-t','1','-c:v','libx264','-pix_fmt','yuv420p','-threads','1','-y',str(path)],check=True)
  yield path.read_bytes()
class FakeS3:
 def __init__(self,data,content_type='video/mp4',length=None):
  self.data=data;self.content_type=content_type;self.length=length
 def head_object(self,**kw):return {'ContentLength':len(self.data) if self.length is None else self.length,'ContentType':self.content_type}
 def get_object(self,**kw):return {'Body':io.BytesIO(self.data)}

def test_valid_stream_and_hash(sample):
 r=module.verify_uploaded_video(FakeS3(sample),'bucket','outputs/J/T/clip.mp4',job_id='J',attempt_id='T')
 assert r['verified'] and r['sha256']==hashlib.sha256(sample).hexdigest() and r['width']==128

def test_wrong_attempt_prefix(sample):
 with pytest.raises(VideoError,match='INVALID_R2_OUTPUT_PREFIX'):
  module.verify_uploaded_video(FakeS3(sample),'bucket','outputs/J/other/clip.mp4',job_id='J',attempt_id='T')

def test_fake_size(sample):
 with pytest.raises(VideoError,match='VIDEO_R2_LENGTH_MISMATCH'):
  module.verify_uploaded_video(FakeS3(sample,length=len(sample)+12),'bucket','outputs/J/T/clip.mp4',job_id='J',attempt_id='T')

def test_fake_content_type(sample):
 with pytest.raises(VideoError,match='VIDEO_MIME_MISMATCH'):
  module.verify_uploaded_video(FakeS3(sample,content_type='image/png'),'bucket','outputs/J/T/clip.mp4',job_id='J',attempt_id='T')

def test_corrupted_bytes():
 with pytest.raises(VideoError):module.verify_uploaded_video(FakeS3(b'Z'*300),'bucket','outputs/J/T/clip.mp4',job_id='J',attempt_id='T')

def test_invalid_ids(sample):
 with pytest.raises(VideoError,match='INVALID_ATTEMPT_ID'):
  module.verify_uploaded_video(FakeS3(sample),'bucket','outputs/J/T/clip.mp4',job_id='../J',attempt_id='T')
