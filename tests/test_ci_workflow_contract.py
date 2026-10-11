"""Static non-network checks preventing duplicate CI and accidental provider deploy."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CI=ROOT/'.github/workflows/test-direct-queue.yml'
MANUAL=ROOT/'.github/workflows/phase14-release-gate.yml'
WORKER=ROOT/'.github/workflows/build-salad-worker.yml'

def test_single_automatic_regression_entrypoint():
 a=CI.read_text();b=MANUAL.read_text()
 assert 'on:\n  push:' in a and 'pull_request:' in a
 assert 'on:\n  workflow_dispatch:' in b
 assert '  push:' not in b and '  pull_request:' not in b
 assert 'cancel-in-progress: true' in a

def test_python_frontend_both_required():
 text=CI.read_text()
 assert 'ci_python_matrix.py' in text and 'ci_fixture_fixes.py' in text
 assert 'node --test tests/*.mjs' in text and 'ci_node_report.py' in text
 assert 'npm --prefix frontend run build' in text
 assert 'needs: [python-and-worker, frontend]' in text
 assert 'test "$PYTHON_RESULT" = success' in text
 assert 'test "$FRONTEND_RESULT" = success' in text

def test_no_runtime_deploy_actions_in_auto_ci():
 text=CI.read_text()
 for bad in ('docker compose up','docker push','salad deploy','kubectl apply','--apply'):
  assert bad not in text
 assert 'phase14_release_gate.py' in text

def test_worker_build_explicit_authorization():
 text=WORKER.read_text()
 assert 'confirm_build_and_push' in text
 assert 'workflow_dispatch:' in text
 assert '\non:\n  push:' not in text
