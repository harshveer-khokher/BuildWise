"""Non-geometric remedies. CLAUDE.md §9 point 5.

Where a rule allows it, a violation can be addressed without redrawing: buying chargeable
FAR, compounding (paying a fee to regularise rather than redraw), an NOC route (for
GIS/periphery-adjacent constraints), or asking PUDA/GMADA to revise the zoning plan itself.

These map onto Remedy.kind in packages/schema/findings.py: purchase_chargeable_far,
compounding, noc_route, zoning_revision_request (geometric_edit is repair.py's concern).

Hard rule (CLAUDE.md §1 rule 1, and this task's own instruction): a Remedy.description is
architect-facing prose, but it must never state a number this module didn't itself compute
from the Finding it was given. Where the underlying policy document (a compounding/composition
policy PDF, a chargeable-FAR circular) was not supplied to the corpus -- true as of this build,
per INTEGRATION.md's Stage 0 handoff -- the description says so plainly instead of inventing a
fee schedule or a percentage cap. Fake precision is worse than declared uncertainty
(CLAUDE.md §1 rule 6).
"""

from __future__ import annotations

from packages.schema.building_model import BuildingModel
from packages.schema.findings import Finding, Remedy


def _is_numeric(value: float | str | None) -> bool:
    return isinstance(value, (int, float))


def _excess(finding: Finding) -> float | None:
    """observed - required, only when both are numbers and observed exceeds required.
    Returns None (never a guess) when either value is missing or non-numeric."""
    if _is_numeric(finding.observed) and _is_numeric(finding.required):
        excess = float(finding.observed) - float(finding.required)  # type: ignore[arg-type]
        return excess if excess > 0 else None
    return None


def _rule_concerns(finding: Finding, *keywords: str) -> bool:
    text = f"{finding.rule_id} {finding.title}".lower()
    return any(k in text for k in keywords)


def purchase_chargeable_far(finding: Finding, model: BuildingModel) -> Remedy | None:
    """Applicable to FAR-shaped violations. CLAUDE.md glossary: 'Chargeable FAR: Recent
    policy allows buying extra FAR at a fee tied to collector rate.' No chargeable-FAR
    circular has been ingested into the corpus yet (see INTEGRATION.md Stage 0 handoff) --
    so this remedy names the mechanism and, where computable, the extra FAR area a purchase
    would need to cover, but never a fee, a rate, or an eligibility cap that isn't backed by
    a citation."""
    if not _rule_concerns(finding, "far", "floor area ratio"):
        return None
    excess = _excess(finding)
    excess_area_sqm = None
    if excess is not None and model.plot_area_sqm:
        excess_area_sqm = round(excess * model.plot_area_sqm, 2)

    if excess_area_sqm is not None:
        description = (
            f"The floor area ratio exceeds the applicable cap by {excess:.3f} "
            f"(about {excess_area_sqm:.1f} sqm of covered area on this {model.plot_area_sqm:.0f} "
            "sqm plot). GMADA's chargeable-FAR policy allows buying additional FAR at a fee "
            "tied to the collector rate; whether this excess falls within a purchasable band, "
            "and at what fee, is not something this tool can state -- no chargeable-FAR "
            "circular has been verified into the rule corpus yet. Confirm the current rate "
            "and eligibility with GMADA before relying on this route."
        )
    else:
        description = (
            "This is an FAR violation. GMADA's chargeable-FAR policy allows buying additional "
            "FAR at a fee tied to the collector rate, but the excess area could not be computed "
            "from this finding's observed/required values, and no chargeable-FAR circular has "
            "been verified into the rule corpus yet. Confirm applicability and fee with GMADA "
            "before relying on this route."
        )
    return Remedy(kind="purchase_chargeable_far", description=description, area_lost_sqm=None, edit_ref=None, verified=False)


