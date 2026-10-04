import "./enhancements.css";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { mergeJob, mergeJobList, isStale, submissionBody, requestId, validateVariables, containsCredentialLikeData } from "./contracts.js";

const API = import.meta.env.VITE_API_BASE || "/api";
let sessionToken = ""; // Deliberately memory-only: never store an admin token in localStorage.

async function api(path, options = {}, tokenOverride = undefined) {
  const headers = new Headers(options.headers || {});
  const token = tokenOverride === undefined ? sessionToken : tokenOverride;
  if (token) headers.set("X-Internal-Token", token);
  const r = await fetch(`${API}${path}`, { ...options, headers });
  if (!r.ok) {
    const body = await r.text();
    let parsed;
    try { parsed = JSON.parse(body); } catch { parsed = null; }
    const error = new Error(parsed?.error?.message || `${r.status}: ${body}`);
    error.status = r.status;
    error.code = parsed?.error?.code;
    error.path = parsed?.error?.path || (Array.isArray(parsed?.detail) ? parsed.detail[0]?.loc?.join(".") : "");
    throw error;
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

function normalizeVariables(keys, previous = {}, capabilities = null) {
  const next = {};
  const declared = new Map((capabilities?.fields || []).map(field => [field.variable_key, field]));
  keys.forEach(key => {
    if (Object.prototype.hasOwnProperty.call(previous, key)) {
      next[key] = previous[key];
    } else {
      const definition = declared.get(key);
      next[key] = definition?.default !== undefined && definition?.default !== null
        ? definition.default
        : defaultValueFor(key);
      if (definition?.kind === "select" && definition?.options?.length) {
        next[key] = definition.default ?? definition.options[0];
      }
      if (["integer", "number"].includes(definition?.kind) && typeof next[key] === "number") {
        if (definition.minimum != null) next[key] = Math.max(definition.minimum, next[key]);
        if (definition.maximum != null) next[key] = Math.min(definition.maximum, next[key]);
        if (Number(definition.step) > 0) {
          const base = definition.minimum ?? 0;
          next[key] = base + Math.round((next[key] - base) / definition.step) * definition.step;
        }
        if (definition.kind === "integer") next[key] = Math.round(next[key]);
      }
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

function variableKind(key, value, definition = null) {
  if (definition?.kind === "prompt") return "textarea";
  if (definition?.kind) return definition.kind === "integer" || definition.kind === "number" ? "number" : definition.kind;
  if (/^input\.image_\d+$/.test(key)) return "image";
  if (key.startsWith("prompt.")) return "textarea";
  if (typeof value === "boolean" || /enabled$/i.test(key)) return "boolean";
  if (
    typeof value === "number" ||
    /(seed|steps|cfg|denoise|width|height|strength(?:_(?:model|clip))?|(?:model|clip)_strength|count)$/i.test(key)
  ) return "number";
  return "text";
}

function numberStep(key, definition = null) {
  if (definition?.step != null) return String(definition.step);
  if (/seed|steps|width|height|count/i.test(key)) return "1";
  if (/strength|cfg|denoise/i.test(key)) return "0.01";
  return "any";
}

const ASPECT_RATIOS = [
  { label: "1:1", width: 1, height: 1 },
  { label: "4:3", width: 4, height: 3 },
  { label: "3:2", width: 3, height: 2 },
  { label: "16:9", width: 16, height: 9 },
  { label: "9:16", width: 9, height: 16 }
];

function fitDimension(target, definition) {
  const step = Number(definition?.step) > 0 ? Number(definition.step) : 1;
  const minimum = Number.isFinite(definition?.minimum) ? definition.minimum : 1;
  const maximum = Number.isFinite(definition?.maximum) ? definition.maximum : Number.MAX_SAFE_INTEGER;
  const clamped = Math.min(maximum, Math.max(minimum, target));
  const value = minimum + Math.round((clamped - minimum) / step) * step;
  return Math.min(maximum, Math.max(minimum, definition?.kind === "integer" ? Math.round(value) : value));
}

function loadLocalVariables(workflowId, keys, capabilities = null, capabilityVersion = null) {
  if (!workflowId) return { variables: normalizeVariables(keys, {}, capabilities), incompatible: false };

  try {
    const raw = localStorage.getItem(`comfyui-controller:variables:${workflowId}`);
    if (!raw) return { variables: normalizeVariables(keys, {}, capabilities), incompatible: false };

    const stored = JSON.parse(raw);
    const wrapped = stored && typeof stored === "object" && stored.variables && typeof stored.variables === "object";
    const saved = wrapped ? stored.variables : stored;
    if (wrapped && capabilityVersion && stored.capability_version && stored.capability_version !== capabilityVersion) {
      return { variables: normalizeVariables(keys, {}, capabilities), incompatible: true };
    }
    const sanitized = { ...saved };

    // Signed upload URLs expire. Never restore image URLs from browser storage.
    keys.filter(k => /^input\.image_\d+$/.test(k)).forEach(k => {
      sanitized[k] = "";
    });

    return { variables: normalizeVariables(keys, sanitized, capabilities), incompatible: false };
  } catch {
    return { variables: normalizeVariables(keys, {}, capabilities), incompatible: false };
  }
}

function saveLocalVariables(workflowId, variables, capabilityVersion = null) {
  if (!workflowId) return;

  try {
    const safe = { ...variables };
    Object.keys(safe).forEach(key => {
      if (/^input\.image_\d+$/.test(key)) safe[key] = "";
    });
    localStorage.setItem(`comfyui-controller:variables:${workflowId}`,
      JSON.stringify({ schema_version: 2, capability_version: capabilityVersion, variables: safe }));
  } catch {
    // Browser storage is optional; ignore quota/privacy-mode failures.
  }
}

function loadSeedMode(workflowId, capabilityVersion) {
  try {
    const saved = JSON.parse(localStorage.getItem(`comfyui-controller:seed-mode:${workflowId}`) || "null");
    if (saved?.capability_version === capabilityVersion && ["fixed", "random"].includes(saved.mode)) return saved.mode;
  } catch { /* Browser storage is optional. */ }
  return "fixed";
}

function loadPresets(workflowId) {
  try {
    const value = JSON.parse(localStorage.getItem(`comfyui-controller:presets:${workflowId}`) || "[]");
    return Array.isArray(value) ? value.filter(item => item && typeof item.id === "string" && typeof item.name === "string") : [];
  } catch { return []; }
}

export default function App() {
  const jobsPolling = useRef(false);
  const jobsGeneration = useRef(0);
  const instancesPolling = useRef(false);
  const selectionRequest = useRef(0);
  const loadedWorkflow = useRef(null);
  const liveVariables = useRef({});
  const submitting = useRef(false);
  const pendingSubmission = useRef(null);
  const defaultPresetApplied = useRef("");
  const sourceJob = useRef(null);
  const workflowDefaults = useRef({ id: "", variables: {} });
  const fieldRefs = useRef({});
  const uploadRevision = useRef(0);
  const uploadActive = useRef(false);
  const latestTokenDraft = useRef("");
  const appliedToken = useRef("");
  const tokenCheckGeneration = useRef(0);
  const tokenCheckController = useRef(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [submissionUncertain, setSubmissionUncertain] = useState(false);
  const [browserConnection, setBrowserConnection] = useState("checking");
  const [clock, setClock] = useState(Date.now());
  const [currentJobId, setCurrentJobId] = useState(null);
  const [workflows, setWorkflows] = useState([]);
  const [selectedCapabilities, setSelectedCapabilities] = useState(null);
  const [capabilitySpecDraft, setCapabilitySpecDraft] = useState("");
  const [seedMode, setSeedMode] = useState("fixed");
  const [presets, setPresets] = useState([]);
  const [presetName, setPresetName] = useState("");
  const [includePromptsInPreset, setIncludePromptsInPreset] = useState(true);
  const [referenceOrder, setReferenceOrder] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [workflowId, setWorkflowId] = useState("");
  const [workflowName, setWorkflowName] = useState("");
  const [workflowJson, setWorkflowJson] = useState(blankWorkflow);
  const [selected, setSelected] = useState("");
  const [priority, setPriority] = useState("");
  const [gpuName, setGpuName] = useState("");
  const [adminConfigured, setAdminConfigured] = useState(false);
  const [adminToken, setAdminToken] = useState("");
  const [tokenApplied, setTokenApplied] = useState(false);
  const [tokenStatus, setTokenStatus] = useState("not_applied");
  const [tokenFeedback, setTokenFeedback] = useState("No token has been applied in this tab.");
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
  const [fieldErrors, setFieldErrors] = useState({});
  const [formRevision, setFormRevision] = useState(0);
  const [variablesDraft, setVariablesDraft] = useState(
    JSON.stringify({ "input.image_1": "" }, null, 2)
  );
  liveVariables.current = variables;

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
    () => imageKeys.filter(key => selectedCapabilities?.references?.find(r => r.variable_key === key)?.required !== false &&
      !String(variables[key] || "").trim()),
    [imageKeys, variables, selectedCapabilities]
  );

  const currentDefaults = workflowDefaults.current.id === selected
    ? workflowDefaults.current.variables
    : normalizeVariables(placeholderKeys, {}, selectedCapabilities);
  const variablesJsonDirty = variablesDraft !== JSON.stringify(variables, null, 2);
  const formChanged = placeholderKeys.some(key =>
    JSON.stringify(variables[key]) !== JSON.stringify(currentDefaults[key])
  ) || Boolean(uploadingKey) || variablesJsonDirty;

  const selectedName = useMemo(
    () => workflows.find(w => w.id === selected)?.name || selected,
    [workflows, selected]
  );
  const baseReferenceSlots = selectedCapabilities?.references || [];
  const fieldByKey = new Map((selectedCapabilities?.fields || []).map(field => [field.variable_key, field]));
  const widthKey = placeholderKeys.find(key => /(?:^|\.)(?:output\.)?width$/i.test(key));
  const heightKey = placeholderKeys.find(key => /(?:^|\.)(?:output\.)?height$/i.test(key));
  const widthDefinition = fieldByKey.get(widthKey);
  const heightDefinition = fieldByKey.get(heightKey);
  const canChooseAspectRatio = Boolean(widthKey && heightKey &&
    ["integer", "number"].includes(variableKind(widthKey, variables[widthKey], widthDefinition)) &&
    ["integer", "number"].includes(variableKind(heightKey, variables[heightKey], heightDefinition)));
  const currentAspectRatio = canChooseAspectRatio && Number(variables[widthKey]) > 0 && Number(variables[heightKey]) > 0
    ? ASPECT_RATIOS.find(ratio => Math.abs(Number(variables[widthKey]) / Number(variables[heightKey]) - ratio.width / ratio.height) < 0.0001)?.label || "custom"
    : "custom";
  const referenceByKey = new Map(baseReferenceSlots.map(slot => [slot.variable_key, slot]));
  const canReorderReferences = baseReferenceSlots.length > 1 && baseReferenceSlots.length === imageKeys.length &&
    baseReferenceSlots.every(slot => slot.reorderable && slot.role === "reference");
  const renderedFieldKeys = canReorderReferences && referenceOrder.length === baseReferenceSlots.length
    ? [...referenceOrder, ...placeholderKeys.filter(key => !baseReferenceSlots.some(slot => slot.variable_key === key))]
    : placeholderKeys;
  const advancedFieldKeys = renderedFieldKeys.filter(key => Boolean(fieldByKey.get(key)?.advanced));
  const regularFieldKeys = renderedFieldKeys.filter(key => !fieldByKey.get(key)?.advanced);

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
        setBrowserConnection("connected");
        if (pendingSubmission.current && !data.admin_configured) recoverSubmission(false);
      })
      .catch(e => setMessage(`Unable to load GPU settings: ${e.message}`));
    refreshWorkflows().catch(e => setMessage(e.message));
    refreshJobs().catch(e => setMessage(e.message));
    refreshInstances().catch(() => {});
    try {
      const pending = JSON.parse(sessionStorage.getItem("comfyui-controller:pending-request") || "null");
      if (pending?.client_request_id) {
        pendingSubmission.current = pending;
        setSubmissionUncertain(true);
      }
    } catch { /* Session storage is optional. */ }

    const jobsTimer = setInterval(() => {
      refreshJobs().catch(() => {});
    }, 6000);
    const instanceTimer = setInterval(() => {
      refreshInstances().catch(() => {});
    }, 10000);
    const clockTimer = setInterval(() => setClock(Date.now()), 1000);
    return () => {
      clearInterval(jobsTimer);
      clearInterval(instanceTimer);
      clearInterval(clockTimer);
    };
  }, []);

  useEffect(() => {
    setVariables(prev => {
      const next = normalizeVariables(placeholderKeys, prev, selectedCapabilities);
      setVariablesDraft(JSON.stringify(next, null, 2));
      return next;
    });
  }, [placeholderKeys.join("|"), selectedCapabilities?.capability_version]);

  useEffect(() => {
    if (selected && loadedWorkflow.current?.id === selected) {
      saveLocalVariables(selected, variables, selectedCapabilities?.capability_version);
    }
    setVariablesDraft(JSON.stringify(variables, null, 2));
  }, [variables, selected, selectedCapabilities?.capability_version]);

  useEffect(() => {
    if (!selected || !selectedCapabilities?.seed_variable) return;
    try {
      localStorage.setItem(`comfyui-controller:seed-mode:${selected}`,
        JSON.stringify({ capability_version: selectedCapabilities.capability_version, mode: seedMode }));
    } catch { /* Browser storage is optional. */ }
  }, [selected, selectedCapabilities?.capability_version, seedMode]);

  useEffect(() => {
    if (!selected || loadedWorkflow.current?.id !== selected || !selectedCapabilities?.capability_version || !presets.length) return;
    const defaultPreset = presets.find(preset => preset.is_default);
    if (!defaultPreset) return;
    const key = `${selected}:${selectedCapabilities.capability_version}:${defaultPreset.id}`;
    if (defaultPresetApplied.current === key) return;
    defaultPresetApplied.current = key;
    if (defaultPreset.capability_version !== selectedCapabilities.capability_version ||
        defaultPreset.workflow_version !== loadedWorkflow.current.workflow_version) {
      setMessage(`Default preset “${defaultPreset.name}” needs review because its Workflow version changed.`);
      return;
    }
    const next = normalizeVariables(loadedWorkflow.current.variable_keys, defaultPreset.variables || {}, selectedCapabilities);
    liveVariables.current = next;
    setVariables(next);
    setSeedMode(defaultPreset.seed_mode || "fixed");
    if (canReorderReferences && Array.isArray(defaultPreset.reference_order) &&
        defaultPreset.reference_order.length === baseReferenceSlots.length &&
        new Set(defaultPreset.reference_order).size === baseReferenceSlots.length &&
        baseReferenceSlots.every(slot => defaultPreset.reference_order.includes(slot.variable_key))) {
      setReferenceOrder(defaultPreset.reference_order);
    }
    setMessage(`Default preset “${defaultPreset.name}” was applied. Reference images were left empty.`);
  }, [selected, selectedCapabilities?.capability_version, presets, canReorderReferences]);

  async function refreshInstances() {
    if (instancesPolling.current) return;
    instancesPolling.current = true;
    try {
      const data = await api("/salad/instances");
      setInstanceInfo(previous => previous?.group_name === data.group_name && previous.version > data.version ? previous : data);
      setInstanceError("");
    } catch (e) {
      setInstanceError(e.message);
    } finally {
      instancesPolling.current = false;
    }
  }

  function changeAdminToken(value) {
    latestTokenDraft.current = value;
    tokenCheckGeneration.current += 1;
    tokenCheckController.current?.abort();
    tokenCheckController.current = null;
    setAdminToken(value);
    if (value && value === appliedToken.current) {
      setTokenStatus("connected");
      setTokenFeedback("This verified token is already applied in this browser tab.");
    } else if (value) {
      setTokenStatus("unapplied");
      setTokenFeedback(tokenApplied
        ? "This draft is not applied. The previously verified token remains active."
        : "This token is only a draft. Apply it to check the connection.");
    } else {
      setTokenStatus("not_applied");
      setTokenFeedback(tokenApplied
        ? "The draft is empty. The previously verified token remains active."
        : "No token has been applied in this tab.");
    }
  }

  async function applyAdminToken() {
    const candidate = adminToken;
    if (!adminConfigured) {
      setTokenStatus("unavailable");
      setTokenFeedback("The server has no APP_INTERNAL_TOKEN configured.");
      return;
    }
    if (!candidate) {
      setTokenStatus("not_applied");
      setTokenFeedback("Enter the token, then choose Apply Token.");
      return;
    }

    tokenCheckController.current?.abort();
    const controller = new AbortController();
    tokenCheckController.current = controller;
    const generation = ++tokenCheckGeneration.current;
    const timeout = setTimeout(() => controller.abort(), 8000);
    setTokenStatus("checking");
    setTokenFeedback("Checking the token with the controller…");
    try {
      // A read-only authenticated endpoint verifies the token without changing
      // Salad settings or starting a GPU action.
      await api("/salad/settings", { signal: controller.signal }, candidate);
      if (generation !== tokenCheckGeneration.current || latestTokenDraft.current !== candidate) return;
      sessionToken = candidate;
      appliedToken.current = candidate;
      setTokenApplied(true);
      setTokenStatus("connected");
      setTokenFeedback("Connected. The verified token is held in memory for this tab only.");
      setMessage("Admin token verified and applied for this browser tab.");
      refreshJobs().catch(() => {});
      refreshInstances().catch(() => {});
      if (activePage === "settings") refreshDeploymentSettings();
      if (pendingSubmission.current) recoverSubmission();
    } catch (error) {
      if (generation !== tokenCheckGeneration.current || latestTokenDraft.current !== candidate) return;
      if (error.name === "AbortError") {
        setTokenStatus("timeout");
        setTokenFeedback(tokenApplied
          ? "The check timed out. The previously verified token remains active."
          : "The check timed out. The token was not applied; check the connection and retry.");
      } else if (error.status === 401) {
        setTokenStatus("invalid");
        setTokenFeedback(tokenApplied
          ? "This token is invalid. The previously verified token remains active."
          : "This token was rejected. It was not applied.");
      } else if (error.status === 503) {
        setTokenStatus("unavailable");
        setTokenFeedback("The controller is not configured to accept an admin token.");
      } else if (!error.status || error.name === "TypeError") {
        setTokenStatus("network_error");
        setTokenFeedback(tokenApplied
          ? "The controller could not be reached. The previously verified token remains active."
          : "The controller could not be reached; the token was not applied.");
      } else {
        setTokenStatus("unavailable");
        setTokenFeedback(tokenApplied
          ? `The controller returned HTTP ${error.status}. The previously verified token remains active.`
          : `The controller returned HTTP ${error.status}; the token was not applied.`);
      }
    } finally {
      clearTimeout(timeout);
      if (generation === tokenCheckGeneration.current) tokenCheckController.current = null;
    }
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
    if (!adminConfigured || !tokenApplied) {
      setMessage("Set APP_INTERNAL_TOKEN in the private server .env, then apply the valid token in the browser.");
      return;
    }
    const prompts = {
      stop: instanceInfo?.queue_mode === "direct"
        ? "STOP the direct GPU Container Group? A running job must finish first; pending jobs stay in SQLite."
        : "STOP the entire Container Group? The only worker and any running task may be interrupted. Pending remote jobs remain in Salad.",
      start: "Start the Container Group? After it settles you can request one replica.",
      replica: "Request one billable GPU replica now?",
      "keep-warm": instanceInfo?.queue_mode === "direct"
        ? "Keep one billable GPU active while idle? This changes the local controller policy; start the GPU separately if it is off."
        : "Keep one billable RTX 5090 available even when the queue is empty? " +
          "This may cause a Salad configuration update/reallocation. Enable before starting a job.",
      "auto-scale": instanceInfo?.queue_mode === "direct"
        ? "Disable direct Keep Warm? The scheduler auto-stops idle GPUs only when DIRECT_GPU_AUTO_CONTROL=true."
        : "Return to automatic scale-to-zero? Salad will release the GPU once idle; " +
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
      setJobs(prev => prev.map(item => item.id === job.id ? mergeJob(item, updated) : item));
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
      jobsGeneration.current += 1;
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
      setSeedMode(draft.seed_mode || "fixed");
      sourceJob.current = job.id;
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
      : "Retry the saved Job with a new billable execution attempt?";
    if (!window.confirm(warning)) return;
    setJobBusyId(job.id);
    try {
      const output = await api(`/jobs/${encodeURIComponent(job.id)}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allow_duplicate: mayStillRun })
      });
      jobsGeneration.current += 1;
      setJobs(previous => previous.map(item => item.id === output.id ? mergeJob(item, output) : item));
      setMessage(`Retry accepted: ${output.id}`);
      await refreshJobs();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setJobBusyId("");
    }
  }

  async function refreshWorkflows() {
    const data = await api("/catalog");
    setWorkflows(Array.isArray(data?.workflows) ? data.workflows : []);
  }

  async function resetGpuHold() {
    if (!adminConfigured || !tokenApplied) return;
    if (!window.confirm("Clear GPU HOLD? Only do this after resolving the worker error. Auto GPU mode may allocate a billable machine.")) return;
    setGroupBusy(true);
    try {
      const response = await api("/direct/reset-hold", { method: "POST" });
      setMessage(response.message || "GPU HOLD cleared.");
      await refreshInstances();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setGroupBusy(false);
    }
  }

  async function refreshJobs(allPending = false) {
    if (jobsPolling.current) return;
    jobsPolling.current = true;
    const generation = jobsGeneration.current;
    try {
    const list = await api("/jobs?limit=30");
    const pending = list
      .filter(job => !TERMINAL_STATES.has(job.state))
      .slice(0, allPending === true ? 30 : 10);

    if (pending.length === 0) {
      if (generation === jobsGeneration.current) setJobs(previous => mergeJobList(previous, list));
      setBrowserConnection("connected");
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
    if (generation === jobsGeneration.current) setJobs(previous => mergeJobList(previous, list.map(job => byId.get(job.id) || job)));
    setBrowserConnection("connected");
    } catch (error) {
      setBrowserConnection("disconnected");
      throw error;
    } finally {
      jobsPolling.current = false;
    }
  }

  function captureFieldRef(key, element) {
    if (element) fieldRefs.current[key] = element;
    else delete fieldRefs.current[key];
  }

  function readLatestVariables(keys = loadedWorkflow.current?.variable_keys || placeholderKeys) {
    const current = liveVariables.current || {};
    const latest = {};
    for (const key of keys) {
      const element = fieldRefs.current[key];
      if (!element || /^input\.image_\d+$/.test(key)) {
        latest[key] = current[key];
        continue;
      }
      const definition = loadedWorkflow.current?.capabilities?.fields?.find(field => field.variable_key === key);
      const kind = variableKind(key, current[key], definition);
      if (kind === "boolean") latest[key] = Boolean(element.checked);
      else if (kind === "number") {
        if (element.value === "") latest[key] = "";
        else {
          const parsed = element.valueAsNumber;
          latest[key] = Number.isFinite(parsed) ? parsed : element.value;
        }
      } else latest[key] = element.value;
    }
    return latest;
  }

  function updateVariable(key, value) {
    const next = { ...liveVariables.current, [key]: value };
    liveVariables.current = next;
    setVariables(next);
    setFieldErrors(previous => {
      if (!Object.prototype.hasOwnProperty.call(previous, key)) return previous;
      const error = validateVariables([key], next, loadedWorkflow.current?.capabilities)[key];
      const updated = { ...previous };
      if (error) updated[key] = error;
      else delete updated[key];
      return updated;
    });
  }

  function randomizeSeed(key) {
    const minimum = selectedCapabilities?.seed_range?.minimum ?? 0;
    const maximum = selectedCapabilities?.seed_range?.maximum ?? 2147483647;
    updateVariable(key, Math.floor(Math.random() * (maximum - minimum + 1)) + minimum);
  }

  function setAspectRatio(label) {
    const ratio = ASPECT_RATIOS.find(item => item.label === label);
    if (!ratio || !canChooseAspectRatio) return;
    const currentWidth = Number(variables[widthKey]) || 1024;
    const currentHeight = Number(variables[heightKey]) || 1024;
    const targetRatio = ratio.width / ratio.height;
    const area = currentWidth * currentHeight;
    const width = fitDimension(Math.sqrt(area * targetRatio), widthDefinition);
    const height = fitDimension(Math.sqrt(area / targetRatio), heightDefinition);
    updateVariable(widthKey, width);
    updateVariable(heightKey, height);
  }

  function persistPresets(next) {
    setPresets(next);
    try { localStorage.setItem(`comfyui-controller:presets:${selected}`, JSON.stringify(next)); }
    catch { setMessage("Browser storage is unavailable; the preset was not saved."); }
  }

  function savePreset() {
    const name = presetName.trim();
    if (!name) { setMessage("Enter a name for this preset."); return; }
    if (!loadedWorkflow.current || loadedWorkflow.current.id !== selected) { setMessage("Load a saved Workflow before creating a preset."); return; }
    const keys = loadedWorkflow.current.variable_keys || [];
    const latest = readLatestVariables(keys);
    const errors = validateVariables(keys, latest, loadedWorkflow.current.capabilities);
    const invalid = Object.keys(errors).filter(key => !/^input\.image_\d+$/.test(key));
    if (invalid.length) { setMessage("Correct invalid settings before saving the preset."); return; }
    const savedVariables = {};
    for (const key of keys) {
      if (/^input\.image_\d+$/.test(key) || (!includePromptsInPreset && key.startsWith("prompt."))) continue;
      savedVariables[key] = latest[key];
    }
    if (containsCredentialLikeData(savedVariables)) {
      setMessage("This preset contains credential-like text. Remove it before saving the preset.");
      return;
    }
    const createdAt = new Date().toISOString();
    const preset = {
      id: requestId(), name, schema_version: 1, workflow_id: selected,
      workflow_version: loadedWorkflow.current.workflow_version,
      capability_version: loadedWorkflow.current.capability_version,
      seed_mode: seedMode, variables: savedVariables, includes_prompts: includePromptsInPreset,
      reference_order: canReorderReferences ? [...referenceOrder] : undefined,
      includes_references: false, created_at: createdAt, updated_at: createdAt, is_default: false
    };
    persistPresets([preset, ...presets.filter(item => item.name.toLowerCase() !== name.toLowerCase())].slice(0, 50));
    setPresetName("");
    setMessage(`Preset “${name}” saved on this browser. Reference images were not saved.`);
  }

  function applyPreset(preset) {
    if (!preset || !loadedWorkflow.current) return;
    if (preset.workflow_id !== selected || preset.workflow_version !== loadedWorkflow.current.workflow_version ||
        preset.capability_version !== loadedWorkflow.current.capability_version) {
      setMessage(`Preset “${preset.name}” is incompatible with the current Workflow version and was not applied.`);
      return;
    }
    const next = normalizeVariables(loadedWorkflow.current.variable_keys, {
      ...liveVariables.current,
      ...(preset.variables || {}),
      ...Object.fromEntries((selectedCapabilities?.references || []).map(ref => [ref.variable_key, liveVariables.current[ref.variable_key] || ""]))
    }, selectedCapabilities);
    const errors = validateVariables(loadedWorkflow.current.variable_keys, next, selectedCapabilities);
    const invalid = Object.keys(errors).filter(key => !/^input\.image_\d+$/.test(key));
    if (invalid.length) { setMessage(`Preset “${preset.name}” contains settings that are no longer valid.`); return; }
    liveVariables.current = next;
    setVariables(next);
    setSeedMode(preset.seed_mode || "fixed");
    if (canReorderReferences && Array.isArray(preset.reference_order) &&
        preset.reference_order.length === baseReferenceSlots.length &&
        new Set(preset.reference_order).size === baseReferenceSlots.length &&
        baseReferenceSlots.every(slot => preset.reference_order.includes(slot.variable_key))) {
      setReferenceOrder(preset.reference_order);
    }
    sourceJob.current = null;
    setMessage(`Preset “${preset.name}” applied. No Job was created.`);
  }

  function renamePreset(preset) {
    const name = window.prompt("Rename preset", preset.name)?.trim();
    if (!name || name === preset.name) return;
    const duplicate = presets.some(item => item.id !== preset.id && item.name.toLowerCase() === name.toLowerCase());
    if (duplicate) { setMessage("A preset with that name already exists."); return; }
    persistPresets(presets.map(item => item.id === preset.id ? { ...item, name, updated_at: new Date().toISOString() } : item));
  }

  function deletePreset(preset) {
    if (!window.confirm(`Delete preset “${preset.name}”?`)) return;
    persistPresets(presets.filter(item => item.id !== preset.id));
    setMessage(`Preset “${preset.name}” deleted. Existing Jobs were not changed.`);
  }

  function setDefaultPreset(preset) {
    const next = presets.map(item => ({ ...item, is_default: item.id === preset.id }));
    persistPresets(next);
    defaultPresetApplied.current = "";
    setMessage(`“${preset.name}” is now the default for this Workflow in this browser.`);
  }

  function moveReference(key, direction) {
    if (!canReorderReferences) return;
    setReferenceOrder(current => {
      const order = current.length === baseReferenceSlots.length
        ? [...current]
        : baseReferenceSlots.map(slot => slot.variable_key);
      const index = order.indexOf(key);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= order.length) return order;
      [order[index], order[nextIndex]] = [order[nextIndex], order[index]];
      return order;
    });
  }

  async function saveWorkflow() {
    setBusy(true);
    setMessage("");

    try {
      const parsed = JSON.parse(workflowJson);
      const id = workflowId.trim();
      if (!id) throw new Error("Workflow ID is required");
      const capabilitySpec = capabilitySpecDraft.trim() ? JSON.parse(capabilitySpecDraft) : null;

      await api(`/workflows/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id,
          name: workflowName.trim() || id,
          api_prompt: parsed,
          capability_spec: capabilitySpec
        })
      });

      const keys = extractPlaceholders(parsed);
      const nextVariables = normalizeVariables(keys, variables, selectedCapabilities);
      setVariables(nextVariables);
      setSelected(id);
      setUploadedNames({});

      await refreshWorkflows();
      await loadWorkflow(id, nextVariables);
      setMessage(`Workflow saved. ${keys.length} runtime variable(s) detected.`);
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadWorkflow(id, restoredVariables = null) {
    const request = ++selectionRequest.current;
    uploadRevision.current += 1;
    uploadActive.current = false;
    setUploadingKey("");
    setFieldErrors({});
    loadedWorkflow.current = null;
    defaultPresetApplied.current = "";
    setSelectedCapabilities(null);
    setCapabilitySpecDraft("");
    setPresets([]);
    setReferenceOrder([]);
    sourceJob.current = null;
    setWorkflowLoading(Boolean(id));
    setSelected(id);
    setUploadedNames({});
    if (!id) return;

    try {
      const w = await api(`/workflows/${encodeURIComponent(id)}`);
      if (request !== selectionRequest.current) return;
      const json = JSON.stringify(w.api_prompt, null, 2);
      const keys = extractPlaceholders(w.api_prompt);
      const capabilities = w.capabilities || null;
      const defaults = normalizeVariables(keys, {}, capabilities);
      const local = restoredVariables === null
        ? loadLocalVariables(id, keys, capabilities, w.capability_version)
        : { variables: normalizeVariables(keys, restoredVariables, capabilities), incompatible: false };
      const nextVariables = local.variables;

      setWorkflowId(w.id);
      setWorkflowName(w.name);
      setWorkflowJson(json);
      setSelectedCapabilities(capabilities);
      setCapabilitySpecDraft(w.capability_spec ? JSON.stringify(w.capability_spec, null, 2) : "");
      setReferenceOrder((capabilities?.references || []).map(slot => slot.variable_key));
      setVariables(nextVariables);
      liveVariables.current = nextVariables;
      loadedWorkflow.current = w;
      workflowDefaults.current = { id: w.id, variables: JSON.parse(JSON.stringify(defaults)) };
      setVariablesDraft(JSON.stringify(nextVariables, null, 2));
      setSeedMode(loadSeedMode(w.id, w.capability_version));
      setPresets(loadPresets(w.id));
      if (local.incompatible) {
        setMessage("Saved values belonged to an older Workflow version. They were reset to the current defaults; review the form before running.");
      }
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
      if (request === selectionRequest.current) setMessage(e.message);
    } finally {
      if (request === selectionRequest.current) setWorkflowLoading(false);
    }
  }

  async function uploadFile(key, file) {
    if (!file) return;

    if (uploadActive.current) {
      setMessage("Wait for the current image upload to finish before choosing another file.");
      return;
    }
    if (file.type && !file.type.toLowerCase().startsWith("image/")) {
      setFieldErrors(previous => ({ ...previous, [key]: "Choose an image file." }));
      setMessage(`${friendlyLabel(key)} must be an image file.`);
      return;
    }

    uploadActive.current = true;
    const revision = uploadRevision.current;
    setUploadingKey(key);
    const selection = selectionRequest.current;
    setFieldErrors(previous => {
      const next = { ...previous };
      delete next[key];
      return next;
    });
    setMessage(`Uploading ${friendlyLabel(key)}...`);

    try {
      const form = new FormData();
      form.append("file", file);
      const out = await api("/uploads", { method: "POST", body: form });
      if (revision !== uploadRevision.current || selection !== selectionRequest.current) return;
      if (typeof out?.s3_uri !== "string" || !out.s3_uri) {
        throw new Error("The upload completed without an image reference. Try again.");
      }

      // A stable URI survives R2 signature expiry; the backend signs it for each run.
      updateVariable(key, out.s3_uri);
      setUploadedNames(prev => ({ ...prev, [key]: file.name }));
      setMessage(`${friendlyLabel(key)} uploaded successfully.`);
    } catch (e) {
      if (revision === uploadRevision.current && selection === selectionRequest.current) {
        setFieldErrors(previous => ({ ...previous, [key]: e.message || "Image upload failed. Try again." }));
        setMessage(e.message || "Image upload failed. Try again.");
      }
    } finally {
      if (revision === uploadRevision.current) {
        uploadActive.current = false;
        setUploadingKey("");
      }
    }
  }

  function clearUpload(key) {
    if (uploadingKey === key) {
      uploadRevision.current += 1;
      uploadActive.current = false;
      setUploadingKey("");
    }
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
      const next = normalizeVariables(placeholderKeys, parsed, selectedCapabilities);
      setVariables(next);
      liveVariables.current = next;
      setVariablesDraft(JSON.stringify(next, null, 2));
      const errors = validateVariables(placeholderKeys, next, selectedCapabilities);
      setFieldErrors(errors);
      setMessage(Object.keys(errors).length
        ? "Variables JSON applied. Correct the highlighted fields before generating."
        : "Variables JSON applied.");
    } catch (e) {
      setMessage(`Invalid Variables JSON: ${e.message}`);
    }
  }

  async function pastePrompt(key) {
    const element = fieldRefs.current[key];
    if (!element) {
      setMessage("The prompt field is not available. Click it and use the keyboard Paste command.");
      return;
    }
    const before = element.value;
    const start = element.selectionStart ?? before.length;
    const end = element.selectionEnd ?? start;
    try {
      if (!navigator.clipboard?.readText) throw new Error("clipboard unavailable");
      const text = await navigator.clipboard.readText();
      if (!text) {
        setMessage("The clipboard is empty. The prompt was left unchanged.");
        return;
      }
      if (element.value !== before) {
        setMessage("The prompt changed while clipboard access was pending. Click Paste again.");
        return;
      }
      const next = before.slice(0, start) + text + before.slice(end);
      updateVariable(key, next);
      const cursor = start + text.length;
      requestAnimationFrame(() => {
        const current = fieldRefs.current[key];
        current?.focus();
        current?.setSelectionRange(cursor, cursor);
      });
      setMessage(`${friendlyLabel(key)} pasted. The cursor remains in the prompt.`);
    } catch {
      setMessage("Clipboard access was unavailable or denied. Focus the prompt and use Ctrl+V (or ⌘V on Mac) to paste manually.");
      element.focus();
    }
  }

  function clearForm() {
    if (!selected || workflowLoading || !formChanged) return;
    const confirmed = window.confirm(
      "Reset this workflow form to its defaults? Applied token, connection settings, saved Jobs and outputs remain. Running Jobs are not cancelled."
    );
    if (!confirmed) return;
    uploadRevision.current += 1;
    uploadActive.current = false;
    setUploadingKey("");
    const defaults = workflowDefaults.current.id === selected
      ? workflowDefaults.current.variables
      : normalizeVariables(placeholderKeys, {}, selectedCapabilities);
    const next = JSON.parse(JSON.stringify(defaults));
    setVariables(next);
    liveVariables.current = next;
    setUploadedNames({});
    setFieldErrors({});
    setVariablesDraft(JSON.stringify(next, null, 2));
    setFormRevision(version => version + 1);
    setSeedMode("fixed");
    setReferenceOrder(baseReferenceSlots.map(slot => slot.variable_key));
    sourceJob.current = null;
    setMessage("Form reset. Existing Jobs, outputs, connection settings and the applied token remain unchanged.");
  }

  function resetAdvancedSettings() {
    const keys = new Set((selectedCapabilities?.fields || []).filter(field => field.advanced).map(field => field.variable_key));
    const defaults = workflowDefaults.current.id === selected
      ? workflowDefaults.current.variables
      : normalizeVariables(placeholderKeys, {}, selectedCapabilities);
    const next = { ...liveVariables.current };
    for (const key of keys) next[key] = defaults[key];
    liveVariables.current = next;
    setVariables(next);
    setSeedMode("fixed");
    setFieldErrors(previous => Object.fromEntries(Object.entries(previous).filter(([key]) => !keys.has(key))));
    setVariablesDraft(JSON.stringify(next, null, 2));
    setMessage("Advanced settings reset to this Workflow’s defaults. Prompts and reference images were preserved.");
  }

  function rememberSubmission(body) {
    pendingSubmission.current = body;
    try { sessionStorage.setItem("comfyui-controller:pending-request", JSON.stringify(body)); } catch { /* Optional. */ }
  }

  function submissionAccepted(out) {
    pendingSubmission.current = null;
    try { sessionStorage.removeItem("comfyui-controller:pending-request"); } catch { /* Optional. */ }
    setSubmissionUncertain(false);
    setCurrentJobId(out.id);
    jobsGeneration.current += 1;
    setJobs(previous => [mergeJob(previous.find(job => job.id === out.id), out), ...previous.filter(job => job.id !== out.id)]);
    setMessage(`Accepted: ${out.id} · ${out.status || out.state}. Output appears in Jobs & outputs after completion.`);
  }

  async function recoverSubmission(resend = true) {
    if (adminConfigured && !sessionToken) {
      setMessage("Apply the admin token before recovering the saved request.");
      return;
    }
    if (submitting.current || !pendingSubmission.current) return;
    submitting.current = true;
    setBusy(true);
    try {
      let out;
      try {
        out = await api(`/job-requests/${encodeURIComponent(pendingSubmission.current.client_request_id)}`);
      } catch (error) {
        if (error.status !== 404 || !resend) throw error;
        out = await api("/jobs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(pendingSubmission.current)});
      }
      submissionAccepted(out);
    } catch (error) {
      setMessage(`Submission outcome is unknown. Recover the saved request before creating another Job: ${error.message}`);
      setSubmissionUncertain(true);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  async function run() {
    if (submitting.current) return;
    if (pendingSubmission.current) { await recoverSubmission(); return; }
    if (!selected) {
      setMessage("Choose a workflow first.");
      return;
    }
    if (workflowLoading || loadedWorkflow.current?.id !== selected) {
      setMessage("Wait for the selected workflow to finish loading.");
      return;
    }
    if (adminConfigured && !tokenApplied) {
      setMessage("Apply a valid admin token in Infrastructure & cost before generating.");
      return;
    }
    if (!priority) {
      setMessage("Wait for the server GPU configuration to load.");
      return;
    }
    if (variablesJsonDirty) {
      setMessage("Apply the Variables JSON edits, or use Clear Form to discard them, before generating.");
      return;
    }

    // Read live controls immediately before creating the immutable request
    // snapshot. This catches a final keystroke before React's next render.
    const latest = readLatestVariables(loadedWorkflow.current.variable_keys || placeholderKeys);
    liveVariables.current = latest;
    setVariables(latest);
    const activeKeys = loadedWorkflow.current.variable_keys || placeholderKeys;
    const submissionValues = { ...latest };
    if (seedMode === "random" && loadedWorkflow.current.capabilities?.seed_variable) {
      submissionValues[loadedWorkflow.current.capabilities.seed_variable] =
        loadedWorkflow.current.capabilities.seed_range?.minimum ?? 0;
    }
    const errors = validateVariables(activeKeys, submissionValues, loadedWorkflow.current.capabilities);
    setFieldErrors(errors);
    if (uploadActive.current || uploadingKey) {
      setMessage("Wait for the reference image upload to finish before generating.");
      return;
    }
    if (Object.keys(errors).length) {
      setMessage("Correct the highlighted workflow fields before generating.");
      const firstInvalid = Object.keys(errors)[0];
      fieldRefs.current[firstInvalid]?.focus?.();
      return;
    }

    setBusy(true);
    submitting.current = true;
    setMessage("");

    try {
      const snapshot = JSON.parse(JSON.stringify(submissionValues));
      const body = submissionBody(loadedWorkflow.current, snapshot, priority, requestId(), sourceJob.current, seedMode,
        canReorderReferences ? referenceOrder : null);
      rememberSubmission(body);
      const out = await api("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });

      const seedVariable = loadedWorkflow.current.capabilities?.seed_variable;
      if (seedMode === "random" && seedVariable && Number.isSafeInteger(out.snapshot?.seed)) {
        const updated = { ...liveVariables.current, [seedVariable]: out.snapshot.seed };
        liveVariables.current = updated;
        setVariables(updated);
      }
      submissionAccepted(out);
      await refreshJobs();
    } catch (e) {
      const serverField = typeof e.path === "string" ? e.path.replace(/^body\./, "").replace(/^variables\./, "") : "";
      if (serverField && (loadedWorkflow.current?.variable_keys || []).includes(serverField)) {
        setFieldErrors(previous => ({ ...previous, [serverField]: e.message }));
      } else if (e.fieldErrors) {
        setFieldErrors(previous => ({ ...previous, ...e.fieldErrors }));
      }
      if (e.status && e.status < 500 && (e.status !== 409 || e.code === "workflow_changed")) {
        pendingSubmission.current = null;
        try { sessionStorage.removeItem("comfyui-controller:pending-request"); } catch { /* Optional. */ }
      }
      setSubmissionUncertain(Boolean(pendingSubmission.current));
      setMessage(e.message);
    } finally {
      submitting.current = false;
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
            Create and edit with saved workflows. Execution follows the server's configured queue mode.
          </p>
        </div>
        <div className="status" data-state={browserConnection}>
          <span className="dot"></span>
          Browser connection: {browserConnection}
          <div className="hint">Tool: {selectedName || "none"} · GPU: {instanceInfo?.provider_status || "unknown"}</div>
        </div>
      </header>

      {message && <div className="notice" role="status">{message}</div>}
      <nav className="page-tabs" aria-label="Controller pages">
        <button type="button" className={activePage === "editor" ? "tab-active" : "ghost"}
          onClick={() => setActivePage("editor")}>Create &amp; edit</button>
        <button type="button" className={activePage === "jobs" ? "tab-active" : "ghost"}
          onClick={() => setActivePage("jobs")}>Jobs &amp; outputs</button>
        <button type="button" className={activePage === "infrastructure" ? "tab-active" : "ghost"}
          onClick={() => setActivePage("infrastructure")}>Infrastructure &amp; cost</button>
        <button type="button" className={activePage === "settings" ? "tab-active" : "ghost"}
          onClick={showSettings}>Settings</button>
      </nav>

      {activePage !== "settings" ? (<>
      <section hidden={activePage !== "infrastructure"} className="card instance-card" aria-label="Salad GPU worker status">
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
              <span>Requested: {instanceInfo.replicas ?? "unknown"}</span>
              <span>Group: <strong>{instanceInfo.status || "unknown"}</strong></span>
              <span>{instanceInfo.queue_mode === "direct"
                ? `Controller: SQLite pull queue · ${instanceInfo.auto_gpu_control ? "auto GPU" : "manual GPU"}`
                : `Autoscaler: ${instanceInfo.autoscaler_enabled ? "enabled" : "off"}`}</span>
              <span>Mode: <strong>{instanceInfo.keep_warm ? "Keep Warm · 1 GPU"
                : instanceInfo.queue_mode === "direct" && !instanceInfo.auto_gpu_control
                  ? "Manual · no automatic start/stop" : "Auto · scale to zero"}</strong></span>
              {instanceInfo.hold && <span>GPU HOLD: {String(instanceInfo.hold)}</span>}
              {instanceInfo.pending_change && <span>Change pending</span>}
            </div>
            <div className="instance-list">
              {(instanceInfo.instances || []).map(instance => (
                <div className="instance-item" key={instance.id}>
                  <div>
                    <strong>{instance.state || "unknown"}</strong>
                    <div className="mono">{instance.id}</div>
                    <div className="hint">
                      Provider ready: {instance.provider_ready == null ? "unknown" : instance.provider_ready ? "yes" : "no"}
                      {instance.pull_progress?.value != null ? ` · Image pull value: ${instance.pull_progress.value} (unit unknown)` : ""}
                    </div>
                  </div>
                  <button className="danger ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || instanceInfo.pending_change || instanceInfo.keep_warm}
                    title={instanceInfo.keep_warm ? "Return to Auto before stopping the GPU" : "Stop the whole Container Group"}
                    onClick={() => groupAction("stop")}>Stop worker</button>
                </div>
              ))}
              {!(instanceInfo.instances || []).length && <p className="hint">No allocated instances.</p>}
            </div>
            <p className="hint">Last observation: {instanceInfo.last_updated_at ? new Date(instanceInfo.last_updated_at).toLocaleString() : "unknown"}
              {isStale(instanceInfo, clock) || instanceError ? " · Stale data" : " · Recent observation"}</p>
            <p className="hint">Worker connection: {instanceInfo.worker_status || "unknown"}. Selected-tool readiness: unknown.</p>
            <p className="hint">Rate, estimated cost, balance and billing: unknown. {instanceInfo.financial?.limitation}</p>
            <div className="button-row">
              {instanceInfo.queue_mode === "direct" && instanceInfo.hold && (
                <button className="danger ghost" disabled={groupBusy || !tokenApplied || !adminConfigured}
                  onClick={resetGpuHold}>Reset GPU HOLD</button>
              )}
              {instanceInfo.status === "stopped" ? (
                <button className="ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || instanceInfo.pending_change || Boolean(instanceInfo.hold)}
                  onClick={() => groupAction("start")}>Start group</button>
              ) : (
                <>
                  {Number(instanceInfo.replicas || 0) === 0 && (
                    <button className="ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || instanceInfo.pending_change || Boolean(instanceInfo.hold)}
                      onClick={() => groupAction("replica")}>Start 1 GPU replica</button>
                  )}
                  {Number(instanceInfo.replicas || 0) > 0 && !(instanceInfo.instances || []).length && (
                    <button className="danger ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || instanceInfo.pending_change || instanceInfo.keep_warm}
                      onClick={() => groupAction("stop")}>Stop requested worker</button>
                  )}
                </>
              )}
            </div>
            <div className="warm-controls">
              <div>
                <strong>{instanceInfo.keep_warm ? "Keep Warm is ON"
                  : instanceInfo.queue_mode === "direct" && !instanceInfo.auto_gpu_control
                    ? "Direct GPU control is MANUAL" : "Auto scale-to-zero is ON"}</strong>
                <p className="hint">
                  {instanceInfo.keep_warm
                    ? (instanceInfo.queue_mode === "direct"
                      ? "Local Keep Warm prevents automatic idle shutdown; start the GPU separately if it is stopped. Billing continues while allocated."
                      : "Salad keeps a minimum of 1 billable GPU while this mode is enabled. Return to Auto when editing is finished.")
                    : instanceInfo.queue_mode === "direct"
                      ? (instanceInfo.auto_gpu_control
                        ? "Local scheduler starts on demand and stops after the configured idle timeout."
                        : "Start one replica manually. Automatic start/stop is disabled in private .env.")
                      : "Enable Keep Warm BEFORE a batch of edits so the GPU is not released between jobs."}
                </p>
                {instanceInfo.pending_change && <p className="hint">Salad is applying the change. Refresh to confirm before starting another action.</p>}
              </div>
              {instanceInfo.keep_warm ? (
                <button className="ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || instanceInfo.pending_change}
                  onClick={() => groupAction("auto-scale")}>Return to Auto</button>
              ) : (
                <button className="ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || instanceInfo.pending_change || instanceInfo.status === "stopped"}
                  onClick={() => groupAction("keep-warm")}>Keep Warm · 1 GPU</button>
              )}
            </div>
          </>
        ) : !instanceError && <p className="muted">Loading Salad instance status…</p>}
        <TokenControl id="admin-token" value={adminToken} status={tokenStatus} feedback={tokenFeedback}
          configured={adminConfigured} onChange={changeAdminToken} onApply={applyAdminToken} />
      </section>

      <section hidden={activePage !== "editor"} className="grid">
        <article className="card">
          <h2>1. Workflow library</h2>

          <label>Saved workflow</label>
          <select value={selected} onChange={e => loadWorkflow(e.target.value)}>
            <option value="">Choose...</option>
            {workflows.map(w => (
              <option key={w.id} value={w.id}>
                {w.name}{w.capabilities?.operation ? ` · ${w.capabilities.operation.replaceAll("_", " ")}` : ""}
                {w.capabilities?.model?.name ? ` · ${w.capabilities.model.name}` : ""}
              </option>
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
          <details className="advanced capability-editor">
            <summary>Workflow capability metadata</summary>
            <p className="hint">Optional, versioned UI metadata. Every field must be an existing placeholder, and reference roles must map to a real LoadImage node. Sampler options and numeric ranges are enabled only when declared here.</p>
            <textarea className="code compact" aria-label="Workflow capability metadata JSON"
              value={capabilitySpecDraft} onChange={e => setCapabilitySpecDraft(e.target.value)}
              placeholder={'{"schema_version":1,"operation":"image_edit","fields":{"generation.steps":{"kind":"integer","label":"Steps","minimum":1,"maximum":40,"default":8,"advanced":true}},"reference_inputs":[{"variable_key":"input.image_1","label":"Identity reference","role":"identity","order":0,"required":true}]}' }
              spellCheck={false} />
          </details>
        </article>

        <article className="card" id="inputs-run">
          <h2>2. Inputs & Run</h2>

          <p className="muted">
            Selected: <strong>{selectedName || "none"}</strong>
          </p>

          {selectedCapabilities && (
            <div className="workflow-capability-header">
              <div><strong>{selectedCapabilities.operation?.replaceAll("_", " ") || "Workflow"}</strong>
                {selectedCapabilities.model?.name && <span> · {selectedCapabilities.model.name}</span>}</div>
              <span className="pill">Model availability unverified</span>
              <p className="hint">Workflow {selectedCapabilities.workflow_version?.slice(0, 12)} · {baseReferenceSlots.length} reference slot(s) · {selectedCapabilities.outputs?.length || 0} declared output(s)</p>
            </div>
          )}

          {selectedCapabilities && (
            <details className="workflow-summary">
              <summary>Workflow structure</summary>
              {selectedCapabilities.workflow_summary?.available ? (
                <>
                  <p><strong>Inputs:</strong> {[...(selectedCapabilities.workflow_summary.inputs || []).map(item => `${item.label} (${item.role})`)].join(", ") || "No user inputs"}</p>
                  <p><strong>Model:</strong> {selectedCapabilities.model?.name || "Model loader found; filename is configurable or not declared"}</p>
                  <p><strong>LoRAs:</strong> {(selectedCapabilities.loras || []).map(item => item.name || `Configurable LoRA at node ${item.node_id}`).join(", ") || "None found in this graph"}</p>
                  <p><strong>Outputs:</strong> {(selectedCapabilities.outputs || []).map(item => item.media_type).join(", ") || "Output node not recognized"}</p>
                  <details>
                    <summary>Processing nodes and connections</summary>
                    <ol>{(selectedCapabilities.workflow_summary.nodes || []).map(node => <li key={node.node_id}>{node.label} <span className="mono">({node.category})</span></li>)}</ol>
                    <ul>{(selectedCapabilities.workflow_summary.edges || []).map((edge, index) => <li key={`${edge.from}-${edge.to}-${index}`}>Node {edge.from} → {edge.input} → node {edge.to}</li>)}</ul>
                  </details>
                </>
              ) : <p className="hint">This Workflow has no valid saved API graph summary.</p>}
            </details>
          )}

          {selected && canChooseAspectRatio && (
            <div className="field-block aspect-ratio-control">
              <label htmlFor="output-aspect-ratio">Output aspect ratio</label>
              <select id="output-aspect-ratio" value={currentAspectRatio}
                onChange={event => setAspectRatio(event.target.value)}>
                <option value="custom">Custom · {variables[widthKey] || "?"} × {variables[heightKey] || "?"}</option>
                {ASPECT_RATIOS.map(ratio => <option value={ratio.label} key={ratio.label}>{ratio.label}</option>)}
              </select>
              <p className="hint">Choosing a ratio updates the saved Workflow’s width and height inputs. Published limits and steps are applied.</p>
            </div>
          )}

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

          {selected && regularFieldKeys.map((key, index) => (
            <VariableField
              key={`${key}:${formRevision}`}
              variableKey={key}
              value={variables[key]}
              definition={fieldByKey.get(key)}
              reference={referenceByKey.get(key)}
              labelOverride={canReorderReferences && referenceByKey.has(key)
                ? `Image reference ${referenceOrder.indexOf(key) + 1}` : ""}
              reorderControl={canReorderReferences && referenceByKey.has(key) ? {
                upEnabled: referenceOrder.indexOf(key) > 0,
                downEnabled: referenceOrder.indexOf(key) < referenceOrder.length - 1,
                moveUp: () => moveReference(key, -1),
                moveDown: () => moveReference(key, 1)
              } : null}
              disabled={seedMode === "random" && key === selectedCapabilities?.seed_variable}
              uploadedName={uploadedNames[key]}
              uploading={Boolean(uploadingKey)}
              isUploading={uploadingKey === key}
              error={fieldErrors[key]}
              onFieldRef={captureFieldRef}
              onChange={updateVariable}
              onUpload={uploadFile}
              onClearUpload={clearUpload}
              onRandomizeSeed={randomizeSeed}
              onPastePrompt={pastePrompt}
            />
          ))}

          {selected && advancedFieldKeys.length > 0 && (
            <details className="advanced-settings">
              <summary>Advanced settings <span className="counter">{advancedFieldKeys.length}</span></summary>
              {selectedCapabilities?.seed_variable && (
                <div className="field-block">
                  <label htmlFor="seed-mode">Seed mode</label>
                  <select id="seed-mode" value={seedMode} onChange={e => setSeedMode(e.target.value)}>
                    <option value="fixed">Fixed seed · reuse the entered value</option>
                    <option value="random">Random seed · resolve a new value when submitted</option>
                  </select>
                  <p className="hint">The resolved seed is saved in the Job snapshot. Repeatability depends on model and runtime conditions.</p>
                </div>
              )}
              {advancedFieldKeys.map(key => (
                <VariableField key={`${key}:${formRevision}`} variableKey={key} value={variables[key]}
                  definition={fieldByKey.get(key)} reference={referenceByKey.get(key)}
                  disabled={seedMode === "random" && key === selectedCapabilities?.seed_variable}
                  uploadedName={uploadedNames[key]} uploading={Boolean(uploadingKey)} isUploading={uploadingKey === key}
                  error={fieldErrors[key]} onFieldRef={captureFieldRef} onChange={updateVariable}
                  onUpload={uploadFile} onClearUpload={clearUpload} onRandomizeSeed={randomizeSeed} onPastePrompt={pastePrompt} />
              ))}
              <button type="button" className="ghost" onClick={resetAdvancedSettings}>Reset advanced settings</button>
            </details>
          )}

          {selected && (
            <details className="preset-panel">
              <summary>Personal presets <span className="counter">{presets.length}</span></summary>
              <p className="hint">Presets are stored in this browser only. Reference images and temporary upload links are never saved. Compatible version checks prevent silently applying old settings.</p>
              <div className="preset-create">
                <label htmlFor="preset-name">Preset name</label>
                <input id="preset-name" value={presetName} maxLength={80} onChange={e => setPresetName(e.target.value)} placeholder="e.g. Portrait · soft light" />
                <label className="checkbox-label">
                  <input type="checkbox" checked={includePromptsInPreset} onChange={e => setIncludePromptsInPreset(e.target.checked)} />
                  <span>Include prompt text</span>
                </label>
                <button type="button" className="ghost" disabled={!loadedWorkflow.current || busy} onClick={savePreset}>Save preset</button>
              </div>
              {presets.length === 0 ? <p className="hint">No saved presets for this Workflow.</p> : (
                <div className="preset-list">
                  {presets.map(preset => {
                    const compatible = preset.capability_version === selectedCapabilities?.capability_version &&
                      preset.workflow_version === loadedWorkflow.current?.workflow_version;
                    return <div className="preset-row" key={preset.id}>
                      <div><strong>{preset.name}</strong>{preset.is_default && <span className="pill">Default</span>}
                        <p className="hint">{compatible ? "Compatible" : "Needs review · Workflow changed"} · {preset.includes_prompts ? "includes prompts" : "settings only"}</p>
                      </div>
                      <div className="button-row">
                        <button type="button" disabled={!compatible || busy} onClick={() => applyPreset(preset)}>Apply</button>
                        <button type="button" className="ghost" onClick={() => setDefaultPreset(preset)}>Set default</button>
                        <button type="button" className="ghost" onClick={() => renamePreset(preset)}>Rename</button>
                        <button type="button" className="danger ghost" onClick={() => deletePreset(preset)}>Delete</button>
                      </div>
                    </div>;
                  })}
                </div>
              )}
            </details>
          )}

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
              </div>
            </details>
          )}

          <label>GPU configuration (from server .env)</label>
          <p className="hint">
            {priority ? `${priority}${gpuName ? ` · ${gpuName}` : ""}` : "Loading server GPU settings..."}
          </p>
          {adminConfigured && !tokenApplied && <p className="validation">Apply a valid token in Infrastructure &amp; cost before running a Job.</p>}

          {missingImages.length > 0 && selected && (
            <p className="validation">
              Required: {missingImages.map(friendlyLabel).join(", ")}
            </p>
          )}

          {Object.keys(fieldErrors).length > 0 && (
            <p className="form-validation" role="alert">{Object.keys(fieldErrors).length} field(s) need attention. Correct the highlighted values before generating.</p>
          )}
          <div className="generate-actions">
            <button
              className="primary"
              disabled={busy || workflowLoading || submissionUncertain || Boolean(uploadingKey) || !selected || missingImages.length > 0 || Object.keys(fieldErrors).length > 0 || variablesJsonDirty || !priority || (adminConfigured && !tokenApplied)}
              onClick={run}
              aria-busy={busy}
              title={busy ? "Request is being submitted" : submissionUncertain ? "Recover the saved request first" : ""}
            >
              {busy ? "Submitting…" : "Run on Salad GPU"}
            </button>
            <button type="button" className="ghost clear-form" disabled={busy || workflowLoading || !selected || !formChanged} onClick={clearForm}>
              Clear Form
            </button>
          </div>
          {(workflowLoading || submissionUncertain || Boolean(uploadingKey) || !selected || missingImages.length > 0 || Object.keys(fieldErrors).length > 0 || variablesJsonDirty || !priority || (adminConfigured && !tokenApplied)) && (
            <p className="hint generate-reason" role="status">
              {workflowLoading ? "Loading workflow…" : adminConfigured && !tokenApplied ? (submissionUncertain ? "Apply the admin token to recover the previous request." : "Apply the admin token to enable Generate.") : submissionUncertain ? "Recover the previous request before generating." : uploadingKey ? "Wait for the image upload to finish." : !selected ? "Choose a workflow to enable Generate." : missingImages.length ? `Required: ${missingImages.map(friendlyLabel).join(", ")}` : Object.keys(fieldErrors).length ? "Correct the highlighted fields to enable Generate." : variablesJsonDirty ? "Apply JSON edits or clear them before generating." : !priority ? "Waiting for GPU configuration." : ""}
            </p>
          )}
          {currentJobId && <p className="hint" role="status">Current Job: {jobs.find(job => job.id === currentJobId)?.status || "unknown"} · See Jobs &amp; outputs for results.</p>}
          {submissionUncertain && <button className="ghost" disabled={busy || browserConnection === "checking" || (adminConfigured && !tokenApplied)} onClick={() => recoverSubmission()}>Recover last submission</button>}
        </article>
      </section>

      <section hidden={activePage !== "jobs"} className="card jobs">
        <div className="row">
          <h2>3. Recent jobs</h2>
          <button className="ghost" onClick={() => refreshJobs(true)}>Refresh all</button>
        </div>

        <div className="joblist">
          {jobs.length === 0 && <p className="muted">No jobs yet.</p>}

          {jobs.map(j => (
            <Job key={j.id} job={j} fallbackPriority={priority}
              disabled={jobBusyId === j.id}
              adminReady={adminConfigured && tokenApplied}
              onEdit={editJob} onRetry={retryJob} onDelete={hideJob} onRefresh={refreshOneJob} />
          ))}
        </div>
      </section>
      </>) : (
        <section className="card settings-card">
          <h2>Salad deployment settings</h2>
          <p className="hint">These three non-secret values live in the controller SQLite database, not .env. Saving a draft never changes the active GPU group.</p>
          <TokenControl id="settings-admin-token" value={adminToken} status={tokenStatus} feedback={tokenFeedback}
            configured={adminConfigured} onChange={changeAdminToken} onApply={applyAdminToken} />
          <div className="button-row">
            <button type="button" className="ghost" disabled={settingsBusy || !tokenApplied}
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
                <button type="button" disabled={settingsBusy || !tokenApplied}
                  onClick={saveDeploymentDraft}>Save draft to DB</button>
                <button type="button" className="primary"
                  disabled={settingsBusy || !tokenApplied || !deploymentSettings.has_changes}
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

function TokenControl({ id, value, status, feedback, configured, onChange, onApply }) {
  const busy = status === "checking";
  return (
    <div className="admin-auth">
      <label htmlFor={id}>Admin token (kept only in this browser tab)</label>
      <div className="token-entry">
        <input id={id} type="password" autoComplete="off" value={value}
          onChange={event => onChange(event.target.value)} placeholder="APP_INTERNAL_TOKEN from server .env" />
        <button type="button" disabled={!configured || busy || !value} onClick={onApply}>
          {busy ? "Checking…" : "Apply Token"}
        </button>
      </div>
      <p className="token-status" data-state={status} role="status" aria-live="polite">{feedback}</p>
      {!configured && <p className="validation">Admin actions are disabled. Set APP_INTERNAL_TOKEN in the private server .env.</p>}
    </div>
  );
}

function VariableField({
  variableKey,
  value,
  definition = null,
  labelOverride = "",
  disabled = false,
  reference = null,
  reorderControl = null,
  uploadedName,
  uploading,
  isUploading,
  error,
  onFieldRef,
  onChange,
  onUpload,
  onClearUpload,
  onRandomizeSeed,
  onPastePrompt
}) {
  const kind = variableKind(variableKey, value, definition);
  const label = labelOverride || definition?.label || reference?.label || friendlyLabel(variableKey);
  const fieldId = `variable-${variableKey}`;
  const errorId = `error-${variableKey}`;
  const errorProps = error ? { "aria-invalid": true, "aria-describedby": errorId } : {};
  const helpParts = [definition?.description];
  if (definition?.minimum != null || definition?.maximum != null) {
    helpParts.push(`Allowed: ${definition.minimum ?? "no minimum"}–${definition.maximum ?? "no maximum"}`);
  }
  if (definition?.default !== undefined && definition?.default !== null) helpParts.push(`Default: ${definition.default}`);
  if (reference) helpParts.push(`${reference.role} reference · ${reference.required ? "required" : "optional"}`);
  const help = helpParts.filter(Boolean).join(" · ");

  if (kind === "image") {
    return (
      <div className="field-block">
        <label htmlFor={fieldId}>{label}</label>
        <input
          id={fieldId}
          type="file"
          accept="image/*"
          disabled={uploading || disabled}
          onChange={e => {
            const file = e.target.files?.[0];
            e.currentTarget.value = "";
            onUpload(variableKey, file);
          }}
          {...errorProps}
        />
        <div className="upload-status">
          <span className={value ? "ready" : "hint"}>
            {isUploading
              ? "Uploading..."
              : value
                ? `Ready${uploadedName ? ` · ${uploadedName}` : ""}`
                : `${reference?.required === false ? "Optional" : "Required"} reference image`}
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
          {reorderControl && (
            <span className="reference-order-controls" aria-label={`Reorder ${label}`}>
              <button type="button" className="link-button" disabled={!reorderControl.upEnabled} onClick={reorderControl.moveUp} aria-label={`Move ${label} up`}>↑</button>
              <button type="button" className="link-button" disabled={!reorderControl.downEnabled} onClick={reorderControl.moveDown} aria-label={`Move ${label} down`}>↓</button>
            </span>
          )}
        </div>
        {help && <p className="hint">{help}</p>}
        {error && <p className="field-error" id={errorId} role="alert">{error}</p>}
      </div>
    );
  }

  if (kind === "textarea") {
    return (
      <div className="field-block">
        <div className="field-heading">
          <label htmlFor={fieldId}>{label}</label>
          <button type="button" className="ghost paste-button" aria-label={`Paste into ${label}`}
            onClick={() => onPastePrompt(variableKey)}>
            <span aria-hidden="true">▣</span> Paste
          </button>
        </div>
        <textarea
          id={fieldId}
          ref={element => onFieldRef(variableKey, element)}
          className="runtime-textarea"
          value={value ?? ""}
          disabled={disabled}
          onChange={e => onChange(variableKey, e.target.value)}
          onCompositionEnd={e => onChange(variableKey, e.currentTarget.value)}
          placeholder={`{{${variableKey}}}`}
          {...errorProps}
        />
        {help && <p className="hint">{help}</p>}
        {error && <p className="field-error" id={errorId} role="alert">{error}</p>}
      </div>
    );
  }

  if (kind === "boolean") {
    return (
      <div className="field-block checkbox-field">
        <label className="checkbox-label">
          <input
            id={fieldId}
            type="checkbox"
            ref={element => onFieldRef(variableKey, element)}
            checked={Boolean(value)}
            disabled={disabled}
            onChange={e => onChange(variableKey, e.target.checked)}
            {...errorProps}
          />
          <span>{label}</span>
        </label>
        <span className="hint"><code>{`{{${variableKey}}}`}</code></span>
        {help && <p className="hint">{help}</p>}
        {error && <p className="field-error" id={errorId} role="alert">{error}</p>}
      </div>
    );
  }

  if (kind === "select") {
    return (
      <div className="field-block">
        <label htmlFor={fieldId}>{label}</label>
        <select id={fieldId} ref={element => onFieldRef(variableKey, element)} value={value ?? ""}
          disabled={disabled} onChange={e => onChange(variableKey, e.target.value)} {...errorProps}>
          <option value="" disabled>Choose…</option>
          {(definition?.options || []).map(option => <option key={option} value={option}>{option}</option>)}
        </select>
        {help && <p className="hint">{help}</p>}
        {error && <p className="field-error" id={errorId} role="alert">{error}</p>}
      </div>
    );
  }

  if (kind === "number") {
    const isSeed = /seed/i.test(variableKey);
    const min = definition?.minimum;
    const max = definition?.maximum;
    const step = numberStep(variableKey, definition);
    return (
      <div className="field-block">
        <label htmlFor={fieldId}>{label}</label>
        <div className="inline-control">
          <input
            id={fieldId}
            type="number"
            ref={element => onFieldRef(variableKey, element)}
            step={step}
            min={min ?? undefined}
            max={max ?? undefined}
            value={value ?? ""}
            disabled={disabled}
            {...errorProps}
            onChange={e => {
              const raw = e.target.value;
              const numeric = e.target.valueAsNumber;
              onChange(variableKey, raw === "" ? "" : Number.isFinite(numeric) ? numeric : raw);
            }}
          />
          {isSeed && (
            <button
              type="button"
              className="ghost inline-button"
              disabled={disabled}
              onClick={() => onRandomizeSeed(variableKey)}
            >
              Randomize
            </button>
          )}
        </div>
        {Number.isFinite(min) && Number.isFinite(max) && max > min && (
          <input className="range-control" type="range" min={min} max={max} step={step}
            value={typeof value === "number" ? Math.min(max, Math.max(min, value)) : min}
            disabled={disabled}
            aria-label={`${label} range`}
            onChange={e => onChange(variableKey, e.target.valueAsNumber)} />
        )}
        <span className="hint"><code>{`{{${variableKey}}}`}</code></span>
        {help && <p className="hint">{help}</p>}
        {error && <p className="field-error" id={errorId} role="alert">{error}</p>}
      </div>
    );
  }

  return (
    <div className="field-block">
      <label htmlFor={fieldId}>{label}</label>
      <input
        id={fieldId}
        type="text"
        ref={element => onFieldRef(variableKey, element)}
        value={value ?? ""}
        disabled={disabled}
        onChange={e => onChange(variableKey, e.target.value)}
        placeholder={`{{${variableKey}}}`}
        {...errorProps}
      />
      {help && <p className="hint">{help}</p>}
      {error && <p className="field-error" id={errorId} role="alert">{error}</p>}
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
  const snapshot = job.snapshot || null;
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
        <p className="validation">Overdue — confirm the previous execution has stopped before retrying.</p>
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
      {snapshot && (
        <details className="job-snapshot">
          <summary>Settings used for this Job</summary>
          <p><strong>Operation:</strong> {snapshot.operation || "unknown"} · <strong>Workflow:</strong> {snapshot.workflow_id || job.workflow_id}
            {snapshot.workflow_version && <> · <strong>Version:</strong> {snapshot.workflow_version.slice(0, 12)}</>}</p>
          {snapshot.model?.name && <p><strong>Model:</strong> {String(snapshot.model.name).split(/[\\/]/).pop()}</p>}
          <p><strong>Seed:</strong> {snapshot.seed ?? "not recorded"} ({snapshot.seed_mode || "fixed"})
            {snapshot.output_spec?.width && snapshot.output_spec?.height && <> · <strong>Output:</strong> {snapshot.output_spec.width} × {snapshot.output_spec.height}</>}
            {snapshot.output_spec?.count && <> · <strong>Count:</strong> {snapshot.output_spec.count}</>}</p>
          {snapshot.positive_prompt != null && <div><strong>Positive prompt</strong><pre className="prompt-preview" dir="auto">{snapshot.positive_prompt || "(empty)"}</pre></div>}
          {snapshot.negative_prompt != null && <div><strong>Negative prompt</strong><pre className="prompt-preview" dir="auto">{snapshot.negative_prompt || "(empty)"}</pre></div>}
          {(snapshot.references || []).length > 0 && <div><strong>Reference images</strong><ol>{snapshot.references.map((reference, index) =>
            <li key={`${reference.variable}-${index}`}>{reference.label || reference.variable} · {reference.role} · slot {Number(reference.order) + 1}</li>)}</ol></div>}
          {(snapshot.loras || []).length > 0 && <div><strong>LoRAs recorded</strong><ul>{snapshot.loras.map((lora, index) =>
            <li key={`${lora.name}-${index}`}>{String(lora.name || "LoRA").split(/[\\/]/).pop()}
              {lora.strength_model != null && <> · model {lora.strength_model}</>}
              {lora.strength_clip != null && <> · CLIP {lora.strength_clip}</>}</li>)}</ul></div>}
          {snapshot.workflow_summary?.available && <details>
            <summary>Saved Workflow structure</summary>
            <ol>{(snapshot.workflow_summary.nodes || []).map(node => <li key={node.node_id}>{node.label} <span className="mono">({node.category})</span></li>)}</ol>
          </details>}
        </details>
      )}
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
