import assert from "node:assert/strict";
import {assetDownloadPath, downloadFilename, fetchAssetDownload} from "../frontend/src/download.js";

assert.equal(assetDownloadPath("/api", "job /1", "asset?2"),
  "/api/jobs/job%20%2F1/assets/asset%3F2/download");
assert.equal(downloadFilename("attachment; filename=\"fallback.png\"; filename*=UTF-8''final%20image.png"),
  "final image.png");
assert.equal(downloadFilename("", {storage_key: "outputs/job/attempt/generated.mp4", mime_type: "video/mp4"}),
  "generated.mp4");

const calls = [];
const blob = new Blob(["original-image-bytes"], {type: "image/png"});
const result = await fetchAssetDownload({
  url: "/api/jobs/job-1/assets/asset-1/download",
  token: "session-only-token",
  asset: {asset_id: "asset-1"},
  fetchImpl: async (url, options) => {
    calls.push({url, options});
    return {
      ok: true,
      redirected: false,
      headers: {get: name => name === "Content-Disposition" ? "attachment; filename=\"output.png\"" : null},
      blob: async () => blob,
    };
  },
});
assert.equal(result.blob, blob);
assert.equal(result.filename, "output.png");
assert.equal(calls[0].options.headers["X-Internal-Token"], "session-only-token");
assert.equal(calls[0].options.credentials, "same-origin");
assert.equal(calls[0].url.includes("session-only-token"), false, "the token must never be put in the URL");

await assert.rejects(() => fetchAssetDownload({
  url: "/private", fetchImpl: async () => ({
    ok: false, status: 401, text: async () => JSON.stringify({error: {message: "Controller access required"}}),
  }),
}), /Controller access required/);
await assert.rejects(() => fetchAssetDownload({
  url: "/private", fetchImpl: async () => ({ok: true, redirected: true}),
}), /unexpected redirect/);
await assert.rejects(() => fetchAssetDownload({
  url: "/private", fetchImpl: async () => ({ok: true, redirected: false,
    headers: {get: () => null}, blob: async () => new Blob([])}),
}), /file is empty/);

console.log("Authenticated download helper: passed");
