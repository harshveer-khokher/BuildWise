"""Deterministic classification into one of CLAUDE.md §8's seven ambiguity classes.

CLAUDE.md §1 rule 1 allows a model to *classify labels* -- it must not decide the class from
"vibes." Every function here is plain, inspectable Python: given a BuildingModel and/or a set
of Findings (and, for a couple of classes, small extra context an LLM never touches), it
either fires or it doesn't, and the evidence dict on the trigger says exactly why. An LLM only
ever sees the already-decided class plus its evidence, in dossier.py, to write prose.

The seven classes, and where the trigger lives here:

    extraction           -- Room.confidence == "low", or a Floor missing height_m
    missing_input        -- zoned_area / plot_area_sqm / plot_polygon / allotment_date is None
    instrument_conflict  -- two+ Findings for the same conceptual check disagree on citation.doc
                            and required value (CLAUDE.md §6.8: zoning plan vs base rules vs
                            circular vs NBC)
    vintage              -- allotment_date sits on either side of a regime cutoff date that is
                            actually present in the ingested clause text (e.g. the 1996 rules'
                            30-6-1997 cutoff in Rule 16(ii))
    discretionary        -- the governing clause text itself uses discretionary language
                            ("may be permitted", "at the discretion of", "competent authority")
    definitional         -- a stilt (or mumty/balcony) floor is present and the governing FAR/
                            height clause text has no explicit carve-out for it
    practice_divergence  -- an external objection-history record shows this office has
                            objected to a rule-compliant design before (needs real casework;
                            never inferred from the model alone)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from packages.schema.building_model import BuildingModel
from packages.schema.findings import Finding

AmbiguityClass = Literal[
    "extraction",
    "missing_input",
    "instrument_conflict",
    "vintage",
    "discretionary",
    "definitional",
    "practice_divergence",
]

_DISCRETIONARY_PHRASES = (
    "may be permitted",
    "may be relaxed",
    "at the discretion of",
    "in the discretion of",
    "competent authority may",
    "as may be approved by",
    "subject to the satisfaction of",
)


@dataclass
class AmbiguityTrigger:
    ambiguity_class: AmbiguityClass
    reason: str
    """Human-legible one-line reason, safe to show a developer debugging the classifier."""
    evidence: dict = field(default_factory=dict)
    """Deterministic facts that fired the trigger -- e.g. {"field": "zoned_area"}. Never
    contains prose written by a model; dossier.py's LLM narration reads this, it doesn't
    write it."""
    rule_id: str | None = None
    """Set when the trigger is tied to a specific Finding, e.g. for instrument_conflict."""


# ---------------------------------------------------------------------------
# missing_input
# ---------------------------------------------------------------------------

def classify_missing_input(model: BuildingModel) -> list[AmbiguityTrigger]:
    triggers: list[AmbiguityTrigger] = []
    if model.zoned_area is None:
        triggers.append(
            AmbiguityTrigger(
                ambiguity_class="missing_input",
                reason="No zoning plan traced for this plot; zoned_area is unset.",
                evidence={"field": "zoned_area", "value": None},
            )
        )
    if model.plot_area_sqm is None or model.plot_polygon is None:
        triggers.append(
            AmbiguityTrigger(
                ambiguity_class="missing_input",
                reason="Plot polygon/area not established; every area-ratio check (coverage, FAR) is blocked.",
                evidence={"field": "plot_area_sqm", "value": model.plot_area_sqm},
            )
        )
    if model.jurisdiction.allotment_date is None:
        triggers.append(
            AmbiguityTrigger(
                ambiguity_class="missing_input",
                reason="Allotment date unknown; which rule vintage applies cannot be determined.",
                evidence={"field": "jurisdiction.allotment_date", "value": None},
            )
        )
    return triggers


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------

def classify_extraction(model: BuildingModel) -> list[AmbiguityTrigger]:
    triggers: list[AmbiguityTrigger] = []
    for floor in model.floors:
        for idx, room in enumerate(floor.rooms):
            if room.confidence == "low":
                triggers.append(
                    AmbiguityTrigger(
                        ambiguity_class="extraction",
                        reason=f"Room use label on floor {floor.level}, room #{idx} has confidence=low.",
                        evidence={
                            "source": "low_confidence_label",
                            "floor": floor.level,
                            "room_index": idx,
                            "confidence": room.confidence,
                        },
                    )
                )
        if floor.height_m is None:
            triggers.append(
                AmbiguityTrigger(
                    ambiguity_class="extraction",
                    reason=f"Floor {floor.level} has no height_m -- not recoverable from a section sheet.",
                    evidence={"source": "missing_section_height", "floor": floor.level},
                )
            )
    return triggers


# ---------------------------------------------------------------------------
# instrument_conflict
# ---------------------------------------------------------------------------

def classify_instrument_conflict(
    findings: list[Finding], group_key: str = "title"
) -> list[AmbiguityTrigger]:
    """Group findings by a conceptual-check key (default: identical title -- a real engine
    should instead expose a stable `check_family` on Finding/rule pack; until then, matching
    title is the best legible proxy) and flag groups where two+ *binding* citations
    (doc/clause) disagree on the required value. A Citation.status == "conflict" (CLAUDE.md
    §6.5: transcription mismatch, rule disabled) is deliberately NOT folded in here -- that is
    a single-document transcription disagreement, not a cross-instrument conflict, and is
    classified as `extraction` instead (see classify_transcription_conflict)."""
    triggers: list[AmbiguityTrigger] = []
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        groups.setdefault(getattr(f, group_key), []).append(f)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        seen: dict[tuple[str, str], Finding] = {}
        for f in group:
            seen[(f.citation.doc, f.citation.clause)] = f
        distinct_sources = list(seen.values())
        if len(distinct_sources) < 2:
            continue
        required_values = {repr(f.required) for f in distinct_sources}
        if len(required_values) < 2:
            continue  # same value from multiple docs is corroboration, not conflict
        triggers.append(
            AmbiguityTrigger(
                ambiguity_class="instrument_conflict",
                reason=f"{len(distinct_sources)} binding instruments give different required values for '{key}'.",
                evidence={
                    "check": key,
                    "sources": [
                        {"doc": f.citation.doc, "clause": f.citation.clause, "required": f.required}
                        for f in distinct_sources
                    ],
                },
                rule_id=distinct_sources[0].rule_id,
            )
        )
    return triggers


def classify_transcription_conflict(findings: list[Finding]) -> list[AmbiguityTrigger]:
    """A single clause's own two-pass table transcription disagreed (CLAUDE.md §6.3/§6.5:
    Citation.status == 'conflict'). This is an extraction problem, not an instrument
    conflict."""
    triggers = []
    for f in findings:
        if f.citation.status == "conflict":
            triggers.append(
                AmbiguityTrigger(
                    ambiguity_class="extraction",
                    reason=f"Two-pass table transcription disagreed for {f.citation.doc}:{f.citation.clause}; rule disabled.",
                    evidence={"source": "transcription_conflict", "doc": f.citation.doc, "clause": f.citation.clause},
                    rule_id=f.rule_id,
                )
            )
    return triggers


# ---------------------------------------------------------------------------
# vintage
# ---------------------------------------------------------------------------

def classify_vintage(
    model: BuildingModel,
    cutoff_iso_date: str,
    regime_description: str,
    citation_doc: str,
    citation_clause: str,
) -> AmbiguityTrigger | None:
    """Trigger when a known regime-cutoff date exists in the ingested clause text and the
    plot's allotment_date determines which side of it applies. This is deliberately generic
    over the cutoff rather than hardcoding one, because the only cutoff actually present in
    the supplied 1996 rules corpus is Rule 16(ii)'s 30-6-1997 date (pre/post-1997-06-30
    allotments owe different charges under the amended FAR rule) -- callers (rule pack
    authoring, tests) pass that in explicitly rather than this module guessing at bylaw text
    it was never given."""
    if model.jurisdiction.allotment_date is None:
        return None  # that's missing_input, not vintage -- see classify_missing_input
    from datetime import date

    cutoff = date.fromisoformat(cutoff_iso_date)
    side = "before" if model.jurisdiction.allotment_date < cutoff else "on-or-after"
    return AmbiguityTrigger(
        ambiguity_class="vintage",
        reason=(
            f"Allotment date {model.jurisdiction.allotment_date.isoformat()} is {side} the "
            f"{cutoff_iso_date} regime cutoff for: {regime_description}."
        ),
        evidence={
            "allotment_date": model.jurisdiction.allotment_date.isoformat(),
            "cutoff_date": cutoff_iso_date,
            "side": side,
            "regime_description": regime_description,
            "citation": {"doc": citation_doc, "clause": citation_clause},
        },
    )


# ---------------------------------------------------------------------------
# discretionary
# ---------------------------------------------------------------------------

def classify_discretionary(
    clause_text: str, citation_doc: str, citation_clause: str, rule_id: str | None = None
) -> AmbiguityTrigger | None:
    lowered = clause_text.lower()
    for phrase in _DISCRETIONARY_PHRASES:
        if phrase in lowered:
            return AmbiguityTrigger(
                ambiguity_class="discretionary",
                reason=f"Clause text contains discretionary language ('{phrase}').",
                evidence={
                    "matched_phrase": phrase,
                    "citation": {"doc": citation_doc, "clause": citation_clause},
                },
                rule_id=rule_id,
            )
    return None


# ---------------------------------------------------------------------------
# definitional
# ---------------------------------------------------------------------------

def classify_definitional_stilt(
    model: BuildingModel, far_or_height_clause_text: str | None, citation_doc: str, citation_clause: str
) -> AmbiguityTrigger | None:
    """A stilt floor is present, and the governing FAR/height clause text (as actually
    ingested) has no explicit carve-out for it. This is the flagship example named in
    CLAUDE.md §14's demo narrative. `far_or_height_clause_text=None` also triggers (clause
    text unavailable to check at all is at least as ambiguous as clause text that's silent)."""
    stilt_floors = [f for f in model.floors if f.is_stilt]
    if not stilt_floors:
        return None
    text = (far_or_height_clause_text or "").lower()
    if "stilt" in text:
        return None  # clause explicitly addresses stilt -- not ambiguous
    return AmbiguityTrigger(
        ambiguity_class="definitional",
        reason=(
            f"{len(stilt_floors)} stilt floor(s) present (level(s) "
            f"{[f.level for f in stilt_floors]}); governing FAR/height clause text has no "
            "stilt carve-out."
        ),
        evidence={
            "stilt_levels": [f.level for f in stilt_floors],
            "clause_mentions_stilt": False,
            "citation": {"doc": citation_doc, "clause": citation_clause},
        },
    )


