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

export function submissionBody(workflow, variables, priority, clientRequestId, sourceJobId = null) {
  if (!workflow?.id || !workflow?.workflow_version) throw new Error("Wait for the saved workflow to load.");
  const keys = workflow.variable_keys || [];
  const effective = Object.fromEntries(keys.map(key => [key, variables[key]]));
  if (keys.some(key => effective[key] === undefined)) throw new Error("A required workflow field is missing.");
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
