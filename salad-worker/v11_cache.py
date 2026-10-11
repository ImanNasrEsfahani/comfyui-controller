"""Verified per-container artifact cache; never downloads from a user-provided URL.

An operator-trusted manifest maps opaque artifact IDs to checksums and an HTTPS
URL on a fixed host. In Salad without persistent mounts, this only avoids
redownloads *within the life of this container*, not across cold starts.
"""
from __future__ import annotations
import hashlib
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request,urlopen

ID=re.compile(r'^[a-zA-Z0-9_-]{1,80}$')
HEX=re.compile(r'^[a-f0-9]{64}$')
_LOCK=threading.RLock()

class ArtifactError(ValueError):pass


def hash_file(path):
    h=hashlib.sha256(); size=0
    with open(path,'rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            h.update(chunk);size+=len(chunk)
    return h.hexdigest(),size


def validated_entry(item, trusted_hosts):
    if not isinstance(item,dict) or set(item)!={'id','sha256','size_bytes','url'}:
        raise ArtifactError('manifest shape rejected')
    if not isinstance(item['id'],str) or not ID.fullmatch(item['id']) or not isinstance(item['sha256'],str) or not HEX.fullmatch(item['sha256']):
        raise ArtifactError('invalid artifact identity')
    if type(item['size_bytes']) is not int or not 0<item['size_bytes']<=80*1024**3:
        raise ArtifactError('invalid declared size')
    p=urlparse(item['url'])
    if p.scheme!='https' or p.hostname not in trusted_hosts or p.username or p.password or p.query or p.fragment or p.port not in (None,443):
        raise ArtifactError('untrusted artifact source')
    return item


def default_fetch(item,out):
    # No automatic redirects to untrusted origins. Production ingress must do
    # server-side URL validation on each redirect or use an injected trusted fetcher.
    import urllib.request
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ArtifactError('redirect not allowed')
    opener=urllib.request.build_opener(NoRedirect)
    with opener.open(Request(item['url'],headers={'Accept-Encoding':'identity'}),timeout=60) as res:
        if res.status!=200:raise ArtifactError('download failed')
        remaining=item['size_bytes']
        while remaining:
            chunk=res.read(min(1024*1024,remaining))
            if not chunk:raise ArtifactError('truncated_artifact')
            out.write(chunk)
            remaining-=len(chunk)
        if res.read(1):raise ArtifactError('artifact_larger_than_declared')


class ArtifactCache:
    def __init__(self,root,*,trusted_hosts,fetcher=None):
        requested=Path(root)
        if requested.is_symlink():raise ArtifactError('symlink cache root')
        self.root=requested.resolve();self.trusted_hosts=frozenset(trusted_hosts)
        self.fetcher=fetcher or default_fetch
        if not self.root.exists():self.root.mkdir(parents=True,mode=0o700)
        if self.root.is_symlink():raise ArtifactError('symlink cache root')
    def ensure(self,item):
        item=validated_entry(item,self.trusted_hosts)
        # Deterministic name, independent of user input/file URL basename.
        dest=self.root/(item['id']+'-'+item['sha256']+'.artifact')
        with _LOCK:
            if dest.is_symlink():raise ArtifactError('symlink artifact')
            if dest.is_file():
                if hash_file(dest)==(item['sha256'],item['size_bytes']):return dest
                raise ArtifactError('cached artifact checksum mismatch')
            fd,name=tempfile.mkstemp(prefix='.artifact-',dir=self.root)
            try:
                with os.fdopen(fd,'wb') as out:self.fetcher(item,out)
                if hash_file(name)!=(item['sha256'],item['size_bytes']):raise ArtifactError('download digest or size mismatch')
                os.chmod(name,0o600)
                os.replace(name,dest)
                return dest
            finally:
                if os.path.exists(name):os.unlink(name)