# ---------------------------------------------------------------------------
# practice_divergence
# ---------------------------------------------------------------------------

def classify_practice_divergence(
    rule_id: str, objection_history: list[dict]
) -> AmbiguityTrigger | None:
    """Fires only from real casework: a record that this office objected to a design that
    was, on paper, rule-compliant. Never inferred from the BuildingModel alone -- there is
    nothing in a single drawing that could tell you an office's unwritten practice."""
    matches = [
        h for h in objection_history
        if h.get("rule_id") == rule_id and h.get("was_compliant_on_paper") is True
    ]
    if not matches:
        return None
    return AmbiguityTrigger(
        ambiguity_class="practice_divergence",
        reason=(
            f"{len(matches)} prior case(s) show this office objecting to designs compliant "
            f"with {rule_id} on paper."
        ),
        evidence={"rule_id": rule_id, "prior_cases": matches},
        rule_id=rule_id,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def classify_all(
    model: BuildingModel,
    findings: list[Finding] | None = None,
    vintage_cutoffs: list[dict] | None = None,
    discretionary_clauses: list[dict] | None = None,
    definitional_far_clause: dict | None = None,
    objection_history: list[dict] | None = None,
) -> list[AmbiguityTrigger]:
    """Run every deterministic trigger and return everything that fired. Each optional
    argument supplies the small piece of *already-verified* corpus/casework context a given
    trigger needs; omit it and that trigger simply produces nothing (never a guess).

    vintage_cutoffs: list of {"cutoff_iso_date", "regime_description", "citation_doc", "citation_clause"}
    discretionary_clauses: list of {"clause_text", "citation_doc", "citation_clause", "rule_id"}
    definitional_far_clause: {"clause_text", "citation_doc", "citation_clause"}
    objection_history: list of {"rule_id", "was_compliant_on_paper", ...}
    """
    triggers: list[AmbiguityTrigger] = []
    triggers += classify_missing_input(model)
    triggers += classify_extraction(model)
    if findings:
        triggers += classify_instrument_conflict(findings)
        triggers += classify_transcription_conflict(findings)
        if objection_history:
            rule_ids = {f.rule_id for f in findings}
            for rid in rule_ids:
                t = classify_practice_divergence(rid, objection_history)
                if t:
                    triggers.append(t)
    for cutoff in vintage_cutoffs or []:
        t = classify_vintage(model, **cutoff)
        if t:
            triggers.append(t)
    for clause in discretionary_clauses or []:
        t = classify_discretionary(**clause)
        if t:
            triggers.append(t)
    if definitional_far_clause:
        t = classify_definitional_stilt(
            model,
            definitional_far_clause.get("clause_text"),
            definitional_far_clause["citation_doc"],
            definitional_far_clause["citation_clause"],
        )
        if t:
            triggers.append(t)
    return triggers
