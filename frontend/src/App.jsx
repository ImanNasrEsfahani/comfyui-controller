import "./enhancements.css";
import React, { useEffect, useMemo, useState } from "react";

const API = import.meta.env.VITE_API_BASE || "/api";
let sessionToken = ""; // Deliberately memory-only: never store an admin token in localStorage.

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (sessionToken) headers.set("X-Internal-Token", sessionToken);
  const r = await fetch(`${API}${path}`, { ...options, headers });
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

const RETRYABLE_STATES = new Set(["failed", "cancelled", "submit_failed", "stalled"]);


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
  const [adminConfigured, setAdminConfigured] = useState(false);
  const [adminToken, setAdminToken] = useState("");
  const [activePage, setActivePage] = useState("editor");
  const [deploymentSettings, setDeploymentSettings] = useState(null);
  const [settingsDraft, setSettingsDraft] = useState({ image: "", group_name: "", display_name: "" });
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [instanceInfo, setInstanceInfo] = useState(null);
  const [instanceError, setInstanceError] = useState("");
  const [groupBusy, setGroupBusy] = useState(false);
  const [jobBusyId, setJobBusyId] = useState("");
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
        setAdminConfigured(Boolean(data.admin_configured));
      })
      .catch(e => setMessage(`Unable to load GPU settings: ${e.message}`));
    refreshWorkflows().catch(e => setMessage(e.message));
    refreshJobs().catch(e => setMessage(e.message));
    refreshInstances().catch(() => {});

    const jobsTimer = setInterval(() => {
      refreshJobs().catch(() => {});
    }, 6000);
    const instanceTimer = setInterval(() => {
      refreshInstances().catch(() => {});
    }, 10000);
    return () => {
      clearInterval(jobsTimer);
      clearInterval(instanceTimer);
    };
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

  async function refreshInstances() {
    try {
      const data = await api("/salad/instances");
      setInstanceInfo(data);
      setInstanceError("");
    } catch (e) {
      setInstanceError(e.message);
    }
  }

  function changeAdminToken(value) {
    sessionToken = value;
    setAdminToken(value);
  }

  async function refreshDeploymentSettings() {
    setSettingsBusy(true);
    setSettingsMessage("");
    try {
      const result = await api("/salad/settings");
      setDeploymentSettings(result);
      setSettingsDraft({ ...result.draft });
    } catch (err) {
      setSettingsMessage(err.message);
    } finally {
      setSettingsBusy(false);
    }
  }

  function showSettings() {
    setActivePage("settings");
    if (sessionToken) refreshDeploymentSettings();
  }

  async function saveDeploymentDraft() {
    setSettingsBusy(true);
    setSettingsMessage("");
    try {
      const result = await api("/salad/settings", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settingsDraft)
      });
      setDeploymentSettings(result);
      setSettingsDraft({ ...result.draft });
      setSettingsMessage("Draft saved in SQLite. The active group is unchanged. Press Deploy when the GPU is idle.");
    } catch (err) {
      setSettingsMessage(err.message);
    } finally {
      setSettingsBusy(false);
    }
  }

  async function deployDeploymentDraft() {
    if (!window.confirm("Deploy the saved configuration? GPU must have 0 replicas and no outstanding jobs. A new group may be created, but old groups are never deleted.")) return;
    setSettingsBusy(true);
    setSettingsMessage("Waiting for Salad to deploy the saved configuration...");
    try {
      const result = await api("/salad/settings/deploy", { method: "POST" });
      setDeploymentSettings(result);
      setSettingsDraft({ ...result.draft });
      setSettingsMessage(result.message || "Deployment completed.");
      await refreshInstances();
    } catch (err) {
      setSettingsMessage(err.message);
    } finally {
      setSettingsBusy(false);
    }
  }

  async function groupAction(action) {
    if (!adminConfigured || !adminToken) {
      setMessage("Set an admin token in the private .env and enter it above.");
      return;
    }
    const prompts = {
      stop: "STOP the entire Container Group? The only worker and any running task may be interrupted. Pending remote jobs remain in Salad.",
      start: "Start the Container Group? After it settles you can request one replica.",
      replica: "Request one billable GPU replica now?",
      "keep-warm": "Keep one billable RTX 5090 available even when the queue is empty? " +
        "This may cause a Salad configuration update/reallocation. Enable before starting a job.",
      "auto-scale": "Return to automatic scale-to-zero? Salad will release the GPU once idle; " +
        "verify the instance count before assuming billing has stopped."
    };
    if (!window.confirm(prompts[action])) return;
    setGroupBusy(true);
    try {
      const response = await api(`/salad/${action}`, { method: "POST" });
      setMessage(response.message || `Group action ${action} accepted.`);
      await refreshInstances();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setGroupBusy(false);
    }
  }

  async function refreshOneJob(job) {
    setJobBusyId(job.id);
    try {
      const updated = await api(`/jobs/${encodeURIComponent(job.id)}`);
      setJobs(prev => prev.map(item => item.id === job.id ? updated : item));
      setMessage(`Status refreshed: ${updated.state}`);
    } catch (e) {
      setMessage(e.message);
    } finally {
      setJobBusyId("");
    }
  }

  async function hideJob(job) {
    const remoteWarning = TERMINAL_STATES.has(job.state)
      ? "Hide this job from the controller? This does not remove files from R2."
      : "Hide this job locally? Its REMOTE Salad job will NOT be cancelled and may still run and incur costs.";
    if (!window.confirm(remoteWarning)) return;
    setJobBusyId(job.id);
    try {
      await api(`/jobs/${encodeURIComponent(job.id)}`, { method: "DELETE" });
      setJobs(previous => previous.filter(item => item.id !== job.id));
      setMessage("Job hidden locally. Any remote Salad job remains unchanged.");
    } catch (e) {
      setMessage(e.message);
    } finally {
      setJobBusyId("");
    }
  }

  async function editJob(job) {
    setJobBusyId(job.id);
    try {
      const draft = await api(`/jobs/${encodeURIComponent(job.id)}/draft`);
      await loadWorkflow(draft.workflow_id, draft.variables);
      setMessage(draft.warning || "Job inputs restored. Edit the prompt and run when ready.");
      document.getElementById("inputs-run")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      setMessage(e.message);
    } finally {
      setJobBusyId("");
    }
  }

  async function retryJob(job) {
    const mayStillRun = job.state === "stalled" || job.state === "submit_failed";
    const warning = mayStillRun
      ? "The original remote job may STILL EXECUTE. Retrying creates a NEW job and could cost twice. Continue?"
      : "Submit a NEW billable attempt with the previously saved inputs?";
    if (!window.confirm(warning)) return;
    setJobBusyId(job.id);
    try {
      const output = await api(`/jobs/${encodeURIComponent(job.id)}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allow_duplicate: mayStillRun })
      });
      setMessage(`New attempt submitted: ${output.id}`);
      await refreshJobs();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setJobBusyId("");
    }
  }

  async function refreshWorkflows() {
    setWorkflows(await api("/workflows"));
  }

  async function refreshJobs(allPending = false) {
    const list = await api("/jobs?limit=30");
    const pending = list
      .filter(job => !TERMINAL_STATES.has(job.state))
      .slice(0, allPending === true ? 30 : 10);

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

  async function loadWorkflow(id, restoredVariables = null) {
    setSelected(id);
    setUploadedNames({});
    if (!id) return;

    try {
      const w = await api(`/workflows/${encodeURIComponent(id)}`);
      const json = JSON.stringify(w.api_prompt, null, 2);
      const keys = extractPlaceholders(w.api_prompt);
      const nextVariables = restoredVariables === null
        ? loadLocalVariables(id, keys)
        : normalizeVariables(keys, restoredVariables);

      setWorkflowId(w.id);
      setWorkflowName(w.name);
      setWorkflowJson(json);
      setVariables(nextVariables);
      setVariablesDraft(JSON.stringify(nextVariables, null, 2));
      if (restoredVariables !== null) {
        const names = {};
        keys.filter(key => /^input\.image_\d+$/.test(key)).forEach(key => {
          if (nextVariables[key]) {
            names[key] = decodeURIComponent(String(nextVariables[key]).split("/").pop() || "Saved image");
          }
        });
        setUploadedNames(names);
      }
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

      // A stable URI survives R2 signature expiry; the backend signs it for each run.
      updateVariable(key, out.s3_uri);
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

      {message && <div className="notice" role="status">{message}</div>}
      <nav className="page-tabs" aria-label="Controller pages">
        <button type="button" className={activePage === "editor" ? "tab-active" : "ghost"}
          onClick={() => setActivePage("editor")}>Editor</button>
        <button type="button" className={activePage === "settings" ? "tab-active" : "ghost"}
          onClick={showSettings}>Settings</button>
      </nav>

      {activePage === "editor" ? (<>
      <section className="card instance-card" aria-label="Salad GPU worker status">
        <div className="row instance-heading">
          <div>
            <h2>Salad GPU instances</h2>
            <p className="hint">Live status updates every 10 seconds. Stop affects the entire single-worker Container Group.</p>
          </div>
          <button className="ghost" onClick={() => refreshInstances()}>Refresh instances</button>
        </div>
        {instanceError && <p className="validation">Instance status unavailable: {instanceError}</p>}
        {instanceInfo ? (
          <>
            <div className="instance-summary">
              <span><strong>{instanceInfo.instances?.length ?? 0}</strong> instances</span>
              <span>Requested: {instanceInfo.replicas ?? 0}</span>
              <span>Group: <strong>{instanceInfo.status || "unknown"}</strong></span>
              <span>Autoscaler: {instanceInfo.autoscaler_enabled ? "enabled" : "off"}</span>
              <span>Mode: <strong>{instanceInfo.keep_warm ? "Keep Warm · 1 GPU" : "Auto · scale to zero"}</strong></span>
              {instanceInfo.pending_change && <span>Change pending</span>}
            </div>
            <div className="instance-list">
              {(instanceInfo.instances || []).map(instance => (
                <div className="instance-item" key={instance.id}>
                  <div>
                    <strong>{instance.state || "unknown"}</strong>
                    <div className="mono">{instance.id}</div>
                    <div className="hint">
                      Ready: {instance.ready ? "yes" : "no"}
                      {instance.pulling_progress != null ? ` · Pulling ${instance.pulling_progress}%` : ""}
                    </div>
                  </div>
                  <button className="danger ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change || instanceInfo.keep_warm}
                    title={instanceInfo.keep_warm ? "Return to Auto before stopping the GPU" : "Stop the whole Container Group"}
                    onClick={() => groupAction("stop")}>Stop worker</button>
                </div>
              ))}
              {!(instanceInfo.instances || []).length && <p className="hint">No allocated instances.</p>}
            </div>
            <div className="button-row">
              {instanceInfo.status === "stopped" ? (
                <button className="ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change}
                  onClick={() => groupAction("start")}>Start group</button>
              ) : (
                <>
                  {Number(instanceInfo.replicas || 0) === 0 && (
                    <button className="ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change}
                      onClick={() => groupAction("replica")}>Start 1 GPU replica</button>
                  )}
                  {Number(instanceInfo.replicas || 0) > 0 && !(instanceInfo.instances || []).length && (
                    <button className="danger ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change || instanceInfo.keep_warm}
                      onClick={() => groupAction("stop")}>Stop requested worker</button>
                  )}
                </>
              )}
            </div>
            <div className="warm-controls">
              <div>
                <strong>{instanceInfo.keep_warm ? "Keep Warm is ON" : "Auto scale-to-zero is ON"}</strong>
                <p className="hint">
                  {instanceInfo.keep_warm
                    ? "Salad keeps a minimum of 1 billable GPU while this mode is enabled. Return to Auto when editing is finished."
                    : "Enable Keep Warm BEFORE a batch of edits so the GPU is not released between jobs."}
                </p>
                {instanceInfo.pending_change && <p className="hint">Salad is applying the change. Refresh to confirm before starting another action.</p>}
              </div>
              {instanceInfo.keep_warm ? (
                <button className="ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change}
                  onClick={() => groupAction("auto-scale")}>Return to Auto</button>
              ) : (
                <button className="ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change || instanceInfo.status === "stopped"}
                  onClick={() => groupAction("keep-warm")}>Keep Warm · 1 GPU</button>
              )}
            </div>
          </>
        ) : !instanceError && <p className="muted">Loading Salad instance status…</p>}
        <div className="admin-auth">
          <label htmlFor="admin-token">Admin token (kept only in this browser tab)</label>
          <input id="admin-token" type="password" autoComplete="off" value={adminToken}
            onChange={e => changeAdminToken(e.target.value)} placeholder="APP_INTERNAL_TOKEN from server .env" />
          {!adminConfigured && <p className="validation">Admin actions are disabled. Set APP_INTERNAL_TOKEN in the private server .env and rebuild the backend.</p>}
        </div>
      </section>

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

        <article className="card" id="inputs-run">
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
          <button className="ghost" onClick={() => refreshJobs(true)}>Refresh all</button>
        </div>

        <div className="joblist">
          {jobs.length === 0 && <p className="muted">No jobs yet.</p>}

          {jobs.map(j => (
            <Job key={j.id} job={j} fallbackPriority={priority}
              disabled={jobBusyId === j.id}
              adminReady={adminConfigured && Boolean(adminToken)}
              onEdit={editJob} onRetry={retryJob} onDelete={hideJob} onRefresh={refreshOneJob} />
          ))}
        </div>
      </section>
      </>) : (
        <section className="card settings-card">
          <h2>Salad deployment settings</h2>
          <p className="hint">These three non-secret values live in the controller SQLite database, not .env. Saving a draft never changes the active GPU group.</p>
          <div className="admin-auth">
            <label htmlFor="settings-admin-token">Admin token (browser tab only)</label>
            <input type="password" id="settings-admin-token" autoComplete="off" value={adminToken}
              onChange={e => changeAdminToken(e.target.value)} placeholder="APP_INTERNAL_TOKEN" />
          </div>
          <div className="button-row">
            <button type="button" className="ghost" disabled={settingsBusy || !adminToken}
              onClick={refreshDeploymentSettings}>Load / refresh settings</button>
          </div>
          {settingsMessage && <p className="notice" role="status">{settingsMessage}</p>}
          {deploymentSettings && (
            <>
              <div className="settings-current">
                <h3>Currently active (live)</h3>
                <p><strong>Image:</strong> <code>{deploymentSettings.active.image}</code></p>
                <p><strong>Group:</strong> <code>{deploymentSettings.active.group_name}</code></p>
                <p><strong>Display name:</strong> {deploymentSettings.active.display_name}</p>
              </div>
              <div className="settings-fields">
                <label htmlFor="settings-image">Docker image</label>
                <input id="settings-image" type="text" value={settingsDraft.image}
                  onChange={e => setSettingsDraft(prev => ({ ...prev, image: e.target.value }))}
                  placeholder="ghcr.io/owner/image:version" />
                <label htmlFor="settings-group">Container Group name</label>
                <input id="settings-group" type="text" value={settingsDraft.group_name}
                  onChange={e => setSettingsDraft(prev => ({ ...prev, group_name: e.target.value }))}
                  placeholder="qwen-comfyui-5090-v4" />
                <label htmlFor="settings-label">Container Group display name</label>
                <input id="settings-label" type="text" value={settingsDraft.display_name}
                  onChange={e => setSettingsDraft(prev => ({ ...prev, display_name: e.target.value }))}
                  placeholder="Qwen-ComfyUI-RTX-5090-V4" />
              </div>
              <p className="hint">If Salad reserves a deleted group name, Deploy automatically chooses a unique suffix. Existing groups are preserved, never silently deleted.</p>
              {deploymentSettings.provisioning && (
                <p className="hint">Pending provisioning: {deploymentSettings.provisioning.group_name}</p>
              )}
              <div className="button-row">
                <button type="button" disabled={settingsBusy || !adminToken}
                  onClick={saveDeploymentDraft}>Save draft to DB</button>
                <button type="button" className="primary"
                  disabled={settingsBusy || !adminToken || !deploymentSettings.has_changes}
                  onClick={deployDeploymentDraft}>Deploy saved draft</button>
              </div>
              <p className="hint">Deploy is refused if the active GPU/Keep Warm is on, changes are pending, or a local job is still active. Wait for the old group to reach 0 replicas first. Deploy may take up to 45 seconds.</p>
            </>
          )}
        </section>
      )}
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

function Job({ job, fallbackPriority, disabled, adminReady, onEdit, onRetry, onDelete, onRefresh }) {
  const [images, setImages] = useState([]);
  const [imageError, setImageError] = useState("");
  const [loadingImages, setLoadingImages] = useState(false);

  async function refreshImages() {
    setLoadingImages(true);
    setImageError("");
    try {
      const response = await api(`/jobs/${encodeURIComponent(job.id)}/images`);
      setImages(response.images || []);
      if (!(response.images || []).length) setImageError("No output image has been found in R2 yet.");
    } catch (e) {
      setImageError(e.message);
    } finally {
      setLoadingImages(false);
    }
  }

  useEffect(() => {
    if (job.state === "succeeded") refreshImages();
  }, [job.id, job.state]);

  const retryable = RETRYABLE_STATES.has(job.state) && job.variables !== null;
  const canManage = adminReady && !disabled;
  return (
    <div className="job">
      <div className="job-top">
        <div>
          <strong>{job.workflow_id}</strong>
          <div className="mono">{job.id}</div>
          <div className="hint">Priority: {job.priority || fallbackPriority || ""}</div>
          <div className="hint">Created: {job.created_at ? new Date(job.created_at).toLocaleString() : "unknown"}</div>
        </div>
        <span className={`pill ${job.state}`}>{job.state}</span>
      </div>
      {job.state === "stalled" && (
        <p className="validation">Overdue — the remote job may still be queued or running. Retry could create a duplicate.</p>
      )}
      {job.error_text && <p className="validation">{job.error_text}</p>}
      {job.poll_warning && <p className="hint">{job.poll_warning}</p>}
      <div className="job-actions">
        <button className="ghost" disabled={disabled} onClick={() => onEdit(job)}>Edit &amp; Run</button>
        {retryable && <button className="ghost" disabled={!canManage} onClick={() => onRetry(job)}>Retry</button>}
        <button className="danger ghost" disabled={!canManage} onClick={() => onDelete(job)}>Remove</button>
        <button className="ghost" disabled={disabled} onClick={() => onRefresh(job)}>Refresh status</button>
        <button className="ghost" disabled={loadingImages} onClick={refreshImages}>
          {loadingImages ? "Checking…" : "Check outputs"}
        </button>
      </div>
      {images.length > 0 && (
        <div className="output-thumbnails">
          {images.map((image, index) => (
            <a key={image.key} href={image.url} target="_blank" rel="noreferrer"
              title={`Open output ${index + 1}`}>
              <img src={image.url} alt={`Output ${index + 1}`} loading="lazy"
                onError={() => setImageError("A preview failed to load. Refresh outputs to renew the signed link.")} />
              <span>Output {index + 1}</span>
            </a>
          ))}
        </div>
      )}
      {imageError && <p className="hint">{imageError}</p>}
    </div>
  );
}
