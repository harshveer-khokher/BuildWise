import { useState } from "react";
import {
  groupByRuleId,
  groupHeadingTitle,
  sortGroups,
  SEVERITY_LABEL,
  CONTAINMENT_RULE_ID,
} from "../lib/findings";
import { StatusBadge } from "./StatusBadge";
import EstimatedEnvelopePanel from "./EstimatedEnvelopePanel";

function formatValue(v) {
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

function RemedyList({ remedies }) {
  if (!remedies || remedies.length === 0) return null;
  // Dedupe by description across instances in a group, mirroring
  // packages/report/render.py's render_markdown grouped-remedy behaviour.
  const seen = new Set();
  const unique = [];
  for (const r of remedies) {
    if (seen.has(r.description)) continue;
    seen.add(r.description);
    unique.push(r);
  }
  return (
    <div className="finding-remedies">
      <h4>Remedies</h4>
      <ul>
        {unique.map((r, i) => (
          <li key={i}>
            <code>{r.kind}</code>{" "}
            <span className={r.verified ? "remedy-verified" : "remedy-unverified"}>
              {r.verified ? "verified" : "not yet verified"}
            </span>
            {r.area_lost_sqm !== null && r.area_lost_sqm !== undefined && (
              <span className="hint"> (~{r.area_lost_sqm} sq m)</span>
            )}
            <p>{r.description}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Citation({ citation }) {
  return (
    <dl className="citation-block">
      <div>
        <dt>Document</dt>
        <dd>{citation.doc}</dd>
      </div>
      <div>
        <dt>Clause</dt>
        <dd>§{citation.clause}</dd>
      </div>
      <div>
        <dt>Version</dt>
        <dd>{citation.version}</dd>
      </div>
      {citation.url && (
        <div>
          <dt>Source</dt>
          <dd>
            <a href={citation.url} target="_blank" rel="noreferrer">
              {citation.url}
            </a>
          </dd>
        </div>
      )}
    </dl>
  );
}

function GroupDetail({ group }) {
  const f0 = group[0];
  const allRemedies = group.flatMap((f) => f.remedies || []);
  const distinctByValue = new Set(group.map((f) => `${f.title}|${f.observed}|${f.required}`));

  return (
    <div className="finding-detail">
      <dl className="finding-fields">
        <div>
          <dt>Rule ID</dt>
          <dd>
            <code>{f0.rule_id}</code>
          </dd>
        </div>
        <div>
          <dt>Severity</dt>
          <dd>{SEVERITY_LABEL[f0.severity] || f0.severity}</dd>
        </div>
        <div>
          <dt>Compoundable</dt>
          <dd>{f0.compoundable ? "Yes" : "No"}</dd>
        </div>
        {f0.ambiguity_class && (
          <div>
            <dt>Ambiguity class</dt>
            <dd>
              <code>{f0.ambiguity_class}</code>
            </dd>
          </div>
        )}
      </dl>

      <Citation citation={f0.citation} />

      {group.length === 1 || distinctByValue.size === 1 ? (
        <dl className="finding-fields">
          <div>
            <dt>Observed</dt>
            <dd>{formatValue(f0.observed)}</dd>
          </div>
          <div>
            <dt>Required</dt>
            <dd>{formatValue(f0.required)}</dd>
          </div>
          <div>
            <dt>Geometry reference</dt>
            <dd>{f0.geometry_ref ? `${f0.geometry_ref.length}-point polygon` : "not provided"}</dd>
          </div>
        </dl>
      ) : (
        <div className="table-scroll">
          <table className="data-table data-table--compact">
            <thead>
              <tr>
                <th>Instance</th>
                <th>Observed</th>
                <th>Required</th>
                <th>Geometry ref</th>
              </tr>
            </thead>
            <tbody>
              {group.map((f, i) => (
                <tr key={i}>
                  <td>{f.title}</td>
                  <td>{formatValue(f.observed)}</td>
                  <td>{formatValue(f.required)}</td>
                  <td>{f.geometry_ref ? `${f.geometry_ref.length}-point polygon` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RemedyList remedies={allRemedies} />
    </div>
  );
}

/** Findings grouped by rule_id — mirrors packages/report/render.py's render_markdown grouping
 * judgement (see its `_group` / `_heading_title` helpers): several findings sharing one rule_id
 * (e.g. a light/ventilation check run once per room) collapse into a single expandable row with
 * an instance count and table, instead of N near-duplicate rows.
 *
 * `estimatedEnvelope` (from the real-upload path's /cases/assemble response; `null`/undefined for
 * fixtures and whenever plot dimensions weren't entered) is rendered as a distinctly-styled panel
 * directly below the real zoned-area containment finding's row — never merged into that finding,
 * never altering its real status. See EstimatedEnvelopePanel. */
export default function FindingsAccordion({ findings, estimatedEnvelope = null }) {
  const [openId, setOpenId] = useState(null);
  const groups = sortGroups(groupByRuleId(findings));

  if (groups.length === 0) {
    return <p className="hint">No findings were returned.</p>;
  }

  const hasContainmentRow = groups.some((group) => group[0].rule_id === CONTAINMENT_RULE_ID);

  return (
    <div className="accordion">
      {groups.map((group, idx) => {
        const f0 = group[0];
        const id = `finding-${f0.rule_id}-${idx}`;
        const isOpen = openId === id;
        const title = groupHeadingTitle(group);
        const isContainmentRow = f0.rule_id === CONTAINMENT_RULE_ID;
        return (
          <div className="accordion-row" key={id}>
            <h4 className="accordion-row__heading">
              <button
                type="button"
                className="accordion-row__trigger"
                aria-expanded={isOpen}
                aria-controls={`${id}-panel`}
                id={`${id}-trigger`}
                onClick={() => setOpenId(isOpen ? null : id)}
              >
                <StatusBadge status={f0.status} />
                <span className="accordion-row__title">{title}</span>
                {group.length > 1 && <span className="badge count-badge">×{group.length}</span>}
                <span className="badge severity-badge">{SEVERITY_LABEL[f0.severity] || f0.severity}</span>
                {f0.compoundable && <span className="badge subtle-badge">Compoundable</span>}
                {f0.ambiguity_class && (
                  <span className="badge subtle-badge">{f0.ambiguity_class.replace(/_/g, " ")}</span>
                )}
                <span className="accordion-row__chevron" aria-hidden="true">
                  {isOpen ? "−" : "+"}
                </span>
              </button>
            </h4>
            {isOpen && (
              <div
                className="accordion-row__panel"
                id={`${id}-panel`}
                role="region"
                aria-labelledby={`${id}-trigger`}
              >
                <GroupDetail group={group} />
              </div>
            )}
            {isContainmentRow && estimatedEnvelope && (
              <div className="accordion-row__adjunct">
                <EstimatedEnvelopePanel estimatedEnvelope={estimatedEnvelope} />
              </div>
            )}
          </div>
        );
      })}
      {/* Defensive fallback: the containment rule should always be present (it runs
          unconditionally), but if it's ever missing from this findings list, the estimate is
          still surfaced rather than silently dropped (CLAUDE.md §1 rule 6). */}
      {!hasContainmentRow && estimatedEnvelope && (
        <div className="accordion-row__adjunct accordion-row__adjunct--standalone">
          <EstimatedEnvelopePanel estimatedEnvelope={estimatedEnvelope} />
        </div>
      )}
    </div>
  );
}
