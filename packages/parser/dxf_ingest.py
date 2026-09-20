"""DXF -> raw layer/entity geometry.

Track A (CLAUDE.md §4/§10.2). This module does the "read the file" step only: it returns plain
dicts of layers/polylines/lines/texts in the DXF's own coordinate units. It does NOT know about
BuildingModel -- semantics.py is where raw geometry becomes a schema object, per CLAUDE.md §10.1
("assembly is a required parser step, not an extra").

No arithmetic/geometry decisions here beyond reading coordinates back out of ezdxf entities
(CLAUDE.md §1 rule 3: geometry goes through shapely once we get to semantics.py / rules; this
module is pure I/O).

Layer-naming chaos (CLAUDE.md §10.2): real Mohali offices do not agree on layer names. This file
never assumes a clean convention -- `normalize_layer_name` maps known-messy variants
(`WALL`, `wall-ext`, `A-WALL-EXTR`, `BDRM-1`, `MBR`, `TOIL`, ...) onto a small set of semantic
categories via substring heuristics, and falls back to "unknown" rather than guessing wrong.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import ezdxf

# Ordered (keyword-set, category) rules. Order matters: more specific / less ambiguous keys are
# checked first so e.g. "MBR" (master bedroom) doesn't fall through to a generic bucket, and a
# layer like "A-WALL-EXTR" matches "wall" via substring even though it also contains "extr".
_LAYER_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("mbr", "m-bed", "master"), "room_bedroom"),
    (("bdrm", "bed"), "room_bedroom"),
    (("toil", "wc", "bath"), "room_bath"),
    (("kit",), "room_kitchen"),
    (("liv", "drw", "lounge", "foyer"), "room_living"),
    (("stair",), "room_stair"),
    (("gar", "park"), "room_garage"),
    (("stor",), "room_store"),
    (("wall",), "wall"),
    (("text", "annot", "dim", "note"), "annotation"),
]


def normalize_layer_name(raw_layer_name: str) -> str:
    """Map a real-world, possibly ugly DXF layer name onto a small semantic category.

    Case-insensitive substring match against a small keyword table. Returns "unknown" rather
    than guessing when nothing matches -- an unrecognised layer should surface as an
    `assumptions` note downstream (semantics.py), not silently vanish into a wrong bucket.
    """
    n = raw_layer_name.strip().lower().replace("_", "-")
    for keywords, category in _LAYER_KEYWORDS:
        if any(k in n for k in keywords):
            return category
    return "unknown"


def _polyline_points(entity: Any) -> tuple[list[list[float]], bool]:
    """Return (points, closed) for an LWPOLYLINE or old-style POLYLINE entity."""
    if entity.dxftype() == "LWPOLYLINE":
        pts = [[float(x), float(y)] for x, y in entity.get_points(format="xy")]
        closed = bool(entity.closed)
    else:  # POLYLINE
        pts = [
            [float(v.dxf.location.x), float(v.dxf.location.y)] for v in entity.vertices
        ]
        closed = bool(entity.is_closed)
    if closed and pts and pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    return pts, closed


def list_layout_names(dxf_path: str | Path) -> list[str]:
    """Names of every non-empty paperspace layout in this DXF, in tab order, excluding "Model"
    (modelspace) and any layout with zero entities.

    A single DWG/DXF commonly holds a whole sheet set as separate named layout tabs (e.g.
    "GROUND FLOOR PLAN", "ELEVATION FRONT", "SECTION A-A") rather than as separate uploaded
    files. Reading those tab names is the DXF/DWG analogue of reading a PDF's title block --
    real content the drafter wrote into the file itself, not a guess based on what the uploader
    happened to name the outer file (role_inference.py's filename fallback is lower-trust
    precisely because a filename is metadata about the upload, not the drawing).

    An empty tab is excluded rather than reported as "found but blank": `ezdxf.new()` (and,
    per ODA File Converter's own output, most real DWGs) always carries a default "Layout1"
    paperspace even when the drafter never used paperspace at all -- an empty layout carries no
    role signal and would just be noise to a caller trying to match tab names against keywords.
    """
    path = Path(dxf_path)
    doc = ezdxf.readfile(str(path))
    names: list[str] = []
    for name in doc.layouts.names_in_taborder():
        if name == "Model":
            continue
        layout = doc.layouts.get(name)
        if next(iter(layout), None) is not None:
            names.append(name)
    return names


def ingest_dxf(path: str | Path, layout: str | None = None) -> dict[str, Any]:
    """Parse a DXF file's modelspace (or, if `layout` is given, that named paperspace layout --
    see `list_layout_names`) into raw layer/entity data.

    Returns a plain dict (JSON-serialisable except for nothing -- all floats/strings/bools):

        {
          "path": str,
          "layout": str | None,        # which paperspace layout was read, None = modelspace
          "insunits": int,             # DXF $INSUNITS header code, 0 = unspecified
          "layers": {raw_name: {"category": str, "entity_count": int}},
          "polylines": [{"layer", "category", "closed", "points": [[x,y], ...]}],
          "lines": [{"layer", "category", "start": [x,y], "end": [x,y]}],
          "texts": [{"layer", "category", "text": str, "insert": [x,y]}],
        }

    Raises FileNotFoundError / ezdxf.DXFStructureError on a bad file -- callers should not
    catch-and-guess; a corrupt DXF is a case for `unknown`, not a silent empty model.
    """
    path = Path(path)
    doc = ezdxf.readfile(str(path))
    msp = doc.layouts.get(layout) if layout else doc.modelspace()
    insunits = int(doc.header.get("$INSUNITS", 0))

    layers: dict[str, dict[str, Any]] = {}
    polylines: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    dimensions_list: list[dict[str, Any]] = []

    def _touch_layer(raw_layer: str) -> str:
        category = normalize_layer_name(raw_layer)
        entry = layers.setdefault(raw_layer, {"category": category, "entity_count": 0})
        entry["entity_count"] += 1
        return category

    for entity in msp:
        raw_layer = entity.dxf.layer
        category = _touch_layer(raw_layer)
        dxftype = entity.dxftype()

        if dxftype in ("LWPOLYLINE", "POLYLINE"):
            points, closed = _polyline_points(entity)
            if len(points) >= 2:
                polylines.append(
                    {"layer": raw_layer, "category": category, "closed": closed, "points": points}
                )
        elif dxftype == "LINE":
            lines.append(
                {
                    "layer": raw_layer,
                    "category": category,
                    "start": [float(entity.dxf.start.x), float(entity.dxf.start.y)],
                    "end": [float(entity.dxf.end.x), float(entity.dxf.end.y)],
                }
            )
        elif dxftype in ("TEXT", "MTEXT"):
            text_value = entity.dxf.text if dxftype == "TEXT" else entity.text
            insert = entity.dxf.insert
            texts.append(
                {
                    "layer": raw_layer,
                    "category": category,
                    "text": str(text_value),
                    "insert": [float(insert.x), float(insert.y)],
                }
            )
        elif dxftype == "DIMENSION":
            # Collected now that extract_overall_height_m() (below) uses them -- previously
            # "out of scope for this hackathon build" per this function's own comment, which is
            # a real gap, not a deliberate omission (a DXF DIMENSION is a first-class,
            # machine-measured entity, unlike PDF's vector-reconstruction approach).
            try:
                measurement = entity.get_measurement()
            except Exception:
                measurement = None
            defpoint = entity.dxf.defpoint
            dimensions_list.append(
                {
                    "layer": raw_layer,
                    "category": category,
                    "measurement": float(measurement) if measurement is not None else None,
                    "defpoint": [float(defpoint.x), float(defpoint.y)],
                    "dimtype": int(entity.dxf.dimtype) if entity.dxf.hasattr("dimtype") else None,
                    "angle": float(entity.dxf.angle) if entity.dxf.hasattr("angle") else None,
                }
            )
        # Everything else (hatches, blocks, ...) is out of scope for this hackathon build
        # (CLAUDE.md §13 cut list spirit) -- it is simply not collected, not mis-collected.

    return {
        "path": str(path),
        "layout": layout,
        "insunits": insunits,
        "layers": layers,
        "polylines": polylines,
        "lines": lines,
        "texts": texts,
        "dimensions": dimensions_list,
    }


def closed_polylines_by_category(ingest: dict[str, Any], category: str) -> list[list[list[float]]]:
    """Convenience filter: closed-ring point lists for a given normalized category."""
    return [
        p["points"]
        for p in ingest["polylines"]
        if p["category"] == category and p["closed"]
    ]


# Standard AutoCAD $INSUNITS header codes actually seen on architectural drawings. 0
# ("unspecified") is deliberately absent -- treated as "assumed already metres" with a note
# rather than a silent guess, same principle as everywhere else numeric interpretation is
# uncertain in this project.
_INSUNITS_TO_METRES: dict[int, float] = {
    1: 0.0254,   # inches
    2: 0.3048,   # feet
    4: 0.001,    # millimeters
    5: 0.01,     # centimeters
    6: 1.0,      # meters
    10: 0.9144,  # yards
}

_VERTICAL_ANGLE_TOLERANCE_DEG = 5.0
_BRACKET_MAX_TOLERANCE_M = 0.02  # 2 cm slop for a chain-sum-vs-bracket match


def _is_vertical_dimension(angle: float | None) -> bool:
    if angle is None:
        return False
    return abs((angle % 180.0) - 90.0) <= _VERTICAL_ANGLE_TOLERANCE_DEG


def extract_overall_height_m(
    dxf_path: str | Path, layout: str | None = None
) -> tuple[float | None, list[dict] | None, str]:
    """DXF analogue of pdf_ingest.extract_overall_height_m(): reads a verified overall height
    off an elevation sheet's own DIMENSION entities -- never a heuristic line-count estimate.

    Unlike the PDF version, which has to RECONSTRUCT a dimension's value by clustering nearby
    vector line positions and OCR'd text tokens (a PDF has no semantic "this is a measurement"
    entity), a DXF DIMENSION entity IS the measurement: `get_measurement()` returns the exact
    value the CAD software itself computed when the drawing was made. This makes the DXF version
    both simpler and more reliable to trust numerically -- PROVIDED the source drawing actually
    used real DIMENSION entities rather than manually-drawn LINE+TEXT mimicking one (a real
    possibility in messier real-world offices, matching this project's own "layer naming chaos"
    experience). That fallback case is NOT handled here and returns (None, None, note) rather
    than guessing at a text-position heuristic with no CAD-verified backing.

    Untested against a real DWG/DXF elevation as of authoring (no sample was available) --
    verify against a real drawing before fully trusting it, the same way the PDF equivalent
    was verified against a real 33-foot building earlier in this project's development.

    Algorithm: collect every roughly-vertical DIMENSION entity's measurement (dimension-line
    angle within `_VERTICAL_ANGLE_TOLERANCE_DEG` of 90 degrees, or derived from defpoint/
    defpoint2 for aligned dimensions with no explicit angle). If one clearly dominates (>=1.5x
    the next largest), it's treated as the verified overall height directly. Otherwise, mirrors
    pdf_ingest's chain-vs-bracket verification: does some contiguous run of the smaller
    dimensions (ordered by position) sum to within `_BRACKET_MAX_TOLERANCE_M` of the largest?
    If so, the largest is confirmed as the real overall-height bracket. If neither holds, no
    height is returned -- declared uncertainty over fake precision (CLAUDE.md §1 rule 6).
    """
    path = Path(dxf_path)
    try:
        doc = ezdxf.readfile(str(path))
    except Exception as exc:
        return None, None, f"could not read this DXF file: {exc}"

    insunits = int(doc.header.get("$INSUNITS", 0))
    unit_to_m = _INSUNITS_TO_METRES.get(insunits, 1.0)
    unit_note_suffix = (
        f" ($INSUNITS={insunits} not recognised -- assumed already metres)"
        if insunits not in _INSUNITS_TO_METRES else ""
    )

    space = doc.layouts.get(layout) if layout else doc.modelspace()
    vertical: list[dict[str, Any]] = []
    for e in space.query("DIMENSION"):
        try:
            measurement = e.get_measurement()
        except Exception:
            continue
        if measurement is None or measurement <= 0:
            continue
        angle = float(e.dxf.angle) if e.dxf.hasattr("angle") else None
        if angle is None and e.dxf.hasattr("defpoint2"):
            dx = e.dxf.defpoint2.x - e.dxf.defpoint.x
            dy = e.dxf.defpoint2.y - e.dxf.defpoint.y
            if dx != 0 or dy != 0:
                angle = math.degrees(math.atan2(dy, dx))
        if not _is_vertical_dimension(angle):
            continue
        raw_text = e.dxf.text if e.dxf.hasattr("text") else ""
        vertical.append({
            "measurement_m": measurement * unit_to_m,
            "y": float(e.dxf.defpoint.y),
            "text": raw_text if raw_text and raw_text != "<>" else "",
        })

    if not vertical:
        return None, None, (
            "no vertical DIMENSION entities found on this sheet -- either no dimensions exist "
            "at all, or the drawing uses manually-drawn line+text 'fake' dimensions rather than "
            "real AutoCAD DIMENSION entities (not parsed here)." + unit_note_suffix
        )

    vertical.sort(key=lambda v: v["measurement_m"], reverse=True)
    largest = vertical[0]
    others = vertical[1:]

    if not others or largest["measurement_m"] >= 1.5 * others[0]["measurement_m"]:
        return (
            largest["measurement_m"],
            [{"text": largest["text"], "value_m": largest["measurement_m"]}],
            f"single dominant vertical dimension ({largest['measurement_m']:.3f} m) found -- "
            f"treated as the overall height directly." + unit_note_suffix,
        )

    others_by_pos = sorted(others, key=lambda v: v["y"])
    n = len(others_by_pos)
    best_match: list[dict[str, Any]] | None = None
    for i in range(n):
        running = 0.0
        for j in range(i, n):
            running += others_by_pos[j]["measurement_m"]
            if abs(running - largest["measurement_m"]) <= _BRACKET_MAX_TOLERANCE_M:
                if best_match is None or (j - i + 1) > len(best_match):
                    best_match = others_by_pos[i:j + 1]
            if running > largest["measurement_m"] + _BRACKET_MAX_TOLERANCE_M:
                break

    if best_match is not None:
        segments = [{"text": s["text"], "value_m": s["measurement_m"]} for s in best_match]
        return (
            largest["measurement_m"], segments,
            f"verified: {len(best_match)} smaller dimension(s) sum to within "
            f"{_BRACKET_MAX_TOLERANCE_M} m of the largest dimension "
            f"({largest['measurement_m']:.3f} m), confirming it as the overall height."
            + unit_note_suffix,
        )

    return None, None, (
        f"largest vertical dimension ({largest['measurement_m']:.3f} m) is not consistent with "
        f"the sum of any contiguous run of the other {len(others)} vertical dimension(s) found "
        "on this sheet -- not confident this is a verified overall-height bracket, so no height "
        "is returned." + unit_note_suffix
    )
