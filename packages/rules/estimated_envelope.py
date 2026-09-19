"""Estimated buildable envelope from the bylaw's own setback FORMULA -- an advisory estimate,
never the real containment verdict.

CLAUDE.md's flagship containment check (PUDA1996.containment.zoned_area) requires a real, traced
zoning plan, because the official document can legally override generic setbacks (CLAUDE.md §2
glossary: a zoning plan "overrides generic setbacks"). This module does NOT feed that check, and
never sets BuildingModel.zoned_area. It computes a separate, clearly-labeled estimate: shrink the
entered plot rectangle inward by the formula-based setbacks in clause 17 (front/rear >=
max(height/4, 2m), side >= max(height/5, 1.5m)), using a real confirmed height
(pdf_ingest.extract_overall_height_m) where one exists.

Orientation (which pair of plot edges is the road-facing front/rear) is inferred from the
drawing itself, never asked of the user:
  1. The building's own ground-floor footprint has a width and a depth (its bounding box in its
     own sheet-local frame).
  2. The front elevation's own drawn width (a real-world measurement, via the same
     extract_drawing_bbox/estimate_scale_pts_per_m already used for plan sheets) tells us which
     of those two -- width or depth -- is the one you see when facing the road, since a front
     elevation is a face-on view of exactly that dimension.
  3. Whichever of the user's entered plot width/length is numerically closer to that same
     real-world dimension is inferred to be the plot's own road-facing (frontage) edge.
If step 2 or 3 can't be done confidently (no matching front elevation, no clean footprint), this
returns {"available": False, "reason": ...} rather than guessing.
"""

from __future__ import annotations

import pathlib
from pathlib import Path
from typing import Any

import fitz
from shapely.geometry import Polygon

from packages.parser.pdf_ingest import (
    estimate_scale_pts_per_m,
    extract_drawing_bbox,
    extract_overall_height_m,
    ingest_plan_sheet,
)
from packages.rules.engine import load_pack

_PACKS_DIR = pathlib.Path(__file__).resolve().parent / "packs"


def _setback_formula_constants(rule_pack_id: str) -> tuple[float, float, float, float] | None:
    """(front_rear_fraction, front_rear_min_m, side_fraction, side_min_m), read live from the
    verified rule pack -- never duplicated here as literals, so a future gazette-diff correction
    to these values is picked up automatically instead of silently drifting out of sync."""
    exact = _PACKS_DIR / f"{rule_pack_id}.yaml"
    if not exact.exists():
        candidates = sorted(_PACKS_DIR.glob("*.yaml"))
        if len(candidates) != 1:
            return None
        exact = candidates[0]
    pack = load_pack(exact)
    fr_rule = next((r for r in pack["rules"] if r["id"] == "PUDA1996.setback.front_rear_formula"), None)
    side_rule = next((r for r in pack["rules"] if r["id"] == "PUDA1996.setback.side_formula"), None)
    if fr_rule is None or side_rule is None:
        return None
    return (
        fr_rule["fraction_of_height"], fr_rule["min_m"],
        side_rule["fraction_of_height"], side_rule["min_m"],
    )


def _elevation_drawn_width_m(elevation_path: str | Path) -> float | None:
    doc = fitz.open(str(elevation_path))
    page = doc[0]
    bbox, _ = extract_drawing_bbox(page)
    scale, _ = estimate_scale_pts_per_m(page, bbox)
    doc.close()
    if not scale:
        return None
    return (bbox.x1 - bbox.x0) / scale


