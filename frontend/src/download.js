function basename(value) {
  const name = String(value || "").split(/[\\/]/).pop()?.trim();
  return name && name !== "." && name !== ".." ? name : "";
}

export function assetDownloadPath(apiBase, jobId, assetId) {
  return `${apiBase}/jobs/${encodeURIComponent(jobId)}/assets/${encodeURIComponent(assetId)}/download`;
}

export function downloadFilename(disposition, asset = {}) {
  const header = String(disposition || "");
  const encoded = header.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1]?.trim();
  if (encoded) {
    try {
      const decoded = basename(decodeURIComponent(encoded.replace(/^"|"$/g, "")));
      if (decoded) return decoded;
    } catch { /* Use the plain filename or asset metadata below. */ }
  }
  const plain = header.match(/filename\s*=\s*"?([^";]+)"?/i)?.[1];
  const parsed = basename(plain);
  if (parsed) return parsed;
  const stored = basename(asset.storage_key || asset.key || asset.filename);
  if (stored) return stored;
  const extension = String(asset.mime_type || "").toLowerCase().startsWith("video/") ? "mp4" : "png";
  return `output-${String(asset.asset_id || "file").replace(/[^A-Za-z0-9._-]/g, "_")}.${extension}`;
}

export async function fetchAssetDownload({url, token = "", asset = {}, fetchImpl = globalThis.fetch}) {
  const headers = token ? {"X-Internal-Token": token} : {};
  const response = await fetchImpl(url, {method: "GET", headers, credentials: "same-origin"});
  if (!response.ok) {
    const body = await response.text();
    let message = `Download failed (HTTP ${response.status})`;
    try { message = JSON.parse(body)?.error?.message || message; } catch { /* Keep generic status. */ }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  if (response.redirected) throw new Error("The secure download endpoint returned an unexpected redirect.");
  const blob = await response.blob();
  if (!blob.size) throw new Error("The downloaded output file is empty.");
  return {blob, filename: downloadFilename(response.headers.get("Content-Disposition"), asset)};
}
