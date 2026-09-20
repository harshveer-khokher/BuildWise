"""packages/parser/dxf_ingest.py::extract_overall_height_m -- the DXF analogue of
pdf_ingest.extract_overall_height_m(), added because height extraction previously only existed
for PDF elevations (semantics.py explicitly skipped every non-PDF sheet for this cross-check).
That gap was a real omission in how much engineering time each format had received this session,
not a deliberate "DXF doesn't need this" decision -- height is exactly as useful from a DXF
elevation as from a PDF one.

Unlike the PDF version, which has to RECONSTRUCT a dimension value from nearby vector line
positions and OCR'd text (a PDF has no semantic "this is a measurement" entity), a DXF DIMENSION
entity IS the measurement -- ezdxf's `get_measurement()` returns the exact value the CAD software
computed. These tests are built on synthetic DXF files (no real DWG/DXF elevation sample was
available when this was written) -- verify against a real drawing before fully trusting it, same
as the PDF equivalent was eventually verified against a real 33-foot building.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import ezdxf
import pytest

from packages.parser.dxf_ingest import extract_overall_height_m

SCRATCH = pathlib.Path(__file__).resolve().parent / "_scratch_dxf_height.dxf"


def _save_and_extract(doc) -> tuple:
    doc.saveas(str(SCRATCH))
    try:
        return extract_overall_height_m(SCRATCH)
    finally:
        SCRATCH.unlink(missing_ok=True)


def test_single_dominant_vertical_dimension_is_the_height():
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()
    dim = msp.add_linear_dim(base=(2, 0), p1=(0, 0), p2=(0, 10.06), angle=90)
    dim.render()
    height_m, segments, note = _save_and_extract(doc)
    assert height_m == pytest.approx(10.06, abs=1e-6)
    assert len(segments) == 1
    assert "single dominant" in note


def test_chain_verified_by_a_larger_bracket_dimension():
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for p1, p2 in [((0, 0), (0, 6.5)), ((0, 6.5), (0, 8.0)), ((0, 8.0), (0, 9.0))]:
        d = msp.add_linear_dim(base=(1, 0), p1=p1, p2=p2, angle=90)
        d.render()
    bracket = msp.add_linear_dim(base=(3, 0), p1=(0, 0), p2=(0, 9.0), angle=90)
    bracket.render()
    height_m, segments, note = _save_and_extract(doc)
    assert height_m == pytest.approx(9.0, abs=1e-6)
    assert len(segments) == 3
    assert "verified" in note


def test_no_dimension_entities_returns_none_not_a_guess():
    doc = ezdxf.new("R2018")
    doc.modelspace()  # empty
    height_m, segments, note = _save_and_extract(doc)
    assert height_m is None
    assert segments is None
    assert "no vertical DIMENSION entities" in note


def test_unmatched_dimensions_return_none_rather_than_a_wrong_guess():
    """A largest dimension that doesn't match any contiguous sum of the others must not be
    silently treated as the height -- CLAUDE.md §1 rule 6, declared uncertainty over fake
    precision."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    d1 = msp.add_linear_dim(base=(1, 0), p1=(0, 0), p2=(0, 6.5), angle=90)
    d1.render()
    d2 = msp.add_linear_dim(base=(1, 0), p1=(0, 6.5), p2=(0, 8.0), angle=90)
    d2.render()
    lone = msp.add_linear_dim(base=(3, 0), p1=(0, 0), p2=(0, 7.7), angle=90)  # not 6.5, not 8.0, not their sum
    lone.render()
    height_m, segments, note = _save_and_extract(doc)
    assert height_m is None
    assert segments is None
    assert "not confident" in note


def test_horizontal_dimensions_are_ignored():
    """A dimension measuring plot width, not building height, must never be mistaken for a
    vertical height reading."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    horiz = msp.add_linear_dim(base=(0, -1), p1=(0, 0), p2=(12.5, 0), angle=0)
    horiz.render()
    height_m, segments, note = _save_and_extract(doc)
    assert height_m is None
    assert "no vertical DIMENSION" in note


def test_insunits_conversion_from_feet():
    """A DXF drawn in feet ($INSUNITS=2) must convert to metres, not be read as if already
    metric -- same unit-conversion discipline as pdf_ingest's feet-inch parsing."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 2  # feet
    msp = doc.modelspace()
    dim = msp.add_linear_dim(base=(2, 0), p1=(0, 0), p2=(0, 33.0), angle=90)  # 33 feet
    dim.render()
    height_m, segments, note = _save_and_extract(doc)
    assert height_m == pytest.approx(33.0 * 0.3048, abs=1e-6)
