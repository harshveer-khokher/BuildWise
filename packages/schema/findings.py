"""Frozen contract, CLAUDE.md §5. Findings are the only output surface for a rule check —
every field here exists so that no downstream consumer (solver, report, web) ever needs to
re-derive a number or a citation. status="unknown" is a first-class outcome: missing zoning
plan or missing section-sheet height means unknown, never pass (CLAUDE.md §5, §10.1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Point = list[float]
Ring = list[Point]


class Citation(BaseModel):
    doc: str
    """doc_id from corpus/MANIFEST.json, e.g. "puda_building_rules_1996"."""
    clause: str
    """clause number, e.g. "7.3.2" — resolves through clauses.jsonl, never a bare page number."""
    version: str
    url: str | None = None
    status: Literal["verified", "seed_unverified", "conflict", "not_stated"] = "seed_unverified"
    """Carried from the rule pack (CLAUDE.md §6.5) so the report can show confidence per-finding."""


class Remedy(BaseModel):
    kind: Literal[
        "geometric_edit",
        "purchase_chargeable_far",
        "compounding",
        "noc_route",
        "zoning_revision_request",
    ]
    description: str
    """Architect-facing narration. Never contains a number the solver didn't produce (CLAUDE.md §9)."""
    area_lost_sqm: float | None = None
    edit_ref: dict | None = None
    """Machine-checkable parameters of the edit the solver applied, e.g.
    {"op": "shrink_wall", "edge": "rear", "delta_m": 0.4}."""
    verified: bool = False
    """True only if the solver re-ran the full rule pack on the edited model and nothing regressed."""


class Finding(BaseModel):
    rule_id: str
    status: Literal["violation", "ambiguity", "advisory", "pass", "unknown"]
    severity: Literal["blocking", "major", "minor"]
    title: str
    citation: Citation
    """No citation → no finding (CLAUDE.md §1 rule 2). Always present, even on status=unknown."""
    observed: float | str | None = None
    required: float | str | None = None
    geometry_ref: Ring | None = None
    """What to highlight on the overlay. None for non-geometric findings (e.g. missing RWH)."""
    compoundable: bool = False
    ambiguity_class: Literal[
        "extraction",
        "missing_input",
        "instrument_conflict",
        "vintage",
        "discretionary",
        "definitional",
        "practice_divergence",
    ] | None = None
    """Set only when status="ambiguity" (CLAUDE.md §8)."""
    remedies: list[Remedy] = Field(default_factory=list)
