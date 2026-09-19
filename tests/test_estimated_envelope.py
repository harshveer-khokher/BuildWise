"""packages/rules/estimated_envelope.py -- the setback-formula buildable-envelope ESTIMATE.

Never confused with the real containment check: this module has no access to, and never sets,
BuildingModel.zoned_area. These tests guard that it (a) produces sane numbers against a real
drawing with a confirmed height, (b) infers orientation correctly (verified against the same
h01 footprint-vs-elevation-width correlation checked by hand during development), (c) fails
honestly (available=False) rather than guessing when an input is missing, and (d) the size-based
fit check flags an oversized footprint without claiming a verified position check.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from packages.parser.semantics import assemble_case
from packages.rules.estimated_envelope import estimate_buildable_envelope
from packages.schema import BuildingModel, Floor, Jurisdiction

CASES_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases"
H01_DIR = CASES_DIR / "real" / "h01"
H01_META = H01_DIR / "h01.meta.json"

requires_h01 = pytest.mark.skipif(not H01_DIR.exists(), reason="h01 real case not present (gitignored)")


@requires_h01
def test_estimate_against_h01_real_drawing():
    model = assemble_case(H01_META)
    model.jurisdiction.authority = "GMADA"
    result = estimate_buildable_envelope(
        model=model,
        front_elevation_path=H01_DIR / "elevation_front.pdf",
        plot_width_m=12.5,
        plot_length_m=20.0,
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
    # h01's own footprint (~8.32m x 11.73m) is smaller than a 12.5x20m plot's estimated
    # envelope, so this should read as a plausible (size-based, unconfirmed-position) fit.
    assert result["fit_status"] == "plausible_fit"
    assert len(result["per_floor_fit"]) == len(model.floors)


@requires_h01
def test_estimate_flags_oversized_footprint_as_likely_exceeding():
    model = assemble_case(H01_META)
    model.jurisdiction.authority = "GMADA"
    result = estimate_buildable_envelope(
        model=model,
        front_elevation_path=H01_DIR / "elevation_front.pdf",
        plot_width_m=9.0,   # only slightly bigger than the ~8.32m footprint width before setbacks
        plot_length_m=13.0,
    )
    assert result["available"] is True
    assert result["fit_status"] == "likely_exceeds"
    assert any(not f["fits_by_size"] for f in result["per_floor_fit"])


@requires_h01
def test_estimate_unavailable_when_setbacks_exceed_plot_size():
    model = assemble_case(H01_META)
    model.jurisdiction.authority = "GMADA"
    result = estimate_buildable_envelope(
        model=model,
        front_elevation_path=H01_DIR / "elevation_front.pdf",
        plot_width_m=3.0,   # smaller than 2x the side setback alone
        plot_length_m=4.0,
    )
    assert result["available"] is False
    assert "no positive buildable area" in result["reason"]


def test_estimate_unavailable_without_a_confirmed_height():
    """A model with no floor heights at all must fail honestly rather than assume one."""
    model = BuildingModel(
        source="vector_pdf",
        jurisdiction=Jurisdiction(authority="GMADA", rule_pack="puda_building_rules_1996"),
        floors=[Floor(level=0, is_stilt=False, footprint=[[0, 0], [8, 0], [8, 11], [0, 11], [0, 0]], height_m=None)],
    )
    result = estimate_buildable_envelope(
        model=model,
        front_elevation_path=H01_DIR / "elevation_front.pdf" if H01_DIR.exists() else pathlib.Path("nonexistent.pdf"),
        plot_width_m=12.5,
        plot_length_m=20.0,
    )
    assert result["available"] is False
    assert "no confirmed" in result["reason"]


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
