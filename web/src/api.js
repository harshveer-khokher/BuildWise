// Thin fetch() wrapper around the BuildWise API (packages/api/main.py).
//
// API_BASE can be overridden at build/dev time with VITE_API_BASE; defaults to the uvicorn
// default from packages/api/main.py's __main__ block.
export const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

async function asJson(resp) {
  const text = await resp.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!resp.ok) {
    const detail = body && body.detail ? extractDetail(body.detail) : text;
    throw new Error(detail || `${resp.status} ${resp.statusText}`);
  }
  return body;
}

// FastAPI/pydantic validation errors arrive as {detail: [{loc, msg, ...}, ...]} or as a plain
// string/dict. Render something a non-engineer can read rather than a raw JSON dump.
function extractDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d === "string" ? d : d.msg || JSON.stringify(d))).join("; ");
  }
  if (detail && typeof detail === "object") {
    if (detail.message) {
      const errors = Array.isArray(detail.errors) ? `: ${detail.errors.join("; ")}` : "";
      return `${detail.message}${errors}`;
    }
    return JSON.stringify(detail);
  }
  return String(detail);
}

async function asBlob(resp) {
  if (!resp.ok) {
    const text = await resp.text();
    let detail = text;
    try {
      const body = JSON.parse(text);
      detail = extractDetail(body.detail ?? body);
    } catch {
      /* not JSON, use raw text */
    }
    throw new Error(detail || `${resp.status} ${resp.statusText}`);
  }
  return resp.blob();
}

export function health() {
  return fetch(`${API_BASE}/health`).then(asJson);
}

export function listJurisdictions() {
  return fetch(`${API_BASE}/jurisdictions`).then(asJson);
}

/** JSON path of POST /upload — used for the sample-fixture flow (a fixture is already a full
 * BuildingModel on the client, so this just validates & echoes it back). */
export function uploadModel(buildingModel) {
  return fetch(`${API_BASE}/upload`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildingModel),
  }).then(asJson);
}

/** POST /cases/assemble — the real multi-file, role-tagged drawing upload.
 * `sheets` is a { role: File } map; `authority` is the selected jurisdiction's authority code
 * (e.g. "GMADA"). */
export function assembleCase(sheets, authority) {
  const form = new FormData();
  for (const [role, file] of Object.entries(sheets)) {
    if (file) form.append(role, file);
  }
  form.append("authority", authority);
  return fetch(`${API_BASE}/cases/assemble`, {
    method: "POST",
    body: form,
  }).then(asJson);
}

export function confirmModel(model, corrections) {
  return fetch(`${API_BASE}/models/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, corrections }),
  }).then(asJson);
}

export function runChecks(model) {
  return fetch(`${API_BASE}/checks/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  }).then(asJson);
}

export function fetchOverlay(model, findings) {
  return fetch(`${API_BASE}/overlay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, findings }),
  }).then(asJson);
}

/** Fetches the exact Markdown text the backend renders — the results page shows this verbatim
 * (preview + download), it is never regenerated or altered client-side. */
export async function fetchReportMarkdown(model, findings) {
  const resp = await fetch(`${API_BASE}/report/markdown`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, findings }),
  });
  return asBlobText(resp);
}

async function asBlobText(resp) {
  const blob = await asBlob(resp);
  return blob.text();
}

export async function reportHtmlUrl(model, findings) {
  const resp = await fetch(`${API_BASE}/report/html`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, findings }),
  });
  const blob = await asBlob(resp);
  return URL.createObjectURL(blob);
}

export async function downloadReportPdf(model, findings) {
  const resp = await fetch(`${API_BASE}/report/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, findings }),
  });
  const blob = await asBlob(resp);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "buildwise-report.pdf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
