import assert from "node:assert/strict";
import { containsCredentialLikeData, submissionBody, validateVariables } from "../frontend/src/contracts.js";

const capabilities = {
  capability_version: "a".repeat(64),
  seed_variable: "generation.seed",
  fields: [
    { variable_key: "generation.seed", kind: "integer", minimum: 0, maximum: 1000000 },
    { variable_key: "generation.steps", kind: "integer", minimum: 1, maximum: 50 },
    { variable_key: "generation.sampler", kind: "select", options: ["euler", "dpmpp_2m"] },
    { variable_key: "prompt.negative", kind: "prompt" }
  ],
  references: [{ variable_key: "input.image_1", role: "identity", required: true }]
};
const workflow = {
  id: "qwen-edit", workflow_version: "b".repeat(64), capability_version: capabilities.capability_version,
  variable_keys: ["input.image_1", "prompt.negative", "generation.seed", "generation.steps", "generation.sampler"],
  capabilities
};
const values = {
  "input.image_1": "s3://bucket/inputs/a/reference.png",
  "prompt.negative": "blurry",
  "generation.seed": 42,
  "generation.steps": 8,
  "generation.sampler": "euler"
};

assert.deepEqual(validateVariables(workflow.variable_keys, values, capabilities), {});
assert.equal(validateVariables(workflow.variable_keys, { ...values, "generation.steps": 60 }, capabilities)["generation.steps"].length > 0, true);
assert.equal(validateVariables(workflow.variable_keys, { ...values, "generation.sampler": "unknown" }, capabilities)["generation.sampler"].length > 0, true);
assert.equal(validateVariables(workflow.variable_keys, { ...values, "generation.seed": -1 }, capabilities)["generation.seed"].length > 0, true);
assert.equal(validateVariables(workflow.variable_keys, { ...values, "generation.steps": 60 }, capabilities)["generation.steps"].length > 0, true);
assert.equal(validateVariables(workflow.variable_keys, { ...values, "generation.steps": 1 }, capabilities).hasOwnProperty("generation.steps"), false);
assert.equal(containsCredentialLikeData({ "prompt.positive": "portrait", "lora.style.name": "soft-style.safetensors" }), false);
assert.equal(containsCredentialLikeData({ "prompt.positive": "api_key: abcdef123456" }), true);
const referenceOrder = ["input.image_1"];
const body = submissionBody(workflow, values, "medium", "request-id", null, "random", referenceOrder);
assert.equal(body.capability_version, capabilities.capability_version);
assert.equal(body.seed_mode, "random");
assert.deepEqual(body.reference_order, referenceOrder);
assert.deepEqual(body.variables, values);

console.log("Axis 3 frontend contract tests passed.");
