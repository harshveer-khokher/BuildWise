"""packages/parser/site_geometry.py -- plot boundary, zoning envelope and setbacks read off a
plan sheet's own drawing.

Before this existed, `plot_polygon`, `plot_area_sqm`, `zoned_area` and `edges` were None/[] on
every real case, so containment, ground coverage, FAR and every setback rule could only answer
`unknown`. The data was on the sheets the whole time: real Mohali submissions draw the plot line
and the zoning line directly on the floor plan, labelled and colour-coded.

These tests are built on a synthetic sheet drawn to a known scale, so they assert exact numbers
without depending on the gitignored real drawings (CLAUDE.md §10.7). The real cases are exercised
separately at the bottom and skip when absent.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fitz

from packages.parser import site_geometry as SG

# 10 pt per foot, so every dimension below is exact in both feet and points.
PT_PER_FT = 10.0
FT_TO_M = 0.3048
SCALE_PT_PER_M = PT_PER_FT / FT_TO_M  # 32.808...

PLOT_X0, PLOT_Y0 = 100.0, 100.0
PLOT_W_FT, PLOT_D_FT = 60.0, 90.0
PLOT_X1 = PLOT_X0 + PLOT_W_FT * PT_PER_FT   # 700
PLOT_Y1 = PLOT_Y0 + PLOT_D_FT * PT_PER_FT   # 1000

MAGENTA = (0.9, 0.0, 0.9)     # #e600e6, as the real sheets use for the plot line
ORANGE = (0.98, 0.29, 0.02)   # #fa4a05, as they use for the zoning line
WALL_FILL = (0.776, 0.710, 0.522)

FRONT_SETBACK_FT, REAR_SETBACK_FT = 10.0, 20.0
ZONE_Y0 = PLOT_Y0 + FRONT_SETBACK_FT * PT_PER_FT   # 200
ZONE_Y1 = PLOT_Y1 - REAR_SETBACK_FT * PT_PER_FT    # 800

SCRATCH = pathlib.Path(__file__).resolve().parent / "_scratch_site.pdf"


def _sheet(
    *,
    plot_colour=MAGENTA,
    plot_label_colour=MAGENTA,
    zoning=True,
    dimensions=("60'", "90'"),
    walls=True,
    zoning_step=False,
    misplace_dimensions=False,
) -> pathlib.Path:
    """A one-page synthetic plan sheet with the same signals a real one carries."""
    doc = fitz.open()
    page = doc.new_page(width=1200, height=1200)

    page.draw_line(fitz.Point(PLOT_X0, PLOT_Y0), fitz.Point(PLOT_X1, PLOT_Y0), color=plot_colour, width=1)
    page.draw_line(fitz.Point(PLOT_X0, PLOT_Y1), fitz.Point(PLOT_X1, PLOT_Y1), color=plot_colour, width=1)
    page.draw_line(fitz.Point(PLOT_X0, PLOT_Y0), fitz.Point(PLOT_X0, PLOT_Y1), color=plot_colour, width=1)
    page.draw_line(fitz.Point(PLOT_X1, PLOT_Y0), fitz.Point(PLOT_X1, PLOT_Y1), color=plot_colour, width=1)
    page.insert_text((PLOT_X0, PLOT_Y0 - 12), "PLOT LINE", color=plot_label_colour, fontsize=9)

    if zoning:
        page.draw_line(fitz.Point(PLOT_X0, ZONE_Y0), fitz.Point(PLOT_X1, ZONE_Y0), color=ORANGE, width=1)
        page.draw_line(fitz.Point(PLOT_X0, ZONE_Y1), fitz.Point(PLOT_X1, ZONE_Y1), color=ORANGE, width=1)
        page.insert_text((PLOT_X0 + 20, ZONE_Y0 - 4), "ZONING LINE", color=ORANGE, fontsize=9)
        if zoning_step:
            # A short run marking a stepped pocket -- must be counted, never applied as a cut.
            page.draw_line(fitz.Point(PLOT_X0, 900), fitz.Point(PLOT_X0 + 120, 900), color=ORANGE, width=1)

    if dimensions:
        width_txt, depth_txt = dimensions
        if misplace_dimensions:
            page.insert_text((PLOT_X0 + 5, PLOT_Y0 + 20), width_txt, fontsize=9)
            page.insert_text((PLOT_X0 + 5, PLOT_Y0 + 40), depth_txt, fontsize=9)
        else:
            # Centred on the axis each one measures, drawn just outside the plot.
            page.insert_text(((PLOT_X0 + PLOT_X1) / 2, PLOT_Y0 - 30), width_txt, fontsize=9)
            page.insert_text((PLOT_X0 - 60, (PLOT_Y0 + PLOT_Y1) / 2), depth_txt, fontsize=9)

    if walls:
        t = 0.75 * PT_PER_FT  # a 9" brick wall
        bx0, by0, bx1, by1 = 250.0, 300.0, 600.0, 700.0
        bars = [
            (bx0, by0, bx1, by0 + t), (bx0, by1 - t, bx1, by1),
            (bx0, by0, bx0 + t, by1), (bx1 - t, by0, bx1, by1),
            (bx0, 400, bx1, 400 + t), (bx0, 500, bx1, 500 + t),
            (bx0, 600, bx1, 600 + t), (350, by0, 350 + t, by1),
            (450, by0, 450 + t, by1), (520, by0, 520 + t, by1),
            (bx0, 350, 500, 350 + t), (300, 420, 300 + t, 690),
            (bx0, 650, bx1, 650 + t),
        ]
        for x0, y0, x1, y1 in bars:
            page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=None, fill=WALL_FILL)

    doc.save(SCRATCH)
    doc.close()
    return SCRATCH


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    SCRATCH.unlink(missing_ok=True)


def test_plot_rectangle_and_area_from_the_labelled_plot_line():
    g = SG.extract_site_geometry(_sheet())
    assert g.usable
    assert g.scale_pts_per_m == pytest.approx(SCALE_PT_PER_M, rel=1e-6)
    expected_sqm = (PLOT_W_FT * FT_TO_M) * (PLOT_D_FT * FT_TO_M)
    assert g.plot_area_sqm == pytest.approx(expected_sqm, abs=0.05)


def test_zoned_envelope_is_the_plot_clipped_by_the_major_zoning_lines():
    g = SG.extract_site_geometry(_sheet())
    depth_ft = PLOT_D_FT - FRONT_SETBACK_FT - REAR_SETBACK_FT
    assert g.zoned_area_sqm == pytest.approx((PLOT_W_FT * FT_TO_M) * (depth_ft * FT_TO_M), abs=0.05)


def test_per_edge_setbacks_match_the_drawn_zoning_line():
    g = SG.extract_site_geometry(_sheet())
    setbacks = sorted(e["zoning_setback_m"] for e in g.edges)
    assert setbacks == pytest.approx(
        [0.0, 0.0, FRONT_SETBACK_FT * FT_TO_M, REAR_SETBACK_FT * FT_TO_M], abs=0.02
    )
    # Two edges flush with the plot line identify the side boundaries; of the rest the smaller
    # setback is taken as the front.
    roles = {e["role"]: e["zoning_setback_m"] for e in g.edges}
    assert roles["front"] == pytest.approx(FRONT_SETBACK_FT * FT_TO_M, abs=0.02)
    assert roles["rear"] == pytest.approx(REAR_SETBACK_FT * FT_TO_M, abs=0.02)
    assert roles["side_a"] == 0.0 and roles["side_b"] == 0.0


def test_walls_are_found_by_masonry_thickness_not_by_being_thin():
    g = SG.extract_site_geometry(_sheet())
    assert g.wall_thickness_m == pytest.approx(0.2286, abs=0.01)  # a 9" brick wall
    assert g.footprint_hull is not None
    built = {e["role"]: e["built_setback_m"] for e in g.edges}
    assert all(v is not None for v in built.values())


def test_a_grey_plot_line_label_identifies_nothing_and_is_refused():
    """h01 labels its plot line in plain grey. Grey and black are the two commonest colours on
    any drawing, so following one would collect the whole sheet -- it must yield nothing."""
    g = SG.extract_site_geometry(_sheet(plot_label_colour=(0.42, 0.42, 0.42)))
    assert not g.usable
    assert any("no coloured 'plot line' label" in n for n in g.notes)


def test_a_line_colour_that_drifts_from_its_label_still_matches():
    """h02 labels its plot line #e600e6 but draws it #db00db. The match is on proximity, then
    confirmed against the sheet's printed dimensions before being accepted."""
    g = SG.extract_site_geometry(_sheet(plot_colour=(0.86, 0.0, 0.86)))
    assert g.usable
    assert any("colour proximity" in n for n in g.notes)


