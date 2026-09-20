"""packages/parser/dxf_ingest.py::list_layout_names + the layout param on ingest_dxf/
extract_overall_height_m, and packages.api.role_inference.guess_layout_roles.

Added because a single DWG/DXF commonly holds a whole sheet set as separate named paperspace
layout tabs ("GROUND FLOOR PLAN", "ELEVATION FRONT", ...) rather than as separate uploaded files
-- the user's own words: "a single dwg file has all information and multiple layouts/elevations
... naming [of the uploaded file] is redundant." Before this, /cases/assemble treated one
uploaded file as exactly one sheet and could only guess its role from the outer filename (DXF has
no title-block text), so a single multi-layout file with an unhelpful filename was rejected
outright even though the file itself already said what each part was.

A layout tab's own name is read the same way a PDF's title block is -- content the drafter wrote
into the file, not metadata about the upload -- so it's treated as a higher-trust signal than
the filename fallback.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import ezdxf
import pytest
from fastapi.testclient import TestClient

from packages.api.main import app
from packages.api.role_inference import guess_layout_roles
from packages.parser.dxf_ingest import extract_overall_height_m, ingest_dxf, list_layout_names

client = TestClient(app)

SCRATCH = pathlib.Path(__file__).resolve().parent / "_scratch_dxf_layouts.dxf"


def _save(doc) -> pathlib.Path:
    doc.saveas(str(SCRATCH))
    return SCRATCH


@pytest.fixture(autouse=True)
def _cleanup_scratch():
    yield
    SCRATCH.unlink(missing_ok=True)


def test_list_layout_names_excludes_model_and_empty_default_layout():
    """ezdxf.new() always creates an empty default paperspace ("Layout1") even when a drawing
    never uses layouts at all -- that carries no role signal and must not be reported."""
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (1, 1))  # something in Model, irrelevant here
    path = _save(doc)
    assert list_layout_names(path) == []


def test_list_layout_names_returns_named_nonempty_layouts_in_tab_order():
    doc = ezdxf.new("R2018")
    ground = doc.layouts.new("GROUND FLOOR PLAN")
    ground.add_line((0, 0), (5, 0))
    elevation = doc.layouts.new("ELEVATION FRONT")
    elevation.add_line((0, 0), (0, 3))
    path = _save(doc)
    assert list_layout_names(path) == ["GROUND FLOOR PLAN", "ELEVATION FRONT"]


def test_ingest_dxf_with_layout_reads_that_layout_not_modelspace():
    doc = ezdxf.new("R2018")
    doc.modelspace().add_lwpolyline(
        [(0, 0), (100, 0), (100, 100), (0, 100)], close=True, dxfattribs={"layer": "WALL"}
    )
    ground = doc.layouts.new("GROUND FLOOR PLAN")
    ground.add_lwpolyline(
        [(0, 0), (10, 0), (10, 10), (0, 10)], close=True, dxfattribs={"layer": "WALL"}
    )
    path = _save(doc)

    from_layout = ingest_dxf(path, layout="GROUND FLOOR PLAN")
    assert from_layout["layout"] == "GROUND FLOOR PLAN"
    assert len(from_layout["polylines"]) == 1
    assert from_layout["polylines"][0]["points"][2] == [10, 10]

    from_modelspace = ingest_dxf(path)
    assert from_modelspace["layout"] is None
    assert from_modelspace["polylines"][0]["points"][2] == [100, 100]


def test_extract_overall_height_m_reads_dimension_from_named_layout():
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    elevation = doc.layouts.new("ELEVATION FRONT")
    dim = elevation.add_linear_dim(base=(2, 0), p1=(0, 0), p2=(0, 10.06), angle=90)
    dim.render()
    path = _save(doc)

    height_m, _segments, note = extract_overall_height_m(path, layout="ELEVATION FRONT")
    assert height_m == pytest.approx(10.06, abs=1e-6)

    # Modelspace has no such dimension -- must not find it there instead.
    height_m_msp, _s, _n = extract_overall_height_m(path)
    assert height_m_msp is None


def test_guess_layout_roles_matches_known_keywords_and_reports_unmatched():
    doc = ezdxf.new("R2018")
    doc.layouts.new("GROUND FLOOR PLAN").add_line((0, 0), (1, 0))
    doc.layouts.new("FRONT ELEVATION").add_line((0, 0), (0, 1))
    doc.layouts.new("A1").add_line((0, 0), (1, 1))  # no recognizable keyword
    path = _save(doc)

    guesses = guess_layout_roles(path)
    assert guesses["GROUND FLOOR PLAN"].role == "ground"
    assert guesses["GROUND FLOOR PLAN"].source == "layout_name"
    assert guesses["FRONT ELEVATION"].role == "elevation_front"
    assert guesses["A1"].role is None


def test_cases_assemble_expands_one_dwg_into_multiple_sheets_by_layout():
    """The end-to-end scenario the user asked for: ONE uploaded file (named however, e.g. from
    a real bungalow DWG) that internally holds a ground-floor plan on one layout tab and a front
    elevation on another. Both must be picked up and used correctly, with no filename hint
    needed at all."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6

    ground = doc.layouts.new("GROUND FLOOR PLAN")
    ground.add_lwpolyline(
        [(0, 0), (10, 0), (10, 8), (0, 8)], close=True, dxfattribs={"layer": "WALL"}
    )

    elevation = doc.layouts.new("FRONT ELEVATION")
    dim = elevation.add_linear_dim(base=(2, 0), p1=(0, 0), p2=(0, 3.2), angle=90)
    dim.render()

    path = _save(doc)

    with open(path, "rb") as f:
        resp = client.post(
            "/cases/assemble",
            files={"files": ("whatever_the_client_named_it.dxf", f, "application/octet-stream")},
            data={"authority": "GMADA"},
        )
    assert resp.status_code == 200
    body = resp.json()

    # Both layouts resolved from ONE uploaded file, keyed by layout, not by the outer filename.
    resolved = body["resolved_roles"]
    assert any(v == "ground" for v in resolved.values())
    assert any(v == "elevation_front" for v in resolved.values())
    assert body["unresolved"] == []

    floors = body["model"]["floors"]
    assert len(floors) == 1
    assert floors[0]["level"] == 0
    assert floors[0]["height_m"] == pytest.approx(3.2, abs=1e-6)
