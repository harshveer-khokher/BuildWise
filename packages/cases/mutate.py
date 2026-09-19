"""Declarative DXF mutation + truth-file generation (CLAUDE.md §10.5).

    mutate("synth/s_smoke.dxf", op="offset_edge", mutation_id="m01",
           layer="A-WALL-EXTR", edge="north", delta_m=1.2)
      -> writes synth/mutated/s_smoke_m01.dxf
      -> writes truth/s_smoke_m01.truth.json, DERIVED from the mutation parameters and the
         geometry itself (shapely), never hand-labeled.

Real Mohali drawings have no digitized DXF yet (only vector PDFs for h01/h02 -- see
INTEGRATION.md's Stage-0 handoff and Track A's note there), so per §10.5 this harness is
demonstrated against the single synth smoke file (packages/cases/synth/s_smoke.dxf,
CLAUDE.md §10.2), NOT against h01/h02. That makes every truth file this module produces today
`provenance: "synthetic"` -- a harness smoke test, never a headline eval number (CLAUDE.md §10.3).
The moment a real approved DXF lands, the same two ops below should run against it unchanged;
only the `provenance` field on the resulting truth file flips to "mutated_real".

Two ops implemented, matching CLAUDE.md §9's "shrink a wall" / "trim a room" menu:

  - offset_edge:  push one edge of a closed wall polyline outward by delta_m along its own
                  normal (simulates a wall creeping toward/into a setback).
  - shrink_room:  pull one edge of a closed room polyline inward by delta_m (simulates a room
                  shrinking below a minimum-area/minimum-dimension threshold).

Both operate only on axis-aligned rectangles (true of every closed polyline in the smoke file);
that restriction is enforced, not assumed silently.

No rule_id / pass-fail is asserted here: this synth case has no plot/zoned_area, so there is
nothing for a PUDA rule to actually check yet (CLAUDE.md §1 rule 1: no invented verdicts). The
truth file instead records the one thing that IS unambiguously true by construction -- the exact
before/after geometry and area delta the mutation produced -- which is exactly what a future
rule-engine-facing truth file needs to grade a `Finding.observed` value against, once this harness
is pointed at a real, plot-anchored case.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import ezdxf
from shapely.geometry import Polygon

CASES_DIR = pathlib.Path(__file__).resolve().parent
SYNTH_DIR = CASES_DIR / "synth"
MUTATED_DIR = SYNTH_DIR / "mutated"
TRUTH_DIR = CASES_DIR / "truth"

_EDGE_AXES = {
    "north": (1, 1),   # (coordinate index, sign of "outward")
    "south": (1, -1),
    "east": (0, 1),
    "west": (0, -1),
}


def _ring_without_closing_point(points: list[list[float]]) -> list[tuple[float, float]]:
    pts = [tuple(p) for p in points]
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def _assert_axis_aligned_rectangle(pts: list[tuple[float, float]], context: str) -> None:
    xs = sorted({round(p[0], 6) for p in pts})
    ys = sorted({round(p[1], 6) for p in pts})
    if len(pts) != 4 or len(xs) != 2 or len(ys) != 2:
        raise ValueError(
            f"mutate: {context} is not an axis-aligned rectangle (got {len(pts)} vertices, "
            f"{len(xs)} distinct x, {len(ys)} distinct y) -- offset_edge/shrink_room only "
            "support the simple rectangular geometry in the synth smoke file."
        )


def _find_layer_polyline(msp: Any, layer: str) -> Any:
    candidates = [
        e
        for e in msp
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == layer and e.closed
    ]
    if not candidates:
        raise ValueError(f"mutate: no closed LWPOLYLINE found on layer '{layer}'.")
    if len(candidates) > 1:
        raise ValueError(
            f"mutate: {len(candidates)} closed polylines on layer '{layer}'; ambiguous which "
            "one to mutate (the smoke file is expected to have exactly one per room/wall layer)."
        )
    return candidates[0]


def _offset_rectangle_edge(
    pts: list[tuple[float, float]], edge: str, delta_m: float
) -> list[tuple[float, float]]:
    axis, sign = _EDGE_AXES[edge]
    extreme = max(p[axis] for p in pts) if sign > 0 else min(p[axis] for p in pts)
    new_pts = []
    for p in pts:
        p = list(p)
        if abs(p[axis] - extreme) < 1e-6:
            p[axis] = p[axis] + sign * delta_m
        new_pts.append(tuple(p))
    return new_pts


def _shrink_rectangle_edge(
    pts: list[tuple[float, float]], edge: str, delta_m: float
) -> list[tuple[float, float]]:
    # Shrinking is offsetting the same edge in the opposite (inward) direction.
    return _offset_rectangle_edge(pts, edge, -delta_m)


def mutate(
    src_dxf: str | pathlib.Path,
    op: str,
    mutation_id: str,
    layer: str,
    edge: str,
    delta_m: float,
) -> dict[str, Any]:
    """Apply one declarative mutation to `src_dxf`, writing a mutated DXF and a truth JSON.

    Returns the truth dict that was written (also available at the returned `truth_path`).
    """
    if op not in ("offset_edge", "shrink_room"):
        raise ValueError(f"mutate: unknown op '{op}' (expected offset_edge or shrink_room)")
    if edge not in _EDGE_AXES:
        raise ValueError(f"mutate: unknown edge '{edge}' (expected one of {sorted(_EDGE_AXES)})")

    src_dxf = pathlib.Path(src_dxf)
    doc = ezdxf.readfile(str(src_dxf))
    msp = doc.modelspace()

    entity = _find_layer_polyline(msp, layer)
    before_pts = _ring_without_closing_point(
        [[float(x), float(y)] for x, y in entity.get_points(format="xy")]
    )
    _assert_axis_aligned_rectangle(before_pts, f"layer '{layer}' in {src_dxf.name}")

    if op == "offset_edge":
        after_pts = _offset_rectangle_edge(before_pts, edge, delta_m)
    else:
        after_pts = _shrink_rectangle_edge(before_pts, edge, delta_m)

    # Rewrite the polyline's points in place.
    entity.set_points([(x, y) for x, y in after_pts], format="xy")

    MUTATED_DIR.mkdir(parents=True, exist_ok=True)
    out_dxf = MUTATED_DIR / f"{src_dxf.stem}_{mutation_id}.dxf"
    doc.saveas(str(out_dxf))

    before_poly = Polygon(before_pts)
    after_poly = Polygon(after_pts)

    axis, sign = _EDGE_AXES[edge]
    before_edge_value = (max if sign > 0 else min)(p[axis] for p in before_pts)
    after_edge_value = (max if sign > 0 else min)(p[axis] for p in after_pts)

    truth = {
        "case_id": f"{src_dxf.stem}_{mutation_id}",
        "provenance": "synthetic",
        "note": (
            "Harness smoke test on synthetic geometry (CLAUDE.md §10.3/§10.5) -- proves "
            "mutate.py can derive an exact geometric truth from declarative mutation "
            "parameters, deterministically, with no hand-labeling and no LLM in the loop "
            "(CLAUDE.md §1 rule 1). This is NOT a labeled rule-violation case: the synth smoke "
            "file has no plot_polygon/zoned_area, so no PUDA rule_id or pass/fail verdict is "
            "asserted here. Never counts toward eval headline metrics."
        ),
        "source_dxf": str(src_dxf),
        "mutated_dxf": str(out_dxf),
        "mutation": {
            "op": op,
            "layer": layer,
            "edge": edge,
            "delta_m": delta_m,
        },
        "ground_truth": {
            "before_polygon": [list(p) for p in before_pts],
            "after_polygon": [list(p) for p in after_pts],
            f"{edge}_edge_coordinate_before_m": before_edge_value,
            f"{edge}_edge_coordinate_after_m": after_edge_value,
            "area_before_sqm": before_poly.area,
            "area_after_sqm": after_poly.area,
            "area_delta_sqm": after_poly.area - before_poly.area,
        },
    }

    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    truth_path = TRUTH_DIR / f"{truth['case_id']}.truth.json"
    truth_path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    truth["truth_path"] = str(truth_path)
    return truth


def main() -> None:
    """Regenerate the two demonstration mutations against the synth smoke DXF."""
    src = SYNTH_DIR / "s_smoke.dxf"

    m01 = mutate(
        src, op="offset_edge", mutation_id="m01",
        layer="A-WALL-EXTR", edge="north", delta_m=1.2,
    )
    print(f"wrote {m01['mutated_dxf']} and {m01['truth_path']}")

    m02 = mutate(
        src, op="shrink_room", mutation_id="m02",
        layer="TOIL", edge="east", delta_m=0.8,
    )
    print(f"wrote {m02['mutated_dxf']} and {m02['truth_path']}")


if __name__ == "__main__":
    main()