def test_a_far_off_colour_is_not_matched():
    g = SG.extract_site_geometry(_sheet(plot_colour=(0.1, 0.6, 0.2)))
    assert not g.usable


def test_interior_dimensions_alone_do_not_verify_a_scale():
    """The bug this guards: two room dimensions sharing the plot's aspect ratio "verified" each
    other and produced a confident 34 sqm plot on a real upper-floor sheet."""
    g = SG.extract_site_geometry(_sheet(misplace_dimensions=True))
    assert not g.usable
    assert any("not confirmed by printed dimensions" in n for n in g.notes)


def test_a_short_zoning_run_is_counted_as_a_step_not_applied_as_a_cut():
    """A stepped pocket (a permitted rear outbuilding) must not shrink the envelope -- doing so
    would manufacture a containment failure the zoning plan does not support."""
    plain = SG.extract_site_geometry(_sheet())
    stepped = SG.extract_site_geometry(_sheet(zoning_step=True))
    assert stepped.zoned_area_sqm == pytest.approx(plain.zoned_area_sqm, abs=0.01)
    assert stepped.unmodelled_zoning_steps >= 1
    assert any("shorter zoning-line run" in n for n in stepped.notes)


def test_no_zoning_line_yields_a_plot_but_never_defaults_the_envelope_to_it():
    g = SG.extract_site_geometry(_sheet(zoning=False))
    assert g.usable and g.plot_area_sqm is not None
    assert g.zoned_area is None
    assert any("containment stays unknown" in n for n in g.notes)