def estimate_buildable_envelope(
    ground_floor_path: str | Path,
    front_elevation_path: str | Path,
    plot_width_m: float,
    plot_length_m: float,
    rule_pack_id: str,
) -> dict[str, Any]:
    """Returns a dict; check `["available"]` before trusting the rest. Never touches a
    BuildingModel -- callers decide how (or whether) to surface this alongside the real, ambiguity-
    tracked containment check."""
    height_m, _segments, height_note = extract_overall_height_m(front_elevation_path)
    if height_m is None:
        return {"available": False, "reason": f"no confirmed height available from the front elevation: {height_note}"}

    ground = ingest_plan_sheet(ground_floor_path)
    fp = ground["footprint"]
    if fp is None:
        return {"available": False, "reason": "the ground floor plan produced no usable footprint to infer orientation from."}
    fp_width = fp[1][0] - fp[0][0]
    fp_depth = fp[2][1] - fp[1][1]

    elevation_width_m = _elevation_drawn_width_m(front_elevation_path)
    if elevation_width_m is None:
        return {"available": False, "reason": "could not measure the front elevation's own drawn width -- not guessing which footprint axis faces the road."}

    road_facing_is_fp_width = abs(elevation_width_m - fp_width) <= abs(elevation_width_m - fp_depth)
    fp_road_facing_dim = fp_width if road_facing_is_fp_width else fp_depth

    plot_frontage_is_width_input = abs(plot_width_m - fp_road_facing_dim) <= abs(plot_length_m - fp_road_facing_dim)

    constants = _setback_formula_constants(rule_pack_id)
    if constants is None:
        return {"available": False, "reason": f"no verified setback-formula constants found for rule pack {rule_pack_id!r}."}
    fr_fraction, fr_min, side_fraction, side_min = constants
    front_rear_setback_m = max(height_m * fr_fraction, fr_min)
    side_setback_m = max(height_m * side_fraction, side_min)

    if plot_frontage_is_width_input:
        frontage_m, depth_m = plot_width_m, plot_length_m
        frontage_source = "width"
    else:
        frontage_m, depth_m = plot_length_m, plot_width_m
        frontage_source = "length"

    envelope_frontage_m = frontage_m - 2 * side_setback_m
    envelope_depth_m = depth_m - 2 * front_rear_setback_m
    if envelope_frontage_m <= 0 or envelope_depth_m <= 0:
        return {
            "available": False,
            "reason": (
                f"setbacks (front/rear {front_rear_setback_m:.2f}m, side {side_setback_m:.2f}m) "
                f"leave no positive buildable area on a {plot_width_m:.2f}m x {plot_length_m:.2f}m "
                "plot -- not a usable estimate."
            ),
        }

    return {
        "available": True,
        "height_m_used": round(height_m, 3),
        "front_rear_setback_m": round(front_rear_setback_m, 3),
        "side_setback_m": round(side_setback_m, 3),
        "frontage_plot_dimension": frontage_source,
        "estimated_envelope_frontage_m": round(envelope_frontage_m, 3),
        "estimated_envelope_depth_m": round(envelope_depth_m, 3),
        "estimated_envelope_area_sqm": round(envelope_frontage_m * envelope_depth_m, 2),
        "note": (
            f"ESTIMATE, not a verified zoning check. Buildable envelope computed by shrinking the "
            f"entered {plot_width_m:.2f}m x {plot_length_m:.2f}m plot inward by clause 17's generic "
            f"setback formula: front/rear >= max(height x {fr_fraction}, {fr_min}m) = "
            f"{front_rear_setback_m:.2f}m, side >= max(height x {side_fraction}, {side_min}m) = "
            f"{side_setback_m:.2f}m, using the confirmed height of {height_m:.2f}m. Orientation "
            f"(the plot's '{frontage_source}' input treated as road frontage) was inferred by "
            f"matching the ground floor's own footprint ({fp_width:.2f}m x {fp_depth:.2f}m) against "
            f"the front elevation's drawn width ({elevation_width_m:.2f}m), then matching that "
            f"footprint axis to whichever entered plot dimension is closer -- never asked of the "
            "user, not guaranteed correct. The real, official zoning plan can legally override "
            "this generic formula (corner-plot rules, road-widening reservations, etc.); this "
            "estimate is not a substitute for one."
        ),
    }
