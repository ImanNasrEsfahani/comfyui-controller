from pathlib import Path
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('phase14_redact',ROOT/'scripts/phase14_redact.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_redact_obvious_secrets():
 text='Authorization: Bearer abcXYZ_123\nDIRECT_WORKER_TOKEN=def456\npassword: supersecret'
 out=m.redact(text)
 assert 'abcXYZ' not in out and 'def456' not in out and 'supersecret' not in out

def test_signed_url_query_stripped():
 text='https://example.com/obj?X-Amz-Signature=abcdef&x=1'
 assert 'abcdef' not in m.redact(text)

def test_innocent_test_status_preserved():
 assert m.redact('17 passed, 2 not run')=='17 passed, 2 not run'
