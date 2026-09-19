"""tools/extract.py's Chandigarh-specific chunker (chunk_clauses_chandigarh).

This document's numbering is far more heterogeneous than the other four corpus documents (see
CHANDIGARH_TOP_HEADINGS/CHANDIGARH_SUBCLAUSE_MARKER docstrings in tools/extract.py) and required
real edge-case handling (cross-line sub-headings, a table-value false positive) -- these tests
guard the specific bugs found and fixed during that work, not just a smoke test.

Skipped entirely if the raw PDF isn't present (mirrors the existing requires_h01-style guards
elsewhere in this test suite for large source files not everyone's checkout will have).
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import pytest

DOC_ID = "chandigarh_building_rules_urban_2017"
ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "corpus" / "raw" / f"{DOC_ID}.pdf"

requires_raw = pytest.mark.skipif(not RAW_PATH.exists(), reason="Chandigarh raw PDF not present in this checkout")


@requires_raw
def _clauses():
    import fitz

    import extract as extract_tool

    doc = fitz.open(str(RAW_PATH))
    # Build page_info the same way ingest_one() does, without writing raster PNGs to disk.
    page_info = []
    for i, page in enumerate(doc):
        text = page.get_text()
        page_info.append({
            "page": i,
            "text_chars": len(text.strip()),
            "ocr_required": len(text.strip()) < extract_tool.OCR_THRESHOLD_CHARS,
            "raster_path": f"pages/p{i:04d}.png",
        })
    clauses, anomalies = extract_tool.chunk_clauses_chandigarh(doc, DOC_ID, page_info)
    doc.close()
    return clauses, anomalies


@requires_raw
def test_all_fifteen_top_level_sections_and_three_annexures_found():
    clauses, anomalies = _clauses()
    numbers = {c["number"] for c in clauses}
    for n in [str(i) for i in range(1, 16)]:
        assert n in numbers, f"top-level clause {n} missing"
    for aid in ("annexure-1", "annexure-2", "annexure-3"):
        assert aid in numbers, f"{aid} missing"
    assert not any("was not located in the body text" in a for a in anomalies)


@requires_raw
def test_residential_and_group_housing_subclauses_split_correctly():
    """Regression guard for the cross-line sub-heading bug: '4.2\\nResidential (GROUP HOUSING)'
    was originally swallowed into 4.1's text because the heading text sits on the line AFTER
    the bare number, not the same line."""
    clauses, _ = _clauses()
    by_number = {c["number"]: c for c in clauses}
    assert "4.1" in by_number
    assert "4.2" in by_number
    assert "PLOTTED" in by_number["4.1"]["heading"].upper()
    assert "GROUP HOUSING" in by_number["4.2"]["heading"].upper()
    # 4.1's text must not have swallowed 4.2's content.
    assert "GROUP HOUSING" not in by_number["4.1"]["text"].upper()


@requires_raw
def test_high_tension_clearance_table_value_is_rejected_not_a_fake_clause():
    """Regression guard: a table row ('High voltage lines above 11 KV...') was originally
    matched as a fake sub-clause '11.50', which stole the rest of the clearance-zone table away
    from the real clause 11.2.3. Verifies the false positive is rejected AND that 11.2.3 gets
    its full table content back."""
    clauses, anomalies = _clauses()
    numbers = {c["number"] for c in clauses}
    assert "11.50" not in numbers
    assert any("11.50" in a and "table value" in a for a in anomalies)
    by_number = {c["number"]: c for c in clauses}
    assert "11.2.3" in by_number
    assert "440KV" in by_number["11.2.3"]["text"] or "440" in by_number["11.2.3"]["text"]


@requires_raw
def test_heading_not_truncated_at_internal_hyphen():
    """Regression guard: heading extraction originally split on any hyphen, truncating
    '11.1.10 Re-Validation of Building Plans' down to just 'Re'."""
    clauses, _ = _clauses()
    by_number = {c["number"]: c for c in clauses}
    assert "11.1.10" in by_number
    assert "Validation" in by_number["11.1.10"]["heading"]


@requires_raw
def test_no_duplicate_clause_ids():
    clauses, _ = _clauses()
    ids = [c["clause_id"] for c in clauses]
    assert len(ids) == len(set(ids))
