// PDF-43/47: pure helpers shared by the UI and offline contract tests.
export function mergeJob(current, incoming) {
  if (!current) return incoming;
  if (incoming.id !== current.id) return current;
  if (Number(incoming.version || 0) < Number(current.version || 0)) return current;
  if (Number(incoming.version || 0) === Number(current.version || 0) &&
      Date.parse(incoming.updated_at || 0) < Date.parse(current.updated_at || 0)) return current;
  return incoming;
}

export function mergeJobList(current, incoming) {
  const previous = new Map(current.map(job => [job.id, job]));
  return incoming.map(job => mergeJob(previous.get(job.id), job));
}

export function isStale(record, now = Date.now()) {
  const received = Date.parse(record?.last_updated_at || "");
  return !Number.isFinite(received) || now - received > (record?.freshness?.stale_after_seconds || 30) * 1000;
}

const INTEGER_FIELD = /(seed|steps|width|height|count)$/i;
const NUMBER_FIELD = /(cfg|denoise|strength)$/i;

// Mirror the part of the server contract that can be proven from saved
// workflow bindings. Model-specific min/max limits are intentionally not
// invented when a workflow does not publish them.
export function validateVariables(keys, variables) {
  const errors = {};
  const values = variables && typeof variables === "object" ? variables : {};

  for (const key of keys || []) {
    const value = values[key];
    if (value === undefined || value === null) {
      errors[key] = "This workflow input is missing.";
      continue;
    }
    if (/^input\.image_\d+$/.test(key)) {
      if (typeof value !== "string" || !value.trim()) {
        errors[key] = "Upload a required reference image.";
      } else if (!/^s3:\/\/[^/]+\/inputs\/[^/]+\/.+$/.test(value)) {
        errors[key] = "Upload this image through the image field before generating.";
      }
      continue;
    }
    if (key.toLowerCase().endsWith("enabled")) {
      if (typeof value !== "boolean") errors[key] = "Choose an enabled or disabled value.";
      continue;
    }
    if (INTEGER_FIELD.test(key)) {
      if (!Number.isSafeInteger(value)) {
        errors[key] = "Enter a whole number within the safe numeric range.";
      } else if (!/seed$/i.test(key) && value <= 0) {
        errors[key] = "Enter a positive whole number.";
      }
      continue;
    }
    if (NUMBER_FIELD.test(key)) {
      if (typeof value !== "number" || !Number.isFinite(value)) {
        errors[key] = "Enter a finite number.";
      }
      continue;
    }
    if (key.startsWith("prompt.") && typeof value !== "string") {
      errors[key] = "Prompt must be text.";
      continue;
    }
    if (typeof value === "number" && !Number.isFinite(value)) {
      errors[key] = "Enter a finite number.";
    }
  }

  return errors;
}

export function submissionBody(workflow, variables, priority, clientRequestId, sourceJobId = null) {
  if (!workflow?.id || !workflow?.workflow_version) throw new Error("Wait for the saved workflow to load.");
  const keys = workflow.variable_keys || [];
  const effective = Object.fromEntries(keys.map(key => [key, variables[key]]));
  if (keys.some(key => effective[key] === undefined)) throw new Error("A required workflow field is missing.");
  const errors = validateVariables(keys, effective);
  if (Object.keys(errors).length) {
    const error = new Error("Fix the highlighted workflow fields before generating.");
    error.fieldErrors = errors;
    throw error;
  }
  return JSON.parse(JSON.stringify({contract_version: 1, client_request_id: clientRequestId,
    workflow_id: workflow.id, workflow_version: workflow.workflow_version,
    variables: effective, priority, source_job_id: sourceJobId}));
}

export function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}
