"""Track C -- ambiguity engine tests. CLAUDE.md §8.

Covers the three stubs called out in the brief (s04 stilt+4 definitional -- the flagship,
s05 missing zoning -- missing_input, s06 low-confidence rooms -- confirmation flag) plus
targeted unit tests for the other four classes using small, explicitly-grounded fixtures
(since those classes need corpus/casework context no single stub carries).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import json

from packages.schema import BuildingModel, Finding, Citation
from packages.ambiguity.classifier import (
    classify_all,
    classify_definitional_stilt,
    classify_discretionary,
    classify_instrument_conflict,
    classify_missing_input,
    classify_practice_divergence,
    classify_transcription_conflict,
    classify_vintage,
)
from packages.ambiguity.dossier import build_dossier

STUB_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases" / "stubs"

# Actual clause text ingested from corpus/extracted/puda_building_rules_1996/clauses.jsonl,
# clause "4#2" (the substitution of Rule 16 -- see INTEGRATION.md's Stage 0 handoff on why
# this, not the original Rule 16 text, is the operative FAR clause). Confirmed to contain no
# mention of "stilt".
FAR_CLAUSE_TEXT_1996 = (
    "In the said Rules, for Rule 16 , the following shall be substituted , namely:- 16 (i) "
    "Floor Area Ratio: The maximum floor area ratio shall not exceed. a) In case of "
    "Educational buildings: 1.0 b) In case of other public buildings: 1.5 c) In case of "
    "residential plotted Development:- i) For plots upto 225 sq.mtr. in area 1.65 ii) For "
    "plots above to 225 sq.mtrs. but not 1.40 exceeding 325 sq.mts. iii) For plots above 325 "
    "sq.mtr but not 1.25 exceeding 430 Sq.mtr. d) In case of Group Housing the Floor Area "
    "Ratio shall be as specified in the zoning plan."
)
FAR_CITATION_DOC = "puda_building_rules_1996"
FAR_CITATION_CLAUSE = "4#2"


def _load(name: str) -> BuildingModel:
    data = json.loads((STUB_DIR / f"{name}.model.json").read_text(encoding="utf-8"))
    return BuildingModel.model_validate(data)


# ---------------------------------------------------------------------------
# s04 -- definitional (flagship)
# ---------------------------------------------------------------------------

def test_s04_stilt_triggers_definitional_ambiguity():
    model = _load("s04_stilt4_500")
    trigger = classify_definitional_stilt(
        model, FAR_CLAUSE_TEXT_1996, FAR_CITATION_DOC, FAR_CITATION_CLAUSE
    )
    assert trigger is not None
    assert trigger.ambiguity_class == "definitional"
    assert trigger.evidence["stilt_levels"] == [0]


def test_s04_definitional_clause_mentioning_stilt_does_not_trigger():
    model = _load("s04_stilt4_500")
    trigger = classify_definitional_stilt(
        model,
        FAR_CLAUSE_TEXT_1996 + " A stilt floor used solely for parking is excluded.",
        FAR_CITATION_DOC,
        FAR_CITATION_CLAUSE,
    )
    assert trigger is None


def test_s04_dossier_has_two_grounded_readings_and_real_numbers():
    model = _load("s04_stilt4_500")
    trigger = classify_definitional_stilt(
        model, FAR_CLAUSE_TEXT_1996, FAR_CITATION_DOC, FAR_CITATION_CLAUSE
    )
    dossier = build_dossier(trigger, model, far_cap=1.00)

    assert dossier.ambiguity_class == "definitional"
    assert len(dossier.readings) == 2
    assert dossier.safer_reading_label == "Include stilt (literal clause reading)"
    assert dossier.proof_document == {"doc": FAR_CITATION_DOC, "clause": FAR_CITATION_CLAUSE}

    # Numbers are computed from the actual stub geometry (14m x 14m footprint x 4 upper
    # floors excl. stilt / x5 incl.), not invented by narration.
    assert dossier.facts["plot_area_sqm"] == 500.0
    assert round(dossier.facts["covered_area_excl_stilt_sqm"], 1) == 784.0
    assert round(dossier.facts["covered_area_incl_stilt_sqm"], 1) == 980.0
    assert round(dossier.facts["far_excl_stilt"], 3) == round(784.0 / 500.0, 3)
    assert round(dossier.facts["far_incl_stilt"], 3) == round(980.0 / 500.0, 3)

    # The justification paragraph must be grounded: every number it states traces back to
    # dossier.facts (spot check a couple).
    para = dossier.justification_paragraph
    assert f"{dossier.facts['covered_area_excl_stilt_sqm']:.1f}" in para
    assert f"{dossier.facts['covered_area_incl_stilt_sqm']:.1f}" in para
    assert FAR_CITATION_CLAUSE in para
    assert len(para) > 400  # this is the "give it real time" paragraph, not a one-liner


def test_no_stilt_means_no_definitional_trigger():
    model = _load("s01_clean_250")
    trigger = classify_definitional_stilt(
        model, FAR_CLAUSE_TEXT_1996, FAR_CITATION_DOC, FAR_CITATION_CLAUSE
    )
    assert trigger is None


# ---------------------------------------------------------------------------
# s05 -- missing_input
# ---------------------------------------------------------------------------

def test_s05_no_zoning_triggers_missing_input():
    model = _load("s05_no_zoning")
    triggers = classify_missing_input(model)
    fields = {t.evidence["field"] for t in triggers}
    assert "zoned_area" in fields
    assert all(t.ambiguity_class == "missing_input" for t in triggers)


def test_s05_missing_input_dossier_never_recommends_assuming_compliant():
    model = _load("s05_no_zoning")
    trigger = next(t for t in classify_missing_input(model) if t.evidence["field"] == "zoned_area")
    dossier = build_dossier(trigger, model)
    assert dossier.safer_reading_label == "Report unknown"
    outcomes = {r.label: r.outcome for r in dossier.readings}
    assert outcomes["Assume compliant"] == "rejected"
    assert outcomes["Report unknown"] == "unknown"
    assert "zoning plan" in dossier.justification_paragraph.lower()


def test_s01_clean_has_no_missing_input():
    model = _load("s01_clean_250")
    assert classify_missing_input(model) == []


# ---------------------------------------------------------------------------
# s06 -- low confidence rooms: confirmation flag, not a submission dossier
# ---------------------------------------------------------------------------

def test_s06_low_confidence_rooms_flag_as_extraction_confirmation():
    model = _load("s06_low_conf")
    triggers = classify_all(model)
    low_conf_triggers = [
        t for t in triggers
        if t.ambiguity_class == "extraction" and t.evidence.get("source") == "low_confidence_label"
    ]
    assert len(low_conf_triggers) == 2  # s06 has exactly two low-confidence rooms

    dossier = build_dossier(low_conf_triggers[0], model)
    assert dossier.is_confirmation_flag is True
    assert dossier.proof_document is None
    assert "confirm" in dossier.justification_paragraph.lower()


# ---------------------------------------------------------------------------
# instrument_conflict
# ---------------------------------------------------------------------------

def _citation(doc: str, clause: str) -> Citation:
    return Citation(doc=doc, clause=clause, version="n/a", status="verified")


def test_instrument_conflict_fires_when_two_docs_disagree_on_same_check():
    findings = [
        Finding(
            rule_id="rules.setback.rear",
            status="violation",
            severity="major",
            title="Rear setback",
            citation=_citation("puda_building_rules_1996", "17"),
            observed=1.8,
            required=3.0,
        ),
        Finding(
            rule_id="zoning.setback.rear",
            status="pass",
            severity="major",
            title="Rear setback",
            citation=_citation("zoning_plan_sector70_s04", "1"),
            observed=1.8,
            required=1.5,
        ),
    ]
    triggers = classify_instrument_conflict(findings)
    assert len(triggers) == 1
    assert triggers[0].ambiguity_class == "instrument_conflict"
    assert len(triggers[0].evidence["sources"]) == 2

    dossier = build_dossier(triggers[0], _load("s01_clean_250"))
    assert len(dossier.readings) == 2
    assert "precedence" in dossier.justification_paragraph.lower()


def test_instrument_conflict_does_not_fire_when_docs_agree():
    findings = [
        Finding(
            rule_id="rules.setback.rear",
            status="pass",
            severity="major",
            title="Rear setback",
            citation=_citation("puda_building_rules_1996", "17"),
            observed=2.0,
            required=1.5,
        ),
        Finding(
            rule_id="zoning.setback.rear",
            status="pass",
            severity="major",
            title="Rear setback",
            citation=_citation("zoning_plan_sector70_s04", "1"),
            observed=2.0,
            required=1.5,
        ),
    ]
    assert classify_instrument_conflict(findings) == []


def test_transcription_conflict_is_extraction_not_instrument_conflict():
    findings = [
        Finding(
            rule_id="rules.coverage.band1",
            status="unknown",
            severity="major",
            title="Site coverage",
            citation=Citation(doc="puda_building_rules_1996", clause="15", version="1996", status="conflict"),
        )
    ]
    triggers = classify_transcription_conflict(findings)
    assert len(triggers) == 1
    assert triggers[0].ambiguity_class == "extraction"


# ---------------------------------------------------------------------------
# vintage -- grounded in the real 30-6-1997 cutoff in clause 4#2 (Rule 16(ii))
# ---------------------------------------------------------------------------

def test_vintage_trigger_grounded_in_real_1997_cutoff():
    model = _load("s02_setback_rear")  # allotment_date 2019-04-01, well after cutoff
    trigger = classify_vintage(
        model,
        cutoff_iso_date="1997-06-30",
        regime_description="charges payable under Rule 16(ii) for pre-existing allotments",
        citation_doc="puda_building_rules_1996",
        citation_clause="4#2",
    )
    assert trigger is not None
    assert trigger.ambiguity_class == "vintage"
    assert trigger.evidence["side"] == "on-or-after"

    dossier = build_dossier(trigger, model)
    assert dossier.safer_reading_label == "Post-cutoff regime"
    assert "1997-06-30" in dossier.justification_paragraph


def test_vintage_none_when_allotment_date_missing():
    from packages.schema.building_model import Jurisdiction

    model = _load("s02_setback_rear").model_copy(deep=True)
    model.jurisdiction = Jurisdiction(
        authority="GMADA", rule_pack="puda_building_rules_1996", allotment_date=None
    )
    trigger = classify_vintage(
        model,
        cutoff_iso_date="1997-06-30",
        regime_description="charges payable under Rule 16(ii)",
        citation_doc="puda_building_rules_1996",
        citation_clause="4#2",
    )
    assert trigger is None  # this is missing_input's job, not vintage's


# ---------------------------------------------------------------------------
# discretionary
# ---------------------------------------------------------------------------

def test_discretionary_language_detected():
    clause_text = "Relaxation in the above requirement may be permitted by the competent authority in special circumstances."
    trigger = classify_discretionary(clause_text, "puda_building_rules_1996", "17#3", rule_id="rules.height.relaxation")
    assert trigger is not None
    assert trigger.ambiguity_class == "discretionary"

    dossier = build_dossier(trigger, _load("s01_clean_250"))
    assert dossier.safer_reading_label == "Relief not assumed"


def test_discretionary_language_absent_returns_none():
    clause_text = "The maximum height shall not exceed 15 metres."
    assert classify_discretionary(clause_text, "puda_building_rules_1996", "17") is None


# ---------------------------------------------------------------------------
# practice_divergence
# ---------------------------------------------------------------------------

def test_practice_divergence_requires_real_casework():
    assert classify_practice_divergence("rules.parking.ecs", []) is None

    history = [
        {"rule_id": "rules.parking.ecs", "was_compliant_on_paper": True, "case_id": "obj_2021_014"}
    ]
    trigger = classify_practice_divergence("rules.parking.ecs", history)
    assert trigger is not None
    assert trigger.ambiguity_class == "practice_divergence"

    dossier = build_dossier(trigger, _load("s01_clean_250"))
    assert dossier.safer_reading_label == "Office practice"
    assert "1" in dossier.justification_paragraph  # prior_case_count grounded, not invented


# ---------------------------------------------------------------------------
# classify_all orchestration sanity
# ---------------------------------------------------------------------------

def test_classify_all_on_s01_is_empty_without_extra_context():
    model = _load("s01_clean_250")
    assert classify_all(model) == []


def test_classify_all_on_s04_includes_definitional_when_far_clause_supplied():
    model = _load("s04_stilt4_500")
    triggers = classify_all(
        model,
        definitional_far_clause={
            "clause_text": FAR_CLAUSE_TEXT_1996,
            "citation_doc": FAR_CITATION_DOC,
            "citation_clause": FAR_CITATION_CLAUSE,
        },
    )
    assert any(t.ambiguity_class == "definitional" for t in triggers)
