"""Hand-written BuildingModel fixtures conforming to packages/schema (CLAUDE.md §10.2).

These unblock tracks B (rules), C (solver) and D (report/UI) without any drawing at all —
they consume a BuildingModel, not a DXF. Run:

    python packages/cases/gen_stub.py

to (re)write packages/cases/stubs/*.model.json. Provenance is always "synthetic": these never
count toward eval metrics (CLAUDE.md §10.3), they only prove the pipes are connected.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from packages.schema import BuildingModel, Edge, Floor, Jurisdiction, Room

STUB_DIR = pathlib.Path(__file__).resolve().parent / "stubs"


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def _edges(x0: float, y0: float, x1: float, y1: float, road_width: float = 12.0) -> list[Edge]:
    return [
        Edge(line=[[x0, y0], [x1, y0]], faces_road=True, road_width_m=road_width, role="front"),
        Edge(line=[[x0, y1], [x1, y1]], faces_road=False, road_width_m=None, role="rear"),
        Edge(line=[[x0, y0], [x0, y1]], faces_road=False, road_width_m=None, role="side_a"),
        Edge(line=[[x1, y0], [x1, y1]], faces_road=False, road_width_m=None, role="side_b"),
    ]


def _jurisdiction(**overrides) -> Jurisdiction:
    base = dict(
        authority="GMADA",
        sector="70",
        plot_no="STUB",
        allotment_date=date(2019, 4, 1),
        rule_pack="puda_building_rules_1996",
    )
    base.update(overrides)
    return Jurisdiction(**base)


def s01_clean_250() -> BuildingModel:
    # 12.5 x 20 = 250 sqm. Buildable envelope inset 3m front/rear, 1.5m sides.
    plot = _rect(0, 0, 12.5, 20)
    envelope = _rect(1.5, 3.0, 11.0, 17.0)
    footprint = _rect(2.0, 3.5, 10.5, 13.5)  # 8.5 x 10 = 85 sqm, well inside envelope
    ground = Floor(
        level=0, is_stilt=False, footprint=footprint, height_m=3.2,
        rooms=[
            Room(polygon=_rect(2.0, 3.5, 6.0, 8.5), use="living", floor=0,
                 openings_area_sqm=3.5, confidence="high"),
            Room(polygon=_rect(6.0, 3.5, 10.5, 8.5), use="bedroom", floor=0,
                 openings_area_sqm=2.4, confidence="high"),
            Room(polygon=_rect(2.0, 8.5, 6.0, 13.5), use="kitchen", floor=0,
                 openings_area_sqm=1.5, confidence="high"),
            Room(polygon=_rect(6.0, 8.5, 10.5, 13.5), use="bath", floor=0,
                 openings_area_sqm=0.8, confidence="high"),
        ],
    )
    first = Floor(level=1, is_stilt=False, footprint=footprint, height_m=3.0,
                  rooms=[Room(polygon=footprint, use="bedroom", floor=1,
                              openings_area_sqm=4.0, confidence="high")])
    return BuildingModel(
        source="dxf",
        jurisdiction=_jurisdiction(plot_no="S01"),
        plot_polygon=plot,
        plot_area_sqm=250.0,
        zoned_area=envelope,
        edges=_edges(0, 0, 12.5, 20),
        floors=[ground, first],
        has_rwh=True,
        tree_count=1,
        assumptions=["Synthetic clean baseline: all geometry hand-authored, no extraction involved."],
    )


def s02_setback_rear() -> BuildingModel:
    # Same envelope as s01, but the rear wall pushes 1.2m past the buildable line (y=17.0 -> 18.2).
    plot = _rect(0, 0, 12.5, 20)
    envelope = _rect(1.5, 3.0, 11.0, 17.0)
    footprint = _rect(2.0, 3.5, 10.5, 18.2)
    ground = Floor(
        level=0, is_stilt=False, footprint=footprint, height_m=3.2,
        rooms=[
            Room(polygon=_rect(2.0, 3.5, 6.0, 8.5), use="living", floor=0,
                 openings_area_sqm=3.5, confidence="high"),
            Room(polygon=_rect(6.0, 14.0, 10.5, 18.2), use="bedroom", floor=0,
                 openings_area_sqm=2.0, confidence="high"),
        ],
    )
    return BuildingModel(
        source="dxf",
        jurisdiction=_jurisdiction(plot_no="S02"),
        plot_polygon=plot,
        plot_area_sqm=250.0,
        zoned_area=envelope,
        edges=_edges(0, 0, 12.5, 20),
        floors=[ground],
        has_rwh=False,
        tree_count=0,
        assumptions=[
            "Synthetic rear-setback violation: rear wall sits 1.2 m inside the required rear "
            "setback (footprint runs to y=18.2, envelope stops at y=17.0). A 0.4 m trim is one "
            "candidate the solver should surface among several; it is not asserted to be the "
            "unique or minimal fix here."
        ],
    )


def s03_far_over() -> BuildingModel:
    # 250 sqm plot, three full floors near the plot extent -> FAR well over any plausible cap.
    plot = _rect(0, 0, 12.5, 20)
    envelope = _rect(1.5, 3.0, 11.0, 17.0)
    footprint = _rect(1.7, 3.2, 10.8, 16.8)  # ~130 sqm per floor
    floors = [
        Floor(level=lvl, is_stilt=False, footprint=footprint, height_m=3.0,
              rooms=[Room(polygon=footprint, use="other", floor=lvl,
                          openings_area_sqm=5.0, confidence="medium")])
        for lvl in range(0, 3)
    ]
    return BuildingModel(
        source="dxf",
        jurisdiction=_jurisdiction(plot_no="S03"),
        plot_polygon=plot,
        plot_area_sqm=250.0,
        zoned_area=envelope,
        edges=_edges(0, 0, 12.5, 20),
        floors=floors,
        has_rwh=True,
        tree_count=1,
        assumptions=[
            "Synthetic FAR violation: 3 floors x ~130 sqm on a 250 sqm plot "
            "(FAR ~1.56) intended to exceed the residential-plotted cap once a verified value "
            "exists; exercises the compoundable-remedy path regardless of the exact seeded number."
        ],
    )


def s04_stilt4_500() -> BuildingModel:
    # 20 x 25 = 500 sqm plot. Stilt (open parking) + 4 upper floors.
    plot = _rect(0, 0, 20, 25)
    envelope = _rect(2.0, 4.0, 18.0, 21.0)
    footprint = _rect(3.0, 5.0, 17.0, 19.0)  # 14 x 14 = 196 sqm
    stilt = Floor(level=0, is_stilt=True, footprint=footprint, height_m=2.4, rooms=[])
    floors = [stilt]
    for lvl in range(1, 5):
        floors.append(Floor(
            level=lvl, is_stilt=False, footprint=footprint, height_m=3.0,
            rooms=[Room(polygon=footprint, use="other", floor=lvl,
                        openings_area_sqm=8.0, confidence="high")],
        ))
    return BuildingModel(
        source="dxf",
        jurisdiction=_jurisdiction(plot_no="S04"),
        plot_polygon=plot,
        plot_area_sqm=500.0,
        zoned_area=envelope,
        edges=_edges(0, 0, 20, 25),
        floors=floors,
        has_rwh=True,
        tree_count=3,
        assumptions=[
            "Synthetic stilt+4 case on a 500 sqm plot: whether the stilt storey counts toward "
            "FAR/height is a genuine definitional ambiguity (CLAUDE.md §8), not resolved here — "
            "the engine should emit ambiguity_class=definitional with both readings, not a "
            "silent pass or fail."
        ],
    )


def s05_no_zoning() -> BuildingModel:
    plot = _rect(0, 0, 12.5, 20)
    footprint = _rect(2.0, 3.5, 10.5, 13.5)
    ground = Floor(level=0, is_stilt=False, footprint=footprint, height_m=3.2,
                   rooms=[Room(polygon=footprint, use="living", floor=0,
                               openings_area_sqm=3.0, confidence="high")])
    return BuildingModel(
        source="vector_pdf",
        jurisdiction=_jurisdiction(plot_no="S05"),
        plot_polygon=plot,
        plot_area_sqm=250.0,
        zoned_area=None,  # digitized zoning plan not available
        edges=_edges(0, 0, 12.5, 20),
        floors=[ground],
        has_rwh=False,
        tree_count=0,
        assumptions=[
            "Synthetic missing-zoning case: zoned_area is None because no zoning plan PDF was "
            "traced for this plot. The containment check must return status=unknown, never pass "
            "(CLAUDE.md §5) — this is the case that guards against that regression."
        ],
    )


def s06_low_conf() -> BuildingModel:
    plot = _rect(0, 0, 12.5, 20)
    envelope = _rect(1.5, 3.0, 11.0, 17.0)
    footprint = _rect(2.0, 3.5, 10.5, 13.5)
    ground = Floor(
        level=0, is_stilt=False, footprint=footprint, height_m=3.2,
        rooms=[
            # Ambiguous: could be "store" or "bedroom" from a raster-scanned plan with a
            # faint/unclear label -- low confidence forces the confirmation-screen path.
            Room(polygon=_rect(2.0, 3.5, 6.0, 8.5), use="store", floor=0,
                 openings_area_sqm=3.5, confidence="low"),
            Room(polygon=_rect(6.0, 3.5, 10.5, 8.5), use="bedroom", floor=0,
                 openings_area_sqm=2.4, confidence="low"),
            Room(polygon=_rect(2.0, 8.5, 10.5, 13.5), use="other", floor=0,
                 openings_area_sqm=1.0, confidence="medium"),
        ],
    )
    return BuildingModel(
        source="raster",
        jurisdiction=_jurisdiction(plot_no="S06"),
        plot_polygon=plot,
        plot_area_sqm=250.0,
        zoned_area=envelope,
        edges=_edges(0, 0, 12.5, 20),
        floors=[ground],
        has_rwh=True,
        tree_count=1,
        assumptions=[
            "Synthetic low-confidence case: two room-use labels are confidence=low, simulating a "
            "raster/scanned source where OCR of the room tag was unreliable. Must route through "
            "the model-confirmation screen before any rule runs, per Confidence semantics in §5."
        ],
    )


STUBS = {
    "s01_clean_250": s01_clean_250,
    "s02_setback_rear": s02_setback_rear,
    "s03_far_over": s03_far_over,
    "s04_stilt4_500": s04_stilt4_500,
    "s05_no_zoning": s05_no_zoning,
    "s06_low_conf": s06_low_conf,
}


def main() -> None:
    STUB_DIR.mkdir(parents=True, exist_ok=True)
    for name, factory in STUBS.items():
        model = factory()
        out = STUB_DIR / f"{name}.model.json"
        out.write_text(json.dumps(model.model_dump(mode="json"), indent=2), encoding="utf-8")
        print(f"wrote {out.relative_to(pathlib.Path.cwd())}")


if __name__ == "__main__":
    main()
