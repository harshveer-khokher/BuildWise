"""Writes the ONE required DXF ingest smoke file (CLAUDE.md §10.2):

    packages/cases/synth/s_smoke.dxf

Deliberately ugly, inconsistent layer names -- WALL, wall-ext, A-WALL-EXTR, BDRM-1, MBR, TOIL --
so nobody treats clean layer naming as the norm while building dxf_ingest.py. One file, not a
generator suite: the real problem is naming chaos across offices, which a generator can't
reproduce, only a hand-authored example of it can stand in for.

Units: header $INSUNITS set to 6 (metres) and all coordinates authored directly in metres, so
downstream mutation deltas (packages/cases/mutate.py) and any semantics.py assembly can treat
coordinates as already-metric without a unit-conversion step of its own.

Run directly to (re)generate the file:

    python packages/cases/gen_synth_smoke.py
"""

from __future__ import annotations

import pathlib

import ezdxf

SYNTH_DIR = pathlib.Path(__file__).resolve().parent / "synth"
OUT_PATH = SYNTH_DIR / "s_smoke.dxf"


def _closed(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return points if points[0] == points[-1] else points + [points[0]]


def build() -> ezdxf.document.Drawing:
    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()

    for name in ("WALL", "wall-ext", "A-WALL-EXTR", "BDRM-1", "MBR", "TOIL"):
        doc.layers.add(name=name)

    # Exterior wall outline: a 10m x 8m rectangular footprint, on the "A-WALL-EXTR" layer --
    # an office that abbreviates "exterior" as "EXTR" and prefixes with a BIM-ish "A-".
    exterior = _closed([(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)])
    msp.add_lwpolyline(exterior, dxfattribs={"layer": "A-WALL-EXTR", "closed": True})

    # An interior partition wall, on the plain "WALL" layer -- same office, different drafter,
    # no naming convention shared with the exterior layer above.
    msp.add_line((5.0, 0.0), (5.0, 8.0), dxfattribs={"layer": "WALL"})

    # A short stub wall for a porch/extension, on "wall-ext" -- easy to misread as "exterior"
    # again but is in fact a *third*, unrelated layer name for wall geometry in this same file.
    msp.add_line((10.0, 3.0), (11.5, 3.0), dxfattribs={"layer": "wall-ext"})
    msp.add_line((11.5, 3.0), (11.5, 5.0), dxfattribs={"layer": "wall-ext"})

    # Master bedroom, layer "MBR" (west half of the footprint).
    mbr = _closed([(0.2, 0.2), (4.8, 0.2), (4.8, 7.8), (0.2, 7.8)])
    msp.add_lwpolyline(mbr, dxfattribs={"layer": "MBR", "closed": True})
    msp.add_text(
        "MASTER BEDROOM", dxfattribs={"layer": "MBR", "height": 0.3}
    ).set_placement((1.0, 4.0))

    # A second bedroom, layer "BDRM-1" (northeast quadrant).
    bdrm1 = _closed([(5.2, 4.2), (9.8, 4.2), (9.8, 7.8), (5.2, 7.8)])
    msp.add_lwpolyline(bdrm1, dxfattribs={"layer": "BDRM-1", "closed": True})
    msp.add_text("BEDROOM 1", dxfattribs={"layer": "BDRM-1", "height": 0.3}).set_placement(
        (6.0, 6.0)
    )

    # Toilet, layer "TOIL" (southeast quadrant, small).
    toil = _closed([(5.2, 0.2), (7.5, 0.2), (7.5, 2.5), (5.2, 2.5)])
    msp.add_lwpolyline(toil, dxfattribs={"layer": "TOIL", "closed": True})
    msp.add_text("TOILET", dxfattribs={"layer": "TOIL", "height": 0.25}).set_placement((5.5, 1.0))

    return doc


def main() -> None:
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    doc = build()
    doc.saveas(str(OUT_PATH))
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
