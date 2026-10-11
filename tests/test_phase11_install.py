import importlib.util,sys,sqlite3,hashlib
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
def import_file(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
installer=import_file('p11installer',ROOT/'scripts/phase11_prepare_checkout.py')
copy=import_file('p11copy',ROOT/'scripts/phase11_migrate_copy.py')

def test_worker_patch_inserts_guarded_hook():
 source=('def build_comfy_payload(job):\n    return job\n\n'
         'def work(job):\n    try:\n        pass\n    finally:\n        done.set()\n        thread.join(timeout=3)\n\n'
         'def main():\n    while True:\n                last_hello = time.time()\n')
 updated=installer.worker_patch(source)
 assert 'WORKER_V11_EXECUTION_ENABLED' in updated and 'cleanup_attempt(job)' in updated
 assert 'WORKER_V11_CAPABILITIES_ENABLED' in updated
 compile(updated,'worker.py','exec')
 with pytest.raises(RuntimeError):installer.worker_patch(updated)

def test_docker_patch_preserves_old_worker():
 source='FROM ubuntu\nCOPY --chmod=755 pull_worker.py /opt/qvr-salad/pull_worker.py\nCMD ["run"]\n'
 actual=installer.docker_patch(source)
 assert 'COPY v11_contract.py' in actual and 'COPY --chmod=755 pull_worker.py' in actual
 with pytest.raises(RuntimeError):installer.docker_patch(actual)

def test_source_pins_not_blind():
 assert installer.BASE=='41b11228bc4728b2781966eafb6d23fe1831cb2f'
 assert installer.BLOBS['salad-worker/pull_worker.py']=='3bfae4b8d14412948e6b07134d3f902e2ca69630'
 assert len(set(installer.BLOBS))==len(installer.BLOBS)

def test_copy_migration_preserves_source(tmp_path):
 source=tmp_path/'main.db';dest=tmp_path/'copy.db'
 conn=sqlite3.connect(source)
 conn.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,owner_user_id TEXT)')
 conn.execute('CREATE TABLE job_attempts(id TEXT PRIMARY KEY,job_id TEXT)')
 conn.execute('CREATE TABLE schema_migrations(revision TEXT PRIMARY KEY,applied_at TEXT,checksum TEXT)')
 conn.commit();conn.close()
 original=copy.sha(source)
 assert copy.copy_and_migrate(source,dest,ROOT)
 assert copy.sha(source)==original and dest.is_file()
 with sqlite3.connect(dest) as c:assert c.execute("SELECT count(*) FROM sqlite_master WHERE name='worker_v11_attempts'").fetchone()[0]==1
 with pytest.raises(RuntimeError):copy.copy_and_migrate(source,dest,ROOT)

def test_copy_rejects_same_path(tmp_path):
 db=tmp_path/'same.db';sqlite3.connect(db).close()
 with pytest.raises(RuntimeError):copy.copy_and_migrate(db,db,ROOT)
