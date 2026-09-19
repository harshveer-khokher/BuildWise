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


def ingest_dxf(path: str | Path) -> dict[str, Any]:
    """Parse a DXF file's modelspace into raw layer/entity data.

    Returns a plain dict (JSON-serialisable except for nothing -- all floats/strings/bools):

        {
          "path": str,
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
    msp = doc.modelspace()
    insunits = int(doc.header.get("$INSUNITS", 0))

    layers: dict[str, dict[str, Any]] = {}
    polylines: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []

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
        # Everything else (hatches, blocks, dimensions, ...) is out of scope for this hackathon
        # build (CLAUDE.md §13 cut list spirit) -- it is simply not collected, not mis-collected.

    return {
        "path": str(path),
        "insunits": insunits,
        "layers": layers,
        "polylines": polylines,
        "lines": lines,
        "texts": texts,
    }


def closed_polylines_by_category(ingest: dict[str, Any], category: str) -> list[list[list[float]]]:
    """Convenience filter: closed-ring point lists for a given normalized category."""
    return [
        p["points"]
        for p in ingest["polylines"]
        if p["category"] == category and p["closed"]
    ]
