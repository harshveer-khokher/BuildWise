"""Overlay renderer (CLAUDE.md §11 Stage 1, Track D scope).

Turns a BuildingModel + list[Finding] into a GeoJSON FeatureCollection a frontend can drop
straight onto a <canvas>/SVG/Leaflet-style overlay on top of the plot outline. This module does
no rule evaluation and no arithmetic beyond geometry construction — it only repackages numbers
and polygons that `packages.rules.engine` (or, until that lands, a caller-supplied fixture list)
already produced (CLAUDE.md §1 rule 1: no verdict is invented here, we only visualize one).

All polygon handling goes through shapely (CLAUDE.md §1 rule 3) — we never index into a ring's
coordinates by hand beyond what's needed to decide Point/LineString/Polygon.

Coordinates stay in the BuildingModel's local metric coordinate system (CLAUDE.md §1 rule 4 —
unit conversion happens only in render.py's display layer, never here).
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, Point as ShapelyPoint, Polygon, mapping

from packages.schema import BuildingModel, Finding

# Colors are advisory metadata for a frontend renderer; they encode nothing that isn't already
# on the Finding itself (status/severity remain in `properties` verbatim for any consumer that
# wants to style differently).
_STATUS_COLOR = {
    "violation": "#d92d20",
    "ambiguity": "#f79009",
    "advisory": "#2970ff",
    "pass": "#12b76a",
    "unknown": "#667085",
}


def _ring_to_geometry(ring: list[list[float]]):
    """Build the right shapely geometry for a geometry_ref, without hand-rolling polygon math.

    geometry_ref is typed as a Ring in the frozen schema, but in practice a finding may want to
    highlight a single edge (2 points, e.g. a setback breach along the rear line) rather than an
    area. We dispatch on point count / closure and let shapely construct + validate the geometry
    rather than special-casing indices ourselves.
    """
    if not ring:
        return None
    if len(ring) == 1:
        return ShapelyPoint(ring[0])
    if len(ring) == 2:
        return LineString(ring)
    is_closed = ring[0] == ring[-1]
    if is_closed and len(ring) >= 4:
        poly = Polygon(ring)
        if not poly.is_valid:
            # Don't silently accept bad geometry from upstream — attempt the standard shapely
            # repair (buffer(0)) but keep it as a polygon, never approximate by hand.
            poly = poly.buffer(0)
        return poly
    return LineString(ring)


def _finding_feature(finding: Finding) -> dict[str, Any]:
    geom = _ring_to_geometry(finding.geometry_ref) if finding.geometry_ref else None
    properties = {
        "kind": "finding",
        "rule_id": finding.rule_id,
        "status": finding.status,
        "severity": finding.severity,
        "title": finding.title,
        "color": _STATUS_COLOR.get(finding.status, "#667085"),
        "observed": finding.observed,
        "required": finding.required,
        "compoundable": finding.compoundable,
        "ambiguity_class": finding.ambiguity_class,
        "citation": finding.citation.model_dump(),
        "remedy_count": len(finding.remedies),
    }
    return {
        "type": "Feature",
        "geometry": mapping(geom) if geom is not None else None,
        "properties": properties,
    }


def _context_feature(ring: list[list[float]] | None, kind: str, extra: dict | None = None) -> dict | None:
    if not ring:
        return None
    geom = _ring_to_geometry(ring)
    if geom is None:
        return None
    properties = {"kind": kind}
    if extra:
        properties.update(extra)
    return {"type": "Feature", "geometry": mapping(geom), "properties": properties}


def build_overlay(model: BuildingModel, findings: list[Finding]) -> dict[str, Any]:
    """Return a GeoJSON FeatureCollection: plot/zoning/floor context + one feature per finding.

    Findings without a geometry_ref (e.g. missing-RWH, ECS count) still get a Feature with
    geometry=null so the frontend's findings list and the overlay layer can share one payload
    and one indexing scheme (properties.rule_id) without the caller needing two response shapes.
    """
    features: list[dict[str, Any]] = []

    plot_feature = _context_feature(model.plot_polygon, "plot_outline")
    if plot_feature is not None:
        features.append(plot_feature)

    zoned_feature = _context_feature(model.zoned_area, "zoned_area")
    if zoned_feature is not None:
        features.append(zoned_feature)
    # zoned_area is None is itself meaningful (CLAUDE.md §5) — surface it as metadata rather than
    # just an absent feature, so a frontend doesn't have to infer "missing" from silence.

    for floor in model.floors:
        floor_feature = _context_feature(
            floor.footprint, "floor_footprint", {"level": floor.level, "is_stilt": floor.is_stilt}
        )
        if floor_feature is not None:
            features.append(floor_feature)

    for finding in findings:
        features.append(_finding_feature(finding))

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "zoned_area_present": model.zoned_area is not None,
            "plot_area_sqm": model.plot_area_sqm,
        },
    }
