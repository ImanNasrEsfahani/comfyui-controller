// Run pure checks with: node tests/test_axis_01_frontend.mjs
// Browser checks: AXIS_UI_URL=http://127.0.0.1:4173 node tests/test_axis_01_frontend.mjs
// Install Playwright for QA only; it is not an application dependency.
import assert from "node:assert/strict";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { mergeJob, mergeJobList, isStale, submissionBody, validateVariables } from "../frontend/src/contracts.js";

test("older Job record cannot replace a terminal record", () => {
  const done = {id: "j1", version: 5, state: "succeeded"};
  assert.equal(mergeJob(done, {id: "j1", version: 4, state: "running"}), done);
});
test("new retry version may reopen its own Job", () => {
  assert.equal(mergeJob({id: "j1", version: 5, state: "failed"}, {id: "j1", version: 6, state: "pending"}).state, "pending");
});
test("entity identities and versions are not compared across scopes", () => {
  const current = {id: "j1", version: 1};
  assert.equal(mergeJob(current, {id: "other", version: 99}), current);
});
test("snapshot lists merge by Job ID", () => {
  const current = [{id: "a", version: 4}, {id: "b", version: 1}];
  assert.deepEqual(mergeJobList(current, [{id: "b", version: 2}, {id: "a", version: 3}]), [{id: "b", version: 2}, current[0]]);
});
test("stale or unknown observation is explicit", () => {
  const record = {last_updated_at: "2026-01-01T00:00:00Z", freshness: {stale_after_seconds: 30}};
  assert.equal(isStale(record, Date.parse("2026-01-01T00:00:31Z")), true);
  assert.equal(isStale(record, Date.parse("2026-01-01T00:00:01Z")), false);
  assert.equal(isStale(null), true);
});
test("submitted snapshot reads latest values and is independent of later edits", () => {
  const wf = {id: "wf", workflow_version: "a".repeat(64), variable_keys: ["prompt.user"]};
  const draft = {"prompt.user": "A", "hidden": "unused"};
  const a = submissionBody(wf, draft, "medium", "request-A");
  draft["prompt.user"] = "B";
  const b = submissionBody(wf, draft, "medium", "request-B");
  assert.equal(a.variables["prompt.user"], "A");
  assert.equal(b.variables["prompt.user"], "B");
  assert.equal("hidden" in b.variables, false);
});
test("unloaded workflows and missing effective fields cannot be submitted", () => {
  assert.throws(() => submissionBody(null, {}, "medium", "key"));
  assert.throws(() => submissionBody({id: "wf", workflow_version: "a", variable_keys: ["prompt.user"]}, {}, "medium", "key"));
});
test("form validation reports all missing and invalid fields without coercing values", () => {
  const keys = ["prompt.user", "generation.seed", "generation.steps", "output.width", "input.image_1"];
  const values = {"prompt.user": "فارسی نیم‌فاصله\nline 2", "generation.seed": 1.5,
    "generation.steps": 0, "output.width": Number.NaN, "input.image_1": "https://remote.invalid/image.png"};
  assert.deepEqual(validateVariables(keys, values), {
    "generation.seed": "Enter a whole number within the safe numeric range.",
    "generation.steps": "Enter a positive whole number.",
    "output.width": "Enter a whole number within the safe numeric range.",
    "input.image_1": "Upload this image through the image field before generating."
  });
  assert.throws(() => submissionBody({id: "wf", workflow_version: "a".repeat(64), variable_keys: keys}, values, "medium", "bad"),
    error => Object.keys(error.fieldErrors).length === 4);
});

