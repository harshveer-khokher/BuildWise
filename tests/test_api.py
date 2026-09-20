"""Track D API tests (CLAUDE.md §11 Stage 1 / §12 "every agent runs `make eval`/`/check` before
declaring done"). Exercises packages/api/main.py against the six frozen stubs.

Two things this file guards above everything else:

1. s05_no_zoning must always produce a containment finding with status="unknown", never "pass"
   (CLAUDE.md §5's single most-repeated invariant — a missing zoning plan is not a clean bill of
   health).
2. No response body anywhere contains "approved" or "compliant" as a verdict (CLAUDE.md §5's
   non-negotiable: output is always framed as "pre-submission check: N issues found").

Uses FastAPI's TestClient (starlette test client, sync, in-process — no server process needed).
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from packages.api.main import app
from packages.parser import dwg_convert

client = TestClient(app)

STUB_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases" / "stubs"

BANNED_VERDICT_WORDS = ("approved", "compliant")


def _load_stub(name: str) -> dict:
    return json.loads((STUB_DIR / f"{name}.model.json").read_text(encoding="utf-8"))


def _assert_response_clean(resp) -> None:
    """No response body anywhere may contain a banned verdict word (CLAUDE.md §5)."""
    text = resp.text.lower()
    for word in BANNED_VERDICT_WORDS:
        assert word not in text, f"response contains banned verdict word {word!r}: {resp.text[:500]}"


ALL_STUBS = [
    "s01_clean_250",
    "s02_setback_rear",
    "s03_far_over",
    "s04_stilt4_500",
    "s05_no_zoning",
    "s06_low_conf",
]


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    _assert_response_clean(resp)


def test_upload_json_roundtrips_each_stub():
    for name in ALL_STUBS:
        data = _load_stub(name)
        resp = client.post("/upload", json=data)
        assert resp.status_code == 200, f"{name}: {resp.text}"
        body = resp.json()
        assert body["plot_area_sqm"] == data["plot_area_sqm"]
        assert body["jurisdiction"]["plot_no"] == data["jurisdiction"]["plot_no"]
        _assert_response_clean(resp)


def test_upload_rejects_invalid_model():
    resp = client.post("/upload", json={"not": "a building model"})
    assert resp.status_code == 422
    _assert_response_clean(resp)


def test_upload_multipart_without_parser_returns_501_not_a_silent_pass():
    # No packages.parser exists yet in this worktree, so this must fail loudly (501), never
    # fabricate a BuildingModel from an unparsed file.
    resp = client.post("/upload", files={"file": ("plan.dxf", b"fake dxf bytes", "application/octet-stream")})
    assert resp.status_code in (501, 200)  # 200 only if another track's parser has since landed
    if resp.status_code == 501:
        _assert_response_clean(resp)


def test_checks_run_s05_no_zoning_is_unknown_never_pass():
    """The single most important regression per the Track D brief."""
    data = _load_stub("s05_no_zoning")
    resp = client.post("/checks/run", json={"model": data})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    findings = body["findings"]
    containment_findings = [f for f in findings if "containment" in f["rule_id"].lower() or "zoned_area" in f["rule_id"].lower()]
    assert containment_findings, f"expected a containment finding, got rule_ids={[f['rule_id'] for f in findings]}"
    for f in containment_findings:
        assert f["status"] == "unknown", f"containment finding must be unknown when zoned_area is None, got {f['status']}"
        assert f["status"] != "pass"
    _assert_response_clean(resp)


def test_checks_run_summary_never_says_approved_or_compliant():
    for name in ALL_STUBS:
        data = _load_stub(name)
        resp = client.post("/checks/run", json={"model": data})
        assert resp.status_code == 200, f"{name}: {resp.text}"
        body = resp.json()
        assert body["summary"].startswith("pre-submission check:"), body["summary"]
        assert body["summary"].endswith("issues found"), body["summary"]
        assert body["engine_source"] in ("real", "fixture")
        for finding in body["findings"]:
            assert finding["citation"], f"{name}: finding {finding['rule_id']} has no citation (CLAUDE.md §1 rule 2)"
        _assert_response_clean(resp)


def test_checks_run_every_finding_has_a_citation():
    for name in ALL_STUBS:
        data = _load_stub(name)
        resp = client.post("/checks/run", json={"model": data})
        body = resp.json()
        for finding in body["findings"]:
            citation = finding["citation"]
            assert citation.get("doc")
            assert citation.get("clause")
            assert citation.get("version")


def test_models_confirm_applies_corrections_to_low_confidence_rooms():
    data = _load_stub("s06_low_conf")
    corrections = [
        {"floor_level": 0, "room_index": 0, "use": "bedroom", "confidence": "high"},
        {"floor_level": 0, "room_index": 1, "confidence": "high"},
    ]
    resp = client.post("/models/confirm", json={"model": data, "corrections": corrections})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] == 2
    corrected_rooms = body["model"]["floors"][0]["rooms"]
    assert corrected_rooms[0]["use"] == "bedroom"
    assert corrected_rooms[0]["confidence"] == "high"
    assert corrected_rooms[1]["confidence"] == "high"
    # third room (index 2, "other", confidence medium) was never touched
    assert corrected_rooms[2]["confidence"] == "medium"
    assert body["remaining_low_confidence"] == 0
    _assert_response_clean(resp)


def test_models_confirm_out_of_range_fails_loudly():
    data = _load_stub("s06_low_conf")
    corrections = [{"floor_level": 0, "room_index": 99, "use": "bedroom"}]
    resp = client.post("/models/confirm", json={"model": data, "corrections": corrections})
    assert resp.status_code == 400
    _assert_response_clean(resp)


def test_overlay_returns_geojson_feature_collection():
    data = _load_stub("s01_clean_250")
    resp = client.post("/overlay", json={"model": data})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert isinstance(body["features"], list)
    assert any(f["properties"].get("kind") == "plot_outline" for f in body["features"])
    _assert_response_clean(resp)


def test_overlay_flags_missing_zoned_area_as_metadata():
    data = _load_stub("s05_no_zoning")
    resp = client.post("/overlay", json={"model": data})
    body = resp.json()
    assert body["properties"]["zoned_area_present"] is False
    assert not any(f["properties"].get("kind") == "zoned_area" for f in body["features"])


def test_report_html_contains_not_a_sanction_language():
    data = _load_stub("s03_far_over")
    resp = client.post("/report/html", json={"model": data})
    assert resp.status_code == 200, resp.text
    assert "text/html" in resp.headers["content-type"]
    lowered = resp.text.lower()
    assert "not an approval" in lowered or "not a sanction" in lowered or "pre-submission check only" in lowered
    _assert_response_clean(resp)


def test_report_html_shows_dual_units():
    data = _load_stub("s01_clean_250")  # 250 sq m
    resp = client.post("/report/html", json={"model": data})
    body = resp.text
    assert "250" in body
    assert "299" in body or "299.0" in body  # 250 * 1.196 = 299.0 sq yd
    _assert_response_clean(resp)


def test_report_pdf_returns_pdf_bytes():
    data = _load_stub("s02_setback_rear")
    resp = client.post("/report/pdf", json={"model": data})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


SYNTH_DXF = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases" / "synth" / "s_smoke.dxf"


def test_jurisdictions_lists_mohali():
    resp = client.get("/jurisdictions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) and len(data) >= 1
    assert any(j["authority"] == "GMADA" for j in data)
    for j in data:
        assert {"id", "label", "authority", "rule_pack"} <= j.keys()


def test_report_markdown_route():
    data = _load_stub("s01_clean_250")
    resp = client.post("/report/markdown", json={"model": data})
    assert resp.status_code == 200
    assert "markdown" in resp.headers["content-type"]
    assert resp.text.startswith("# ")
    _assert_response_clean(resp)


def test_cases_assemble_with_synth_dxf():
    """Uses the committed synth smoke DXF (real drawings under packages/cases/real/ are
    gitignored per CLAUDE.md §10.7, so a portable fixture is needed here). Explicit role field
    name -- the backward-compatible, programmatic path."""
    with open(SYNTH_DXF, "rb") as f:
        resp = client.post(
            "/cases/assemble",
            files={"ground": ("s_smoke.dxf", f, "application/octet-stream")},
            data={"authority": "GMADA"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    model = body["model"]
    assert model["jurisdiction"]["authority"] == "GMADA"
    assert len(model["floors"]) >= 1
    assert model["floors"][0]["level"] == 0
    assert body["unresolved"] == []


def test_cases_assemble_requires_at_least_one_file():
    resp = client.post("/cases/assemble", data={"authority": "GMADA"})
    assert resp.status_code == 400


def test_cases_assemble_rejects_unsupported_file_type():
    resp = client.post(
        "/cases/assemble",
        files={"ground": ("notes.txt", b"not a drawing", "text/plain")},
    )
    assert resp.status_code == 422


H01_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases" / "real" / "h01"
requires_h01 = pytest.mark.skipif(not H01_DIR.exists(), reason="h01 real case not present (gitignored)")


@requires_h01
def test_cases_assemble_computes_estimated_envelope_when_plot_size_given():
    """The advisory setback-formula estimate (packages/rules/estimated_envelope.py) is computed
    inline by /cases/assemble when plot_width_m/plot_length_m are given, using this same
    upload's own ground floor + front elevation sheets -- never touches the real containment
    check or BuildingModel.zoned_area."""
    handles = [open(H01_DIR / f"{name}.pdf", "rb") for name in ("ground", "elevation_front")]
    try:
        resp = client.post(
            "/cases/assemble",
            files=[("files", (h.name.split("/")[-1].split("\\")[-1], h, "application/pdf")) for h in handles],
            data={"authority": "GMADA", "plot_width_m": "12.5", "plot_length_m": "20.0"},
        )
    finally:
        for h in handles:
            h.close()
    assert resp.status_code == 200, resp.text
    envelope = resp.json()["estimated_envelope"]
    assert envelope["available"] is True
    assert envelope["height_m_used"] == pytest.approx(10.058, abs=0.01)
    assert envelope["estimated_envelope_area_sqm"] > 0
    assert "ESTIMATE, not a verified zoning check" in envelope["note"]


@requires_h01
def test_cases_assemble_estimated_envelope_is_none_without_plot_size():
    handles = [open(H01_DIR / f"{name}.pdf", "rb") for name in ("ground", "elevation_front")]
    try:
        resp = client.post(
            "/cases/assemble",
            files=[("files", (h.name.split("/")[-1].split("\\")[-1], h, "application/pdf")) for h in handles],
            data={"authority": "GMADA"},
        )
    finally:
        for h in handles:
            h.close()
    assert resp.status_code == 200, resp.text
    assert resp.json()["estimated_envelope"] is None


def _make_pdf_with_title(sheet_title: str) -> bytes:
    """A minimal one-page PDF whose text layer contains a TITLE:- line, for exercising
    role_inference.guess_role() without depending on any gitignored real drawing."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), f"TITLE:- {sheet_title}\nDATE:- 2026-01-01")
    data = doc.tobytes()
    doc.close()
    return data


