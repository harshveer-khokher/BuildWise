"""Ambiguity dossiers. CLAUDE.md §8: "That justification paragraph is the thing people would
pay for. Give it real time."

A dossier turns a classified AmbiguityTrigger (classifier.py -- deterministic) into:
  - both readings, in plain architect language
  - which reading is safer to submit under, and why
  - the exact document/clause to carry as proof
  - a submission-ready justification paragraph

Grounding discipline (CLAUDE.md §1 rule 1, §9): every number in a dossier -- floor areas,
FAR under each reading, excess area -- is computed here in plain Python via shapely, from the
BuildingModel and the citation/clause data the caller already verified. The narration layer
(``narrate_fn``, defaulting to hand-written templates below) receives only that finished
``facts`` dict and phrases it; it never invents a document, a clause number, or a number of
its own. Swapping in a live LLM call (e.g. an Anthropic Messages API call inside
``packages/api``) later is a matter of passing a different ``narrate_fn`` with the same
signature -- the facts contract does not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from shapely.geometry import Polygon

from packages.schema.building_model import BuildingModel
from .classifier import AmbiguityTrigger

NarrateFn = Callable[[dict], str]


@dataclass
class Reading:
    label: str
    description: str
    outcome: str | None = None
    citation: dict | None = None


@dataclass
class Dossier:
    ambiguity_class: str
    rule_id: str | None
    title: str
    readings: list[Reading]
    safer_reading_label: str | None
    safer_reason: str
    proof_document: dict | None
    justification_paragraph: str
    facts: dict = field(default_factory=dict)
    is_confirmation_flag: bool = False
    """True for the lightweight low-confidence-label case (see build_dossier) -- routed to
    the model-confirmation UI, not a GMADA-submission dossier."""


def _floor_area_sqm(floor) -> float:
    return abs(Polygon(floor.footprint).area)


# ---------------------------------------------------------------------------
# Default (template) narrators -- hand-written once, grounded strictly in `facts`.
# ---------------------------------------------------------------------------

def _narrate_confirmation_flag(facts: dict) -> str:
    return (
        f"Room use on floor {facts['floor']}, room #{facts['room_index']} was extracted with "
        "low confidence and has not been confirmed. This does not yet constitute a rule "
        "finding -- confirm or correct the label on the model-confirmation screen before "
        "any rule check that depends on room use (minimum area, light/ventilation ratio) is "
        "treated as reliable."
    )


def _narrate_missing_input(facts: dict) -> str:
    field_name = facts["field"]
    if field_name == "zoned_area":
        return (
            "The zoned area for this plot has not been traced from a PUDA zoning plan. "
            "Containment of the proposed footprint against the zoned envelope -- the "
            "flagship check this tool performs -- cannot be run without it, and this report "
            "records that check as unresolved rather than as a pass. Treating an untraced "
            "zoning plan as a pass would be indistinguishable, to the submitting architect, "
            "from an actual compliance guarantee it cannot offer; the correct next step is to "
            "obtain the plot's zoning plan (or Architectural Control Sheet, where "
            "applicable) from GMADA and trace it before this check is relied upon."
        )
    if field_name == "plot_area_sqm":
        return (
            "Plot area could not be established from the supplied sheets. Every ratio-based "
            "check that depends on it -- ground coverage, floor area ratio -- is unresolved "
            "until a site plan sheet establishing the plot polygon is supplied; those figures "
            "are not approximated from the visible building footprint."
        )
    return (
        "The plot's allotment date is not recorded. Several rules in the applicable pack are "
        "vintage-dependent (they apply differently, or not at all, depending on when the plot "
        "was allotted); until the allotment date is supplied, this report cannot state which "
        "vintage of the rule governs and marks the relevant checks unresolved."
    )


def _narrate_definitional_stilt(facts: dict) -> str:
    plot = facts["plot_area_sqm"]
    area_excl = facts["covered_area_excl_stilt_sqm"]
    area_incl = facts["covered_area_incl_stilt_sqm"]
    far_excl = facts["far_excl_stilt"]
    far_incl = facts["far_incl_stilt"]
    cap = facts.get("far_cap")
    cap_citation = facts.get("far_cap_citation") or {}
    doc = cap_citation.get("doc", "the applicable rule pack")
    clause = cap_citation.get("clause", "the governing FAR clause")

    lines = [
        (
            f"This design places an open, columns-only stilt storey below {facts['upper_floor_count']} "
            f"upper floors on a {plot:.0f} sqm plot. Whether that stilt storey's footprint counts "
            f"toward covered area for floor area ratio purposes is not settled by the text on file: "
            f"{doc} clause {clause} defines floor area ratio for residential plotted development "
            "by plot-size band but does not mention a stilt, or any other open, non-habitable "
            "ground storey, anywhere in its text."
        ),
        (
            f"Reading A -- exclude the stilt storey (treat it as the open parking storey the "
            "'stilt+4' concession common in more recent GMADA/PUDA practice contemplates, even "
            f"though that concession is not itself present in the rule text on file): covered "
            f"area is {area_excl:.1f} sqm, giving a floor area ratio of {far_excl:.3f}."
        ),
        (
            f"Reading B -- include the stilt storey (the literal reading of the clause, which "
            f"defines the ratio without any stilt carve-out): covered area is {area_incl:.1f} "
            f"sqm, giving a floor area ratio of {far_incl:.3f}."
        ),
    ]
    if cap is not None:
        excess_excl = max(0.0, far_excl - cap) * plot
        excess_incl = max(0.0, far_incl - cap) * plot
        lines.append(
            f"Against the {cap:.2f} cap that applies to this plot's size band under {doc} "
            f"clause {clause}, Reading A leaves {excess_excl:.1f} sqm of covered area in "
            f"excess and Reading B leaves {excess_incl:.1f} sqm in excess -- both readings "
            "are over the cap on the numbers as drawn, so the choice between them changes the "
            "magnitude of the shortfall and which remedy (footprint reduction, chargeable-FAR "
            "purchase, or compounding) is realistic, not whether a violation exists at all."
        )
    lines.append(
        "Because no circular or amendment codifying a stilt exclusion is present in the "
        "verified corpus for this jurisdiction, Reading B -- the literal, no-carve-out reading "
        "-- is the safer basis for this submission: it does not rely on an unwritten "
        "concession an examining officer may or may not extend, and it does not understate the "
        "covered area on record. Reading A remains worth raising, in writing, as the basis for "
        "a discretionary relaxation request if the office's current practice is understood to "
        "allow it -- but it should be argued for explicitly, not assumed."
    )
    return " ".join(lines)


def _narrate_vintage(facts: dict) -> str:
    return (
        f"The plot's allotment date ({facts['allotment_date']}) falls {facts['side']} the "
        f"{facts['cutoff_date']} cutoff in {facts['citation']['doc']} clause "
        f"{facts['citation']['clause']} governing {facts['regime_description']}. On the date "
        "recorded, the post-cutoff regime is the one that applies to this plot; the amount "
        "actually payable or required under that regime is a separate, currently unverified "
        "figure and is not stated here as a number."
    )


def _narrate_discretionary(facts: dict) -> str:
    return (
        f"{facts['citation']['doc']} clause {facts['citation']['clause']} conditions this "
        f"requirement on discretionary language (\"{facts['matched_phrase']}\"), rather than "
        "stating a fixed, self-executing rule. Reading A treats the discretionary relief as "
        "already granted and proceeds on that basis. Reading B treats it as not granted until "
        "the competent authority records it in writing. Reading B is the safer basis for a "
        "pre-submission check: a deemed grant of discretion cannot be evidenced later if the "
        "authority takes the stricter reading, whereas a written relaxation obtained up front "
        "resolves the ambiguity either way. This is the clause to attach a written request "
        "against rather than to assume relief from."
    )


def _narrate_instrument_conflict(facts: dict) -> str:
    sources = facts["sources"]
    parts = [
        f"{s['doc']} clause {s['clause']} states a required value of {s['required']!r}"
        for s in sources
    ]
    return (
        f"For {facts['check']}, the instruments on file disagree: " + "; while ".join(parts) + ". "
        "Per the precedence a plot-specific zoning plan or Architectural Control Sheet outranks "
        "a circular or amendment, which in turn outranks the base rules or byelaws, which "
        "outrank a reference document such as the NBC. This report applies whichever source "
        "that precedence designates, but records both values and both citations rather than "
        "discarding the one it did not apply -- an examining officer working from the other "
        "instrument would otherwise see a discrepancy this report never disclosed."
    )


def _narrate_practice_divergence(facts: dict) -> str:
    return (
        f"{facts['rule_id']} is satisfied by the design as drawn, on the text of the rule. "
        f"This office's own casework, however, shows {facts['prior_case_count']} prior "
        "instance(s) of objecting to designs that were compliant with this same rule on paper. "
        "The safer position for submission is to preempt that objection in writing -- citing "
        "the rule text that supports the design -- rather than to rely on textual compliance "
        "alone and treat a repeat objection as unlikely."
    )


_DEFAULT_NARRATORS: dict[str, NarrateFn] = {
    "missing_input": _narrate_missing_input,
    "definitional": _narrate_definitional_stilt,
    "vintage": _narrate_vintage,
    "discretionary": _narrate_discretionary,
    "instrument_conflict": _narrate_instrument_conflict,
    "practice_divergence": _narrate_practice_divergence,
}


# ---------------------------------------------------------------------------
# build_dossier
# ---------------------------------------------------------------------------

def build_dossier(
    trigger: AmbiguityTrigger,
    model: BuildingModel,
    *,
    far_cap: float | None = None,
    narrate_fn: NarrateFn | None = None,
) -> Dossier:
    """Build a full dossier for a classified trigger. `far_cap` is only consulted for
    `definitional` (stilt) triggers, to show excess area under both readings; pass the
    verified (or seed_unverified) numeric cap from the rule pack -- this function never
    invents one.

    `narrate_fn`, if given, replaces the hand-written default template for this
    ambiguity_class -- e.g. wire in a real LLM call later. It receives exactly the `facts`
    dict this function assembles and must return prose grounded only in it.
    """
    # --- extraction / low-confidence-label: lightweight confirmation flag, not a GMADA dossier ---
    if trigger.ambiguity_class == "extraction" and trigger.evidence.get("source") == "low_confidence_label":
        facts = dict(trigger.evidence)
        narrate = narrate_fn or _narrate_confirmation_flag
        return Dossier(
            ambiguity_class=trigger.ambiguity_class,
            rule_id=trigger.rule_id,
            title="Unconfirmed room-use label",
            readings=[
                Reading(
                    label="Confirm on-screen",
                    description="Route to the model-confirmation UI for a one-click confirm/correct.",
                )
            ],
            safer_reading_label="Confirm on-screen",
            safer_reason="Not a legal ambiguity -- a label uncertainty the confirmation screen resolves directly.",
            proof_document=None,
            justification_paragraph=narrate(facts),
            facts=facts,
            is_confirmation_flag=True,
        )

    if trigger.ambiguity_class == "extraction":
        facts = dict(trigger.evidence)
        return Dossier(
            ambiguity_class=trigger.ambiguity_class,
            rule_id=trigger.rule_id,
            title="Dimension not reliably extractable",
            readings=[
                Reading("Report unknown", "Do not assume a value; the affected check is status=unknown.", outcome="unknown"),
                Reading("Assume a typical value", "Guess a plausible figure from convention.", outcome="rejected"),
            ],
            safer_reading_label="Report unknown",
            safer_reason="CLAUDE.md §1: no code or model may assert a number it did not reliably read.",
            proof_document=None,
            justification_paragraph=(narrate_fn or (lambda f: trigger.reason))(facts),
            facts=facts,
        )

    if trigger.ambiguity_class == "missing_input":
        facts = dict(trigger.evidence)
        narrate = narrate_fn or _DEFAULT_NARRATORS["missing_input"]
        return Dossier(
            ambiguity_class=trigger.ambiguity_class,
            rule_id=trigger.rule_id,
            title=f"Missing input: {facts['field']}",
            readings=[
                Reading("Assume compliant", "Treat the missing input as if it posed no problem.", outcome="rejected"),
                Reading("Report unknown", "Withhold the dependent check(s) until the input is supplied.", outcome="unknown"),
            ],
            safer_reading_label="Report unknown",
            safer_reason="CLAUDE.md §5: missing zoning plan (or other required input) is status=unknown, never pass.",
            proof_document=None,
            justification_paragraph=narrate(facts),
            facts=facts,
        )

    if trigger.ambiguity_class == "definitional":
        stilt_levels = set(trigger.evidence.get("stilt_levels", []))
        area_excl = sum(_floor_area_sqm(f) for f in model.floors if f.level not in stilt_levels)
        area_incl = sum(_floor_area_sqm(f) for f in model.floors)
        plot_area = model.plot_area_sqm or 0.0
        far_excl = area_excl / plot_area if plot_area else 0.0
        far_incl = area_incl / plot_area if plot_area else 0.0
        citation = trigger.evidence.get("citation", {})
        facts = {
            "plot_area_sqm": plot_area,
            "covered_area_excl_stilt_sqm": area_excl,
            "covered_area_incl_stilt_sqm": area_incl,
            "far_excl_stilt": far_excl,
            "far_incl_stilt": far_incl,
            "far_cap": far_cap,
            "far_cap_citation": citation,
            "upper_floor_count": len([f for f in model.floors if f.level not in stilt_levels]),
        }
        narrate = narrate_fn or _DEFAULT_NARRATORS["definitional"]
        return Dossier(
            ambiguity_class=trigger.ambiguity_class,
            rule_id=trigger.rule_id,
            title="Does the stilt storey count toward FAR?",
            readings=[
                Reading(
                    "Exclude stilt (stilt+4 concession)",
                    f"Covered area {area_excl:.1f} sqm, FAR {far_excl:.3f}.",
                    citation=None,
                ),
                Reading(
                    "Include stilt (literal clause reading)",
                    f"Covered area {area_incl:.1f} sqm, FAR {far_incl:.3f}.",
                    citation=citation or None,
                ),
            ],
            safer_reading_label="Include stilt (literal clause reading)",
            safer_reason="No stilt-exclusion circular is in the verified corpus for this jurisdiction; the literal reading needs no unwritten concession.",
            proof_document=citation or None,
            justification_paragraph=narrate(facts),
            facts=facts,
        )

    if trigger.ambiguity_class == "vintage":
        facts = dict(trigger.evidence)
        narrate = narrate_fn or _DEFAULT_NARRATORS["vintage"]
        return Dossier(
            ambiguity_class=trigger.ambiguity_class,
            rule_id=trigger.rule_id,
            title=f"Which vintage regime applies: {facts['regime_description']}",
            readings=[
                Reading("Pre-cutoff regime", f"Allotment before {facts['cutoff_date']}."),
                Reading("Post-cutoff regime", f"Allotment on or after {facts['cutoff_date']}."),
            ],
            safer_reading_label="Post-cutoff regime" if facts["side"] == "on-or-after" else "Pre-cutoff regime",
            safer_reason="Determined directly from the recorded allotment date against the clause's own cutoff.",
            proof_document=facts.get("citation"),
            justification_paragraph=narrate(facts),
            facts=facts,
        )

    if trigger.ambiguity_class == "discretionary":
        facts = dict(trigger.evidence)
        narrate = narrate_fn or _DEFAULT_NARRATORS["discretionary"]
        return Dossier(
            ambiguity_class=trigger.ambiguity_class,
            rule_id=trigger.rule_id,
            title="Discretionary clause language",
            readings=[
                Reading("Relief assumed granted", "Proceed as if the competent authority has already relaxed the requirement.", outcome="rejected"),
                Reading("Relief not assumed", "Treat the requirement as binding absent a written relaxation.", outcome="conservative"),
            ],
            safer_reading_label="Relief not assumed",
            safer_reason="A deemed discretionary grant cannot be evidenced at objection stage if the authority disagrees.",
            proof_document=facts.get("citation"),
            justification_paragraph=narrate(facts),
            facts=facts,
        )

    if trigger.ambiguity_class == "instrument_conflict":
        facts = dict(trigger.evidence)
        narrate = narrate_fn or _DEFAULT_NARRATORS["instrument_conflict"]
        sources = facts["sources"]
        return Dossier(
            ambiguity_class=trigger.ambiguity_class,
            rule_id=trigger.rule_id,
            title=f"Conflicting instruments for {facts['check']}",
            readings=[
                Reading(f"{s['doc']} clause {s['clause']}", f"Required value: {s['required']!r}", citation={"doc": s["doc"], "clause": s["clause"]})
                for s in sources
            ],
            safer_reading_label=None,
            safer_reason="Resolved by precedence (zoning/circular > base rules/byelaws > reference), not by which value is numerically stricter.",
            proof_document={"sources": sources},
            justification_paragraph=narrate(facts),
            facts=facts,
        )

    if trigger.ambiguity_class == "practice_divergence":
        facts = dict(trigger.evidence)
        facts["prior_case_count"] = len(facts.get("prior_cases", []))
        narrate = narrate_fn or _DEFAULT_NARRATORS["practice_divergence"]
        return Dossier(
            ambiguity_class=trigger.ambiguity_class,
            rule_id=trigger.rule_id,
            title=f"Office practice diverges from the written rule for {facts['rule_id']}",
            readings=[
                Reading("Written rule", "The design is compliant with the rule as written.", outcome="pass"),
                Reading("Office practice", "This office has objected to compliant designs before.", outcome="risk"),
            ],
            safer_reading_label="Office practice",
            safer_reason="Determines actual resubmission risk regardless of textual compliance.",
            proof_document=None,
            justification_paragraph=narrate(facts),
            facts=facts,
        )

    raise ValueError(f"No dossier builder for ambiguity_class={trigger.ambiguity_class!r}")
