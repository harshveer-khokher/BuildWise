/** Minimal overlay renderer: draws the GeoJSON FeatureCollection from POST /overlay
 * (packages/report/overlay.py) as plain SVG — plot outline, zoned area, floor footprints and
 * finding geometry, color-coded by finding status. No mapping library; the coordinates are
 * already in the BuildingModel's local metric system, so an SVG viewBox in metres is enough.
 */
function collectBounds(features) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  function visit(coords) {
    if (typeof coords[0] === "number") {
      const [x, y] = coords;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    } else {
      coords.forEach(visit);
    }
  }
  features.forEach((f) => f.geometry && visit(f.geometry.coordinates));
  if (!isFinite(minX)) return { minX: 0, minY: 0, width: 10, height: 10 };
  return { minX, minY, width: maxX - minX || 10, height: maxY - minY || 10 };
}

// Muted, architectural line drawing — not a map. Colors match the app's own palette tokens.
const KIND_STYLE = {
  plot_outline: { stroke: "#211d19", fill: "none" },
  zoned_area: { stroke: "#4d6a80", fill: "#4d6a80", fillOpacity: 0.06 },
  floor_footprint: { stroke: "#a39a8a", fill: "#a39a8a", fillOpacity: 0.1 },
};

export default function OverlaySvg({ overlay }) {
  if (!overlay || !overlay.features?.length) {
    return <p className="hint">No overlay geometry to show.</p>;
  }
  const { minX, minY, width, height } = collectBounds(overlay.features);
  const pad = Math.max(width, height) * 0.08 || 1;
  const viewBox = `${minX - pad} ${minY - pad} ${width + 2 * pad} ${height + 2 * pad}`;

  return (
    <svg viewBox={viewBox} className="overlay-svg" preserveAspectRatio="xMidYMid meet">
      <g transform={`scale(1,-1) translate(0, ${-(2 * minY + height)})`}>
        {overlay.features.map((f, i) => {
          const geom = f.geometry;
          if (!geom) return null;
          const kind = f.properties.kind;
          const style =
            kind === "finding"
              ? { stroke: f.properties.color, fill: f.properties.color, fillOpacity: 0.3 }
              : KIND_STYLE[kind] || { stroke: "#667085", fill: "none" };
          if (geom.type === "Polygon") {
            const points = geom.coordinates[0].map((p) => p.join(",")).join(" ");
            return (
              <polygon
                key={i}
                points={points}
                stroke={style.stroke}
                fill={style.fill}
                fillOpacity={style.fillOpacity ?? 0}
                strokeWidth={Math.max(width, height) * 0.004}
              />
            );
          }
          if (geom.type === "LineString") {
            const points = geom.coordinates.map((p) => p.join(",")).join(" ");
            return (
              <polyline
                key={i}
                points={points}
                stroke={style.stroke}
                fill="none"
                strokeWidth={Math.max(width, height) * 0.006}
              />
            );
          }
          if (geom.type === "Point") {
            const [x, y] = geom.coordinates;
            return <circle key={i} cx={x} cy={y} r={Math.max(width, height) * 0.01} fill={style.stroke} />;
          }
          return null;
        })}
      </g>
    </svg>
  );
}
