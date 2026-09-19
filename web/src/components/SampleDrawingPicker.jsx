import { FIXTURES } from "../fixtures";

/** Quick-start using the six pre-parsed stub BuildingModels (CLAUDE.md §10.2). Clearly labeled
 * as a sample/demo path, not the user's own drawing — real drawings today (h01/h02) lack a
 * site/section sheet and mostly produce honest `unknown`s, so these are the only way to preview
 * a fuller result. */
export default function SampleDrawingPicker({ fixtureId, onFixtureIdChange, onLoad, busy }) {
  return (
    <div className="sample-picker">
      <p className="sample-picker__badge">Sample data, not your drawing</p>
      <p className="hint">
        Preview the full result with one of six pre-parsed sample buildings — useful since a real
        upload today will usually be missing a site or section sheet.
      </p>
      <div className="sample-picker__row">
        <select
          value={fixtureId}
          onChange={(e) => onFixtureIdChange(e.target.value)}
          disabled={busy}
          aria-label="Choose a sample drawing"
        >
          {FIXTURES.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
        <button type="button" className="button button--secondary" onClick={onLoad} disabled={busy}>
          {busy ? "Loading…" : "Load sample"}
        </button>
      </div>
    </div>
  );
}
