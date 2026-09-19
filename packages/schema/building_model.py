"""Frozen contract. Written in Stage 0 per CLAUDE.md §5 — do not change without announcing it
to all four tracks first; a schema edit blocks parser, rules, solver and report simultaneously.

Units: metres and square metres everywhere (CLAUDE.md §1 rule 4). Convert to sq yards
(1 sq m = 1.196 sq yd) only at the display layer (report/, web/) — never inside this package
or inside rules/solver.

Polygons are closed rings: list[[x, y], ...] with the first and last point equal, in the
BuildingModel's local metric coordinate system (established by the site/zoning sheet during
assembly). Every consumer should immediately wrap these in shapely.geometry.Polygon rather than
hand-rolling geometry (CLAUDE.md §1 rule 3).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]
"""low → must be user-confirmed on the model-confirmation screen before any rule runs."""

Point = list[float]  # [x, y] in metres
Ring = list[Point]  # closed polygon ring


class Jurisdiction(BaseModel):
    authority: Literal["GMADA", "MC_KHARAR", "MC_ZIRAKPUR", "UNKNOWN"]
    sector: str | None = None
    plot_no: str | None = None
    allotment_date: date | None = None
    """Decides which rule vintage applies (see ambiguity_class: vintage, CLAUDE.md §8)."""
    rule_pack: str
    """e.g. "puda_building_rules_1996" — must match a pack id under packages/rules/packs/."""


class Edge(BaseModel):
    line: list[Point]
    faces_road: bool
    road_width_m: float | None = None
    role: Literal["front", "rear", "side_a", "side_b", "unknown"]


class Room(BaseModel):
    polygon: Ring
    use: Literal[
        "bedroom", "living", "kitchen", "bath", "wc", "store", "stair", "garage", "other"
    ]
    floor: int
    openings_area_sqm: float
    """For light/ventilation ratio: openings_area_sqm / room floor area."""
    confidence: Confidence


class Floor(BaseModel):
    level: int
    """-1 basement, 0 stilt/ground, 1..n upper floors."""
    is_stilt: bool
    footprint: Ring
    height_m: float | None = None
    """Preferably from the section sheet. May also come from an elevation sheet's own printed
    overall-height dimension (packages.parser.pdf_ingest.extract_overall_height_m) -- a narrow,
    confirmed exception to "never from elevations" for that one specific extraction, verified
    against a real building's as-built height (see INTEGRATION.md). Never from a heuristic
    line-count estimate; that remains cross-check-only."""
    rooms: list[Room] = Field(default_factory=list)


class BuildingModel(BaseModel):
    source: Literal["dxf", "vector_pdf", "raster"]
    jurisdiction: Jurisdiction
    plot_polygon: Ring | None = None
    plot_area_sqm: float | None = None
    zoned_area: Ring | None = None
    """None → the flagship containment check returns status=unknown, never pass (CLAUDE.md §5)."""
    edges: list[Edge] = Field(default_factory=list)
    floors: list[Floor] = Field(default_factory=list)
    projections: list[dict] = Field(default_factory=list)
    """Each: {"type": "chajja" | "balcony", "polygon": Ring, "floor": int}."""
    courtyards: list[Ring] = Field(default_factory=list)
    mumty: dict | None = None
    parking_bays: list[dict] = Field(default_factory=list)
    boundary_wall_height_m: float | None = None
    has_rwh: bool = False
    tree_count: int = 0
    assumptions: list[str] = Field(default_factory=list)
    """Printed verbatim on the report. Every silent inference the parser made goes here."""