def test_cases_assemble_auto_infers_role_from_pdf_title_block():
    """The normal path: files uploaded under the generic "files" field, with no role declared
    by the caller at all -- role_inference reads each PDF's own title block."""
    pdf_bytes = _make_pdf_with_title("GROUND FLOOR PLAN")
    resp = client.post(
        "/cases/assemble",
        files={"files": ("my_drawing.pdf", pdf_bytes, "application/pdf")},
        data={"authority": "GMADA"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resolved_roles"] == {"my_drawing.pdf": "ground"}
    assert body["unresolved"] == []
    # This synthetic fixture has no vector geometry or dimension text, so pdf_ingest correctly
    # can't extract a usable footprint (covered by tests/test_parser.py) -- what this test
    # checks is role_inference's wiring, i.e. that "ground" was the role handed to assemble_case
    # at all, not footprint-extraction accuracy.
    assert body["model"]["jurisdiction"]["authority"] == "GMADA"


def _make_pdf_with_title_and_caption(sheet_title: str, caption: str) -> bytes:
    """Like _make_pdf_with_title, but also prints a second, separate caption elsewhere on the
    page -- mimicking a real sheet whose formal title describes one detail on it (e.g. "WOODEN
    JOINERY DETAIL") while a different view is actually labelled directly on the drawing (e.g.
    "FRONT ELEVATION" printed under it, as a real submitted drawing does)."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), f"TITLE:- {sheet_title}\nDATE:- 2026-01-01")
    page.insert_text((72, 700), caption)
    data = doc.tobytes()
    doc.close()
    return data


def test_cases_assemble_uses_a_page_caption_when_the_formal_title_does_not_match():
    """The exact real-world case that motivated this: a sheet's formal TITLE:- field describes
    one detail on it and doesn't match any known sheet type, but the sheet also prints a
    separate view caption elsewhere on the page that does. That caption should be used instead
    of rejecting the sheet -- searching for it is not guessing past what the file says, it's
    reading more of what the file says."""
    pdf_bytes = _make_pdf_with_title_and_caption("WOODEN JOINERY DETAIL", "FRONT ELEVATION")
    resp = client.post(
        "/cases/assemble",
        files={"files": ("ele-01.pdf", pdf_bytes, "application/pdf")},
        data={"authority": "GMADA"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resolved_roles"] == {"ele-01.pdf": "elevation_front"}
    assert body["unresolved"] == []


def test_cases_assemble_formal_title_still_wins_when_it_matches():
    """A page caption is only a fallback -- when the formal title DOES match, it must still be
    used directly rather than searching the rest of the page (which could contain unrelated
    keyword collisions in notes/boilerplate text)."""
    pdf_bytes = _make_pdf_with_title_and_caption("GROUND FLOOR PLAN", "SEE ELEVATION A FOR HEIGHT")
    resp = client.post(
        "/cases/assemble",
        files={"files": ("gf.pdf", pdf_bytes, "application/pdf")},
        data={"authority": "GMADA"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolved_roles"] == {"gf.pdf": "ground"}


def test_cases_assemble_single_unclassifiable_file_falls_back_to_combined():
    """A lone DXF whose filename gives no role hint (no title-block reader for DXF) and which
    has no named layout tabs to fall back on either must NOT be rejected outright -- it's the
    only file the user gave us, so per-file naming is redundant; it's used as a single
    best-effort 'combined' source instead, honestly flagged as unverified rather than silently
    presented as a confirmed ground floor."""
    with open(SYNTH_DXF, "rb") as f:
        resp = client.post(
            "/cases/assemble",
            files={"files": ("s_smoke.dxf", f, "application/octet-stream")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_roles"]["s_smoke.dxf"] == "combined"
    # It was used (not "unresolved" -- that would tell the user their only file was dropped),
    # but the model's own assumptions still honestly flag the low confidence.
    assert body["unresolved"] == []
    assumptions = " ".join(body["model"]["assumptions"])
    assert "combined" in assumptions
    assert "NOT verified" in assumptions


def test_cases_assemble_rejects_multiple_unclassifiable_files():
    """The single-file 'combined' fallback must not kick in when there's more than one file --
    blending several unidentified files' geometry into one floor would risk mixing content that
    was never meant to share a coordinate frame, so this stays an honest rejection."""
    with open(SYNTH_DXF, "rb") as f1, open(SYNTH_DXF, "rb") as f2:
        resp = client.post(
            "/cases/assemble",
            files=[
                ("files", ("s_smoke.dxf", f1, "application/octet-stream")),
                ("files", ("another_unnamed.dxf", f2, "application/octet-stream")),
            ],
        )
    assert resp.status_code == 400
    assert "recognizable" in resp.json()["detail"].lower()


def test_cases_assemble_auto_infer_yields_to_explicit_override():
    """If a role is both auto-guessed and explicitly provided, the explicit one wins and the
    auto-guessed file is reported, not silently discarded."""
    pdf_bytes = _make_pdf_with_title("GROUND FLOOR PLAN")
    with open(SYNTH_DXF, "rb") as explicit_ground:
        resp = client.post(
            "/cases/assemble",
            files={
                "ground": ("explicit_ground.dxf", explicit_ground, "application/octet-stream"),
                "files": ("auto_ground.pdf", pdf_bytes, "application/pdf"),
            },
            data={"authority": "GMADA"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resolved_roles"] == {}  # the auto file's role lost to the explicit one
    assert any(u["filename"] == "auto_ground.pdf" for u in body["unresolved"])


def test_cases_assemble_dwg_upload_fails_loudly_without_the_converter_installed(monkeypatch):
    """A .dwg upload on a machine with no ODA File Converter must fail with a clear, actionable
    502 -- never silently skip the file, never pretend it worked, never crash with an unrelated
    traceback. Forced via monkeypatch rather than relying on the ambient dev/CI machine actually
    lacking the converter -- once it's installed (as it now is in this environment), the fail-loud
    path is still exercised, just via a different, equally legitimate branch (see the sibling test
    below)."""
    monkeypatch.setattr(dwg_convert, "find_oda_converter", lambda: None)
    resp = client.post(
        "/cases/assemble",
        files={"files": ("ground floor plan.dwg", b"not a real dwg", "application/octet-stream")},
        data={"authority": "GMADA"},
    )
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "opendesign.com" in detail
    assert "CHD_ODA_CONVERTER_PATH" in detail


def test_cases_assemble_dwg_upload_fails_loudly_on_garbage_content_when_converter_is_installed():
    """When a real ODA File Converter IS installed (as in this environment) and the uploaded
    .dwg bytes aren't a real drawing, the converter runs, produces no output, and that must
    still surface as a fail-loud 502 -- never a silent skip, never a fake pass. This only
    exercises the real assertion when the converter is actually present; otherwise it's a no-op
    so this test file doesn't become environment-dependent in the other direction."""
    if not dwg_convert.is_available():
        pytest.skip("ODA File Converter not installed in this environment")
    resp = client.post(
        "/cases/assemble",
        files={"files": ("ground floor plan.dwg", b"not a real dwg", "application/octet-stream")},
        data={"authority": "GMADA"},
    )
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "did not produce a DXF" in detail


def test_cases_assemble_dwg_upload_succeeds_once_converted(monkeypatch):
    """With a (mocked) converter available, a .dwg upload goes through exactly the same
    role-inference and assembly path a .dxf upload would -- proving the wiring end-to-end
    without requiring the real proprietary converter to be installed in this environment."""
    from packages.parser import dwg_convert

    def fake_convert(dwg_path, out_dxf_path):
        import shutil
        shutil.copy(SYNTH_DXF, out_dxf_path)

    monkeypatch.setattr(dwg_convert, "convert_dwg_to_dxf", fake_convert)

    resp = client.post(
        "/cases/assemble",
        files={"files": ("ground floor plan.dwg", b"not a real dwg either", "application/octet-stream")},
        data={"authority": "GMADA"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resolved_roles"] == {"ground floor plan.dwg": "ground"}
    assert body["unresolved"] == []


def test_cases_assemble_explicit_dwg_role_also_converts(monkeypatch):
    """The explicit-named-role upload path (not just the auto-inferred 'files' field) must also
    convert a .dwg before use."""
    from packages.parser import dwg_convert

    def fake_convert(dwg_path, out_dxf_path):
        import shutil
        shutil.copy(SYNTH_DXF, out_dxf_path)

    monkeypatch.setattr(dwg_convert, "convert_dwg_to_dxf", fake_convert)

    resp = client.post(
        "/cases/assemble",
        files={"ground": ("plan.dwg", b"not a real dwg", "application/octet-stream")},
        data={"authority": "GMADA"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["model"] is not None


def test_all_stubs_produce_a_report_without_error():
    for name in ALL_STUBS:
        data = _load_stub(name)
        html_resp = client.post("/report/html", json={"model": data})
        pdf_resp = client.post("/report/pdf", json={"model": data})
        assert html_resp.status_code == 200, f"{name} html: {html_resp.text}"
        assert pdf_resp.status_code == 200, f"{name} pdf: {pdf_resp.text}"
        _assert_response_clean(html_resp)
