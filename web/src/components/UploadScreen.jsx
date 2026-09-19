import { useState } from "react";
import { FIXTURES } from "../fixtures";
import { uploadModel } from "../api";

/** Upload / select-a-case screen (CLAUDE.md §11 Stage 1, §10.2 placeholder mode).
 *
 * Real drawing upload isn't wired up on the backend yet (packages/parser doesn't exist in this
 * worktree) — so this screen's primary path is "pick a BuildingModel fixture and POST it to
 * /upload as JSON", which is exactly the placeholder-mode seam CLAUDE.md §10.2 describes. A file
 * input is still offered so the multipart path (and its honest 501 until Track A lands) is
 * reachable too.
 */
export default function UploadScreen({ onModelLoaded }) {
  const [fixtureId, setFixtureId] = useState(FIXTURES[0].id);
  const [rawJson, setRawJson] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function loadFixture() {
    setBusy(true);
    setError(null);
    try {
      const fixture = FIXTURES.find((f) => f.id === fixtureId);
      const model = await uploadModel(fixture.model);
      onModelLoaded(model, fixture.label);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function loadRawJson() {
    setBusy(true);
    setError(null);
    try {
      const parsed = JSON.parse(rawJson);
      const model = await uploadModel(parsed);
      onModelLoaded(model, "pasted BuildingModel JSON");
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onFileChosen(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch(`${import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000"}/upload`, {
        method: "POST",
        body: form,
      });
      const body = await resp.json().catch(() => null);
      if (!resp.ok) {
        throw new Error(
          resp.status === 501
            ? "Drawing parsing isn't wired up yet on the backend (packages.parser not available). Use a fixture or paste JSON instead."
            : `${resp.status} ${resp.statusText}: ${body?.detail || ""}`
        );
      }
      onModelLoaded(body, file.name);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen">
      <h2>1. Upload a drawing</h2>
      <p className="hint">
        This is a pre-submission check only — never an approval or a sanction. It never says
        "approved" or "compliant"; the result is always framed as issues found.
      </p>

      <div className="card">
        <h3>Real drawing (DXF / PDF)</h3>
        <input type="file" onChange={onFileChosen} disabled={busy} />
        <p className="hint">
          Parsing isn't wired up in this build yet — expect a clear 501, not a silent fake result.
        </p>
      </div>

      <div className="card">
        <h3>Or pick a test case (BuildingModel fixture)</h3>
        <select value={fixtureId} onChange={(e) => setFixtureId(e.target.value)} disabled={busy}>
          {FIXTURES.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
        <button onClick={loadFixture} disabled={busy}>
          {busy ? "Loading…" : "Load fixture"}
        </button>
      </div>

      <div className="card">
        <h3>Or paste a BuildingModel JSON</h3>
        <textarea
          rows={6}
          placeholder='{"source": "dxf", "jurisdiction": {...}, ...}'
          value={rawJson}
          onChange={(e) => setRawJson(e.target.value)}
          disabled={busy}
        />
        <button onClick={loadRawJson} disabled={busy || !rawJson.trim()}>
          Validate &amp; load
        </button>
      </div>

      {error && <p className="error">{error}</p>}
    </section>
  );
}
