// Findings presentation helpers.
//
// The grouping logic here deliberately mirrors packages/report/render.py's `_group` /
// `_heading_title` (Markdown report renderer): group findings sharing one rule_id into a single
// row with an instance table, rather than rendering N near-duplicate rows for e.g. a
// light/ventilation check run once per room. Re-implemented here (not imported — the web/
// package doesn't reach across the packages/ boundary) but kept behaviourally identical.

// Mirrors packages/report/render.py's _STATUS_LABEL exactly, so the same finding reads the same
// way in the on-screen accordion and the downloaded report. Status is never conveyed by color
// alone — every dot is paired with this text label.
export const STATUS_META = {
  violation: { label: "Violation", dot: "🔴", cssVar: "--violation", softVar: "--violation-soft" },
  ambiguity: { label: "Ambiguity", dot: "🟠", cssVar: "--review", softVar: "--review-soft" },
  unknown: { label: "Unknown", dot: "⚪", cssVar: "--unknown", softVar: "--unknown-soft" },
  advisory: { label: "Advisory", dot: "🔵", cssVar: "--info", softVar: "--info-soft" },
  pass: { label: "Pass", dot: "🟢", cssVar: "--pass", softVar: "--pass-soft" },
};

export const STATUS_ORDER = { violation: 0, ambiguity: 1, unknown: 2, advisory: 3, pass: 4 };
export const SEVERITY_ORDER = { blocking: 0, major: 1, minor: 2 };
export const SEVERITY_LABEL = { blocking: "Blocking", major: "Major", minor: "Minor" };

/** Group findings by rule_id, preserving first-seen order — same contract as render.py's
 * _group(). */
export function groupByRuleId(findings) {
  const groups = new Map();
  const order = [];
  for (const f of findings) {
    if (!groups.has(f.rule_id)) {
      groups.set(f.rule_id, []);
      order.push(f.rule_id);
    }
    groups.get(f.rule_id).push(f);
  }
  return order.map((id) => groups.get(id));
}

/** If every finding in the group shares one title, use it. If they differ only by a trailing
 * "(...)"-style qualifier (e.g. "(front)", "(floor 0)"), show the shared prefix instead of one
 * instance's qualifier standing in for the whole group — same regex as render.py's
 * _heading_title(). */
export function groupHeadingTitle(group) {
  const titles = new Set(group.map((f) => f.title));
  if (titles.size > 1) {
    return group[0].title.replace(/\s*\([^()]*\)\s*$/, "").trimEnd();
  }
  return group[0].title;
}

export function sortGroups(groups) {
  return [...groups].sort((a, b) => {
    const sevDiff = (SEVERITY_ORDER[a[0].severity] ?? 9) - (SEVERITY_ORDER[b[0].severity] ?? 9);
    if (sevDiff !== 0) return sevDiff;
    return (STATUS_ORDER[a[0].status] ?? 9) - (STATUS_ORDER[b[0].status] ?? 9);
  });
}

/** Factual counts for the results-page banner: Passed / Flagged / Review. Never a fabricated
 * score — this is a plain tally of the statuses the engine actually returned.
 *   Passed   = status "pass"
 *   Flagged  = status "violation" (a clear rule break, code-verified)
 *   Review   = ambiguity + unknown + advisory — everything that is not a clean pass and not a
 *              clear-cut violation either, i.e. needs a human to read it. Folding "unknown"
 *              into "Passed" would be exactly the fabricated-confidence bug CLAUDE.md §5/§10.1
 *              warns about, so it never happens here. */
export function summarizeCounts(findings) {
  let passed = 0;
  let flagged = 0;
  let review = 0;
  for (const f of findings) {
    if (f.status === "pass") passed += 1;
    else if (f.status === "violation") flagged += 1;
    else review += 1; // ambiguity, unknown, advisory
  }
  return { passed, flagged, review, total: findings.length };
}
