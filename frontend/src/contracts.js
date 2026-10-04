// PDF-43/47: pure helpers shared by the UI and offline contract tests.
export function mergeJob(current, incoming) {
  if (!current) return incoming;
  if (incoming.id !== current.id) return current;
  if (Number(incoming.version || 0) < Number(current.version || 0)) return current;
  if (Number(incoming.version || 0) === Number(current.version || 0) &&
      Date.parse(incoming.updated_at || 0) < Date.parse(current.updated_at || 0)) return current;
  const sameAttempt = incoming.active_attempt_id && incoming.active_attempt_id === current.active_attempt_id;
  if (sameAttempt && Number(incoming.progress?.sequence || 0) < Number(current.progress?.sequence || 0)) return current;
  return incoming;
}

export function mergeJobList(current, incoming) {
  const previous = new Map(current.map(job => [job.id, job]));
  return incoming.map(job => mergeJob(previous.get(job.id), job));
}

export function appendUniqueJobs(current, incoming) {
  const result = [...current];
  const positions = new Map(result.map((job, index) => [job.id, index]));
  for (const job of incoming) {
    const index = positions.get(job.id);
    if (index === undefined) {
      positions.set(job.id, result.length);
      result.push(job);
    } else {
      result[index] = mergeJob(result[index], job);
    }
  }
  return result;
}

