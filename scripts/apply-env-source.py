#!/usr/bin/env python3
"""Adapt the existing GitHub frontend + SQLite module to .env-based settings.

Run once in a full comfyui-controller checkout BEFORE committing to GitHub.
The script is idempotent, does not need credentials, and aborts on unfamiliar code.
"""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
frontend = root / "frontend/src/App.jsx"
db = root / "backend/app/db.py"
source = frontend.read_text(encoding="utf-8")

if "const PRIORITY_OPTIONS" in source:
    source, n = re.subn(r"const PRIORITY_OPTIONS = \[\s*.*?\n\];\n\n", "", source, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("Unknown priority-options block in App.jsx; no files were changed")

if 'const [priority, setPriority] = useState("medium");' in source:
    source = source.replace(
        'const [priority, setPriority] = useState("medium");',
        'const [priority, setPriority] = useState("");\n  const [gpuName, setGpuName] = useState("");'
    )
elif 'const [priority, setPriority] = useState("");' not in source:
    raise SystemExit("Unknown priority state in App.jsx; no files were changed")

# If the original UI was previously patched to one fixed Medium option,
# it still has the useMemo block below. Delete it in either case.
help_block = '''  const priorityHelp = useMemo(
    () => PRIORITY_OPTIONS.find(p => p.value === priority)?.help || "",
    [priority]
  );

'''
source = source.replace(help_block, "")

start_effect = '''  useEffect(() => {
    refreshWorkflows().catch(e => setMessage(e.message));'''
new_effect = '''  useEffect(() => {
    fetch("/health")
      .then(async response => {
        if (!response.ok) throw new Error(`Health check returned ${response.status}`);
        return response.json();
      })
      .then(data => {
        if (!data.default_priority) throw new Error("Backend did not return a priority");
        setPriority(data.default_priority);
        setGpuName(data.gpu_name || "");
      })
      .catch(e => setMessage(`Unable to load GPU settings: ${e.message}`));
    refreshWorkflows().catch(e => setMessage(e.message));'''
if start_effect in source:
    source = source.replace(start_effect, new_effect, 1)
elif 'fetch("/health")' not in source:
    raise SystemExit("Unknown startup effect in App.jsx; no files were changed")

old_picker = '''          <label>GPU priority for this run</label>
          <select value={priority} onChange={e => setPriority(e.target.value)}>
            {PRIORITY_OPTIONS.map(item => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>

          <p className="hint">{priorityHelp}</p>'''
new_picker = '''          <label>GPU configuration (from server .env)</label>
          <p className="hint">
            {priority ? `${priority}${gpuName ? ` · ${gpuName}` : ""}` : "Loading server GPU settings..."}
          </p>'''
if old_picker in source:
    source = source.replace(old_picker, new_picker, 1)
elif new_picker not in source:
    raise SystemExit("Unknown priority picker in App.jsx; no files were changed")

original_disabled = 'disabled={busy || Boolean(uploadingKey) || !selected || missingImages.length > 0}'
new_disabled = 'disabled={busy || Boolean(uploadingKey) || !selected || missingImages.length > 0 || !priority}'
if original_disabled in source:
    source = source.replace(original_disabled, new_disabled, 1)
elif new_disabled not in source:
    raise SystemExit("Unknown run-button condition in App.jsx; no files were changed")

source = source.replace('<Job key={j.id} job={j} />', '<Job key={j.id} job={j} fallbackPriority={priority} />')
source = source.replace('function Job({ job }) {', 'function Job({ job, fallbackPriority }) {')
source = source.replace('job.priority || "medium"', 'job.priority || fallbackPriority || ""')
if 'function Job({ job, fallbackPriority }) {' not in source:
    raise SystemExit("Unknown Job component in App.jsx; no files were changed")

old_db = db.read_text(encoding="utf-8")
new_db = old_db.replace(
    '''c.execute("ALTER TABLE jobs ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium'")''',
    '''# Priority for historic rows is read from the currently configured .env.
            c.execute(
                f"ALTER TABLE jobs ADD COLUMN priority TEXT NOT NULL DEFAULT '{settings.salad_priority}'"
            )'''
)
new_db = new_db.replace(
    'def create_job(local_id, workflow_id, request_payload, *, priority="medium", salad_queue=None):\n    now = utcnow()',
    'def create_job(local_id, workflow_id, request_payload, *, priority=None, salad_queue=None):\n    priority = priority or settings.salad_priority\n    now = utcnow()'
)
if "DEFAULT 'medium'" in new_db or 'priority="medium"' in new_db:
    raise SystemExit("Unrecognized old priority in db.py; no files were changed")

frontend.write_text(source, encoding="utf-8")
db.write_text(new_db, encoding="utf-8")
print("Frontend now reads priority/GPU from backend /health; db.py uses .env priority")
print("Changed:", frontend)
print("Changed:", db)
