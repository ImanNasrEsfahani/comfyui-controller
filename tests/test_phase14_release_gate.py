from pathlib import Path
import importlib.util,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('phase14_gate',ROOT/'scripts/phase14_release_gate.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

def fixture(tmp_path):
    for i,name in g.PHASES.items():
        folder=tmp_path/f'docs/phase-{i:02d}-{name}';folder.mkdir(parents=True)
        (folder/'HANDOFF.md').write_text('Status: PARTIAL / BLOCKED; no GPU E2E')
    return tmp_path

def test_missing_or_partial_fails_closed(tmp_path):
    inventory=g.inventory(fixture(tmp_path));assert len(inventory['phases'])==14
    assert all(p['status']=='PARTIAL/BLOCKED' for p in inventory['phases'])
    assert inventory['release_status']=='BLOCKED'
    assert all(v['status']=='NOT RUN' for v in inventory['external_gates'].values())

def test_fake_evidence_cannot_override(tmp_path):
    root=fixture(tmp_path);ev=root/'fake';ev.mkdir()
    (ev/'gpu.json').write_text('{"status":"PASS","source":"user_claim"}')
    report=g.inventory(root,evidence=ev)
    assert report['release_status']=='BLOCKED' and report['submitted_evidence_files_unverified']==['gpu.json']

def test_docs_presence_not_release_proof(tmp_path):
    root=fixture(tmp_path)
    for f in g.REQUIRED_DOCUMENTS:(root/f).write_text('approved')
    assert all(g.inventory(root)['decision_files'].values())
    assert g.inventory(root)['release_status']=='BLOCKED'

def test_missing_phase_reported(tmp_path):
    x=g.inventory(tmp_path);assert len(x['phases'])==14 and all(p['status']=='NOT RUN' for p in x['phases'])

def test_unverified_handoff_not_promoted():
    assert g.source_status('All tests passed in unit fixtures')=='UNVERIFIED'
    assert g.source_status('not DONE_VERIFIED')=='PARTIAL/BLOCKED'

def test_cli_enforce_exits_nonzero(tmp_path):
    r=subprocess.run([sys.executable,str(ROOT/'scripts/phase14_release_gate.py'),'--repo',str(fixture(tmp_path)),
                      '--enforce'],capture_output=True,text=True)
    assert r.returncode==2 and 'RELEASE REFUSED' in r.stderr

def test_cli_writes_report(tmp_path):
    out=tmp_path/'report.json';r=subprocess.run([sys.executable,str(ROOT/'scripts/phase14_release_gate.py'),
                  '--repo',str(tmp_path),'--output',str(out)],capture_output=True,text=True)
    assert r.returncode==0 and json.loads(out.read_text())['release_status']=='BLOCKED'