def compounding(finding: Finding, model: BuildingModel) -> Remedy | None:
    """Applicable when the rule pack has marked this specific finding compoundable
    (CLAUDE.md glossary: paying a prescribed fee to regularise a violation instead of
    redrawing; some offences are compoundable, some are not -- product-critical distinction,
    so this remedy only fires when Finding.compoundable is True, never as a default)."""
    if not finding.compoundable:
        return None
    excess = _excess(finding)
    if excess is not None:
        description = (
            f"This violation ({finding.title}) is flagged compoundable under the applicable "
            f"rule ({finding.citation.doc}, clause {finding.citation.clause}). The observed "
            f"excess over the permitted value is {excess:.3f} in the finding's own units. "
            "PUDA's composition policy allows regularising some offences on payment of a "
            "prescribed fee instead of redrawing; the fee schedule itself is not in the "
            "verified corpus, so it must be confirmed with GMADA rather than assumed here."
        )
    else:
        description = (
            f"This violation ({finding.title}) is flagged compoundable under the applicable "
            f"rule ({finding.citation.doc}, clause {finding.citation.clause}). PUDA's "
            "composition policy allows regularising some offences on payment of a prescribed "
            "fee instead of redrawing; the fee schedule is not in the verified corpus, so it "
            "must be confirmed with GMADA rather than assumed here."
        )
    return Remedy(kind="compounding", description=description, area_lost_sqm=None, edit_ref=None, verified=False)


def noc_route(finding: Finding, model: BuildingModel) -> Remedy | None:
    """Applicable to GIS-layer-adjacent constraints (periphery control, defence
    establishment radius, highway control lines -- CLAUDE.md §7's GIS-layer checks). These
    are typically resolved by an NOC from the relevant authority rather than by redrawing."""
    if not _rule_concerns(finding, "periphery", "noc", "defence", "highway", "control line", "no-development", "mullanpur"):
        return None
    description = (
        f"{finding.title} sits in GIS-constraint territory (periphery control / NOC-radius "
        "type checks), which a redraw of the building footprint cannot resolve on its own. "
        "The usual route is a No-Objection Certificate from the relevant authority for this "
        "specific constraint; which authority and what documentation it requires depends on "
        f"the citation this finding carries ({finding.citation.doc}, clause "
        f"{finding.citation.clause}) and should be confirmed there, not inferred."
    )
    return Remedy(kind="noc_route", description=description, area_lost_sqm=None, edit_ref=None, verified=False)


def zoning_revision_request(finding: Finding, model: BuildingModel) -> Remedy | None:
    """Applicable to zoned-area containment violations, and to any finding whose status is
    'unknown' specifically because zoned_area is missing. A geometric edit can't fix a
    footprint that's outside the zoned area if the zoned area itself is what's wrong (e.g. an
    outdated trace, or a genuine case for asking PUDA to revise the zoning plan for the
    plot) -- this remedy names that avenue explicitly rather than only ever proposing to move
    the building."""
    if not _rule_concerns(finding, "zon", "containment", "envelope"):
        return None
    if model.zoned_area is None:
        description = (
            f"{finding.title} could not be checked because no zoned area is on file for this "
            "plot (zoned_area is unset). Per CLAUDE.md's own contract this must stay "
            "status=unknown rather than pass -- the remedy here is procedural, not geometric: "
            "obtain or trace the zoning plan for this plot before submission, or, if none "
            "exists for this plot's band yet, request one from PUDA."
        )
    else:
        description = (
            f"{finding.title}: the footprint falls outside the zoned area on file. Besides a "
            "geometric edit that pulls the footprint back inside the zoned area (see the "
            "geometric-edit remedies on this finding, if any were found), a zoning-plan "
            "revision request to PUDA is the non-geometric route when the zoned area itself "
            "is believed to be outdated or drawn incorrectly for this plot -- that determination "
            "is not something this tool can make, only surface as an option."
        )
    return Remedy(kind="zoning_revision_request", description=description, area_lost_sqm=None, edit_ref=None, verified=False)


_ALL_NON_GEOMETRIC = (purchase_chargeable_far, compounding, noc_route, zoning_revision_request)


def non_geometric_remedies_for_finding(finding: Finding, model: BuildingModel) -> list[Remedy]:
    """Run every non-geometric remedy rule against a finding and return the ones that apply.
    Order: chargeable FAR, compounding, NOC route, zoning revision -- matches CLAUDE.md §9
    point 5's listing order."""
    out: list[Remedy] = []
    for rule in _ALL_NON_GEOMETRIC:
        remedy = rule(finding, model)
        if remedy is not None:
            out.append(remedy)
    return out
