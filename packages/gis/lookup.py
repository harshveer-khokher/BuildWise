"""GIS-layer lookups (CLAUDE.md §7 "GIS-layer checks (gis/, not from the drawing)"). Point-in-
polygon against layers under packages/gis/layers/, using shapely (CLAUDE.md §1 rule 3).

Scope, deliberately small (per the Track B task brief, this is lower priority than the rule
engine/first pack): only the periphery-control layer, and only as a placeholder. The Periphery
Control Rules 1959 (corpus/raw/periphery_control_rules_1959.pdf, doc_id
periphery_control_rules_1959) is legal text -- no GIS boundary data was supplied with it, so
`layers/periphery.geojson` is an explicitly-marked illustrative placeholder, not a digitized
periphery boundary. Every result from this module is `confidence: low` for that reason; nothing
here should ever be surfaced as a confident periphery violation. Coordinates are expected as
(longitude, latitude) WGS84 -- a plot's real-world location is not something the frozen
BuildingModel schema carries today (it only has a local metric plot_polygon), so wiring this
into the rule engine/report needs that geocoding step from Track A/D -- see INTEGRATION.md.
"""

from __future__ import annotations

import json
import pathlib

from shapely.geometry import Point, shape

LAYERS_DIR = pathlib.Path(__file__).resolve().parent / "layers"


def load_layer(name: str) -> list[dict]:
    """Load a GeoJSON FeatureCollection under layers/<name>.geojson. Returns the raw feature
    list (geometry + properties), not shapely objects, so callers can inspect `properties`
    (which carries the placeholder/status notice) before deciding how much to trust a hit."""
    path = LAYERS_DIR / f"{name}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"no GIS layer named {name!r} under {LAYERS_DIR}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("features", [])


def point_in_layer(lon: float, lat: float, layer_name: str) -> dict | None:
    """Return the first feature whose polygon contains (lon, lat), or None. Never asserts a
    numeric value or verdict -- CLAUDE.md §1 rule 1 -- callers decide what a hit means."""
    point = Point(lon, lat)
    for feature in load_layer(layer_name):
        geom = shape(feature["geometry"])
        if geom.contains(point):
            return feature
    return None


def check_periphery(lon: float, lat: float) -> dict:
    """Point-in-polygon against the (placeholder) periphery control layer.

    Returns a plain dict, not a Finding -- CLAUDE.md's Finding schema wants a citation resolved
    through a clause_id and this layer isn't tied to a specific numeric clause (Periphery Control
    Rules 1959 restricts development generally within the zone; the corpus's own REPORT.md flags
    this document's clause numbering as unreliable, see INTEGRATION.md). A caller in
    packages/rules or packages/report can wrap this into a Finding with
    ambiguity_class="missing_input" / ambiguity_class="discretionary" as appropriate once a real
    periphery boundary and a stable clause anchor are available.
    """
    hit = point_in_layer(lon, lat, "periphery")
    return {
        "inside_periphery_zone": hit is not None,
        "confidence": "low",
        "layer_status": "seed_unverified",
        "note": (
            "packages/gis/layers/periphery.geojson is an illustrative placeholder, not a "
            "digitized Periphery Control Act 1952 / Periphery Control Rules 1959 boundary. "
            "Never present this result as a confirmed periphery-zone determination."
        ),
        "feature": hit,
    }
