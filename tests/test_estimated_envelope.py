"""packages/rules/estimated_envelope.py -- the setback-formula buildable-envelope ESTIMATE.

Never confused with the real containment check: this module has no access to, and never sets,
BuildingModel.zoned_area. These tests guard that it (a) produces sane numbers against a real
drawing with a confirmed height, (b) infers orientation correctly (verified against the same
h01 footprint-vs-elevation-width correlation checked by hand during development), and (c) fails
honestly (available=False) rather than guessing when an input is missing.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from packages.rules.estimated_envelope import estimate_buildable_envelope

CASES_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases"
H01_DIR = CASES_DIR / "real" / "h01"

requires_h01 = pytest.mark.skipif(not H01_DIR.exists(), reason="h01 real case not present (gitignored)")


@requires_h01
def test_estimate_against_h01_real_drawing():
    result = estimate_buildable_envelope(
        ground_floor_path=H01_DIR / "ground.pdf",
        front_elevation_path=H01_DIR / "elevation_front.pdf",
        plot_width_m=12.5,
        plot_length_m=20.0,
        rule_pack_id="puda_building_rules_1996",
    )
    assert result["available"] is True
    assert result["height_m_used"] == pytest.approx(10.058, abs=0.01)
    # Confirmed by hand: front elevation's drawn width (7.45m) matches the ground floor
    # footprint's WIDTH (8.32m) far better than its DEPTH (11.73m) -- so orientation should
    # resolve to the plot's "width" input being the road-facing frontage.
    assert result["frontage_plot_dimension"] == "width"
    assert result["front_rear_setback_m"] == pytest.approx(max(10.058 * 0.25, 2.0), abs=0.01)
    assert result["side_setback_m"] == pytest.approx(max(10.058 * 0.2, 1.5), abs=0.01)
    assert result["estimated_envelope_area_sqm"] > 0
    assert "ESTIMATE, not a verified zoning check" in result["note"]


@requires_h01
def test_estimate_unavailable_when_setbacks_exceed_plot_size():
    result = estimate_buildable_envelope(
        ground_floor_path=H01_DIR / "ground.pdf",
        front_elevation_path=H01_DIR / "elevation_front.pdf",
        plot_width_m=3.0,   # smaller than 2x the side setback alone
        plot_length_m=4.0,
        rule_pack_id="puda_building_rules_1996",
    )
    assert result["available"] is False
    assert "no positive buildable area" in result["reason"]


def test_estimate_unavailable_without_a_confirmed_height():
    """A blank synthetic elevation has no dimension chain at all -- extract_overall_height_m
    returns None, and this must fail honestly rather than assume a height."""
    import fitz

    doc = fitz.open()
    doc.new_page()
    tmp_elev = pathlib.Path(__file__).resolve().parent / "_scratch_blank_elevation.pdf"
    doc.save(tmp_elev)
    doc.close()

    doc2 = fitz.open()
    doc2.new_page()
    tmp_ground = pathlib.Path(__file__).resolve().parent / "_scratch_blank_ground.pdf"
    doc2.save(tmp_ground)
    doc2.close()

    try:
        result = estimate_buildable_envelope(
            ground_floor_path=tmp_ground,
            front_elevation_path=tmp_elev,
            plot_width_m=12.5,
            plot_length_m=20.0,
            rule_pack_id="puda_building_rules_1996",
        )
        assert result["available"] is False
        assert "no confirmed height" in result["reason"]
    finally:
        tmp_elev.unlink(missing_ok=True)
        tmp_ground.unlink(missing_ok=True)


def test_setback_constants_fall_back_to_the_sole_pack_when_id_doesnt_match():
    """Mirrors the same single-pack fallback convention already used by
    engine.run_checks()/api's _resolve_pack_path -- an unrecognized rule_pack id still resolves
    when exactly one pack file exists, rather than failing outright."""
    from packages.rules.estimated_envelope import _setback_formula_constants

    assert _setback_formula_constants("not_a_real_pack_id") == (0.25, 2.0, 0.2, 1.5)


def test_setback_constants_match_the_verified_pack_values_exactly():
    """Regression guard: these must be READ from the pack, never hardcoded as duplicate
    literals that could drift if the pack's verified values ever change."""
    from packages.rules.estimated_envelope import _setback_formula_constants

    fr_fraction, fr_min, side_fraction, side_min = _setback_formula_constants("puda_building_rules_1996")
    assert (fr_fraction, fr_min) == (0.25, 2.0)
    assert (side_fraction, side_min) == (0.2, 1.5)
