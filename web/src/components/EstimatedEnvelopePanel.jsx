import { sqmToSqyd } from "../lib/geometry";

function formatValue(v) {
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

// Muted/neutral for "fits by size" (never the green used for a real `pass`), muted amber/warning
// for "likely exceeds" (never the red used for a real `violation`) — both reuse existing status
// color tokens from index.css, per the design brief, rather than inventing new colors.
const FIT_STATUS_META = {
  plausible_fit: { label: "Fits, by size (estimate)", cssVar: "--unknown" },
  likely_exceeds: { label: "Likely exceeds buildable area (estimate)", cssVar: "--review" },
};

function FitStatus({ fitStatus }) {
  const meta = FIT_STATUS_META[fitStatus];
  if (meta) {
    return (
      <span className="estimate-fit-badge" style={{ "--badge-color": `var(${meta.cssVar})` }}>
        {meta.label}
      </span>
    );
  }
  // "inconclusive", or any value this frontend doesn't recognise — plain neutral text, no pill,
  // per the brief. Shown verbatim rather than guessed at.
  return <span className="hint">{fitStatus ? `${fitStatus} (estimate)` : "Inconclusive (estimate)"}</span>;
}

/** Renders the backend's advisory "estimated buildable envelope"
 * (packages/rules/estimated_envelope.py), positioned immediately next to the real, code-verified
 * zoned-area containment Finding (PUDA1996.containment.zoned_area) in FindingsAccordion — never
 * merged into it, never replacing its own real `unknown` status.
 *
 * This is explicitly NOT a verified check: no zoning-plan sheet exists for this upload, so the
 * envelope is a generic-setback-formula approximation, and the fit check is by footprint SIZE
 * only, never by verified position (see the `note` field rendered in full below). Every field the
 * backend returns is rendered — nothing invented, nothing paraphrased away, nothing dropped,
 * per CLAUDE.md's "never fabricate, always disclose exactly what was computed and how". */
export default function EstimatedEnvelopePanel({ estimatedEnvelope }) {
  if (!estimatedEnvelope) return null;

  if (!estimatedEnvelope.available) {
    return (
      <div className="envelope-estimate envelope-estimate--unavailable">
        <span className="envelope-estimate__chip">Estimate</span>
        <p className="hint">
          Buildable-envelope estimate not available: {estimatedEnvelope.reason}
        </p>
      </div>
    );
  }

  const {
    height_m_used: heightUsed,
    front_rear_setback_m: frontRearSetback,
    side_setback_m: sideSetback,
    frontage_plot_dimension: frontageDimension,
    estimated_envelope_frontage_m: envelopeFrontage,
    estimated_envelope_depth_m: envelopeDepth,
    estimated_envelope_area_sqm: envelopeAreaSqm,
    fit_status: fitStatus,
    fit_reason: fitReason,
    per_floor_fit: perFloorFit,
    note,
  } = estimatedEnvelope;

  return (
    <div className="envelope-estimate">
      <div className="envelope-estimate__head">
        <span className="envelope-estimate__chip">Estimate — not a verified zoning check</span>
        <FitStatus fitStatus={fitStatus} />
      </div>

      {fitReason && <p className="envelope-estimate__reason">{fitReason}</p>}

      <dl className="finding-fields">
        <div>
          <dt>Height used</dt>
          <dd>{formatValue(heightUsed)} m</dd>
        </div>
        <div>
          <dt>Front/rear setback</dt>
          <dd>{formatValue(frontRearSetback)} m</dd>
        </div>
        <div>
          <dt>Side setback</dt>
          <dd>{formatValue(sideSetback)} m</dd>
        </div>
        <div>
          <dt>Frontage dimension used</dt>
          <dd>{formatValue(frontageDimension)}</dd>
        </div>
        <div>
          <dt>Estimated envelope</dt>
          <dd>
            {formatValue(envelopeFrontage)} m × {formatValue(envelopeDepth)} m
          </dd>
        </div>
        <div>
          <dt>Estimated envelope area</dt>
          <dd>
            {formatValue(envelopeAreaSqm)} sq m
            {envelopeAreaSqm !== null && envelopeAreaSqm !== undefined
              ? ` (${sqmToSqyd(envelopeAreaSqm)} sq yd)`
              : ""}
          </dd>
        </div>
      </dl>

      {perFloorFit?.length > 0 && (
        <div className="table-scroll">
          <table className="data-table data-table--compact">
            <thead>
              <tr>
                <th>Floor</th>
                <th>Footprint frontage</th>
                <th>Footprint depth</th>
                <th>Fits by size</th>
              </tr>
            </thead>
            <tbody>
              {perFloorFit.map((f, i) => (
                <tr key={i}>
                  <td>{formatValue(f.floor_level)}</td>
                  <td>{formatValue(f.footprint_frontage_m)} m</td>
                  <td>{formatValue(f.footprint_depth_m)} m</td>
                  <td>{f.fits_by_size ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {note && (
        <details className="envelope-estimate__disclosure">
          <summary>How was this estimated?</summary>
          <p>{note}</p>
        </details>
      )}
    </div>
  );
}
