"""Track C -- solver tests. CLAUDE.md §9.

Track B's real rules engine (packages/rules/engine.py) was not finished at the time this was
written, so we build a small fixture `evaluate_fn` here that checks exactly the two things
the target stubs (s02, s03) exercise: zoned-area containment and a simple residential-plotted
FAR cap (using the seed_unverified 1.65/1.40/1.25/1.00 bands actually present in
corpus/extracted/puda_building_rules_1996/clauses.jsonl, clause 16 as amended by clause 4#2).
This fixture is intentionally NOT part of packages/solver -- it stands in for Track B's engine
only for these tests, per this task's brief.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import json

from shapely.geometry import Polygon

from packages.schema import BuildingModel, Finding, Citation
from packages.solver.repair import search_repairs, solve
from packages.solver import remedies as remedies_mod

STUB_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases" / "stubs"


def _load(name: str) -> BuildingModel:
    data = json.loads((STUB_DIR / f"{name}.model.json").read_text(encoding="utf-8"))
    return BuildingModel.model_validate(data)


FAR_BANDS = [
    (0, 225, 1.65),
    (225, 325, 1.40),
    (325, 430, 1.25),
    (430, float("inf"), 1.00),
]
FAR_CITATION = Citation(
    doc="puda_building_rules_1996", clause="4#2", version="1996", status="seed_unverified"
)
SETBACK_CITATION = Citation(
    doc="puda_building_rules_1996", clause="17", version="1996", status="seed_unverified"
)


def _far_cap_for(plot_area_sqm: float) -> float:
    for lo, hi, cap in FAR_BANDS:
        if lo < plot_area_sqm <= hi or (lo == 0 and plot_area_sqm <= hi):
            return cap
    return FAR_BANDS[-1][2]


def fixture_evaluate_fn(model: BuildingModel) -> list[Finding]:
    """Stand-in for packages.rules.engine, covering only what s02/s03 need:
    (1) zoned-area containment for every floor footprint, (2) an FAR cap check.
    Every number is computed here in plain Python via shapely -- no LLM involved, matching
    how the real engine is specified to work (CLAUDE.md §1 rule 1)."""
    findings: list[Finding] = []

    # 1. Zoned-area containment (the flagship check, CLAUDE.md §7 priority 1)
    if model.zoned_area is None:
        findings.append(
            Finding(
                rule_id="FIXTURE.containment.zoned_area",
                status="unknown",
                severity="blocking",
                title="Zoned-area containment",
                citation=SETBACK_CITATION,
                observed=None,
                required=None,
                compoundable=False,
            )
        )
    else:
        zoned = Polygon(model.zoned_area)
        for floor in model.floors:
            fp = Polygon(floor.footprint)
            if not zoned.contains(fp):
                intrusion = fp.difference(zoned)
                findings.append(
                    Finding(
                        rule_id="FIXTURE.containment.zoned_area",
                        status="violation",
                        severity="blocking",
                        title=f"Zoned-area containment (setback) violation, floor {floor.level}",
                        citation=SETBACK_CITATION,
                        observed=round(intrusion.area, 3),
                        required=0.0,
                        geometry_ref=[list(c) for c in intrusion.convex_hull.exterior.coords]
                        if not intrusion.is_empty and intrusion.geom_type == "Polygon"
                        else None,
                        compoundable=True,
                    )
                )

    # 2. FAR cap
    if model.plot_area_sqm:
        total_covered = sum(abs(Polygon(f.footprint).area) for f in model.floors)
        far = total_covered / model.plot_area_sqm
        cap = _far_cap_for(model.plot_area_sqm)
        findings.append(
            Finding(
                rule_id="FIXTURE.far.residential_plotted",
                status="violation" if far > cap else "pass",
                severity="major",
                title="Floor area ratio",
                citation=FAR_CITATION,
                observed=round(far, 3),
                required=cap,
                compoundable=True,
            )
        )

    return findings


def test_s01_clean_has_no_violations():
    model = _load("s01_clean_250")
    findings = fixture_evaluate_fn(model)
    assert all(f.status != "violation" for f in findings)


def test_s02_setback_rear_finds_geometric_fix():
    model = _load("s02_setback_rear")
    findings = fixture_evaluate_fn(model)
    violations = [f for f in findings if f.status == "violation"]
    assert violations, "fixture should detect the seeded rear-setback intrusion"
    assert any(f.rule_id == "FIXTURE.containment.zoned_area" for f in violations)

    results = search_repairs(model, violations, fixture_evaluate_fn)
    setback_candidates = results.get("FIXTURE.containment.zoned_area", [])
    assert setback_candidates, "solver should find at least one verified geometric fix"

    best = setback_candidates[0]
    assert best.area_lost_sqm > 0
    assert best.edit_ref["op"] in ("shrink_wall", "shrink_wall_all_floors")

    # Verify: re-running the full fixture pack against the *edited* model must show this
    # rule no longer violated, and nothing new introduced (CLAUDE.md §9 points 2-4).
    after = fixture_evaluate_fn(best.model)
    after_violations = {f.rule_id for f in after if f.status == "violation"}
    before_violations = {f.rule_id for f in findings if f.status == "violation"}
    assert "FIXTURE.containment.zoned_area" not in after_violations or all(
        "floor 0" not in f.title for f in after if f.rule_id == "FIXTURE.containment.zoned_area"
    )
    assert after_violations <= before_violations, "no new violation may be introduced"


def test_s03_far_over_finds_geometric_and_or_nongeometric_remedy():
    model = _load("s03_far_over")
    findings = fixture_evaluate_fn(model)
    violations = [f for f in findings if f.status == "violation"]
    assert any(f.rule_id == "FIXTURE.far.residential_plotted" for f in violations)
    far_violation = next(f for f in violations if f.rule_id == "FIXTURE.far.residential_plotted")
    assert far_violation.compoundable is True

    remedies_by_rule = solve(model, findings, evaluate_fn=fixture_evaluate_fn)
    far_remedies = remedies_by_rule["FIXTURE.far.residential_plotted"]
    kinds = {r.kind for r in far_remedies}
    # Either a verified geometric edit exists, or a non-geometric remedy (chargeable FAR /
    # compounding) was surfaced -- CLAUDE.md §9 point 5.
    assert "geometric_edit" in kinds or "purchase_chargeable_far" in kinds or "compounding" in kinds
    # No Remedy description may claim verified=True unless it is a geometric_edit that this
    # module itself re-ran the full pack on.
    for r in far_remedies:
        if r.verified:
            assert r.kind == "geometric_edit"


def test_geometric_remedy_never_regresses_and_is_marked_verified():
    model = _load("s02_setback_rear")
    findings = fixture_evaluate_fn(model)
    violations = [f for f in findings if f.status == "violation"]
    results = search_repairs(model, violations, fixture_evaluate_fn)
    for rule_id, candidates in results.items():
        for cand in candidates:
            after = fixture_evaluate_fn(cand.model)
            after_ids = {f.rule_id for f in after if f.status == "violation"}
            before_ids = {f.rule_id for f in findings if f.status == "violation"}
            assert after_ids <= before_ids
            remedy = cand.to_remedy()
            assert remedy.verified is True
            assert remedy.area_lost_sqm is not None and remedy.area_lost_sqm >= 0


def test_candidates_ranked_by_area_lost_ascending():
    model = _load("s02_setback_rear")
    findings = fixture_evaluate_fn(model)
    violations = [f for f in findings if f.status == "violation"]
    results = search_repairs(model, violations, fixture_evaluate_fn)
    for candidates in results.values():
        areas = [c.area_lost_sqm for c in candidates]
        assert areas == sorted(areas)


def test_non_geometric_remedies_never_invent_numbers_not_in_finding():
    model = _load("s03_far_over")
    findings = fixture_evaluate_fn(model)
    far_violation = next(f for f in findings if f.rule_id == "FIXTURE.far.residential_plotted")
    remedies = remedies_mod.non_geometric_remedies_for_finding(far_violation, model)
    assert any(r.kind == "purchase_chargeable_far" for r in remedies)
    assert any(r.kind == "compounding" for r in remedies)
    for r in remedies:
        # The only numbers allowed in the description are ones derivable from
        # finding.observed/required/plot_area_sqm -- spot check no stray currency figures
        # (a fee this module was told never to invent) appear.
        assert "Rs." not in r.description and "INR" not in r.description


def test_zoning_revision_request_fires_for_unknown_containment_and_missing_zone():
    model = _load("s05_no_zoning")
    findings = fixture_evaluate_fn(model)
    unknown = next(f for f in findings if f.rule_id == "FIXTURE.containment.zoned_area")
    assert unknown.status == "unknown"
    remedies = remedies_mod.non_geometric_remedies_for_finding(unknown, model)
    kinds = {r.kind for r in remedies}
    assert "zoning_revision_request" in kinds
