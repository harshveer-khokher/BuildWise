// Client-side plot-rectangle synthesis (design brief scope decision #2).
//
// This is a *fallback*, used only when the assembled/loaded BuildingModel has no
// plot_area_sqm of its own (true for every real upload today — no case in this build ships a
// site/zoning sheet, see INTEGRATION.md). It unblocks ground-coverage/FAR checks, which only
// need a plot area, but it does NOT unblock zoned-area containment: containment needs the real
// buildable envelope traced from a site/zoning sheet, which cannot be derived from a width x
// length figure. Callers must keep telling the user that distinction — see the caption in
// PlotSizeInput.jsx.
//
// Internal units are metres/square metres everywhere per CLAUDE.md §1 rule 4; conversion only
// happens here, at the point the user's own unit choice is turned into the model's units.

export const UNIT_TO_METRES = {
  m: 1,
  ft: 0.3048,
  yd: 0.9144,
};

export const UNIT_LABELS = {
  m: "metres",
  ft: "feet",
  yd: "yards",
};

/** width/length in the user's chosen unit -> a closed 4-point axis-aligned rectangle ring in
 * metres, plus its area in square metres. Origin at (0,0) — this is a synthesized plot with no
 * real-world position, never claimed to align with any drawing datum. */
export function synthesizePlotRectangle(widthValue, lengthValue, unit) {
  const factor = UNIT_TO_METRES[unit] ?? 1;
  const widthM = Number(widthValue) * factor;
  const lengthM = Number(lengthValue) * factor;
  const plotPolygon = [
    [0, 0],
    [widthM, 0],
    [widthM, lengthM],
    [0, lengthM],
    [0, 0],
  ];
  const plotAreaSqm = widthM * lengthM;
  return { plotPolygon, plotAreaSqm, widthM, lengthM };
}

export const SQM_TO_SQYD = 1.196;

export function sqmToSqyd(value) {
  if (value === null || value === undefined) return null;
  return Math.round(value * SQM_TO_SQYD * 100) / 100;
}

/** Merges a user-entered width x length into a BuildingModel that has no plot_area_sqm of its
 * own, per the brief's exact contract: sets plot_polygon + plot_area_sqm and appends one
 * assumptions-array string documenting the synthesis. Returns the model unchanged if it already
 * carries a plot_area_sqm (the assembled drawing's own value always wins). */
export function mergeSynthesizedPlot(model, widthValue, lengthValue, unit) {
  if (model.plot_area_sqm !== null && model.plot_area_sqm !== undefined) {
    return model;
  }
  const { plotPolygon, plotAreaSqm } = synthesizePlotRectangle(widthValue, lengthValue, unit);
  return {
    ...model,
    plot_polygon: plotPolygon,
    plot_area_sqm: plotAreaSqm,
    assumptions: [
      ...(model.assumptions || []),
      "plot_polygon/plot_area_sqm synthesized from user-entered width x length input, not traced from a site/zoning sheet.",
    ],
  };
}
