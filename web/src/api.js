// Thin fetch() wrapper around the Track D API (packages/api/main.py). No component library,
// no state manager — this is a proof that the API contract works end-to-end from a browser
// (CLAUDE.md §11 Stage 1: "API skeleton, upload, model-confirmation screen, overlay renderer").
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
    const detail = body && body.detail ? JSON.stringify(body.detail) : text;
    throw new Error(`${resp.status} ${resp.statusText}: ${detail}`);
  }
  return body;
}

export function health() {
  return fetch(`${API_BASE}/health`).then(asJson);
}

export function uploadModel(buildingModel) {
  return fetch(`${API_BASE}/upload`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildingModel),
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

export async function reportHtmlUrl(model, findings) {
  const resp = await fetch(`${API_BASE}/report/html`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, findings }),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}

export async function downloadReportPdf(model, findings) {
  const resp = await fetch(`${API_BASE}/report/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, findings }),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "mohali-check-report.pdf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
