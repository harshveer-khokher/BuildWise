import { STATUS_META } from "../lib/findings";

/** A finding's status, always as dot + text label together — status is never conveyed by
 * color alone (accessibility requirement in the design brief). */
export function StatusBadge({ status }) {
  const meta = STATUS_META[status] || { label: status, dot: "•", cssVar: "--ink-soft" };
  return (
    <span className="badge status-badge" style={{ "--badge-color": `var(${meta.cssVar})` }}>
      <span aria-hidden="true">{meta.dot}</span>
      {meta.label}
    </span>
  );
}

const CONFIDENCE_META = {
  low: { label: "Low confidence", cssVar: "--violation" },
  medium: { label: "Medium confidence", cssVar: "--review" },
  high: { label: "High confidence", cssVar: "--pass" },
};

export function ConfidenceBadge({ confidence }) {
  const meta = CONFIDENCE_META[confidence] || { label: confidence, cssVar: "--ink-soft" };
  return (
    <span className="badge confidence-badge" style={{ "--badge-color": `var(${meta.cssVar})` }}>
      {meta.label}
    </span>
  );
}

const CITATION_STATUS_META = {
  verified: "Two independent transcription passes agreed exactly.",
  seed_unverified: "Transcribed but not yet independently confirmed against the gazette.",
  conflict: "Transcription passes disagreed; this rule is disabled.",
  not_stated: "The source clause does not state a number for this case.",
};

export function CitationStatusNote({ status }) {
  const note = CITATION_STATUS_META[status];
  return (
    <span className="citation-status">
      <code>{status}</code>
      {note ? <span className="hint"> — {note}</span> : null}
    </span>
  );
}
