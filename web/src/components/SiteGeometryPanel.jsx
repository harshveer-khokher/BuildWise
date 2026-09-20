const SQM_TO_SQYD = 1.196;

// Plot-edge roles, which are a different vocabulary from the sheet roles in lib/roles.js --
// "front" here is a boundary of the plot, not a front elevation sheet.
const EDGE_LABELS = {
  front: "Front",
  rear: "Rear",
  side_a: "Side A",
  side_b: "Side B",
  unknown: "Unidentified edge",
};

function edgeLabel(role) {
  return EDGE_LABELS[role] || role;
}

function fmt(value, digits = 2) {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

/** Per-edge row: what the zoning line permits vs. what was actually built to.
 *
 * The verdict is deliberately one-sided. The built figure is measured to the nearest masonry
 * drawn inside the plot, which also picks up a boundary wall standing on the plot line — so it
 * can only ever UNDER-state the real setback. That makes "meets the zoning line" sound, while a
 * shortfall is something to confirm rather than a settled violation. Same rule the backend
 * applies to the findings themselves. */
function EdgeRow({ edge }) {
  const required = edge.zoning_setback_m;
  const built = edge.built_setback_m;
  const known = required !== null && required !== undefined && built !== null && built !== undefined;
  const meets = known && built + 0.01 >= required;

  return (
    <tr>
      <th scope="row">{edgeLabel(edge.role)}</th>
      <td>{fmt(required)} m</td>
      <td>{fmt(built)} m</td>
      <td>
        {!known ? (
          <span className="hint">not measurable</span>
        ) : meets ? (
          <span className="site-geom__ok">meets the zoning line</span>
        ) : (
          <span className="site-geom__short">
            {fmt(required - built)} m short — confirm
          </span>
        )}
      </td>
    </tr>
  );
}

/** Plot, buildable envelope and setbacks, measured off the drawing itself.
 *
 * Distinct from EstimatedEnvelopePanel, which computes a *theoretical* envelope from rule
 * formulas plus plot dimensions typed on the intake screen. Everything here was read from the
 * sheet's own labelled PLOT LINE and ZONING LINE, at a scale cross-checked in both directions
 * against dimensions printed on that same sheet. */
export default function SiteGeometryPanel({ siteGeometry }) {
  if (!siteGeometry) return null;

  const {
    plot_area_sqm: plotAreaSqm,
    zoned_area_sqm: zonedAreaSqm,
    scale_pts_per_m: scale,
    wall_thickness_m: wallThickness,
    unmodelled_zoning_steps: steps,
    edges = [],
  } = siteGeometry;

  const coveragePct =
    plotAreaSqm && zonedAreaSqm ? (zonedAreaSqm / plotAreaSqm) * 100 : null;

  return (
    <div className="section-block site-geom">
      <h3>Plot and buildable envelope</h3>
      <p className="hint">
        Measured from the drawing's own <strong>plot line</strong> and <strong>zoning line</strong>,
        at a scale cross-checked against dimensions printed on the same sheet. Not typed in, and
        not a theoretical envelope.
      </p>

      <div className="site-geom__figures">
        <div className="site-geom__figure">
          <span className="site-geom__value">{fmt(plotAreaSqm, 1)} m²</span>
          <span className="site-geom__label">
            Plot area
            {plotAreaSqm ? ` · ${(plotAreaSqm * SQM_TO_SQYD).toFixed(0)} sq yd` : ""}
          </span>
        </div>
        <div className="site-geom__figure">
          <span className="site-geom__value">{fmt(zonedAreaSqm, 1)} m²</span>
          <span className="site-geom__label">
            Buildable envelope
            {coveragePct !== null ? ` · ${coveragePct.toFixed(1)}% of plot` : ""}
          </span>
        </div>
      </div>

      {edges.length > 0 && (
        <table className="site-geom__table">
          <thead>
            <tr>
              <th scope="col">Edge</th>
              <th scope="col">Zoning line allows</th>
              <th scope="col">Built to</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {edges.map((edge, i) => (
              <EdgeRow key={`${edge.role}-${i}`} edge={edge} />
            ))}
          </tbody>
        </table>
      )}

      <ul className="site-geom__notes hint">
        {wallThickness ? (
          <li>
            Building extent taken from masonry drawn {(wallThickness * 100).toFixed(0)} cm thick.
            It is an upper bound — it also encloses any boundary wall on the plot line — so a
            shortfall above is flagged for confirmation, never reported as a settled violation.
          </li>
        ) : (
          <li>
            No masonry could be identified on this sheet, so no built setback was measured.
          </li>
        )}
        {steps > 0 && (
          <li>
            {steps} shorter zoning-line run{steps === 1 ? "" : "s"} also found. These mark steps in
            the envelope (typically a permitted rear outbuilding) and are not included above, so
            the real permitted envelope is this size or larger — never smaller.
          </li>
        )}
        {scale ? <li>Scale used: {scale} pt/m.</li> : null}
      </ul>
    </div>
  );
}
