"""Track A -- parser tests (CLAUDE.md §4/§10). Exercises:

  - dxf_ingest.py against the required ugly-layer-name smoke file (§10.2)
  - pdf_ingest.py against the real h01/h02 vector-PDF sheets (§10.4, Tier B)
  - semantics.py end-to-end assembly against h01/h02's meta.json (§10.1)
  - mutate.py's declarative mutation + truth generation (§10.5)

h01/h02 are real, gitignored drawings (CLAUDE.md §10.7) -- these tests skip gracefully if they
are not present on disk (e.g. a fresh checkout without the real cases), rather than failing the
whole suite over data that is deliberately not committed.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from packages.cases import mutate as mutate_mod
from packages.parser import dxf_ingest, pdf_ingest, semantics
from packages.schema import BuildingModel

CASES_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases"
SYNTH_DXF = CASES_DIR / "synth" / "s_smoke.dxf"
H01_META = CASES_DIR / "real" / "h01" / "h01.meta.json"
H02_META = CASES_DIR / "real" / "h02" / "h02.meta.json"

requires_synth_dxf = pytest.mark.skipif(
    not SYNTH_DXF.exists(), reason="synth smoke DXF not generated (run packages/cases/gen_synth_smoke.py)"
)
requires_h01 = pytest.mark.skipif(not H01_META.exists(), reason="h01 real case not present (gitignored)")
requires_h02 = pytest.mark.skipif(not H02_META.exists(), reason="h02 real case not present (gitignored)")


# ---------------------------------------------------------------------------
# dxf_ingest.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_name,expected_category",
    [
        ("WALL", "wall"),
        ("wall-ext", "wall"),
        ("A-WALL-EXTR", "wall"),
        ("BDRM-1", "room_bedroom"),
        ("MBR", "room_bedroom"),
        ("TOIL", "room_bath"),
        ("some-totally-unrecognised-layer", "unknown"),
    ],
)
def test_normalize_layer_name_handles_ugly_names(raw_name, expected_category):
    assert dxf_ingest.normalize_layer_name(raw_name) == expected_category


@requires_synth_dxf
def test_ingest_dxf_smoke_file_has_expected_geometry():
    result = dxf_ingest.ingest_dxf(SYNTH_DXF)

    # All six deliberately-ugly layers from CLAUDE.md §10.2 are present.
    assert set(result["layers"]) == {"WALL", "wall-ext", "A-WALL-EXTR", "BDRM-1", "MBR", "TOIL"}

    wall_polys = dxf_ingest.closed_polylines_by_category(result, "wall")
    assert len(wall_polys) == 1  # the exterior outline is the only closed "wall" polyline
    exterior = wall_polys[0]
    assert exterior[0] == exterior[-1]  # closed ring

    from shapely.geometry import Polygon

    assert Polygon(exterior).area == pytest.approx(80.0)  # 10m x 8m

    bedroom_polys = dxf_ingest.closed_polylines_by_category(result, "room_bedroom")
    assert len(bedroom_polys) == 2  # MBR + BDRM-1

    bath_polys = dxf_ingest.closed_polylines_by_category(result, "room_bath")
    assert len(bath_polys) == 1  # TOIL


@requires_synth_dxf
def test_ingest_dxf_missing_file_raises_not_silently_empty():
    with pytest.raises(Exception):
        dxf_ingest.ingest_dxf(CASES_DIR / "synth" / "does_not_exist.dxf")


# ---------------------------------------------------------------------------
# pdf_ingest.py
# ---------------------------------------------------------------------------


@requires_h01
def test_ingest_plan_sheet_h01_ground_produces_plausible_footprint():
    result = pdf_ingest.ingest_plan_sheet(CASES_DIR / "real" / "h01" / "ground.pdf")

    assert result["scale_pts_per_m"] is not None
    assert result["footprint"] is not None
    fp = result["footprint"]
    width_m = fp[1][0] - fp[0][0]
    height_m = fp[2][1] - fp[1][1]
    # A residential plot's ground floor footprint is somewhere in a sane architectural range --
    # this is a smoke bound against a badly-broken scale estimate, not a precision claim.
    assert 3.0 < width_m < 40.0
    assert 3.0 < height_m < 40.0

    assert result["title_block"]["sheet_title"] == "Ground floor plan"
    assert result["title_block"]["plot_no"] == "351"

    # Every room this heuristic produces must be explicitly low/medium confidence -- never "high"
    # (CLAUDE.md §5: confidence semantics gate whether a value needs user confirmation).
    assert result["rooms"], "expected at least one room recovered from the label+dimension text"
    assert all(r["confidence"] in ("low", "medium") for r in result["rooms"])

    assert len(result["notes"]) >= 2  # bbox + scale notes must always be present


@requires_h01
def test_extract_title_block_does_not_bleed_into_next_field():
    # Regression guard for a bug caught during development: a blank "CLIENT :-" field must not
    # swallow the next label's line as its own value.
    text = "CLIENT :-\nDRAWING NO:-\n"
    fields = pdf_ingest.extract_title_block(text)
    assert fields["client"] is None
    assert fields["drawing_no"] is None


def test_clean_dimension_values_m_parses_and_clamps():
    values = pdf_ingest._clean_dimension_values_m("38'-6\" x 19'-6\"")
    assert values == pytest.approx([11.7348, 5.9436])
    # A garbled fraction glyph producing an inches value >= 12 must be rejected, not clamped
    # into a wrong-but-plausible number.
    assert pdf_ingest._clean_dimension_values_m("3'-101\" x 8'-6\"") == pytest.approx([2.5908])


@requires_h02
def test_sheet_title_role_mismatch_detected_on_h02_elevation_front():
    # h02's meta.json declares this file role "elevation_front", but the sheet's own title
    # block reads "WOODEN JOINERY DETAIL" -- exactly the sheet-role-mismatch case CLAUDE.md
    # §10.1 warns about. This must be detectable, not silently trusted.
    result = pdf_ingest.ingest_plan_sheet(CASES_DIR / "real" / "h02" / "elevation_front.pdf")
    title = result["title_block"]["sheet_title"]
    assert not pdf_ingest.sheet_title_matches_role(title, ("elevation",))


# ---------------------------------------------------------------------------
# semantics.py -- multi-sheet assembly
# ---------------------------------------------------------------------------


@requires_h01
def test_assemble_case_h01_produces_valid_building_model_with_known_gaps():
    model = semantics.assemble_case(H01_META)

    assert isinstance(model, BuildingModel)  # validates against the frozen schema by construction

    # Distinct levels, one per plan sheet (ground/first/second -> 0/1/2), per the §10.1 assertion.
    levels = [f.level for f in model.floors]
    assert levels == sorted(levels)
    assert len(levels) == len(set(levels))
    assert set(levels) == {0, 1, 2}

    # No site/section sheet was supplied -- these must be None/[], never guessed (CLAUDE.md §5).
    assert model.plot_polygon is None
    assert model.zoned_area is None
    assert model.edges == []
    assert all(f.height_m is None for f in model.floors)

    # The gaps must be recorded verbatim in assumptions, not silently swallowed.
    joined = "\n".join(model.assumptions)
    assert "no 'section' role sheet supplied" in joined
    assert "no 'site'/'zoning' role sheet supplied" in joined

    # Jurisdiction fields recovered from the drawing's own title block.
    assert model.jurisdiction.plot_no == "351"


@requires_h02
def test_assemble_case_h02_flags_elevation_role_mismatch_in_assumptions():
    model = semantics.assemble_case(H02_META)
    assert isinstance(model, BuildingModel)
    joined = "\n".join(model.assumptions)
    assert "elevation_front" in joined
    assert "does not confirm that" in joined


@requires_synth_dxf
def test_ingest_sheet_dispatches_dxf_by_extension():
    ingested = semantics._ingest_sheet(SYNTH_DXF)
    assert ingested["footprint"] is not None
    from shapely.geometry import Polygon

    assert Polygon(ingested["footprint"]).area == pytest.approx(80.0)
    assert len(ingested["rooms"]) == 3  # MBR, BDRM-1, TOIL


@requires_synth_dxf
def test_assemble_case_rejects_duplicate_floor_level(tmp_path):
    # "stilt" and "ground" both map to Floor.level=0 in semantics._PLAN_LEVELS -- a case whose
    # meta.json declares both must raise per the §10.1 assembly assertion ("every plan sheet
    # maps to a distinct level"), rather than silently keeping one and dropping the other.
    import shutil

    case_dir = tmp_path / "bad_case"
    case_dir.mkdir()
    shutil.copy(SYNTH_DXF, case_dir / "a.dxf")
    meta = {"sheets": {"stilt": "a.dxf", "ground": "a.dxf"}, "known_gaps": []}
    (case_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="distinct level"):
        semantics.assemble_case(case_dir / "meta.json")


@requires_synth_dxf
def test_assemble_case_single_dxf_ground_sheet_assembles_cleanly(tmp_path):
    import shutil

    case_dir = tmp_path / "good_case"
    case_dir.mkdir()
    shutil.copy(SYNTH_DXF, case_dir / "a.dxf")
    meta = {"sheets": {"ground": "a.dxf"}, "known_gaps": []}
    (case_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    model = semantics.assemble_case(case_dir / "meta.json")
    assert len(model.floors) == 1
    assert model.floors[0].level == 0
    assert model.source == "dxf"


# ---------------------------------------------------------------------------
# mutate.py
# ---------------------------------------------------------------------------


@requires_synth_dxf
def test_mutate_offset_edge_derives_exact_truth(tmp_path, monkeypatch):
    # Redirect output dirs so this test doesn't depend on / clobber the checked-in demonstration
    # mutations under packages/cases/synth/mutated and packages/cases/truth.
    monkeypatch.setattr(mutate_mod, "MUTATED_DIR", tmp_path / "mutated")
    monkeypatch.setattr(mutate_mod, "TRUTH_DIR", tmp_path / "truth")

    truth = mutate_mod.mutate(
        SYNTH_DXF, op="offset_edge", mutation_id="t01",
        layer="A-WALL-EXTR", edge="north", delta_m=1.2,
    )

    assert truth["ground_truth"]["area_before_sqm"] == pytest.approx(80.0)
    assert truth["ground_truth"]["area_after_sqm"] == pytest.approx(92.0)
    assert truth["ground_truth"]["area_delta_sqm"] == pytest.approx(12.0)
    assert truth["ground_truth"]["north_edge_coordinate_before_m"] == pytest.approx(8.0)
    assert truth["ground_truth"]["north_edge_coordinate_after_m"] == pytest.approx(9.2)
    assert truth["provenance"] == "synthetic"

    # The mutated DXF must itself re-ingest cleanly through dxf_ingest.py.
    mutated_path = pathlib.Path(truth["mutated_dxf"])
    assert mutated_path.exists()
    reingested = dxf_ingest.ingest_dxf(mutated_path)
    wall_polys = dxf_ingest.closed_polylines_by_category(reingested, "wall")
    from shapely.geometry import Polygon

    assert Polygon(wall_polys[0]).area == pytest.approx(92.0)

    # Truth file was actually written to disk and round-trips through json.
    truth_path = pathlib.Path(truth["truth_path"])
    assert truth_path.exists()
    reloaded = json.loads(truth_path.read_text(encoding="utf-8"))
    assert reloaded["case_id"] == "s_smoke_t01"


@requires_synth_dxf
def test_mutate_shrink_room_reduces_area(tmp_path, monkeypatch):
    monkeypatch.setattr(mutate_mod, "MUTATED_DIR", tmp_path / "mutated")
    monkeypatch.setattr(mutate_mod, "TRUTH_DIR", tmp_path / "truth")

    truth = mutate_mod.mutate(
        SYNTH_DXF, op="shrink_room", mutation_id="t02",
        layer="TOIL", edge="east", delta_m=0.8,
    )
    assert truth["ground_truth"]["area_delta_sqm"] < 0


@requires_synth_dxf
def test_mutate_rejects_non_rectangular_or_missing_layer(tmp_path, monkeypatch):
    monkeypatch.setattr(mutate_mod, "MUTATED_DIR", tmp_path / "mutated")
    monkeypatch.setattr(mutate_mod, "TRUTH_DIR", tmp_path / "truth")

    with pytest.raises(ValueError):
        mutate_mod.mutate(
            SYNTH_DXF, op="offset_edge", mutation_id="t03",
            layer="does-not-exist", edge="north", delta_m=1.0,
        )


def test_checked_in_demonstration_mutations_exist_and_are_synthetic():
    # The two demonstration mutations generated by `python packages/cases/mutate.py` should be
    # present so the harness output is inspectable without re-running anything.
    for case_id in ("s_smoke_m01", "s_smoke_m02"):
        truth_path = CASES_DIR / "truth" / f"{case_id}.truth.json"
        if not truth_path.exists():
            pytest.skip(f"{truth_path} not generated yet (run python packages/cases/mutate.py)")
        data = json.loads(truth_path.read_text(encoding="utf-8"))
        assert data["provenance"] == "synthetic"
        assert "area_delta_sqm" in data["ground_truth"]
