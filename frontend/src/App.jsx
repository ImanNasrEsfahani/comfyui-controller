import "./enhancements.css";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { mergeJob, mergeJobList, appendUniqueJobs, stagePercent, formatDuration, jobStateLabel,
  isStale, submissionBody, requestId, validateVariables, containsCredentialLikeData } from "./contracts.js";

const API = import.meta.env.VITE_API_BASE || "/api";
const ACCESS_REQUIRED_MESSAGE = "Private Jobs, uploads, outputs, and infrastructure need controller access. Apply the configured token in Infrastructure & cost; if the server has no token, set APP_INTERNAL_TOKEN in its private .env first.";
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
    const error = new Error(parsed?.error?.message || `Request failed (HTTP ${r.status})`);
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

function stampReceived(job) {
  return job ? { ...job, client_received_at: Date.now(),
    client_received_monotonic: globalThis.performance?.now?.() } : job;
}

function formatObservedAt(value) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString();
}

function formatMoney(value, currency) {
  if (!Number.isFinite(Number(value)) || !currency) return "Unknown";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency,
      maximumFractionDigits: 6 }).format(Number(value));
  } catch {
    return `${Number(value).toFixed(6)} ${currency}`;
  }
}

function readableStage(value) {
  return String(value || "unknown").replaceAll("_", " ");
}


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
  const historyGeneration = useRef(0);
  const historyBusy = useRef(false);
  const jobsPollFailures = useRef(0);
  const nextJobsPollAt = useRef(0);
  const instancesPolling = useRef(false);
  const instancePollFailures = useRef(0);
  const nextInstancePollAt = useRef(0);
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
  const uploadKeyRef = useRef("");
  const uploadController = useRef(null);
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
  const [historyItems, setHistoryItems] = useState([]);
  const [historyCursor, setHistoryCursor] = useState(null);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyFilters, setHistoryFilters] = useState({state: "", workflow_id: "", created_after: "", created_before: "", q: ""});
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [comparisonIds, setComparisonIds] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [lastJobsSync, setLastJobsSync] = useState(null);
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
    refreshJobs().catch(() => {});
    refreshInstances().catch(() => {});
    try {
      const pending = JSON.parse(sessionStorage.getItem("comfyui-controller:pending-request") || "null");
      if (pending?.client_request_id) {
        pendingSubmission.current = pending;
        setSubmissionUncertain(true);
      }
    } catch { /* Session storage is optional. */ }

    const jobsTimer = setInterval(() => {
      if (document.visibilityState === "visible") refreshJobs().catch(() => {});
    }, 6000);
    const instanceTimer = setInterval(() => {
      if (document.visibilityState === "visible") refreshInstances().catch(() => {});
    }, 10000);
    const clockTimer = setInterval(() => {
      if (document.visibilityState === "visible") setClock(Date.now());
    }, 1000);
    const onOnline = () => {
      setBrowserConnection("checking");
      refreshJobs(true).catch(() => {});
      refreshInstances(true).catch(() => {});
    };
    const onOffline = () => setBrowserConnection("disconnected");
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        setBrowserConnection("checking");
        refreshJobs(true).catch(() => {});
        refreshInstances(true).catch(() => {});
      }
    };
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(jobsTimer);
      clearInterval(instanceTimer);
      clearInterval(clockTimer);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  useEffect(() => {
    if (activePage === "jobs") loadHistory(true);
  }, [activePage]);

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

  async function refreshInstances(force = false) {
    if (instancesPolling.current || (!force && Date.now() < nextInstancePollAt.current)) return;
    instancesPolling.current = true;
    try {
      const data = await api("/salad/instances");
      setInstanceInfo(previous => previous?.group_name === data.group_name && previous.version > data.version ? previous : data);
      setInstanceError("");
      instancePollFailures.current = 0;
      nextInstancePollAt.current = 0;
    } catch (e) {
      instancePollFailures.current += 1;
      nextInstancePollAt.current = Date.now() + Math.min(60000, 10000 * (2 ** Math.min(3, instancePollFailures.current - 1)));
      if (e.status) setBrowserConnection("connected");
      setInstanceError(e.status === 401 || e.status === 403 || e.status === 503 ? ACCESS_REQUIRED_MESSAGE : e.message);
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
      refreshJobs(true).catch(() => {});
      refreshInstances(true).catch(() => {});
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
        ? "Stop the direct GPU Container Group? Stop is blocked while Jobs are pending, running, finalizing, transferring, or uncertain."
        : "Stop the Container Group? Stop is blocked while controller-tracked Jobs are pending, running, finalizing, transferring, or uncertain.",
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
      const updated = stampReceived(await api(`/jobs/${encodeURIComponent(job.id)}`));
      setJobs(prev => prev.map(item => item.id === job.id ? mergeJob(item, updated) : item));
      setHistoryItems(prev => prev.map(item => item.id === job.id ? mergeJob(item, updated) : item));
      setLastJobsSync(Date.now());
      setBrowserConnection("connected");
      setMessage(`Status refreshed: ${updated.state}`);
    } catch (e) {
      setMessage(e.message);
    } finally {
      setJobBusyId("");
    }
  }

  async function hideJob(job) {
    const remoteWarning = TERMINAL_STATES.has(job.state)
      ? "Hide this Job from history? This does not remove its output files."
      : job.execution_mode === "direct" && job.state === "pending"
        ? "Remove this queued Job? It will be cancelled before dispatch and hidden from history."
        : job.execution_mode === "direct"
          ? "Hide this Job from history? An active Direct Worker Job will NOT be cancelled and may continue running."
          : "Hide this Job locally? Its remote Salad Queue Job will NOT be cancelled and may still run.";
    if (!window.confirm(remoteWarning)) return;
    setJobBusyId(job.id);
    try {
      await api(`/jobs/${encodeURIComponent(job.id)}`, { method: "DELETE" });
      jobsGeneration.current += 1;
      setJobs(previous => previous.filter(item => item.id !== job.id));
      setHistoryItems(previous => previous.filter(item => item.id !== job.id));
      setComparisonIds(previous => previous.filter(id => id !== job.id));
      setComparison(null);
      setMessage("Job hidden from history. Any active execution remains unchanged.");
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

  async function editOutput(asset, job) {
    if (busy || uploadingKey || formChanged) {
      setActivePage("editor");
      setMessage("The current form has unsaved changes. Submit or reset it before loading this Job as a new draft.");
      return;
    }
    if (!asset?.s3_uri) {
      setMessage("This output has no durable asset reference and cannot be used for an edit draft.");
      return;
    }
    setJobBusyId(job.id);
    try {
      const draft = await api(`/jobs/${encodeURIComponent(job.id)}/draft`);
      await loadWorkflow(draft.workflow_id, draft.variables);
      setSeedMode(draft.seed_mode || "fixed");
      sourceJob.current = job.id;
      const draftWorkflow = loadedWorkflow.current;
      const referenceSlots = (draftWorkflow?.capabilities?.references || []).map(slot => slot.variable_key);
      const imageSlots = (draftWorkflow?.variable_keys || []).filter(key => /^input\.image_\d+$/.test(key));
      const target = referenceSlots.find(key => imageSlots.includes(key)) || imageSlots[0];
      if (!target) {
        setActivePage("editor");
        setMessage("A new draft was loaded, but its Workflow has no image reference slot for this output.");
        return;
      }
      updateVariable(target, asset.s3_uri);
      setUploadedNames(previous => ({ ...previous, [target]: `Edited from output ${asset.asset_id.slice(0, 8)}` }));
      setActivePage("editor");
      setMessage(`A separate draft now uses output ${asset.asset_id.slice(0, 8)} as ${friendlyLabel(target)}. The source Job is unchanged.`);
      requestAnimationFrame(() => document.getElementById(`variable-${target}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (e) {
      setMessage(e.message);
    } finally {
      setJobBusyId("");
    }
  }

  function useOutputAsReference(asset, job) {
    if (!selected || !asset?.s3_uri || uploadActive.current) {
      setActivePage("editor");
      setMessage(!selected ? "Choose a Workflow with an image reference slot first." : "Finish or clear the current upload before selecting an output reference.");
      return;
    }
    const capabilitySlots = (selectedCapabilities?.references || []).map(slot => slot.variable_key);
    const validSlots = (capabilitySlots.length ? capabilitySlots : imageKeys)
      .filter(key => imageKeys.includes(key) && /^input\.image_\d+$/.test(key));
    const target = validSlots.find(key => !liveVariables.current[key]);
    if (!target) {
      setActivePage("editor");
      setMessage(validSlots.length ? "Every image reference slot is filled. Clear one before using this output." : "The selected Workflow has no supported image reference slot.");
      return;
    }
    updateVariable(target, asset.s3_uri);
    setUploadedNames(previous => ({ ...previous, [target]: `Output from ${job.id.slice(0, 8)}` }));
    setActivePage("editor");
    setMessage(`${friendlyLabel(target)} now references output ${asset.asset_id.slice(0, 8)} directly; the image was not uploaded again.`);
    requestAnimationFrame(() => {
      document.getElementById(`variable-${target}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
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
      const received = stampReceived(output);
      setJobs(previous => previous.map(item => item.id === output.id ? mergeJob(item, received) : item));
      setHistoryItems(previous => previous.map(item => item.id === output.id ? mergeJob(item, received) : item));
      setMessage(`Retry accepted: ${output.id}`);
      await refreshJobs();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setJobBusyId("");
    }
  }

  async function cancelJob(job) {
    if (!window.confirm("Cancel this Job? A queued Job will be removed before execution. An active Job will remain in “Cancellation requested” until the Worker confirms the ComfyUI interrupt.")) return;
    setJobBusyId(job.id);
    try {
      const output = stampReceived(await api(`/jobs/${encodeURIComponent(job.id)}/cancel`, {method: "POST"}));
      setJobs(previous => previous.map(item => item.id === output.id ? mergeJob(item, output) : item));
      setHistoryItems(previous => previous.map(item => item.id === output.id ? mergeJob(item, output) : item));
      setMessage(output.state === "cancel_requested"
        ? "Cancellation requested. The Job will show Cancelled only after the Worker confirms it stopped."
        : output.state === "cancelled" ? "Job cancelled; it will not be dispatched." : `Job is already ${jobStateLabel(output.state).toLowerCase()}.`);
      await refreshJobs(true);
      if (activePage === "jobs") await loadHistory(true);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setJobBusyId("");
    }
  }

  function toggleComparison(job) {
    setComparison(null);
    setComparisonIds(previous => previous.includes(job.id)
      ? previous.filter(id => id !== job.id)
      : previous.length < 2 ? [...previous, job.id] : [previous[1], job.id]);
  }

  async function compareSelectedJobs() {
    if (comparisonIds.length !== 2) return;
    try {
      const params = new URLSearchParams({first_id: comparisonIds[0], second_id: comparisonIds[1]});
      setComparison(await api(`/job-comparison?${params.toString()}`));
    } catch (error) {
      setHistoryError(error.message);
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
    if (!allPending && Date.now() < nextJobsPollAt.current) return;
    jobsPolling.current = true;
    const generation = jobsGeneration.current;
    try {
    const rawList = await api("/jobs?limit=30");
    const list = rawList.map(stampReceived);
    const pending = list
      .filter(job => !TERMINAL_STATES.has(job.state))
      .slice(0, allPending === true ? 30 : 10);
    const refreshed = await Promise.all(
      pending.map(async job => {
        try {
          return stampReceived(await api(`/jobs/${encodeURIComponent(job.id)}`));
        } catch {
          return job;
        }
      })
    );

    const byId = new Map(refreshed.map(job => [job.id, job]));
    const latest = list.map(job => byId.get(job.id) || job);
    if (generation === jobsGeneration.current) {
      setJobs(previous => mergeJobList(previous, latest));
      const latestById = new Map(latest.map(job => [job.id, job]));
      setHistoryItems(previous => previous.map(item => latestById.has(item.id)
        ? mergeJob(item, latestById.get(item.id)) : item));
    }
    jobsPollFailures.current = 0;
    nextJobsPollAt.current = 0;
    setBrowserConnection("connected");
    setLastJobsSync(Date.now());
    } catch (error) {
      jobsPollFailures.current += 1;
      nextJobsPollAt.current = Date.now() + Math.min(60000, 6000 * (2 ** Math.min(4, jobsPollFailures.current - 1)));
      setBrowserConnection(error.status ? "connected" : "disconnected");
      if (error.status === 401 || error.status === 403 || error.status === 503) {
        setMessage(ACCESS_REQUIRED_MESSAGE);
      }
      throw error;
    } finally {
      jobsPolling.current = false;
    }
  }

  async function loadHistory(reset = true, filterOverride = null) {
    if (historyBusy.current) return;
    const filters = filterOverride || historyFilters;
    const generation = reset ? historyGeneration.current + 1 : historyGeneration.current;
    historyGeneration.current = generation;
    historyBusy.current = true;
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const params = new URLSearchParams({limit: "24"});
      if (filters.state) params.set("state", filters.state);
      if (filters.workflow_id) params.set("workflow_id", filters.workflow_id);
      if (filters.created_after) params.set("created_after", new Date(`${filters.created_after}T00:00:00`).toISOString());
      if (filters.created_before) params.set("created_before", new Date(`${filters.created_before}T23:59:59.999`).toISOString());
      if (filters.q.trim()) params.set("q", filters.q.trim());
      if (!reset && historyCursor) params.set("cursor", historyCursor);
      const page = await api(`/jobs/history?${params.toString()}`);
      if (generation !== historyGeneration.current) return;
      const items = (page.items || []).map(stampReceived);
      setHistoryItems(previous => reset ? items : appendUniqueJobs(previous, items));
      setHistoryTotal(page.total || 0);
      setHistoryCursor(page.next_cursor || null);
      setLastJobsSync(Date.now());
    } catch (error) {
      if (generation === historyGeneration.current) {
        if (error.status) setBrowserConnection("connected");
        setHistoryError(error.status === 401 || error.status === 403 || error.status === 503
          ? ACCESS_REQUIRED_MESSAGE : error.message);
      }
    } finally {
      historyBusy.current = false;
      setHistoryLoading(false);
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
    uploadController.current?.abort();
    uploadController.current = null;
    uploadActive.current = false;
    uploadKeyRef.current = "";
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
    setFormRevision(version => version + 1);
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

    if (uploadActive.current && uploadKeyRef.current !== key) {
      setMessage(`Finish or clear ${friendlyLabel(uploadKeyRef.current)} before uploading another reference.`);
      return;
    }
    if (file.type && !file.type.toLowerCase().startsWith("image/")) {
      setFieldErrors(previous => ({ ...previous, [key]: "Choose an image file." }));
      setMessage(`${friendlyLabel(key)} must be an image file.`);
      return;
    }

    if (uploadActive.current) uploadController.current?.abort();
    const revision = ++uploadRevision.current;
    uploadActive.current = true;
    uploadKeyRef.current = key;
    const controller = new AbortController();
    uploadController.current = controller;
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
      const out = await api("/uploads", { method: "POST", body: form, signal: controller.signal });
      if (revision !== uploadRevision.current || selection !== selectionRequest.current) return;
      if (typeof out?.s3_uri !== "string" || !out.s3_uri) {
        throw new Error("The upload completed without an image reference. Try again.");
      }

      // A stable URI survives R2 signature expiry; the backend signs it for each run.
      updateVariable(key, out.s3_uri);
      setUploadedNames(prev => ({ ...prev, [key]: file.name }));
      setMessage(`${friendlyLabel(key)} uploaded successfully.`);
    } catch (e) {
      if (revision === uploadRevision.current && selection === selectionRequest.current && e.name !== "AbortError") {
        setFieldErrors(previous => ({ ...previous, [key]: e.message || "Image upload failed. Try again." }));
        setMessage(e.message || "Image upload failed. Try again.");
      }
    } finally {
      if (revision === uploadRevision.current) {
        uploadActive.current = false;
        uploadKeyRef.current = "";
        uploadController.current = null;
        setUploadingKey("");
      }
    }
  }

  function clearUpload(key, preserveExisting = false) {
    if (uploadingKey === key) {
      uploadRevision.current += 1;
      uploadController.current?.abort();
      uploadController.current = null;
      uploadActive.current = false;
      uploadKeyRef.current = "";
      setUploadingKey("");
    }
    if (!preserveExisting || !liveVariables.current[key]) {
      updateVariable(key, "");
      setUploadedNames(prev => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
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
    uploadController.current?.abort();
    uploadController.current = null;
    uploadActive.current = false;
    uploadKeyRef.current = "";
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
    const accepted = stampReceived(out);
    setCurrentJobId(accepted.id);
    jobsGeneration.current += 1;
    setJobs(previous => [mergeJob(previous.find(job => job.id === accepted.id), accepted), ...previous.filter(job => job.id !== accepted.id)]);
    setMessage(`Accepted: ${accepted.id} · ${accepted.status || accepted.state}. Output appears in Jobs & outputs after completion.`);
  }

  async function recoverSubmission(resend = true) {
    if (!adminConfigured || !sessionToken) {
      setMessage(ACCESS_REQUIRED_MESSAGE);
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
    if (!adminConfigured || !tokenApplied) {
      setMessage(ACCESS_REQUIRED_MESSAGE);
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
      if (activePage === "jobs") await loadHistory(true);
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

  const infrastructureActivity = instanceInfo?.job_activity || {};
  const infrastructureControlPending = Boolean(instanceInfo?.pending_change || instanceInfo?.pending_operation);
  const infrastructureStopBlocked = Boolean(infrastructureActivity.stop_blocked);
  const infrastructureFinancial = instanceInfo?.financial || {};
  const infrastructureSessions = instanceInfo?.sessions || [];

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
          <button className="ghost" onClick={() => refreshInstances(true)}>Refresh instances</button>
        </div>
        {instanceError && <p className="validation">Instance status unavailable: {instanceError}</p>}
        {instanceInfo ? (
          <>
            <div className="instance-summary">
              <span><strong>{instanceInfo.instances?.length ?? 0}</strong> instances</span>
              <span>Requested: {instanceInfo.replicas ?? "unknown"}</span>
              <span>Group: <strong>{instanceInfo.status || "unknown"}</strong></span>
              <span>Phase: <strong>{instanceInfo.phase_label || readableStage(instanceInfo.phase)}</strong></span>
              <span>Ready: <strong>{readableStage(instanceInfo.readiness || "unknown")}</strong></span>
              <span>{instanceInfo.queue_mode === "direct"
                ? `Controller: SQLite pull queue · ${instanceInfo.auto_gpu_control ? "auto GPU" : "manual GPU"}`
                : `Autoscaler: ${instanceInfo.autoscaler_enabled ? "enabled" : "off"}`}</span>
              <span>Mode: <strong>{instanceInfo.keep_warm ? "Keep Warm · 1 GPU"
                : instanceInfo.queue_mode === "direct" && !instanceInfo.auto_gpu_control
                  ? "Manual · no automatic start/stop" : "Auto · scale to zero"}</strong></span>
              {instanceInfo.hold && <span>GPU HOLD: {String(instanceInfo.hold)}</span>}
              {instanceInfo.pending_change && <span>Change pending</span>}
              {instanceInfo.pending_operation && <span>Operation pending: {readableStage(instanceInfo.pending_operation.action)}</span>}
            </div>
            <div className="instance-list">
              {(instanceInfo.instances || []).map(instance => (
                <div className="instance-item" key={instance.id}>
                  <div>
                    <strong>{instance.phase_label || readableStage(instance.state || instance.provider_status)}</strong>
                    <div className="mono">{instance.id}</div>
                    <div className="hint">
                      Provider ready: {instance.provider_ready == null ? "unknown" : instance.provider_ready ? "yes" : "no"}
                      {instance.pull_progress?.percent != null
                        ? ` · Image pull: ${instance.pull_progress.percent}%`
                        : instance.pull_progress?.raw_value != null
                          ? ` · Image pull progress: ${instance.pull_progress.raw_value}${instance.pull_progress.unit ? ` ${instance.pull_progress.unit}` : " (unit unknown)"}` : ""}
                    </div>
                    {instance.pull_progress?.percent != null && <progress className="instance-progress" max="100" value={instance.pull_progress.percent} aria-label="Image pull progress" />}
                    <div className="hint">Observed session: {formatDuration(instance.session_duration_seconds)}
                      {instance.ready_duration_seconds != null ? ` · Ready time: ${formatDuration(instance.ready_duration_seconds)}` : " · Ready time: not recorded"}</div>
                  </div>
                  <button className="danger ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || infrastructureControlPending || instanceInfo.keep_warm || infrastructureStopBlocked}
                    title={infrastructureStopBlocked ? "Finish or resolve all pending, active, finalizing, and uncertain Jobs first" : instanceInfo.keep_warm ? "Return to Auto before stopping the GPU" : "Stop the whole Container Group"}
                    onClick={() => groupAction("stop")}>Stop worker</button>
                </div>
              ))}
              {!(instanceInfo.instances || []).length && <p className="hint">No allocated instances.</p>}
            </div>
            <p className="hint">Last observation: {instanceInfo.last_updated_at ? new Date(instanceInfo.last_updated_at).toLocaleString() : "unknown"}
              {isStale(instanceInfo, clock) || instanceError ? " · Stale data" : " · Recent observation"}</p>
            <p className="hint">Worker connection: {instanceInfo.worker?.status || instanceInfo.worker_status || "unknown"}
              {instanceInfo.worker?.runtime_readiness ? ` · ComfyUI runtime: ${instanceInfo.worker.runtime_readiness}` : ""}
              {instanceInfo.worker?.last_heartbeat_at ? ` · Last authenticated heartbeat: ${formatObservedAt(instanceInfo.worker.last_heartbeat_at)}` : ""}</p>
            <p className="hint">Selected model readiness: {instanceInfo.model_readiness || "unknown"}. {instanceInfo.model_readiness_reason}</p>
            <div className="instance-cost-grid">
              <span><small>Operator rate</small><strong>{infrastructureFinancial.hourly_rate != null
                ? `${formatMoney(infrastructureFinancial.hourly_rate, infrastructureFinancial.currency)}/hour` : "Unknown"}</strong></span>
              <span><small>Estimated observed cost</small><strong>{infrastructureFinancial.estimated_cost != null
                ? formatMoney(infrastructureFinancial.estimated_cost, infrastructureFinancial.estimated_cost_currency) : "Unknown"}</strong></span>
              <span><small>Account balance</small><strong>Unknown</strong></span>
              <span><small>Provider billing</small><strong>Unknown</strong></span>
            </div>
            <p className="hint">Cost estimate formula: configured hourly rate × controller-observed allocated seconds ÷ 3,600. Estimate scope: {readableStage(infrastructureFinancial.estimate_scope || "not available")}. Billing boundaries are not known. {infrastructureFinancial.limitation}</p>
            {Object.entries(infrastructureFinancial.estimated_cost_by_currency || {}).length > 1 && <p className="hint">Separate currency estimates: {Object.entries(infrastructureFinancial.estimated_cost_by_currency).map(([currency, value]) => `${formatMoney(value, currency)} (${currency})`).join(" · ")}</p>}
            <div className="job-activity-summary" role="status">
              <strong>Job activity guard</strong>
              <span>Pending {infrastructureActivity.pending || 0}</span><span>Running {infrastructureActivity.running || 0}</span>
              <span>Finalizing / transfer {infrastructureActivity.finalizing || infrastructureActivity.transferring || 0}</span>
              <span>Uncertain {infrastructureActivity.uncertain || 0}</span>
              {infrastructureStopBlocked && <span className="stop-guard">Stop and scale-to-zero are disabled until activity clears.</span>}
            </div>
            {instanceInfo.pending_operation && <p className="operation-pending" role="status">
              {instanceInfo.pending_operation.safe_detail || "Waiting for Salad to report the requested target state."}
              {instanceInfo.pending_operation.requested_at ? ` · Requested ${formatObservedAt(instanceInfo.pending_operation.requested_at)}` : ""}
            </p>}
            {instanceInfo.phase_timeline?.length > 0 && <div className="instance-timeline">
              <h3>Lifecycle observations</h3>
              <ol>{instanceInfo.phase_timeline.slice(-12).map(event => <li key={event.event_id}>
                <strong>{readableStage(event.stage)}</strong><span>{formatObservedAt(event.observed_at)}</span>
                {event.provider_status && <small>Provider: {event.provider_status}</small>}
              </li>)}</ol>
            </div>}
            {infrastructureSessions.length > 0 && <details className="instance-sessions">
              <summary>Observed sessions and cost estimates ({infrastructureSessions.length})</summary>
              <div>{infrastructureSessions.slice(0, 8).map(session => <p key={session.session_id}>
                <strong>{session.instance_id}</strong> · Started {formatObservedAt(session.started_at)} · Duration {formatDuration(session.duration_seconds)}
                {session.first_ready_at ? ` · Ready ${formatObservedAt(session.first_ready_at)}` : " · Ready time not recorded"}
                {Object.entries(session.estimated_cost_by_currency || {}).map(([currency, amount]) => ` · Estimated ${formatMoney(amount, currency)}`).join("")}
              </p>)}</div>
            </details>}
            <div className="button-row">
              {instanceInfo.queue_mode === "direct" && instanceInfo.hold && (
                <button className="danger ghost" disabled={groupBusy || !tokenApplied || !adminConfigured}
                  onClick={resetGpuHold}>Reset GPU HOLD</button>
              )}
              {instanceInfo.status === "stopped" ? (
                <button className="ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || infrastructureControlPending || Boolean(instanceInfo.hold)}
                  onClick={() => groupAction("start")}>Start group</button>
              ) : (
                <>
                  {Number(instanceInfo.replicas || 0) === 0 && (
                    <button className="ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || infrastructureControlPending || Boolean(instanceInfo.hold)}
                      onClick={() => groupAction("replica")}>Start 1 GPU replica</button>
                  )}
                  {Number(instanceInfo.replicas || 0) > 0 && !(instanceInfo.instances || []).length && (
                    <button className="danger ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || infrastructureControlPending || instanceInfo.keep_warm || infrastructureStopBlocked}
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
                {infrastructureControlPending && <p className="hint">An operation is awaiting provider confirmation. Refresh to confirm before starting another action.</p>}
              </div>
              {instanceInfo.keep_warm ? (
                <button className="ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || infrastructureControlPending || infrastructureStopBlocked}
                  onClick={() => groupAction("auto-scale")}>Return to Auto</button>
              ) : (
                <button className="ghost" disabled={groupBusy || !tokenApplied || !adminConfigured || infrastructureControlPending || instanceInfo.status === "stopped"}
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
              uploadDisabled={!adminConfigured || !tokenApplied}
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
                  uploadDisabled={!adminConfigured || !tokenApplied}
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
          {(!adminConfigured || !tokenApplied) && <p className="validation">{ACCESS_REQUIRED_MESSAGE}</p>}

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
              disabled={busy || workflowLoading || submissionUncertain || Boolean(uploadingKey) || !selected || missingImages.length > 0 || Object.keys(fieldErrors).length > 0 || variablesJsonDirty || !priority || !adminConfigured || !tokenApplied}
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
          {(workflowLoading || submissionUncertain || Boolean(uploadingKey) || !selected || missingImages.length > 0 || Object.keys(fieldErrors).length > 0 || variablesJsonDirty || !priority || !adminConfigured || !tokenApplied) && (
            <p className="hint generate-reason" role="status">
              {workflowLoading ? "Loading workflow…" : !adminConfigured || !tokenApplied ? ACCESS_REQUIRED_MESSAGE : submissionUncertain ? "Recover the previous request before generating." : uploadingKey ? "Wait for the image upload to finish." : !selected ? "Choose a workflow to enable Generate." : missingImages.length ? `Required: ${missingImages.map(friendlyLabel).join(", ")}` : Object.keys(fieldErrors).length ? "Correct the highlighted fields to enable Generate." : variablesJsonDirty ? "Apply JSON edits or clear them before generating." : !priority ? "Waiting for GPU configuration." : ""}
            </p>
          )}
          {currentJobId && <p className="hint" role="status">Current Job: {jobs.find(job => job.id === currentJobId)?.status || "unknown"} · See Jobs &amp; outputs for results.</p>}
          {submissionUncertain && <button className="ghost" disabled={busy || browserConnection === "checking" || !adminConfigured || !tokenApplied} onClick={() => recoverSubmission()}>Recover last submission</button>}
        </article>
      </section>

      <section hidden={activePage !== "jobs"} className="card jobs">
        <div className="row history-heading">
          <div><h2>Job history</h2><p className="hint">Saved Jobs and outputs are restored from the controller after a refresh.</p></div>
          <div className="button-row">
            <button className="ghost" onClick={() => { refreshJobs(true).catch(() => {}); loadHistory(true); }}>Refresh history</button>
            <button className="ghost" disabled={comparisonIds.length !== 2} onClick={compareSelectedJobs}>Compare selected ({comparisonIds.length}/2)</button>
          </div>
        </div>
        <p className={`history-connection ${browserConnection}`} role="status">
          Controller connection: {browserConnection === "connected" ? "Connected" : browserConnection === "disconnected" ? "Disconnected; saved Job state is unchanged" : "Checking"}
          {lastJobsSync ? ` · Last data received ${new Date(lastJobsSync).toLocaleTimeString()}` : " · No successful history refresh yet"}
        </p>
        <form className="history-filters" onSubmit={event => { event.preventDefault(); setComparison(null); loadHistory(true); }}>
          <label>Status
            <select value={historyFilters.state} onChange={event => setHistoryFilters(previous => ({...previous, state: event.target.value}))}>
              <option value="">All statuses</option><option value="pending">Queued</option><option value="running">Running</option>
              <option value="finalizing">Saving output</option><option value="cancel_requested">Cancellation requested</option>
              <option value="succeeded">Completed</option><option value="failed">Failed</option><option value="cancelled">Cancelled</option>
              <option value="stalled">Worker status uncertain</option><option value="submit_failed">Could not submit</option>
            </select>
          </label>
          <label>Tool / Workflow
            <select value={historyFilters.workflow_id} onChange={event => setHistoryFilters(previous => ({...previous, workflow_id: event.target.value}))}>
              <option value="">All tools</option>{workflows.map(workflow => <option key={workflow.id} value={workflow.id}>{workflow.name || workflow.id}</option>)}
            </select>
          </label>
          <label>Created after<input type="date" value={historyFilters.created_after}
            onChange={event => setHistoryFilters(previous => ({...previous, created_after: event.target.value}))} /></label>
          <label>Created before<input type="date" value={historyFilters.created_before}
            onChange={event => setHistoryFilters(previous => ({...previous, created_before: event.target.value}))} /></label>
          <label className="history-search">Search prompt<input type="search" value={historyFilters.q} maxLength={160}
            onChange={event => setHistoryFilters(previous => ({...previous, q: event.target.value}))}
            placeholder="Search saved prompts" /></label>
          <div className="history-filter-actions">
            <button type="submit" disabled={historyLoading}>{historyLoading ? "Searching…" : "Search"}</button>
            <button type="button" className="ghost" disabled={historyLoading} onClick={() => {
              const empty = {state: "", workflow_id: "", created_after: "", created_before: "", q: ""};
              setHistoryFilters(empty); setComparison(null); setComparisonIds([]); loadHistory(true, empty);
            }}>Clear filters</button>
          </div>
        </form>
        <div className="history-count">Showing {historyItems.length} of {historyTotal} matching Jobs</div>
        {historyError && <p className="validation" role="alert">{historyError}</p>}
        {comparison && <section className="comparison-panel" aria-label="Job snapshot comparison">
          <div className="row"><h3>Snapshot comparison</h3><button className="ghost" onClick={() => setComparison(null)}>Close comparison</button></div>
          <p className="hint">Comparing {comparison.first_id} with {comparison.second_id}. Values come from each saved Job snapshot.</p>
          <div className="comparison-scroll"><table><thead><tr><th>Setting</th><th>First Job</th><th>Second Job</th><th>Difference</th></tr></thead>
            <tbody>{Object.keys(comparison.first || {}).map(key => {
              const left = comparison.first[key]; const right = comparison.second[key];
              const different = left !== right && JSON.stringify(left) !== JSON.stringify(right);
              const format = value => value == null || value === "" ? "Not recorded" : typeof value === "object" ? JSON.stringify(value) : String(value);
              return <tr key={key} className={different ? "comparison-different" : ""}><th>{key.replaceAll("_", " ")}</th>
                <td dir="auto">{format(left)}</td><td dir="auto">{format(right)}</td><td>{different ? "Different" : "Same"}</td></tr>;
            })}</tbody></table></div>
          {comparison.differences?.length === 0 && <p className="hint">No recorded snapshot differences.</p>}
        </section>}
        <div className="joblist">
          {historyItems.length === 0 && !historyLoading && <p className="muted">No Jobs match these filters.</p>}
          {historyItems.map(j => (
            <Job key={j.id} job={j} fallbackPriority={priority} clock={clock}
              disabled={jobBusyId === j.id}
              adminReady={adminConfigured && tokenApplied}
              comparisonSelected={comparisonIds.includes(j.id)}
              comparisonDisabled={comparisonIds.length === 2 && !comparisonIds.includes(j.id)}
              onCompare={toggleComparison} onEdit={editJob} onRetry={retryJob} onCancel={cancelJob}
              onEditOutput={editOutput} onUseReference={useOutputAsReference}
              onDelete={hideJob} onRefresh={refreshOneJob} />
          ))}
        </div>
        {historyCursor && <button className="ghost history-more" disabled={historyLoading} onClick={() => loadHistory(false)}>
          {historyLoading ? "Loading…" : "Load more Jobs"}
        </button>}
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
      {!configured && <p className="validation">Private controller data, uploads, and admin actions are disabled. Set APP_INTERNAL_TOKEN in the private server .env.</p>}
    </div>
  );
}

function VariableField({
  variableKey,
  value,
  definition = null,
  labelOverride = "",
  disabled = false,
  uploadDisabled = false,
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
  const [localPreview, setLocalPreview] = useState(null);
  const [draggingFile, setDraggingFile] = useState(false);
  useEffect(() => () => {
    if (localPreview?.url) URL.revokeObjectURL(localPreview.url);
  }, [localPreview?.url]);

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
    const chooseFile = file => {
      if (!file || uploadDisabled) return;
      const url = URL.createObjectURL(file);
      setLocalPreview({ url, file, name: file.name, size: file.size });
      onUpload(variableKey, file);
    };
    const status = isUploading ? "Uploading · progress unavailable" : error ? value ? "Replacement failed · current image kept" : "Upload failed" : value ? "Ready" : localPreview ? "Selected" : "Empty";
    const statusName = error && value ? uploadedName : isUploading ? localPreview?.name : uploadedName || localPreview?.name;
    return (
      <div className={`field-block image-field${draggingFile ? " is-dragging" : ""}`}
        onDragOver={event => { event.preventDefault(); setDraggingFile(true); }}
        onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setDraggingFile(false); }}
        onDrop={event => { event.preventDefault(); setDraggingFile(false); if (!uploadDisabled && (!uploading || isUploading)) chooseFile(event.dataTransfer.files?.[0]); }}>
        <label htmlFor={fieldId}>{label}</label>
        <input
          id={fieldId}
          type="file"
          ref={element => onFieldRef(variableKey, element)}
          accept="image/png,image/jpeg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif"
          disabled={disabled || uploadDisabled || (uploading && !isUploading)}
          onChange={e => {
            const file = e.target.files?.[0];
            e.currentTarget.value = "";
            chooseFile(file);
          }}
          {...errorProps}
        />
        <div className="upload-status">
          <span className={error ? "field-error" : value ? "ready" : "hint"} role="status" aria-live="polite" data-upload-state={status.toLowerCase()}>
            {status}{statusName ? ` · ${statusName}` : ` · ${reference?.required === false ? "optional" : "required"} reference`}
          </span>
          {(value || localPreview || isUploading) && (
            <button
              type="button"
              className="link-button"
              onClick={() => { setLocalPreview(null); onClearUpload(variableKey, isUploading && Boolean(value)); }}
            >
              {isUploading && value ? "Cancel replacement" : isUploading ? "Cancel upload" : "Remove"}
            </button>
          )}
          {reorderControl && (
            <span className="reference-order-controls" aria-label={`Reorder ${label}`}>
              <button type="button" className="link-button" disabled={!reorderControl.upEnabled} onClick={reorderControl.moveUp} aria-label={`Move ${label} up`}>↑</button>
              <button type="button" className="link-button" disabled={!reorderControl.downEnabled} onClick={reorderControl.moveDown} aria-label={`Move ${label} down`}>↓</button>
            </span>
          )}
        </div>
        {isUploading && <progress className="upload-progress" aria-label={`Uploading ${label}; exact progress unavailable`} />}
        <p className="hint upload-drop-hint">{uploadDisabled ? "Apply controller access in Infrastructure & cost before uploading a reference image." : "Drop an image here or choose a file. Preview appears locally before upload."}</p>
        {localPreview && <div className="input-image-preview">
          <img src={localPreview.url} alt={`Local preview of ${localPreview.name}`} />
          <span>{(localPreview.size / 1024 / 1024).toFixed(2)} MB · local preview</span>
        </div>}
        {error && !isUploading && localPreview && <button type="button" className="ghost upload-retry" disabled={uploadDisabled} onClick={() => onUpload(variableKey, localPreview.file)}>Retry upload</button>}
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
          dir="auto"
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
        dir="auto"
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

function elapsedSeconds(job, field, clock) {
  const seconds = job.timing?.[field];
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const active = !TERMINAL_STATES.has(job.state) && job.state !== "stalled";
  const hasStarted = Boolean(job.started_at || job.attempt_history?.some(attempt => attempt.started_at));
  const shouldTick = active && (field === "total_seconds" ||
    (field === "worker_seconds" && hasStarted) ||
    (field === "first_queue_wait_seconds" && !hasStarted));
  const monotonicNow = globalThis.performance?.now?.();
  const elapsedMs = Number.isFinite(monotonicNow) && Number.isFinite(job.client_received_monotonic)
    ? monotonicNow - job.client_received_monotonic : clock - (job.client_received_at || clock);
  return seconds + (shouldTick ? Math.max(0, elapsedMs) / 1000 : 0);
}

function Job({ job, fallbackPriority, disabled, adminReady, clock, comparisonSelected,
  comparisonDisabled, onCompare, onEdit, onEditOutput, onUseReference, onRetry, onCancel, onDelete, onRefresh }) {
  const [images, setImages] = useState([]);
  const [imageError, setImageError] = useState("");
  const [loadingImages, setLoadingImages] = useState(false);
  const [lightbox, setLightbox] = useState(null);
  const [zoom, setZoom] = useState(1);
  const closeLightboxRef = useRef(null);
  const latestLightbox = useRef(null);
  const galleryAssetsRef = useRef([]);
  const imageRequest = useRef(0);

  async function refreshImages() {
    const request = ++imageRequest.current;
    setLoadingImages(true);
    setImageError("");
    try {
      const response = await api(`/jobs/${encodeURIComponent(job.id)}/images`);
      if (request !== imageRequest.current) return;
      const returned = response.assets?.length ? response.assets : response.images || [];
      setImages(returned);
      if (!returned.some(asset => asset.status === "available" || asset.url)) setImageError("No verified output has been found in private storage yet.");
      else setImageError("");
    } catch (e) {
      if (request === imageRequest.current) setImageError(e.message);
    } finally {
      if (request === imageRequest.current) setLoadingImages(false);
    }
  }

  useEffect(() => {
    if (["succeeded", "failed", "cancelled"].includes(job.state)) refreshImages();
    else { imageRequest.current += 1; setLoadingImages(false); }
  }, [job.id, job.state]);

  const refreshedById = new Map(images.map(asset => [asset.asset_id || asset.storage_key || asset.key, asset]));
  const apiAssets = job.assets?.length
    ? job.assets.map(asset => ({ ...asset, ...(refreshedById.get(asset.asset_id || asset.storage_key || asset.key) || {}) }))
    : images;
  const galleryAssets = [...apiAssets].sort((a, b) => String(a.asset_id || a.storage_key || a.key).localeCompare(String(b.asset_id || b.storage_key || b.key)));
  const availableAssets = galleryAssets.filter(asset => asset.status === "available" || (!asset.status && asset.url));
  const attemptSequence = new Map((job.attempt_history || []).map(attempt => [attempt.id, attempt.sequence]));
  galleryAssetsRef.current = availableAssets;
  latestLightbox.current = lightbox;

  function openLightbox(asset) {
    setZoom(1);
    setLightbox({ assetId: asset.asset_id || asset.storage_key || asset.key });
  }

  function moveLightbox(delta) {
    const list = galleryAssetsRef.current;
    if (list.length < 2) return;
    const at = list.findIndex(asset => (asset.asset_id || asset.storage_key || asset.key) === latestLightbox.current?.assetId);
    const next = list[(at + delta + list.length) % list.length];
    setLightbox({ assetId: next.asset_id || next.storage_key || next.key });
    setZoom(1);
  }

  useEffect(() => {
    if (!lightbox) return undefined;
    const restore = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(() => closeLightboxRef.current?.focus());
    const onKeyDown = event => {
      const current = latestLightbox.current;
      const assets = galleryAssetsRef.current;
      if (!current) return;
      if (event.key === "Escape") { event.preventDefault(); setLightbox(null); return; }
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const at = assets.findIndex(asset => (asset.asset_id || asset.storage_key || asset.key) === current.assetId);
        const delta = event.key === "ArrowRight" ? 1 : -1;
        const next = assets[(at + delta + assets.length) % assets.length];
        if (next) { setLightbox({ assetId: next.asset_id || next.storage_key || next.key }); setZoom(1); }
        return;
      }
      if (event.key === "Tab") {
        const dialog = document.querySelector(".output-lightbox[role='dialog']");
        const focusable = [...(dialog?.querySelectorAll("button:not([disabled]),a[href],input:not([disabled]),[tabindex]:not([tabindex='-1'])") || [])];
        if (!focusable.length) return;
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      restore?.focus?.();
    };
  }, [Boolean(lightbox)]);

  const retryable = RETRYABLE_STATES.has(job.state) && job.variables !== null &&
    !(job.state === "stalled" && job.execution_mode === "direct");
  const canManage = adminReady && !disabled;
  const snapshot = job.snapshot || null;
  const active = !TERMINAL_STATES.has(job.state) && job.state !== "stalled";
  const progress = job.progress || null;
  const percent = stagePercent(progress);
  const prompt = snapshot?.positive_prompt ?? job.variables?.["prompt.positive"] ?? job.variables?.["prompt.user"] ?? "";
  const opName = snapshot?.operation === "image_edit" ? "Image edit" :
    snapshot?.operation ? String(snapshot.operation).replaceAll("_", " ") : job.workflow_id || "AI Job";
  const modelName = snapshot?.model?.name || snapshot?.model_id || "Model not recorded";
  const outputCount = job.output_summary?.available ?? job.assets?.filter(asset => asset.status === "available").length ?? 0;
  const expectedOutputs = job.output_summary?.expected_count;
  const failureActions = {
    input: "Edit the inputs, then run a new Job.",
    preparation: "Check the Workflow setup, then retry if the cause is resolved.",
    capacity: "Wait for capacity, then retry.",
    worker: "Review the saved error, then retry the same snapshot.",
    output_transfer: "Refresh outputs first; retry only if no valid output was saved.",
    communication: "Refresh the Job. Retry only after confirming the previous execution stopped."
  };
  const workerHeartbeat = job.communication?.worker_last_heartbeat_at;
  const waitSeconds = elapsedSeconds(job, "first_queue_wait_seconds", clock);
  const workerSeconds = elapsedSeconds(job, "worker_seconds", clock);
  const totalSeconds = elapsedSeconds(job, "total_seconds", clock);
  const activeAssetsCount = job.active_attempt_id
    ? galleryAssets.filter(asset => asset.attempt_id === job.active_attempt_id).length
    : galleryAssets.length;
  const expectedTiles = Math.max(0, Math.min(12, Number(snapshot?.output_spec?.count) || (active ? 1 : 0)) - activeAssetsCount);
  const selectedLightboxAsset = availableAssets.find(asset => (asset.asset_id || asset.storage_key || asset.key) === lightbox?.assetId);

  function downloadUrl(asset) {
    if (asset.asset_id) return `${API}/jobs/${encodeURIComponent(job.id)}/assets/${encodeURIComponent(asset.asset_id)}/download`;
    return asset.url || "";
  }

  return (
    <article className={`job-card job-${job.state || "unknown"}`}>
      <div className="job-card-heading">
        <div className="job-title-wrap">
          <div className="job-title-line"><strong>{opName}</strong><span className={`pill ${job.state || "unknown"}`}>{jobStateLabel(job.state)}</span></div>
          <div className="job-model">{String(modelName).split(/[\\/]/).pop()} · {job.workflow_id || "Workflow not recorded"}</div>
          {prompt && <p className="job-prompt" dir="auto">{String(prompt).trim().slice(0, 220)}{String(prompt).trim().length > 220 ? "…" : ""}</p>}
        </div>
        <div className="job-created">{job.created_at ? new Date(job.created_at).toLocaleString() : "Creation time unavailable"}</div>
      </div>
      {job.state === "stalled" && (
        <p className="validation">Worker status is uncertain. The previous execution may still be running; confirm it stopped before retrying.</p>
      )}
      {job.state === "cancel_requested" && <p className="job-cancel-pending" role="status">Cancellation requested. Waiting for the Worker to confirm the ComfyUI interrupt.</p>}
      {job.error_text && <div className="job-error" role="alert">
        <strong>{job.error_category ? job.error_category.replaceAll("_", " ") : "Job error"}</strong>
        <p>{job.error_text}</p>
        {failureActions[job.error_category] && <span className="hint">{failureActions[job.error_category]}</span>}
      </div>}
      {job.poll_warning && <p className="hint">{job.poll_warning}</p>}
      <div className="job-stage">
        <strong aria-live="polite">{progress?.label || (job.state === "pending" ? "Waiting for a Worker" : jobStateLabel(job.state))}</strong>
        {progress && percent !== null ? (
          <div className="job-progress-block">
            <div className="job-progress-caption"><span>{progress.label} · stage progress</span><span>{progress.value}/{progress.total} {progress.unit || ""} ({percent}%)</span></div>
            <progress max="100" value={percent} aria-label={`${progress.label} stage progress`} aria-valuetext={`${progress.value} of ${progress.total} ${progress.unit || "steps"}`} />
            <small>This is progress for the current stage, not the whole Job.</small>
          </div>
        ) : active && progress ? <div className="job-indeterminate"><span aria-hidden="true" />Stage in progress; this stage has no measurable percentage.</div> : null}
      </div>
      <div className="job-metrics">
        <span><small>Queue wait to first attempt</small><strong>{formatDuration(waitSeconds)}</strong></span>
        <span><small>Worker time</small><strong>{formatDuration(workerSeconds)}</strong></span>
        <span><small>Total elapsed</small><strong>{formatDuration(totalSeconds)}</strong></span>
        <span><small>Outputs</small><strong>{expectedOutputs == null ? outputCount : `${outputCount} / ${expectedOutputs}`}</strong></span>
      </div>
      {job.execution_mode === "direct" && <p className="job-worker-sync">
        Worker: {workerHeartbeat ? `last heard ${new Date(workerHeartbeat).toLocaleTimeString()}` : "no heartbeat recorded"}
        {job.communication?.overdue ? " · status may be out of date" : ""}
      </p>}
      <div className="job-actions">
        <label className="job-compare"><input type="checkbox" checked={comparisonSelected} disabled={comparisonDisabled || disabled}
          onChange={() => onCompare(job)} /> Compare</label>
        <button className="ghost" disabled={disabled} title="Load a copy of this Job's settings into the form; this Job stays unchanged." onClick={() => onEdit(job)}>Load settings to form</button>
        {retryable && <button className="ghost" disabled={!canManage} onClick={() => onRetry(job)}>Retry</button>}
        {job.execution_mode === "direct" && ["pending", "running"].includes(job.state) &&
          <button className="danger ghost" disabled={!canManage} onClick={() => onCancel(job)}>Cancel Job</button>}
        {job.state === "cancel_requested" && <button className="danger ghost" disabled title="Waiting for Worker confirmation">Cancellation pending</button>}
        <button className="danger ghost" disabled={!canManage} onClick={() => onDelete(job)}>Remove</button>
        <button className="ghost" disabled={disabled} onClick={() => onRefresh(job)}>Refresh status</button>
        <button className="ghost" disabled={loadingImages} onClick={refreshImages}>
          {loadingImages ? "Checking…" : "Check outputs"}
        </button>
      </div>
      {snapshot && (
        <details className="job-snapshot">
          <summary>Saved settings and execution details</summary>
          <p><strong>Operation:</strong> {snapshot.operation || "unknown"} · <strong>Workflow:</strong> {snapshot.workflow_id || job.workflow_id}
            {snapshot.workflow_version && <> · <strong>Version:</strong> {snapshot.workflow_version.slice(0, 12)}</>}</p>
          {snapshot.model?.name && <p><strong>Model:</strong> {String(snapshot.model.name).split(/[\\/]/).pop()}</p>}
          <p><strong>Seed:</strong> {snapshot.seed ?? "not recorded"} ({snapshot.seed_mode || "fixed"})
            {snapshot.output_spec?.width && snapshot.output_spec?.height && <> · <strong>Output:</strong> {snapshot.output_spec.width} × {snapshot.output_spec.height}</>}
            {snapshot.output_spec?.count && <> · <strong>Count:</strong> {snapshot.output_spec.count}</>}</p>
          {snapshot.positive_prompt != null && <div><strong>Positive prompt</strong><pre className="prompt-preview" dir="auto">{snapshot.positive_prompt || "(empty)"}</pre></div>}
          {snapshot.negative_prompt != null && <div><strong>Negative prompt</strong><pre className="prompt-preview" dir="auto">{snapshot.negative_prompt || "(empty)"}</pre></div>}
          {snapshot.parameters && Object.keys(snapshot.parameters).length > 0 && <details>
            <summary>Effective parameters</summary>
            <dl className="job-parameter-list">{Object.entries(snapshot.parameters).map(([key, value]) =>
              <React.Fragment key={key}><dt>{key}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></React.Fragment>)}</dl>
          </details>}
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
          <details>
            <summary>Job and Attempt IDs</summary>
            <p className="copyable-id"><span>Job: <code>{job.id}</code></span><button type="button" className="ghost" onClick={() => navigator.clipboard?.writeText(job.id)}>Copy</button></p>
            {job.active_attempt_id && <p className="copyable-id"><span>Current Attempt: <code>{job.active_attempt_id}</code></span><button type="button" className="ghost" onClick={() => navigator.clipboard?.writeText(job.active_attempt_id)}>Copy</button></p>}
            <p className="hint">Priority: {job.priority || fallbackPriority || "not recorded"}</p>
            {(job.attempt_history || []).length > 0 && <ol className="job-attempt-list">{job.attempt_history.map(attempt =>
              <li key={attempt.id}><strong>Attempt {attempt.sequence}</strong> · {jobStateLabel(attempt.state)}
                {attempt.timing?.queue_wait_seconds != null && <> · Wait {formatDuration(attempt.timing.queue_wait_seconds)}</>}
                {attempt.timing?.worker_seconds != null && <> · Worker {formatDuration(attempt.timing.worker_seconds)}</>}
                {attempt.failure_reason && <p>{attempt.failure_reason}</p>}
                <code>{attempt.id}</code>
              </li>)}</ol>}
            {(job.progress_history || []).length > 0 && <details>
              <summary>Recent progress events ({job.progress_history.length})</summary>
              <ol className="job-attempt-list">{job.progress_history.map(event =>
                <li key={`${event.attempt_id}-${event.sequence}`}>{event.label}
                  {event.value != null && <> · {event.value}/{event.total} {event.unit || ""}</>}
                  {event.observed_at && <> · {new Date(event.observed_at).toLocaleTimeString()}</>}
                </li>)}</ol>
            </details>}
          </details>
        </details>
      )}
      {(galleryAssets.length > 0 || expectedTiles > 0 || job.output_summary?.partial_success) && (
        <section className="job-gallery" aria-label={`Outputs for Job ${job.id}`}>
          <div className="gallery-heading"><h3>Outputs</h3>
            {job.output_summary?.partial_success && <span className="pill stalled">Partial result · {job.output_summary.available} available{job.output_summary.expected_count ? ` of ${job.output_summary.expected_count}` : ""}</span>}
          </div>
          <div className="output-gallery-grid">
            {galleryAssets.map((asset, index) => {
              const stableId = asset.asset_id || asset.storage_key || asset.key || `${job.id}:${index}`;
              const available = asset.status === "available" || (!asset.status && Boolean(asset.url));
              const video = asset.media_type === "video" || String(asset.mime_type || "").startsWith("video/");
              const metadata = [asset.width && asset.height ? `${asset.width} × ${asset.height}` : "",
                Number.isFinite(asset.size_bytes) ? `${(asset.size_bytes / 1024 / 1024).toFixed(2)} MB` : "",
                asset.mime_type || ""].filter(Boolean).join(" · ");
              return <article className={`output-card${available ? "" : " output-unavailable"}`} key={stableId}>
                <button type="button" className="output-card-open" disabled={!available || !asset.url}
                  onClick={() => openLightbox(asset)} aria-label={available ? `Open output ${index + 1} in full size` : `Output ${index + 1} unavailable`}>
                  {available ? (video ? <video src={asset.url} preload="metadata" muted onError={() => setImageError("A preview link expired or the file could not be read. Use Check outputs to renew it.")} /> : <img src={asset.url} alt={`Output ${index + 1}`} loading="lazy"
                    onError={() => setImageError("A preview link expired or the file could not be read. Use Check outputs to renew it.")} />)
                    : <span className="output-placeholder-state">File unavailable</span>}
                  <strong>{video ? "Video" : "Output"} {index + 1}{asset.attempt_id && attemptSequence.has(asset.attempt_id) ? ` · Attempt ${attemptSequence.get(asset.attempt_id)}` : ""}</strong>
                  {metadata && <small>{metadata}</small>}
                  {!available && <small>Transfer or file verification failed</small>}
                </button>
                {available && <div className="output-card-actions">
                  <a className="ghost" href={downloadUrl(asset)} download>Download</a>
                  {!video && <>
                    <button type="button" className="ghost" disabled={disabled} onClick={() => onEditOutput(asset, job)}>Edit</button>
                    <button type="button" className="ghost" disabled={disabled || !asset.s3_uri} onClick={() => onUseReference(asset, job)}>Use as reference</button>
                  </>}
                </div>}
              </article>;
            })}
            {Array.from({ length: expectedTiles }, (_, index) => <div className="output-card output-placeholder" key={`pending:${job.id}:${job.active_attempt_id || "none"}:${index}`}>
              <div className="placeholder-preview"><span aria-hidden="true" /></div>
              <strong>{job.state === "finalizing" ? "Verifying output" : job.state === "pending" || job.state === "queued" ? "Waiting for Worker" : jobStateLabel(job.state)}</strong>
              <small>{progress?.label || "Output will appear here when available"}</small>
              {percent !== null && <progress max="100" value={percent} aria-label={`${progress.label} stage progress`} />}
            </div>)}
          </div>
        </section>
      )}
      {selectedLightboxAsset && <div className="output-lightbox-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setLightbox(null); }}>
        <section className="output-lightbox" role="dialog" aria-modal="true" aria-label="Full size output image">
          <header><strong>{selectedLightboxAsset.media_type === "video" ? "Output video" : "Full size output"}</strong>
            <div className="lightbox-actions">
              <button type="button" className="ghost" onClick={() => setZoom(value => Math.min(4, value + 0.25))} aria-label="Zoom in">Zoom +</button>
              <button type="button" className="ghost" onClick={() => setZoom(1)}>Reset zoom</button>
              <button type="button" className="ghost" disabled={availableAssets.length < 2} onClick={() => moveLightbox(-1)}>Previous</button>
              <button type="button" className="ghost" disabled={availableAssets.length < 2} onClick={() => moveLightbox(1)}>Next</button>
              <a className="ghost" href={downloadUrl(selectedLightboxAsset)} download>Download original</a>
              <button type="button" className="ghost" ref={closeLightboxRef} onClick={() => setLightbox(null)}>Close</button>
            </div>
          </header>
          <div className="lightbox-stage">
            {selectedLightboxAsset.media_type === "video" ? <video src={selectedLightboxAsset.url} controls autoPlay /> :
              <img src={selectedLightboxAsset.url} alt="Full size generated output" style={{ transform: `scale(${zoom})` }}
                onError={() => { setImageError("The signed preview link may have expired. Renewing it now."); refreshImages(); }} />}
          </div>
          <footer><span>{selectedLightboxAsset.width && selectedLightboxAsset.height ? `${selectedLightboxAsset.width} × ${selectedLightboxAsset.height}` : selectedLightboxAsset.mime_type || "Output"}</span>
            <span>Use ← and → to navigate outputs · Esc to close</span></footer>
        </section>
      </div>}
      {imageError && <p className="hint">{imageError}</p>}
    </article>
  );
}