export function stagePercent(progress) {
  if (progress?.scope !== "stage" || !Number.isFinite(progress.value) ||
      !Number.isFinite(progress.total) || progress.total <= 0 ||
      progress.value < 0 || progress.value > progress.total) return null;
  return Math.round((progress.value / progress.total) * 100);
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "Not recorded";
  const value = Math.floor(seconds);
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const remainder = value % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${remainder}s`;
  return `${remainder}s`;
}

export function jobStateLabel(state) {
  const labels = {
    submitting: "Submitting", pending: "Queued", queued: "Queued", waiting: "Waiting",
    preparing: "Preparing", processing: "Processing", running: "Running",
    finalizing: "Saving output", cancel_requested: "Cancellation requested",
    cancelled: "Cancelled", succeeded: "Completed", failed: "Failed",
    submit_failed: "Could not submit", stalled: "Worker status uncertain"
  };
  return labels[state] || "Status unavailable";
}

export function isStale(record, now = Date.now()) {
  const received = Date.parse(record?.last_updated_at || "");
  return !Number.isFinite(received) || now - received > (record?.freshness?.stale_after_seconds || 30) * 1000;
}

const INTEGER_FIELD = /(seed|steps|width|height|count)$/i;
const NUMBER_FIELD = /(cfg|denoise|strength(?:_(?:model|clip))?|(?:model|clip)_strength)$/i;

function stepMismatch(value, field) {
  if (!(field?.step > 0)) return false;
  const base = field.minimum ?? 0;
  const steps = (value - base) / field.step;
  return Math.abs(steps - Math.round(steps)) > 1e-8;
}

const SENSITIVE_KEY = /(^|[._-])(token|secret|authorization|api[_-]?key|access[_-]?key|password)($|[._-])/i;
const SENSITIVE_ASSIGNMENT = /\b(?:api[_-]?key|access[_-]?key|client[_-]?secret|password|authorization|bearer|token|secret)\s*[:=]\s*\S+/i;

export function containsCredentialLikeData(value) {
  if (Array.isArray(value)) return value.some(containsCredentialLikeData);
  if (value && typeof value === "object") {
    return Object.entries(value).some(([key, child]) => SENSITIVE_KEY.test(key) || containsCredentialLikeData(child));
  }
  return typeof value === "string" && SENSITIVE_ASSIGNMENT.test(value);
}

// Mirror the part of the server contract that can be proven from saved
// workflow bindings. Model-specific min/max limits are intentionally not
// invented when a workflow does not publish them.
export function validateVariables(keys, variables, capabilities = null) {
  const errors = {};
  const values = variables && typeof variables === "object" ? variables : {};
  const fieldMap = new Map((capabilities?.fields || []).map(field => [field.variable_key, field]));
  const referenceMap = new Map((capabilities?.references || []).map(field => [field.variable_key, field]));

  for (const key of keys || []) {
    const value = values[key];
    if (value === undefined || value === null) {
      errors[key] = "This workflow input is missing.";
      continue;
    }
    if (/^input\.image_\d+$/.test(key)) {
      if (value === "" && referenceMap.get(key)?.required === false) continue;
      if (typeof value !== "string" || !value.trim()) {
        errors[key] = "Upload a required reference image.";
      } else if (!/^s3:\/\/[^/]+\/inputs\/[^/]+\/.+$/.test(value)) {
        errors[key] = "Upload this image through the image field before generating.";
      }
      continue;
    }
    const field = fieldMap.get(key);
    if (key.toLowerCase().endsWith("enabled")) {
      if (typeof value !== "boolean") errors[key] = "Choose an enabled or disabled value.";
      else if (field?.kind && field.kind !== "boolean") errors[key] = "This workflow field has an inconsistent type definition.";
      continue;
    }
    if (INTEGER_FIELD.test(key)) {
      if (!Number.isSafeInteger(value)) {
        errors[key] = "Enter a whole number within the safe numeric range.";
      } else {
        if (/seed$/i.test(key) && value < 0) errors[key] = "Seed must be zero or greater.";
        else if (!/seed$/i.test(key) && value <= 0) errors[key] = "Enter a positive whole number.";
        else if (field?.kind === "select" || field?.kind === "boolean" || field?.kind === "text" || field?.kind === "prompt") {
          errors[key] = "This workflow field has an inconsistent type definition.";
        } else if ((field?.minimum != null && value < field.minimum) ||
          (field?.maximum != null && value > field.maximum)) {
          errors[key] = `Enter a value from ${field.minimum ?? "−∞"} to ${field.maximum ?? "∞"}.`;
        } else if (stepMismatch(value, field)) {
          errors[key] = `Enter a value in steps of ${field.step}.`;
        }
      }
      continue;
    }
    if (NUMBER_FIELD.test(key)) {
      if (typeof value !== "number" || !Number.isFinite(value)) {
        errors[key] = "Enter a finite number.";
      } else if (field?.kind === "select" || field?.kind === "boolean" || field?.kind === "text" || field?.kind === "prompt") {
        errors[key] = "This workflow field has an inconsistent type definition.";
      } else if ((field?.minimum != null && value < field.minimum) ||
        (field?.maximum != null && value > field.maximum)) {
        errors[key] = `Enter a value from ${field.minimum ?? "−∞"} to ${field.maximum ?? "∞"}.`;
      } else if (stepMismatch(value, field)) {
        errors[key] = `Enter a value in steps of ${field.step}.`;
      }
      continue;
    }
    if ((key.startsWith("prompt.") || field?.kind === "prompt" || field?.kind === "text") && typeof value !== "string") {
      errors[key] = "Prompt must be text.";
      continue;
    }
    if (typeof value === "number" && !Number.isFinite(value)) {
      errors[key] = "Enter a finite number.";
    }

    if (field) {
      if (field.kind === "select" && !field.options?.includes(value)) {
        errors[key] = "Choose an option supported by this workflow.";
        continue;
      }
      if (field.kind === "boolean" && typeof value !== "boolean") {
        errors[key] = "Choose an enabled or disabled value.";
        continue;
      }
      if (field.kind === "integer" && !Number.isSafeInteger(value)) {
        errors[key] = "Enter a whole number within the safe numeric range.";
        continue;
      }
      if (field.kind === "number" && (typeof value !== "number" || !Number.isFinite(value))) {
        errors[key] = "Enter a finite number.";
        continue;
      }
      if (field.kind === "text" && typeof value !== "string") {
        errors[key] = "Enter text for this workflow field.";
        continue;
      }
      if (typeof value === "number" && ((field.minimum != null && value < field.minimum) ||
          (field.maximum != null && value > field.maximum))) {
        errors[key] = `Enter a value from ${field.minimum ?? "−∞"} to ${field.maximum ?? "∞"}.`;
      } else if (typeof value === "number" && stepMismatch(value, field)) {
        errors[key] = `Enter a value in steps of ${field.step}.`;
      }
    }
  }

  return errors;
}

export function submissionBody(workflow, variables, priority, clientRequestId, sourceJobId = null, seedMode = null, referenceOrder = null) {
  if (!workflow?.id || !workflow?.workflow_version) throw new Error("Wait for the saved workflow to load.");
  const keys = workflow.variable_keys || [];
  const effective = Object.fromEntries(keys.map(key => [key, variables[key]]));
  if (keys.some(key => effective[key] === undefined)) throw new Error("A required workflow field is missing.");
  const errors = validateVariables(keys, effective, workflow.capabilities);
  if (Object.keys(errors).length) {
    const error = new Error("Fix the highlighted workflow fields before generating.");
    error.fieldErrors = errors;
    throw error;
  }
  return JSON.parse(JSON.stringify({contract_version: 1, client_request_id: clientRequestId,
    workflow_id: workflow.id, workflow_version: workflow.workflow_version,
    capability_version: workflow.capability_version,
    seed_mode: workflow.capabilities?.seed_variable ? (seedMode || "fixed") : undefined,
    reference_order: Array.isArray(referenceOrder) ? referenceOrder : undefined,
    variables: effective, priority, source_job_id: sourceJobId}));
}

export function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}
