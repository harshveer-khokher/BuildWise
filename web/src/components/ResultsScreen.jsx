import { summarizeCounts } from "../lib/findings";
import { roleLabel } from "../lib/roles";
import { FileUsageBadge } from "./StatusBadge";
import FindingsAccordion from "./FindingsAccordion";
import ReportPanel from "./ReportPanel";
import OverlaySvg from "./OverlaySvg";

/** Results hierarchy per the design brief: overall factual counts (never a fabricated score),
 * then the findings accordion, then file outcomes and assumptions (always shown verbatim), then
 * the report. */
export default function ResultsScreen({
  model,
  caseLabel,
  fileAssembly,
  checksResult,
  reportMarkdown,
  overlay,
  onRestart,
}) {
  const { summary, engine_source: engineSource, engine_error: engineError, findings } = checksResult;
  const counts = summarizeCounts(findings);
  const resolvedEntries = fileAssembly ? Object.entries(fileAssembly.resolvedRoles || {}) : [];
  const unresolvedEntries = fileAssembly?.unresolved || [];
  const hasFileOutcomes = resolvedEntries.length > 0 || unresolvedEntries.length > 0;

  return (
    <section className="screen results">
      <div className="screen-header results__header">
        <div>
          <p className="eyebrow">{caseLabel}</p>
          <h2>Results</h2>
        </div>
        <button type="button" className="button button--ghost" onClick={onRestart}>
          Start over
        </button>
      </div>

      {engineError && (
        <div className="notice notice--warning">
          The real rule engine raised an error evaluating this model and the API fell back to a
          fixture result set. Findings below may not reflect the real rule pack.
          <details>
            <summary>Details</summary>
            <pre>{engineError}</pre>
          </details>
        </div>
      )}

      <div className="status-banner">
        <div className="status-banner__counts">
          <span className="status-count status-count--pass">
            <strong>{counts.passed}</strong> Passed
          </span>
          <span className="status-count status-count--flag">
            <strong>{counts.flagged}</strong> Flagged
          </span>
          <span className="status-count status-count--review">
            <strong>{counts.review}</strong> Review
          </span>
        </div>
        <p className="status-banner__summary">{summary}</p>
        <p className="hint">
          Engine: {engineSource === "real" ? "real rule pack" : "fixture result set (real engine unavailable)"}
        </p>
      </div>

      <div className="section-block">
        <h3>Findings</h3>
        <p className="hint">
          Grouped by rule — a check run once per room or edge appears as one row with an instance
          count, not as repeated rows.
        </p>
        <FindingsAccordion findings={findings} />
      </div>

      {hasFileOutcomes && (
        <div className="section-block">
          <h3>Files used in this check</h3>
          <p className="hint">
            Each uploaded file's role was read from the file itself. A file marked "Not used"
            wasn't guessed at — it's left out and explained here rather than silently dropped.
          </p>
          <ul className="file-outcomes">
            {resolvedEntries.map(([filename, role]) => (
              <li className="file-outcome" key={filename}>
                <div className="file-outcome__row">
                  <span className="file-outcome__name">{filename}</span>
                  <FileUsageBadge used />
                  <span className="hint">{roleLabel(role)}</span>
                </div>
              </li>
            ))}
            {unresolvedEntries.map((u) => (
              <li className="file-outcome" key={u.filename}>
                <div className="file-outcome__row">
                  <span className="file-outcome__name">{u.filename}</span>
                  <FileUsageBadge used={false} />
                </div>
                <p className="file-outcome__reason">{u.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {model.assumptions?.length > 0 && (
        <div className="section-block assumptions-block">
          <h3>Assumptions made while reading this drawing</h3>
          <p className="hint">Printed verbatim — every inference made on your behalf, listed rather than hidden.</p>
          <ul>
            {model.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {overlay && (
        <div className="section-block">
          <h3>Plan overview</h3>
          <p className="hint">
            A derived sketch of the plot, zoned area (if traced) and floor footprints — not a
            substitute for the drawing itself.
          </p>
          <OverlaySvg overlay={overlay} />
        </div>
      )}

      <div className="section-block">
        <h3>Report</h3>
        {reportMarkdown ? (
          <ReportPanel markdown={reportMarkdown} model={model} findings={findings} />
        ) : (
          <p className="hint">The report could not be generated for this run.</p>
        )}
      </div>

      <p className="footer-disclaimer">
        This is a pre-submission check only. It is not an approval, not a sanction, and not a
        certificate of compliance by GMADA, PUDA, or any authority.
      </p>
    </section>
  );
}
