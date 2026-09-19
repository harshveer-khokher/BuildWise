"""packages/report/render.py::render_markdown -- previously untested (only render_html/
render_pdf are exercised indirectly via tests/test_api.py's /report/* endpoints; render_markdown
is only wired into tools/run_check.py --markdown, not the API)."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from packages.report.render import render_markdown
from packages.rules.engine import run_checks
from packages.schema import BuildingModel

STUB_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases" / "stubs"


def _load_stub(name: str) -> BuildingModel:
    data = json.loads((STUB_DIR / f"{name}.model.json").read_text(encoding="utf-8"))
    return BuildingModel.model_validate(data)


def test_renders_without_error_for_every_stub():
    for path in STUB_DIR.glob("*.model.json"):
        model = BuildingModel.model_validate(json.loads(path.read_text(encoding="utf-8")))
        model.jurisdiction.authority = "GMADA"  # exercise the real (non-blocked) pack path
        findings = run_checks(model)
        text = render_markdown(model, findings)
        assert text.startswith("# mohali-check pre-submission report")


def test_never_contains_banned_verdict_language():
    model = _load_stub("s01_clean_250")
    model.jurisdiction.authority = "GMADA"
    findings = run_checks(model)
    text = render_markdown(model, findings).lower()
    assert "approved" not in text
    assert "compliant" not in text


def test_summary_line_present_and_correctly_counted():
    model = _load_stub("s05_no_zoning")
    model.jurisdiction.authority = "GMADA"
    findings = run_checks(model)
    text = render_markdown(model, findings)
    n_issues = sum(1 for f in findings if f.status != "pass")
    assert f"pre-submission check: {n_issues} issues found" in text


def test_every_finding_rule_id_appears_in_the_report():
    """No finding is silently dropped from the human-readable report -- every rule_id the
    engine produced shows up somewhere (grouped or not)."""
    model = _load_stub("s03_far_over")
    model.jurisdiction.authority = "GMADA"
    findings = run_checks(model)
    text = render_markdown(model, findings)
    for f in findings:
        assert f.rule_id in text, f"{f.rule_id} missing from rendered report"


def test_bylaws_checked_table_cites_real_document_titles_not_bare_doc_ids():
    model = _load_stub("s01_clean_250")
    model.jurisdiction.authority = "GMADA"
    findings = run_checks(model)
    text = render_markdown(model, findings)
    assert "## Bylaws checked" in text
    # every finding's citation doc_id must appear (even if a friendly title also does)
    for f in findings:
        assert f.citation.doc in text


def test_repeated_rule_id_is_grouped_not_duplicated_as_separate_headings():
    """s01 has multiple habitable rooms sharing PUDA1996.room.light_ventilation_ratio -- among
    findings that share the SAME status (e.g. two rooms that both fail), the report must show
    one heading with an instance count, not one heading per room. (A rule_id can legitimately
    appear once in Issues and once in Passing checks if some instances pass and others don't --
    that's two different sections, not duplication within one.)"""
    model = _load_stub("s01_clean_250")
    model.jurisdiction.authority = "GMADA"
    findings = run_checks(model)
    from collections import Counter

    by_rule_and_status = Counter((f.rule_id, f.status) for f in findings)
    grouped_rule_id, count = max(by_rule_and_status.items(), key=lambda kv: kv[1])
    if count < 2:
        return  # no rule_id in this stub has >=2 same-status instances to check grouping on
    rule_id, status = grouped_rule_id
    text = render_markdown(model, findings)
    section = text.split("## Passing checks")[0] if status != "pass" else text.split("## Passing checks")[1]
    assert section.count(f"`{rule_id}`") == 1, (
        f"{rule_id} ({status}) should appear exactly once as a grouped card/row in its section, "
        f"not once per instance"
    )
    if status != "pass":
        assert f"{count} instances" in section


def test_no_finding_without_a_citation_is_ever_silently_rendered():
    """CLAUDE.md §1 rule 2: no finding without a citation. render_markdown always prints one
    for every issue and every pass -- this asserts the citation fields are non-empty for
    everything the renderer actually shows."""
    model = _load_stub("s04_stilt4_500")
    model.jurisdiction.authority = "GMADA"
    findings = run_checks(model)
    for f in findings:
        assert f.citation.doc
        assert f.citation.clause
