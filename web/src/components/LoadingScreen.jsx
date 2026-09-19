/** Checking state.
 *
 * There is no job queue behind this API — /checks/run is one synchronous request/response, so
 * there is no real progress to report. This screen deliberately does NOT fake step-by-step
 * completion (no "✓ Reading project information" ticking through in sequence) — that would be
 * exactly the fabricated-confidence problem CLAUDE.md §5 exists to prevent, just moved into the
 * loading spinner instead of a finding. Instead: one honest, calm, indeterminate state, plus a
 * static, inert description of what this kind of check generally involves — presented as plain
 * prose, not a checklist, so nothing implies real-time completion signals.
 */
export default function LoadingScreen() {
  return (
    <section className="screen loading-screen" aria-live="polite" aria-busy="true">
      <div className="loading-screen__inner">
        <div className="loading-bar" role="progressbar" aria-label="Checking your plan">
          <div className="loading-bar__fill" />
        </div>
        <h2>Checking your plan…</h2>
        <p className="lede">
          This runs the applicable rule pack against your drawing's geometry — deterministic
          checks, not a guess, so it can take a few seconds on a larger plan.
        </p>
        <p className="hint loading-screen__about">
          In general, a check like this works through: the plot and zoning geometry, each floor's
          footprint and rooms, the applicable clauses for the selected jurisdiction, and the
          citations behind each result.
        </p>
      </div>
    </section>
  );
}
