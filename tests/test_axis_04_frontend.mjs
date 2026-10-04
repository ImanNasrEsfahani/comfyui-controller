import assert from "node:assert/strict";
import {
  appendUniqueJobs, formatDuration, jobStateLabel, mergeJob, stagePercent
} from "../frontend/src/contracts.js";

const current = {
  id: "job-1", version: 3, updated_at: "2026-10-04T10:00:00Z", active_attempt_id: "attempt-2",
  progress: {attempt_id: "attempt-2", sequence: 8, value: 16, total: 30, scope: "stage"}
};
const oldProgress = {...current, progress: {...current.progress, sequence: 7, value: 14}};
assert.equal(mergeJob(current, oldProgress), current, "late progress cannot roll a card backward");
assert.equal(stagePercent(current.progress), 53, "stage progress is expressed only for its own scope");
assert.equal(stagePercent({value: 25, total: 50, scope: "job"}), null, "stage progress is not presented as total Job completion");
assert.equal(stagePercent({value: 4, total: 0, scope: "stage"}), null, "invalid progress remains unknown");
assert.equal(formatDuration(null), "Not recorded");
assert.equal(formatDuration(3661), "1h 1m");
assert.equal(jobStateLabel("cancel_requested"), "Cancellation requested");

const combined = appendUniqueJobs(
  [{id: "job-1", version: 1}, {id: "job-2", version: 1}],
  [{id: "job-2", version: 2}, {id: "job-3", version: 1}]
);
assert.deepEqual(combined.map(job => job.id), ["job-1", "job-2", "job-3"]);
assert.equal(combined[1].version, 2);

console.log("Axis 4 frontend contracts: passed");