def test_scale_hint_lets_a_sheet_without_overall_dimensions_share_the_plot_datum():
    g = SG.extract_site_geometry(_sheet(misplace_dimensions=True), scale_hint=SCALE_PT_PER_M)
    assert g.usable
    assert g.plot_area_sqm == pytest.approx(
        (PLOT_W_FT * FT_TO_M) * (PLOT_D_FT * FT_TO_M), abs=0.05
    )
    assert any("carried over from another sheet" in n for n in g.notes)


# ---------------------------------------------------------------------------
# Real cases (gitignored, CLAUDE.md §10.7) -- skip when absent.
# ---------------------------------------------------------------------------

REAL = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases" / "real"
VIOLATION_GF = REAL / "violation" / "GROUND FLOOR PLAN.pdf"


@pytest.mark.skipif(not VIOLATION_GF.exists(), reason="real 'violation' case not present")
def test_real_violation_sheet_matches_its_own_printed_dimensions():
    """The sheet prints 90' x 51'-1½" for the plot and 13' / 19'-6" for the two zoning setbacks.
    Everything below is derived from the drawn geometry, so agreeing with the printed text is an
    independent confirmation, not a restatement."""
    g = SG.extract_site_geometry(VIOLATION_GF)
    assert g.usable
    assert g.plot_area_sqm == pytest.approx(27.432 * 15.583, rel=0.02)  # 90' x 51'-1.5"
    roles = {e["role"]: e for e in g.edges}
    assert roles["front"]["zoning_setback_m"] == pytest.approx(13 * FT_TO_M, abs=0.08)
    assert roles["rear"]["zoning_setback_m"] == pytest.approx(19.5 * FT_TO_M, abs=0.08)
    # The rear wall was built right up to the permitted envelope; the front was not.
    assert roles["rear"]["built_setback_m"] == pytest.approx(
        roles["rear"]["zoning_setback_m"], abs=0.05
    )
    assert roles["front"]["built_setback_m"] < roles["front"]["zoning_setback_m"] - 1.0