const uiUrl = process.env.AXIS_UI_URL;
const staticDir = process.env.AXIS_STATIC_DIR;
const baselineOnly = process.env.AXIS_BASELINE_CHECK === "true";
test("browser: form, recovery, selection races, views, mobile and multiple tabs", {skip: !uiUrl && !staticDir}, async t => {
  let server, url = uiUrl;
  if (staticDir) {
    const root = resolve(staticDir);
    server = createServer(async (req, res) => {
      const path = resolve(root, "." + (new URL(req.url, "http://localhost").pathname === "/" ? "/index.html" : new URL(req.url, "http://localhost").pathname));
      if (!path.startsWith(root + "/")) {res.writeHead(403).end(); return;}
      try {
        const content = await readFile(path);
        res.setHeader("Content-Type", {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[extname(path)] || "application/octet-stream");
        res.end(content);
      } catch {res.writeHead(404).end();}
    });
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    url = "http://127.0.0.1:" + server.address().port;
  }
  const modulePath = process.env.PLAYWRIGHT_MODULE;
  let chromium;
  let browser;
  try {
    ({chromium} = await import(modulePath ? pathToFileURL(modulePath).href : "playwright"));
    browser = await chromium.launch({headless: true,
      ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {}),
      args: ["--no-sandbox", "--disable-dev-shm-usage", "--no-zygote", "--single-process"]});
  } catch (error) {
    if (server) await new Promise(resolve => server.close(resolve));
    throw error;
  }
  const context = await browser.newContext({viewport: {width: 1200, height: 1000}});
  const sent = [], sentTokens = [], jobs = [], errors = [], tokenAttempts = [];
  let abortNextSubmission = false, delayWorkflowA = false, delaySubmit = false;
  let uploadStartedResolve, uploadReleaseResolve;
  const uploadStarted = new Promise(resolve => { uploadStartedResolve = resolve; });
  const uploadRelease = new Promise(resolve => { uploadReleaseResolve = resolve; });
  const wf = id => id === "image-wf"
    ? ({id, name: id, api_prompt: {"1": {class_type: "LoadImage", inputs: {image: "{{input.image_1}}"}},
        "2": {class_type: "Test", inputs: {text: "{{prompt.user}}"}}}, workflow_version: "b".repeat(64),
        variable_keys: ["input.image_1", "prompt.user"]})
    : ({id, name: id, api_prompt: {"1": {class_type: "Test", inputs: {text: "{{prompt.user}}", seed: "{{generation.seed}}"}}},
        workflow_version: "a".repeat(64), variable_keys: ["prompt.user", "generation.seed"]});
  await context.route("**/health", route => route.fulfill({json: {default_priority: "medium", gpu_name: "test-gpu", admin_configured: true}}));
  await context.route("**/api/**", async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (path === "/api/workflows") return route.fulfill({json: ["wf", "A", "B", "image-wf"].map(id => ({id, name: id}))});
    if (path.startsWith("/api/workflows/")) {
      const id = path.split("/").pop();
      if (id === "A" && delayWorkflowA) await new Promise(resolve => setTimeout(resolve, 300));
      return route.fulfill({json: wf(id)});
    }
    if (path === "/api/salad/settings" && req.method() === "GET") {
      const token = req.headers()["x-internal-token"] || "";
      tokenAttempts.push(token);
      if (token === "valid-token") return route.fulfill({json: {active: {image: "worker", group_name: "g", display_name: "test"},
        draft: {image: "worker", group_name: "g", display_name: "test"}, has_changes: false}});
      return route.fulfill({status: 401, json: {error: {code: "unauthorized", message: "invalid internal token", path: ""}}});
    }
    if (path === "/api/salad/instances") return route.fulfill({json: {name: "test-group", group_name: "test-group", status: "running", provider_status: "running",
      version: 1, replicas: 1, queue_mode: "direct", instances: [{id: "i", state: "running", provider_ready: true,
        pull_progress: {value: .7, unit: null}}], worker_status: "unknown", last_updated_at: new Date().toISOString(), financial: {balance: null, hourly_rate: null, limitation: "No verified financial API"}}});
    if (path === "/api/jobs" && req.method() === "POST") {
      const body = req.postDataJSON(); sent.push(body); sentTokens.push(req.headers()["x-internal-token"] || "");
      if (sentTokens.at(-1) !== "valid-token") return route.fulfill({status: 401, json: {error: {message: "invalid internal token"}}});
      let job = body.client_request_id && jobs.find(job => job.client_request_id === body.client_request_id);
      if (!job) {
        job = {id: "job-" + sent.length, job_id: "job-" + sent.length, client_request_id: body.client_request_id,
          workflow_id: body.workflow_id, variables: body.variables, version: 1, state: "pending", status: "queued",
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(), snapshot: JSON.parse(JSON.stringify(body)), priority: "medium"};
        jobs.unshift(job);
      }
      if (delaySubmit) await new Promise(resolve => setTimeout(resolve, 200));
      if (abortNextSubmission) {abortNextSubmission = false; return route.abort();}
      return route.fulfill({json: job});
    }
    if (path === "/api/uploads" && req.method() === "POST") {
      uploadStartedResolve();
      await uploadRelease;
      return route.fulfill({json: {s3_uri: "s3://test-bucket/inputs/upload-1/photo.png", asset_id: "upload-1"}});
    }
    if (path === "/api/jobs") return route.fulfill({json: jobs});
    if (path.startsWith("/api/job-requests/")) {
      if ((req.headers()["x-internal-token"] || "") !== "valid-token") return route.fulfill({status: 401, json: {error: {message: "invalid internal token"}}});
      const job = jobs.find(job => job.client_request_id === path.split("/").pop());
      return route.fulfill({status: job ? 200 : 404, json: job || {error: {message: "not found"}}});
    }
    if (path.startsWith("/api/jobs/")) return route.fulfill({json: jobs.find(job => job.id === path.split("/").pop()) || {}});
    return route.fulfill({status: 404, json: {error: {message: "unmocked endpoint"}}});
  });
  const page = await context.newPage();
  page.on("pageerror", e => errors.push(e.message));
  try {
    await page.goto(url);
    await page.getByRole("button", {name: "Infrastructure & cost", exact: true}).click();
    await page.locator("#admin-token").fill("valid-token");
    await page.getByRole("button", {name: "Apply Token"}).click();
    await page.locator(".token-status[data-state='connected']").waitFor();
    await page.locator("#admin-token").fill("invalid-token");
    await page.getByRole("button", {name: "Apply Token"}).click();
    await page.locator(".token-status[data-state='invalid']").waitFor();
    assert.match(await page.locator(".token-status").innerText(), /previously verified token remains active/);
    assert.deepEqual(tokenAttempts.slice(0, 2), ["valid-token", "invalid-token"]);
    await page.getByRole("button", {name: "Create & edit", exact: true}).click();
    await page.locator("select").first().selectOption("wf");
    const prompt = page.locator("#inputs-run textarea.runtime-textarea");
    const run = page.getByRole("button", {name: "Run on Salad GPU"});
    await prompt.fill("A"); await run.click();
    await page.getByText(baselineOnly ? /^Submitted: job-/ : /^Accepted: job-/).waitFor();
    await prompt.fill("B"); await run.click();
    await page.getByText(baselineOnly ? /^Submitted: job-2/ : /^Accepted: job-2/).waitFor();
    assert.deepEqual(sent.slice(0, 2).map(body => body.variables["prompt.user"]), ["A", "B"]);
    assert.deepEqual(sentTokens.slice(0, 2), ["valid-token", "valid-token"]);
    assert.equal(JSON.stringify(sent[0]).includes("valid-token"), false);
    assert.equal(jobs.find(job => job.id === "job-1").snapshot.variables["prompt.user"], "A");
    if (!baselineOnly) assert.notEqual(sent[0].client_request_id, sent[1].client_request_id);
    await t.test("A/B payload and immutable snapshot", () => {});
    if (baselineOnly) {
      console.log("Baseline actual payloads:", JSON.stringify(sent.map(body => ({workflow_id: body.workflow_id, variables: body.variables}))));
      return;
    }

    await prompt.fill("instant typing"); delaySubmit = true;
    const count = sent.length;
    await run.evaluate(button => {button.click(); button.click();});
    await page.getByText(/^Accepted: job-3/).waitFor();
    assert.equal(sent.length, count + 1);
    assert.equal(sent.at(-1).variables["prompt.user"], "instant typing"); delaySubmit = false;
    await t.test("immediate submit and same-turn double click", () => {});

    await context.grantPermissions(["clipboard-read", "clipboard-write"], {origin: url});
    await page.evaluate(() => navigator.clipboard.writeText("پرامپت تازه\nwith نیم‌فاصله"));
    await prompt.fill("start old-tail end");
    await prompt.evaluate(element => element.setSelectionRange(6, 14));
    await page.getByRole("button", {name: "Paste into User prompt"}).click();
    await page.waitForFunction(() => document.querySelector("#inputs-run textarea.runtime-textarea")?.value === "start پرامپت تازه\nwith نیم‌فاصله end");
    await run.click();
    await page.getByText(/^Accepted: job-4/).waitFor();
    assert.equal(sent.at(-1).variables["prompt.user"], "start پرامپت تازه\nwith نیم‌فاصله end");
    await t.test("Paste replaces only the selection and the next request carries Unicode multiline text", () => {});

    await prompt.fill("before reset");
    await page.locator("#inputs-run input[type='number']").fill("987654321");
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", {name: "Clear Form"}).click();
    assert.equal(await prompt.inputValue(), "");
    assert.equal(await page.locator("#inputs-run input[type='number']").inputValue(), "123456789");
    assert.equal(jobs.length, 4);
    await t.test("Clear Form restores workflow defaults and leaves Jobs untouched", () => {});

    const uploadFile = {name: "reference.png", mimeType: "image/png", buffer: Buffer.from("fake png")};
    await page.locator("select").first().selectOption("image-wf");
    await page.locator("input[type=file]").setInputFiles(uploadFile);
    await uploadStarted;
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", {name: "Clear Form"}).click();
    uploadReleaseResolve();
    await page.waitForTimeout(100);
    assert.match(await page.locator("#inputs-run").innerText(), /Required placeholder: \{\{input.image_1\}\}/);
    assert.equal(await page.locator("#inputs-run .ready").count(), 0);
    await t.test("late upload response cannot repopulate a cleared form", () => {});

    await page.locator("select").first().selectOption("wf");
    await prompt.waitFor();
    await prompt.fill("uncertain response"); abortNextSubmission = true;
    await run.click();
    const recover = page.getByRole("button", {name: "Recover last submission"});
    await recover.waitFor();
    assert.equal(await page.evaluate(() => JSON.parse(sessionStorage.getItem("comfyui-controller:pending-request")).variables["prompt.user"]), "uncertain response");
    await page.reload();
    await page.getByRole("button", {name: "Infrastructure & cost", exact: true}).click();
    await page.locator("#admin-token").fill("valid-token");
    await page.getByRole("button", {name: "Apply Token"}).click();
    await page.locator(".token-status[data-state='connected']").waitFor();
    await page.getByText(/^Accepted: job-5/).waitFor();
    assert.equal(sent.length, 5);
    assert.equal(await page.evaluate(() => sessionStorage.getItem("comfyui-controller:pending-request")), null);
    await t.test("lost submit response recovers after reload without new POST", () => {});

    delayWorkflowA = true;
    await page.locator("select").first().selectOption("A");
    await page.locator("select").first().selectOption("B");
    await page.waitForTimeout(450);
    assert.equal(await page.locator("select").first().inputValue(), "B");
    assert.equal(await page.locator("input[placeholder='01-general-editor']").inputValue(), "B");
    await t.test("late workflow response cannot replace new selection", () => {});

    await prompt.fill("draft preserved");
    for (const name of ["Jobs & outputs", "Infrastructure & cost", "Settings", "Create & edit"]) await page.getByRole("button", {name, exact: true}).click();
    assert.equal(await prompt.inputValue(), "draft preserved");
    await t.test("draft survives navigation", () => {});

    await page.setViewportSize({width: 360, height: 800});
    for (const name of ["Create & edit", "Jobs & outputs", "Infrastructure & cost", "Settings"]) {
      await page.getByRole("button", {name, exact: true}).click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, name);
    }
    await page.getByRole("button", {name: "Infrastructure & cost", exact: true}).click();
    assert.match(await page.locator(".instance-card").innerText(), /unit unknown/);
    assert.doesNotMatch(await page.locator(".instance-card").innerText(), /0\.7%/);
    await t.test("360px layout and unknown unit/financial telemetry", () => {});

    const second = await context.newPage();
    await second.goto(url); await second.getByRole("button", {name: "Jobs & outputs", exact: true}).click();
    await second.getByText("job-5", {exact: true}).waitFor();
    assert.equal(await second.locator(".job").count(), jobs.length);
    await second.close();
    assert.deepEqual(errors, []);
    await t.test("another tab restores authoritative Jobs and no runtime errors", () => {});
    if (process.env.AXIS_SCREENSHOT) await page.screenshot({path: process.env.AXIS_SCREENSHOT, fullPage: true});
  } finally {
    await context.close(); await browser.close();
    if (server) await new Promise(resolve => server.close(resolve));
  }
});
