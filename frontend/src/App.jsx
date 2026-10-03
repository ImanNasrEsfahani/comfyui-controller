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
      "image": "{{input.image_1}}"
    }
  }
}, null, 2);

const TERMINAL_STATES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "submit_failed"
]);

function extractPlaceholders(value) {
  const found = new Set();
  const regex = /\{\{([A-Za-z0-9_.:-]+)\}\}/g;

  function walk(v) {
    if (Array.isArray(v)) {
      v.forEach(walk);
      return;
    }
    if (v && typeof v === "object") {
      Object.values(v).forEach(walk);
      return;
    }
    if (typeof v !== "string") return;

    let match;
    while ((match = regex.exec(v)) !== null) found.add(match[1]);
  }

  walk(value);
  return [...found].sort(variableSort);
}

function variableSort(a, b) {
  const rank = key => {
    if (/^input\.image_\d+$/.test(key)) return 10;
    if (key.startsWith("prompt.")) return 20;
    if (key.includes("seed")) return 30;
    if (key.includes("steps")) return 31;
    if (key.includes("cfg")) return 32;
    if (key.includes("denoise")) return 33;
    if (key.includes("width")) return 40;
    if (key.includes("height")) return 41;
    if (key.startsWith("lora.")) return 50;
    return 100;
  };

  return rank(a) - rank(b) || a.localeCompare(b, undefined, { numeric: true });
}

function defaultValueFor(key) {
  if (/^input\.image_\d+$/.test(key)) return "";
  if (key.startsWith("prompt.")) return "";
  if (/enabled$/i.test(key)) return true;
  if (/seed$/i.test(key) || key.includes(".seed")) return 123456789;
  if (/steps$/i.test(key) || key.includes(".steps")) return 4;
  if (/cfg$/i.test(key) || key.includes(".cfg")) return 1;
  if (/denoise$/i.test(key) || key.includes(".denoise")) return 1;
  if (/width$/i.test(key) || key.includes(".width")) return 1024;
  if (/height$/i.test(key) || key.includes(".height")) return 1024;
  if (/strength/i.test(key)) return 0.8;
  if (/count$/i.test(key)) return 1;
  return "";
}

function normalizeVariables(keys, previous = {}) {
  const next = {};
  keys.forEach(key => {
    if (Object.prototype.hasOwnProperty.call(previous, key)) {
      next[key] = previous[key];
    } else {
      next[key] = defaultValueFor(key);
    }
  });
  return next;
}

function friendlyLabel(key) {
  const imageMatch = key.match(/^input\.image_(\d+)$/);
  if (imageMatch) return `Image ${imageMatch[1]}`;

  const map = {
    "prompt.user": "User prompt",
    "prompt.positive": "Positive prompt",
    "prompt.negative": "Negative prompt",
    "generation.seed": "Seed",
    "generation.steps": "Steps",
    "generation.cfg": "CFG",
    "generation.denoise": "Denoise",
    "output.width": "Output width",
    "output.height": "Output height"
  };

  if (map[key]) return map[key];

  return key
    .replace(/[._:-]+/g, " ")
    .replace(/\b\w/g, m => m.toUpperCase());
}

function variableKind(key, value) {
  if (/^input\.image_\d+$/.test(key)) return "image";
  if (key.startsWith("prompt.")) return "textarea";
  if (typeof value === "boolean" || /enabled$/i.test(key)) return "boolean";
  if (
    typeof value === "number" ||
    /(seed|steps|cfg|denoise|width|height|strength|count)$/i.test(key)
  ) return "number";
  return "text";
}

function numberStep(key) {
  if (/seed|steps|width|height|count/i.test(key)) return "1";
  if (/strength|cfg|denoise/i.test(key)) return "0.01";
  return "any";
}

function loadLocalVariables(workflowId, keys) {
  if (!workflowId) return normalizeVariables(keys);

  try {
    const raw = localStorage.getItem(`comfyui-controller:variables:${workflowId}`);
    if (!raw) return normalizeVariables(keys);

    const saved = JSON.parse(raw);
    const sanitized = { ...saved };

    // Signed upload URLs expire. Never restore image URLs from browser storage.
    keys.filter(k => /^input\.image_\d+$/.test(k)).forEach(k => {
      sanitized[k] = "";
    });

    return normalizeVariables(keys, sanitized);
  } catch {
    return normalizeVariables(keys);
  }
}

