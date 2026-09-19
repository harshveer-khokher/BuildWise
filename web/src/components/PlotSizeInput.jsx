/** Plot width x length input — a fallback, not a real site survey (design brief scope #2).
 *
 * Entering a width and length here unblocks ground-coverage/FAR checks, which only need a plot
 * area. It does NOT unblock the zoned-area containment check: containment needs the real
 * buildable envelope traced from a site/zoning sheet, a different polygon that cannot be derived
 * from plot dimensions alone. That caveat is stated plainly below the inputs so nobody mistakes
 * "I entered my plot size" for "containment is now checkable."
 */
export default function PlotSizeInput({ width, length, unit, onChange, disabledInfo }) {
  if (disabledInfo) {
    return (
      <div className="plot-size plot-size--readonly">
        <p className="field-value">
          {disabledInfo.areaSqm.toLocaleString()} sq m ({disabledInfo.areaSqyd.toLocaleString()} sq yd)
        </p>
        <p className="hint">
          Plot area was already present in the uploaded drawing, so the manual width x length
          input below is not needed.
        </p>
      </div>
    );
  }

  return (
    <div className="plot-size">
      <div className="plot-size__row">
        <label className="field">
          <span className="field-label">Width</span>
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={width}
            onChange={(e) => onChange({ width: e.target.value })}
            placeholder="e.g. 15"
          />
        </label>
        <span className="plot-size__times" aria-hidden="true">
          ×
        </span>
        <label className="field">
          <span className="field-label">Length</span>
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={length}
            onChange={(e) => onChange({ length: e.target.value })}
            placeholder="e.g. 45"
          />
        </label>
        <label className="field field--unit">
          <span className="field-label">Unit</span>
          <select value={unit} onChange={(e) => onChange({ unit: e.target.value })}>
            <option value="m">m</option>
            <option value="ft">ft</option>
            <option value="yd">yd</option>
          </select>
        </label>
      </div>
      <p className="hint">
        Used as a rectangle approximation of the plot for ground-coverage and FAR checks only.
        It does <strong>not</strong> enable the zoned-area containment check — that needs the
        buildable envelope traced from a real site/zoning sheet, which this cannot substitute for.
      </p>
    </div>
  );
}
