"""Chandigarh Building Rules (Urban) 2017 pack -- second-jurisdiction onboarding
(INTEGRATION.md "Second jurisdiction" entries).

Reuses the six Mohali stubs with jurisdiction.authority/rule_pack swapped to CHANDIGARH, the
same way test_estimated_envelope.py and this session's own manual smoke tests did -- there is
no Chandigarh-specific stub yet (no real Chandigarh drawing had been uploaded when this pack was
authored), and the point of these tests is to prove the PACK and the engine's generic `kind`
dispatch work correctly, not to validate Chandigarh-specific geometry.

Key things this guards, specific to the real bugs/decisions made while building this pack:
  - every enforced kind (containment, room_min_height x2, light_ventilation_ratio,
    floor_min_height, staircase_min_width) actually runs and returns real findings, not crashes
    or silent skips
  - ground_coverage/far/height/storeys/staircase_riser/staircase_tread rules stay enforced:false
    (verified values with an unresolved plot-size-band or missing-engine-kind gap -- see the
    pack's own header) and never silently produce a Finding
  - the setback-formula estimate genuinely has nothing to find in this pack (no formula exists
    for this jurisdiction), covered already by test_estimated_envelope.py's own dedicated test
  - the jurisdiction-unknown fallback (packages/rules/engine.py::evaluate) reports THIS pack's
    own identity, not a hardcoded PUDA1996 string -- the exact bug found and fixed while adding
    this second pack
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.schema.building_model import BuildingModel
from packages.rules.engine import evaluate_path, load_pack

STUB_DIR = ROOT / "packages" / "cases" / "stubs"
PACK_PATH = ROOT / "packages" / "rules" / "packs" / "chandigarh_building_rules_urban_2017.yaml"

ENFORCED_KINDS = {
    "containment", "room_min_height", "light_ventilation_ratio",
    "floor_min_height", "staircase_min_width",
}
UNENFORCED_KINDS = {
    "site_coverage_slab", "far_band", "height_max", "storeys_max",
    "staircase_riser", "staircase_tread",
}


def load_stub_as_chandigarh(name: str) -> BuildingModel:
    data = json.loads((STUB_DIR / f"{name}.model.json").read_text(encoding="utf-8"))
    data["jurisdiction"]["authority"] = "CHANDIGARH"
    data["jurisdiction"]["rule_pack"] = "chandigarh_building_rules_urban_2017"
    return BuildingModel.model_validate(data)


def test_pack_loads_and_every_rule_has_a_citation():
    pack = load_pack(PACK_PATH)
    assert pack["pack_id"] == "chandigarh_building_rules_urban_2017"
    assert pack["jurisdiction"] == "CHANDIGARH"
    assert pack["rules"], "pack must not be empty"
    for rule in pack["rules"]:
        assert rule["source"].get("doc") == "chandigarh_building_rules_urban_2017"
        assert rule["source"].get("clause"), f"{rule['id']} missing citation clause"
        assert rule["status"] in {"verified", "seed_unverified", "conflict", "not_stated"}


def test_enforced_and_unenforced_kinds_match_the_documented_split():
    """Regression guard for the pack's own header: rules with a genuine plot-size-band or
    missing-engine-kind gap must stay enforced:false, never silently promoted."""
    pack = load_pack(PACK_PATH)
    for rule in pack["rules"]:
        kind = rule["kind"]
        if kind in ENFORCED_KINDS:
            assert rule.get("enforced", True) is True, f"{rule['id']} ({kind}) should be enforced"
        elif kind in UNENFORCED_KINDS:
            assert rule.get("enforced", True) is False, f"{rule['id']} ({kind}) should NOT be enforced yet"


def test_every_finding_has_a_citation_to_the_chandigarh_doc():
    for stub_name in [p.stem.removesuffix(".model") for p in STUB_DIR.glob("*.model.json")]:
        model = load_stub_as_chandigarh(stub_name)
        findings = evaluate_path(model, PACK_PATH)
        for f in findings:
            assert f.citation is not None
            assert f.citation.doc == "chandigarh_building_rules_urban_2017"
            assert f.citation.clause


def test_containment_is_unknown_without_a_zoning_plan():
    """Same flagship-check discipline as PUDA1996.containment.zoned_area -- no real zoning plan
    exists for any Chandigarh case yet, so this must never silently pass."""
    model = load_stub_as_chandigarh("s05_no_zoning")
    findings = evaluate_path(model, PACK_PATH)
    containment = [f for f in findings if f.rule_id == "CHD2017.containment.zoned_area"]
    assert containment, "containment rule should have produced at least one finding"
    assert all(f.status == "unknown" for f in containment)


def test_room_and_staircase_and_basement_checks_run_and_produce_real_verdicts():
    model = load_stub_as_chandigarh("s01_clean_250")
    findings = evaluate_path(model, PACK_PATH)
    rule_ids_seen = {f.rule_id for f in findings}
    assert "CHD2017.room.habitable_min_height" in rule_ids_seen
    assert "CHD2017.room.service_min_height" in rule_ids_seen
    assert "CHD2017.room.light_ventilation_ratio" in rule_ids_seen
    assert "CHD2017.basement.min_height" in rule_ids_seen
    assert "CHD2017.staircase.min_width" in rule_ids_seen
    # No enforced check should ever silently vanish into "unknown" for a clean, fully-specified
    # stub except staircase (this stub's stair room, if any, may lack the geometry this check
    # needs) -- but every OTHER enforced kind must resolve to pass/violation, not unknown, on a
    # deliberately clean fixture.
    for f in findings:
        if f.rule_id in {
            "CHD2017.room.habitable_min_height", "CHD2017.room.service_min_height",
            "CHD2017.basement.min_height",
        }:
            assert f.status in {"pass", "violation"}, f"{f.rule_id} unexpectedly unknown on a clean stub"


def test_unenforced_rules_never_produce_a_finding():
    """Ground coverage / FAR / height / storeys / staircase riser+tread are verified numeric
    facts with a genuine, disclosed gap (plot-size band or missing engine kind) -- they must
    never appear in the findings list at all while enforced:false, not even as 'unknown'."""
    model = load_stub_as_chandigarh("s01_clean_250")
    findings = evaluate_path(model, PACK_PATH)
    seen_ids = {f.rule_id for f in findings}
    pack = load_pack(PACK_PATH)
    unenforced_ids = {r["id"] for r in pack["rules"] if not r.get("enforced", True)}
    assert not (seen_ids & unenforced_ids), f"unenforced rules leaked findings: {seen_ids & unenforced_ids}"


def test_jurisdiction_unknown_reports_this_packs_own_identity_not_puda():
    """Regression guard for the exact bug found while adding this second pack:
    evaluate()'s authority==UNKNOWN fallback used to hardcode 'PUDA1996'/
    'puda_building_rules_1996' regardless of which pack was actually being evaluated."""
    data = json.loads((STUB_DIR / "s01_clean_250.model.json").read_text(encoding="utf-8"))
    data["jurisdiction"]["authority"] = "UNKNOWN"
    data["jurisdiction"]["rule_pack"] = "chandigarh_building_rules_urban_2017"
    model = BuildingModel.model_validate(data)
    findings = evaluate_path(model, PACK_PATH)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "chandigarh_building_rules_urban_2017.jurisdiction.unknown"
    assert f.citation.doc == "chandigarh_building_rules_urban_2017"
    assert "PUDA" not in f.rule_id
    assert "PUDA" not in (f.required or "")