function saveLocalVariables(workflowId, variables) {
  if (!workflowId) return;

  try {
    const safe = { ...variables };
    Object.keys(safe).forEach(key => {
      if (/^input\.image_\d+$/.test(key)) safe[key] = "";
    });
    localStorage.setItem(
      `comfyui-controller:variables:${workflowId}`,
      JSON.stringify(safe)
    );
  } catch {
    // Browser storage is optional; ignore quota/privacy-mode failures.
  }
}

export default function App() {
  const [workflows, setWorkflows] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [workflowId, setWorkflowId] = useState("");
  const [workflowName, setWorkflowName] = useState("");
  const [workflowJson, setWorkflowJson] = useState(blankWorkflow);
  const [selected, setSelected] = useState("");
  const [priority, setPriority] = useState("");
  const [gpuName, setGpuName] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploadingKey, setUploadingKey] = useState("");
  const [uploadedNames, setUploadedNames] = useState({});
  const [variables, setVariables] = useState({ "input.image_1": "" });
  const [variablesDraft, setVariablesDraft] = useState(
    JSON.stringify({ "input.image_1": "" }, null, 2)
  );

  const placeholderKeys = useMemo(() => {
    try {
      return extractPlaceholders(JSON.parse(workflowJson));
    } catch {
      // While editing temporarily-invalid JSON, still show placeholders already present.
      return extractPlaceholders(workflowJson);
    }
  }, [workflowJson]);

  const imageKeys = useMemo(
    () => placeholderKeys.filter(key => /^input\.image_\d+$/.test(key)),
    [placeholderKeys]
  );

  const missingImages = useMemo(
    () => imageKeys.filter(key => !String(variables[key] || "").trim()),
    [imageKeys, variables]
  );

  const selectedName = useMemo(
    () => workflows.find(w => w.id === selected)?.name || selected,
    [workflows, selected]
  );

  useEffect(() => {
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
    refreshWorkflows().catch(e => setMessage(e.message));
    refreshJobs().catch(e => setMessage(e.message));

    const t = setInterval(() => {
      refreshJobs().catch(() => {});
    }, 6000);

    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    setVariables(prev => {
      const next = normalizeVariables(placeholderKeys, prev);
      setVariablesDraft(JSON.stringify(next, null, 2));
      return next;
    });
  }, [placeholderKeys.join("|")]);

  useEffect(() => {
    if (selected) saveLocalVariables(selected, variables);
    setVariablesDraft(JSON.stringify(variables, null, 2));
  }, [variables, selected]);

  async function refreshWorkflows() {
    setWorkflows(await api("/workflows"));
  }

  async function refreshJobs() {
    const list = await api("/jobs?limit=30");
    const pending = list
      .filter(job => !TERMINAL_STATES.has(job.state))
      .slice(0, 10);

    if (pending.length === 0) {
      setJobs(list);
      return;
    }

    const refreshed = await Promise.all(
      pending.map(async job => {
        try {
          return await api(`/jobs/${encodeURIComponent(job.id)}`);
        } catch {
          return job;
        }
      })
    );

    const byId = new Map(refreshed.map(job => [job.id, job]));
    setJobs(list.map(job => byId.get(job.id) || job));
  }

  function updateVariable(key, value) {
    setVariables(prev => ({ ...prev, [key]: value }));
  }

  function randomizeSeed(key) {
    updateVariable(key, Math.floor(Math.random() * 2147483647));
  }

  async function saveWorkflow() {
    setBusy(true);
    setMessage("");

    try {
      const parsed = JSON.parse(workflowJson);
      const id = workflowId.trim();
      if (!id) throw new Error("Workflow ID is required");

      await api(`/workflows/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id,
          name: workflowName.trim() || id,
          api_prompt: parsed
        })
      });

      const keys = extractPlaceholders(parsed);
      const nextVariables = normalizeVariables(keys, variables);
      setVariables(nextVariables);
      setSelected(id);
      setUploadedNames({});
      saveLocalVariables(id, nextVariables);

      await refreshWorkflows();
      setMessage(`Workflow saved. ${keys.length} runtime variable(s) detected.`);
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadWorkflow(id) {
    setSelected(id);
    setUploadedNames({});
    if (!id) return;

    try {
      const w = await api(`/workflows/${encodeURIComponent(id)}`);
      const json = JSON.stringify(w.api_prompt, null, 2);
      const keys = extractPlaceholders(w.api_prompt);
      const nextVariables = loadLocalVariables(id, keys);

      setWorkflowId(w.id);
      setWorkflowName(w.name);
      setWorkflowJson(json);
      setVariables(nextVariables);
      setVariablesDraft(JSON.stringify(nextVariables, null, 2));
    } catch (e) {
      setMessage(e.message);
    }
  }

  async function uploadFile(key, file) {
    if (!file) return;

    setUploadingKey(key);
    setMessage(`Uploading ${friendlyLabel(key)}...`);

    try {
      const form = new FormData();
      form.append("file", file);
      const out = await api("/uploads", { method: "POST", body: form });

      updateVariable(key, out.url);
      setUploadedNames(prev => ({ ...prev, [key]: file.name }));
      setMessage(`${friendlyLabel(key)} uploaded successfully.`);
    } catch (e) {
      setMessage(e.message);
    } finally {
      setUploadingKey("");
    }
  }

  function clearUpload(key) {
    updateVariable(key, "");
    setUploadedNames(prev => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  function applyVariablesJson() {
    try {
      const parsed = JSON.parse(variablesDraft || "{}");
      const next = normalizeVariables(placeholderKeys, parsed);
      setVariables(next);
      setVariablesDraft(JSON.stringify(next, null, 2));
      setMessage("Variables JSON applied.");
    } catch (e) {
      setMessage(`Invalid Variables JSON: ${e.message}`);
    }
  }

  function resetVariables() {
    const next = normalizeVariables(placeholderKeys);
    setVariables(next);
    setUploadedNames({});
    setVariablesDraft(JSON.stringify(next, null, 2));
    setMessage("Runtime variables reset to defaults.");
  }

  async function run() {
    if (!selected) {
      setMessage("Choose a workflow first.");
      return;
    }

    if (missingImages.length > 0) {
      setMessage(`Upload required image(s): ${missingImages.map(friendlyLabel).join(", ")}.`);
      return;
    }

    setBusy(true);
    setMessage("");

    try {
      const out = await api("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow_id: selected,
          variables,
          priority
        })
      });

      setMessage(`Submitted: ${out.id} · Priority: ${out.priority || priority}`);
      await refreshJobs();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }

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
              <input
                value={workflowId}
                onChange={e => setWorkflowId(e.target.value)}
                placeholder="01-general-editor"
              />
            </div>
            <div>
              <label>Name</label>
              <input
                value={workflowName}
                onChange={e => setWorkflowName(e.target.value)}
                placeholder="General Editor"
              />
            </div>
          </div>

          <div className="label-row">
            <label>ComfyUI API Format JSON</label>
            <span className="counter">{placeholderKeys.length} variable(s)</span>
          </div>

          <textarea
            className="code large"
            value={workflowJson}
            onChange={e => setWorkflowJson(e.target.value)}
            spellCheck={false}
          />

          <p className="hint">
            Runtime placeholders use the form <code>{"{{input.image_1}}"}</code>, <code>{"{{prompt.user}}"}</code>, etc.
          </p>

          <button disabled={busy} onClick={saveWorkflow}>Save workflow</button>
        </article>

        <article className="card">
          <h2>2. Inputs & Run</h2>

          <p className="muted">
            Selected: <strong>{selectedName || "none"}</strong>
          </p>

          {!selected && (
            <div className="empty-state">
              Choose a saved workflow first. Its required inputs will appear here automatically.
            </div>
          )}

          {selected && placeholderKeys.length === 0 && (
            <div className="empty-state">
              This workflow has no runtime placeholders. It can be submitted as-is.
            </div>
          )}

          {selected && placeholderKeys.map(key => (
            <VariableField
              key={key}
              variableKey={key}
              value={variables[key]}
              uploadedName={uploadedNames[key]}
              uploading={uploadingKey === key}
              onChange={updateVariable}
              onUpload={uploadFile}
              onClearUpload={clearUpload}
              onRandomizeSeed={randomizeSeed}
            />
          ))}

          {selected && placeholderKeys.length > 0 && (
            <details className="advanced">
              <summary>Advanced: Variables JSON</summary>
              <textarea
                className="code compact"
                value={variablesDraft}
                onChange={e => setVariablesDraft(e.target.value)}
                spellCheck={false}
              />
              <div className="button-row">
                <button type="button" className="ghost" onClick={applyVariablesJson}>
                  Apply JSON
                </button>
                <button type="button" className="ghost" onClick={resetVariables}>
                  Reset variables
                </button>
              </div>
            </details>
          )}

          <label>GPU configuration (from server .env)</label>
          <p className="hint">
            {priority ? `${priority}${gpuName ? ` · ${gpuName}` : ""}` : "Loading server GPU settings..."}
          </p>

          {missingImages.length > 0 && selected && (
            <p className="validation">
              Required: {missingImages.map(friendlyLabel).join(", ")}
            </p>
          )}

          <button
            className="primary"
            disabled={busy || Boolean(uploadingKey) || !selected || missingImages.length > 0 || !priority}
            onClick={run}
          >
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
            <Job key={j.id} job={j} fallbackPriority={priority} />
          ))}
        </div>
      </section>
    </main>
  );
}

function VariableField({
  variableKey,
  value,
  uploadedName,
  uploading,
  onChange,
  onUpload,
  onClearUpload,
  onRandomizeSeed
}) {
  const kind = variableKind(variableKey, value);
  const label = friendlyLabel(variableKey);

  if (kind === "image") {
    return (
      <div className="field-block">
        <label>{label}</label>
        <input
          type="file"
          accept="image/*"
          disabled={uploading}
          onChange={e => onUpload(variableKey, e.target.files?.[0])}
        />
        <div className="upload-status">
          <span className={value ? "ready" : "hint"}>
            {uploading
              ? "Uploading..."
              : value
                ? `Ready${uploadedName ? ` · ${uploadedName}` : ""}`
                : `Required placeholder: {{${variableKey}}}`}
          </span>
          {value && (
            <button
              type="button"
              className="link-button"
              onClick={() => onClearUpload(variableKey)}
            >
              Clear
            </button>
          )}
        </div>
      </div>
    );
  }

  if (kind === "textarea") {
    return (
      <div className="field-block">
        <label>{label}</label>
        <textarea
          className="runtime-textarea"
          value={value ?? ""}
          onChange={e => onChange(variableKey, e.target.value)}
          placeholder={`{{${variableKey}}}`}
        />
      </div>
    );
  }

  if (kind === "boolean") {
    return (
      <div className="field-block checkbox-field">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={e => onChange(variableKey, e.target.checked)}
          />
          <span>{label}</span>
        </label>
        <span className="hint"><code>{`{{${variableKey}}}`}</code></span>
      </div>
    );
  }

  if (kind === "number") {
    const isSeed = /seed/i.test(variableKey);
    return (
      <div className="field-block">
        <label>{label}</label>
        <div className="inline-control">
          <input
            type="number"
            step={numberStep(variableKey)}
            value={value ?? ""}
            onChange={e => {
              const raw = e.target.value;
              onChange(variableKey, raw === "" ? "" : Number(raw));
            }}
          />
          {isSeed && (
            <button
              type="button"
              className="ghost inline-button"
              onClick={() => onRandomizeSeed(variableKey)}
            >
              Randomize
            </button>
          )}
        </div>
        <span className="hint"><code>{`{{${variableKey}}}`}</code></span>
      </div>
    );
  }

  return (
    <div className="field-block">
      <label>{label}</label>
      <input
        type="text"
        value={value ?? ""}
        onChange={e => onChange(variableKey, e.target.value)}
        placeholder={`{{${variableKey}}}`}
      />
    </div>
  );
}

function Job({ job, fallbackPriority }) {
  const images = collectImages(job.output);

  return (
    <div className="job">
      <div>
        <strong>{job.workflow_id}</strong>
        <div className="mono">{job.id}</div>
        <div className="hint">Priority: {job.priority || fallbackPriority || ""}</div>
      </div>

      <span className={`pill ${job.state}`}>{job.state}</span>

      <div className="outputs">
        {images.map((u, i) => (
          <a key={i} href={u} target="_blank" rel="noreferrer">
            output {i + 1}
          </a>
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
      if (/\.(png|jpe?g|webp)(\?|$)/i.test(v) || v.includes("X-Amz-")) {
        found.push(v);
      }
    }
  }

  walk(value);
  return [...new Set(found)].slice(0, 8);
}
