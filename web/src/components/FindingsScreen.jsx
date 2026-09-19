import { useEffect, useState } from "react";
import { runChecks, fetchOverlay, reportHtmlUrl, downloadReportPdf } from "../api";
import OverlaySvg from "./OverlaySvg";

const STATUS_ORDER = { violation: 0, ambiguity: 1, unknown: 2, advisory: 3, pass: 4 };

/** Findings list + overlay screen (CLAUDE.md §11 Stage 1).
 *
 * Calls POST /checks/run (packages.api.checks.run_checks — real rules engine if Track B has
 * landed, else the fixture set) and POST /overlay (packages.report.overlay.build_overlay).
 * The summary line is always "pre-submission check: N issues found" straight from the API —
 * this component never re-derives or rewords it (CLAUDE.md §5).
 */
export default function FindingsScreen({ model, caseLabel, onRestart }) {
  const [result, setResult] = useState(null);
  const [overlay, setOverlay] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(null);
  const [reportUrl, setReportUrl] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError(null);
    runChecks(model)
      .then((checksResult) => {
        if (cancelled) return;
        setResult(checksResult);
        return fetchOverlay(model, checksResult.findings);
      })
      .then((overlayResult) => {
        if (cancelled) return;
        setOverlay(overlayResult);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err.message || err));
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [model]);

  async function openHtmlReport() {
    try {
      const url = await reportHtmlUrl(model, result.findings);
      setReportUrl(url);
      window.open(url, "_blank");
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function downloadPdf() {
    try {
      await downloadReportPdf(model, result.findings);
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  return (
    <section className="screen">
      <h2>3. Findings — {caseLabel}</h2>

      {busy && <p className="hint">Running checks…</p>}
      {error && <p className="error">{error}</p>}

      {result && (
        <>
          <div className="summary-banner">{result.summary}</div>
          <p className="hint">
            Engine: <strong>{result.engine_source}</strong>{" "}
            {result.engine_source === "fixture"
              ? "(packages.rules.engine not wired up yet — showing hand-written fixture findings that exercise the real Finding schema)"
              : "(real rule pack from packages.rules.engine)"}
          </p>

          <table className="findings-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Severity</th>
                <th>Rule</th>
                <th>Title</th>
                <th>Observed</th>
                <th>Required</th>
                <th>Citation</th>
                <th>Compoundable</th>
              </tr>
            </thead>
            <tbody>
              {[...result.findings]
                .sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9))
                .map((f, i) => (
                  <tr key={i}>
                    <td className={`status-${f.status}`}>{f.status}</td>
                    <td>{f.severity}</td>
                    <td>{f.rule_id}</td>
                    <td>
                      {f.title}
                      {f.ambiguity_class && <div className="hint">ambiguity: {f.ambiguity_class}</div>}
                      {f.remedies?.length > 0 && (
                        <ul className="remedies">
                          {f.remedies.map((r, ri) => (
                            <li key={ri}>
                              <strong>{r.kind}</strong> {r.verified ? "(verified)" : "(not yet verified)"}: {r.description}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td>{f.observed ?? "—"}</td>
                    <td>{f.required ?? "—"}</td>
                    <td className="citation">
                      {f.citation.doc} §{f.citation.clause} (v{f.citation.version}, {f.citation.status})
                    </td>
                    <td>{f.compoundable ? "yes" : "no"}</td>
                  </tr>
                ))}
            </tbody>
          </table>

          <h3>Overlay</h3>
          <OverlaySvg overlay={overlay} />

          <div className="actions">
            <button onClick={openHtmlReport}>Open HTML report</button>
            <button onClick={downloadPdf}>Download PDF report</button>
            <button onClick={onRestart}>Start over</button>
          </div>
          {reportUrl && (
            <p className="hint">
              Report opened in a new tab (<a href={reportUrl} target="_blank" rel="noreferrer">link</a>).
            </p>
          )}
        </>
      )}
    </section>
  );
}
