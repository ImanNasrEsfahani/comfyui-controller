import React, { useEffect, useMemo, useState } from "react";

const API = import.meta.env.VITE_API_BASE || "/api";

async function api(path, options = {}) {
  const r = await fetch(`${API}${path}`, options);
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status}: ${body}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

const blankWorkflow = JSON.stringify({
  "1": {
    "class_type": "LoadImage",
    "inputs": {
      "image": "{{input.image_1}}",
      "upload": "image"
    }
  }
}, null, 2);

export default function App() {
  const [workflows, setWorkflows] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [workflowId, setWorkflowId] = useState("");
  const [workflowName, setWorkflowName] = useState("");
  const [workflowJson, setWorkflowJson] = useState(blankWorkflow);
  const [variables, setVariables] = useState(JSON.stringify({
    "input.image_1": ""
  }, null, 2));
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function refreshWorkflows() {
    const data = await api("/workflows");
    setWorkflows(data);
    if (!selected && data[0]) setSelected(data[0].id);
  }

  async function refreshJobs() {
    setJobs(await api("/jobs?limit=30"));
  }

  useEffect(() => {
    refreshWorkflows().catch(e => setMessage(e.message));
    refreshJobs().catch(e => setMessage(e.message));
    const t = setInterval(() => refreshJobs().catch(() => {}), 6000);
    return () => clearInterval(t);
  }, []);

  async function saveWorkflow() {
    setBusy(true);
    setMessage("");
    try {
      const parsed = JSON.parse(workflowJson);
      if (!workflowId.trim()) throw new Error("Workflow ID is required");
      await api(`/workflows/${encodeURIComponent(workflowId.trim())}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          id: workflowId.trim(),
          name: workflowName.trim() || workflowId.trim(),
          api_prompt: parsed
        })
      });
      setMessage("Workflow saved.");
      await refreshWorkflows();
      setSelected(workflowId.trim());
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadWorkflow(id) {
    setSelected(id);
    if (!id) return;
    try {
      const w = await api(`/workflows/${encodeURIComponent(id)}`);
      setWorkflowId(w.id);
      setWorkflowName(w.name);
      setWorkflowJson(JSON.stringify(w.api_prompt, null, 2));
    } catch (e) {
      setMessage(e.message);
    }
  }

  async function uploadFile(file) {
    if (!file) return;
    setBusy(true);
    setMessage("Uploading...");
    try {
      const form = new FormData();
      form.append("file", file);
      const out = await api("/uploads", {method: "POST", body: form});
      const vars = JSON.parse(variables || "{}");
      vars["input.image_1"] = out.url;
      setVariables(JSON.stringify(vars, null, 2));
      setMessage("Upload complete. input.image_1 was filled with a signed R2 URL.");
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!selected) return setMessage("Choose a workflow first.");
    setBusy(true);
    setMessage("");
    try {
      const vars = JSON.parse(variables || "{}");
      const out = await api("/jobs", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workflow_id: selected, variables: vars})
      });
      setMessage(`Submitted: ${out.id}`);
      await refreshJobs();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }

  const selectedName = useMemo(
    () => workflows.find(w => w.id === selected)?.name || selected,
    [workflows, selected]
  );

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">Always-on controller</p>
          <h1>Qwen / ComfyUI</h1>
          <p className="muted">
            Edit configuration here. GPU compute runs only through the Salad queue.
          </p>
        </div>
        <div className="status">
          <span className="dot"></span>
          Controller online
        </div>
      </header>

      {message && <div className="notice">{message}</div>}

      <section className="grid">
        <article className="card">
          <h2>1. Workflow library</h2>
          <label>Saved workflow</label>
          <select value={selected} onChange={e => loadWorkflow(e.target.value)}>
            <option value="">Choose...</option>
            {workflows.map(w => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </select>

          <div className="two">
            <div>
              <label>ID</label>
              <input value={workflowId} onChange={e => setWorkflowId(e.target.value)}
                     placeholder="01-general-editor" />
            </div>
            <div>
              <label>Name</label>
              <input value={workflowName} onChange={e => setWorkflowName(e.target.value)}
                     placeholder="General Editor" />
            </div>
          </div>

          <label>ComfyUI API Format JSON</label>
          <textarea className="code large" value={workflowJson}
                    onChange={e => setWorkflowJson(e.target.value)} />

          <button disabled={busy} onClick={saveWorkflow}>Save workflow</button>
        </article>

        <article className="card">
          <h2>2. Inputs & Run</h2>
          <p className="muted">
            Selected: <strong>{selectedName || "none"}</strong>
          </p>

          <label>Upload Image 1</label>
          <input type="file" accept="image/*" onChange={e => uploadFile(e.target.files?.[0])} />

          <label>Variables JSON</label>
          <textarea className="code" value={variables}
                    onChange={e => setVariables(e.target.value)} />

          <p className="hint">
            Placeholder example: <code>{"{{input.image_1}}"}</code>
          </p>

          <button className="primary" disabled={busy || !selected} onClick={run}>
            Run on Salad GPU
          </button>
        </article>
      </section>

      <section className="card jobs">
        <div className="row">
          <h2>3. Recent jobs</h2>
          <button className="ghost" onClick={refreshJobs}>Refresh</button>
        </div>

        <div className="joblist">
          {jobs.length === 0 && <p className="muted">No jobs yet.</p>}
          {jobs.map(j => (
            <Job key={j.id} job={j} />
          ))}
        </div>
      </section>
    </main>
  );
}

function Job({job}) {
  const images = collectImages(job.output);
  return (
    <div className="job">
      <div>
        <strong>{job.workflow_id}</strong>
        <div className="mono">{job.id}</div>
      </div>
      <span className={`pill ${job.state}`}>{job.state}</span>
      <div className="outputs">
        {images.map((u, i) => (
          <a key={i} href={u} target="_blank" rel="noreferrer">output {i + 1}</a>
        ))}
      </div>
    </div>
  );
}

function collectImages(value) {
  const found = [];
  function walk(v) {
    if (Array.isArray(v)) return v.forEach(walk);
    if (v && typeof v === "object") return Object.values(v).forEach(walk);
    if (typeof v === "string" && /^https?:\/\//.test(v)) {
      if (/\.(png|jpe?g|webp)(\?|$)/i.test(v) || v.includes("X-Amz-")) found.push(v);
    }
  }
  walk(value);
  return [...new Set(found)].slice(0, 8);
}
