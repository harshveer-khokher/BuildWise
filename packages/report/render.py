"""Report rendering: HTML (Jinja2) and PDF (reportlab), CLAUDE.md §11 Stage 1 / §14.

Unit conversion happens ONLY here (CLAUDE.md §1 rule 4): everything upstream (schema, rules,
solver) stays in metres/square metres, and 1 sq m = 1.196 sq yd is applied at this display
layer alone, never persisted back into a BuildingModel or a Finding.

CLAUDE.md §5 non-negotiable: never output "approved" or "compliant." The summary line is always
`pre-submission check: N issues found`, and the footer states plainly that this is not a
sanction. Both PDF and HTML renderers go through the same `_report_context()` so that invariant
can't drift between the two output formats.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from packages.schema import BuildingModel, Finding

SQM_TO_SQYD = 1.196
"""CLAUDE.md §1 rule 4. Mohali practice uses sq yards; both units appear in output."""

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "corpus" / "MANIFEST.json"

_STATUS_ORDER = {"violation": 0, "ambiguity": 1, "unknown": 2, "advisory": 3, "pass": 4}
_STATUS_LABEL = {
    "violation": "🔴 Violation",
    "ambiguity": "🟠 Ambiguity",
    "unknown": "⚪ Unknown",
    "advisory": "🔵 Advisory",
    "pass": "🟢 Pass",
}

_BANNED_WORDS = ("approved", "compliant")
"""Never let generation logic accidentally introduce sanction language (CLAUDE.md §5). Checked
by tests, not just documented here. Note "compliance" (e.g. "not a certificate of compliance")
is fine — it's the negated noun the footer is required to use; only the bare verdict words are
banned."""


def sqm_to_sqyd(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * SQM_TO_SQYD, 2)


def summary_line(findings: list[Finding]) -> str:
    """`pre-submission check: N issues found` — never "approved"/"compliant" (CLAUDE.md §5).

    An "issue" is any finding that isn't a clean pass: violation, ambiguity, advisory, and
    unknown all count, because none of those four are safe to submit on without a human reading
    them (unknown least of all — missing zoning/height data isn't a pass, CLAUDE.md §5/§10.1).
    """
    n_issues = sum(1 for f in findings if f.status != "pass")
    return f"pre-submission check: {n_issues} issues found"


def _report_context(model: BuildingModel, findings: list[Finding]) -> dict[str, Any]:
    plot_area_sqm = model.plot_area_sqm
    return {
        "report_title": "mohali-check pre-submission report",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "summary_line": summary_line(findings),
        "jurisdiction": model.jurisdiction,
        "plot_area_sqm": plot_area_sqm if plot_area_sqm is not None else "unknown",
        "plot_area_sqyd": sqm_to_sqyd(plot_area_sqm) if plot_area_sqm is not None else "unknown",
        "zoned_area_present": model.zoned_area is not None,
        "findings": findings,
        "assumptions": model.assumptions,
    }


def _load_doc_titles() -> dict[str, dict[str, str]]:
    """doc_id -> {title, doc_type, effective_from} from corpus/MANIFEST.json, so a report can
    name "Punjab Urban Planning and Development Authority (Building) Rules, 1996" instead of
    just the bare doc_id. Read-only, falls back to the doc_id itself if the manifest is missing
    or a doc_id isn't in it -- never blocks report generation on this being unavailable."""
    if not _MANIFEST_PATH.exists():
        return {}
    try:
        manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        d["doc_id"]: {
            "title": d.get("title", d["doc_id"]),
            "doc_type": d.get("doc_type", "unknown"),
            "effective_from": d.get("effective_from", "unknown"),
        }
        for d in manifest.get("documents", [])
    }


def render_markdown(model: BuildingModel, findings: list[Finding]) -> str:
    """A single self-contained Markdown report: which bylaws were checked (with full titles,
    not just doc_ids), every issue with its citation, and a plain pass list -- everything
    CLAUDE.md §1 rule 2 requires (no finding without a citation) laid out for a human to read
    top to bottom, not just machine-consumed. Shares `_report_context()` with render_html/
    render_pdf so the numbers and footer language can't drift between formats.
    """
    ctx = _report_context(model, findings)
    j = ctx["jurisdiction"]
    doc_titles = _load_doc_titles()
    lines: list[str] = []

    lines.append(f"# {ctx['report_title']}")
    lines.append("")
    lines.append(f"*Generated {ctx['generated_at']}*")
    lines.append("")
    lines.append(f"## {ctx['summary_line']}")
    lines.append("")
    lines.append(
        "> This is a **pre-submission check only**. It is not an approval, not a sanction, "
        "and not a certificate of compliance by GMADA, PUDA, or any authority."
    )
    lines.append("")

    # --- Plot & jurisdiction -------------------------------------------------------------
    lines.append("## Plot & jurisdiction")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Authority | {j.authority} |")
    lines.append(f"| Sector / Plot no. | {j.sector or '*unknown*'} / {j.plot_no or '*unknown*'} |")
    lines.append(f"| Rule pack | `{j.rule_pack}` |")
    lines.append(f"| Allotment date | {j.allotment_date or '*unknown*'} |")
    if ctx["plot_area_sqm"] == "unknown":
        lines.append("| Plot area | *unknown — no site/zoning sheet on file* |")
    else:
        lines.append(f"| Plot area | {ctx['plot_area_sqm']} sq m ({ctx['plot_area_sqyd']} sq yd) |")
    zoned = "yes" if ctx["zoned_area_present"] else "**no — containment check is `unknown`, never `pass`**"
    lines.append(f"| Zoned area on file | {zoned} |")
    lines.append("")

    # --- Bylaws checked --------------------------------------------------------------------
    cited_docs: dict[str, dict[str, Any]] = {}
    for f in findings:
        doc_id = f.citation.doc
        entry = cited_docs.setdefault(
            doc_id,
            {"clauses": set(), "count": 0, "statuses": {}, "version": f.citation.version},
        )
        entry["clauses"].add(f.citation.clause)
        entry["count"] += 1
        entry["statuses"][f.citation.status] = entry["statuses"].get(f.citation.status, 0) + 1

    lines.append("## Bylaws checked")
    lines.append("")
    if not cited_docs:
        lines.append("*No findings were produced, so no bylaw was actually cited.*")
    else:
        lines.append("| Document | Version | Clauses cited | Findings | Verification status |")
        lines.append("|---|---|---|---|---|")
        for doc_id in sorted(cited_docs):
            entry = cited_docs[doc_id]
            title = doc_titles.get(doc_id, {}).get("title", doc_id)
            clause_list = ", ".join(f"§{c}" for c in sorted(entry["clauses"]))
            status_str = ", ".join(f"{k}: {v}" for k, v in sorted(entry["statuses"].items()))
            lines.append(
                f"| {title} (`{doc_id}`) | {entry['version']} | {clause_list} | "
                f"{entry['count']} | {status_str} |"
            )
    lines.append("")
    lines.append(
        "*Verification status per CLAUDE.md §6.5: `verified` = two independent transcription "
        "passes agreed exactly; `seed_unverified` = value transcribed but not yet independently "
        "confirmed against the gazette; `conflict` = passes disagreed, rule disabled; "
        "`not_stated` = the clause text does not state a number for this case.*"
    )
    lines.append("")

    # --- Issues (everything that isn't a clean pass) ---------------------------------------
    # Grouped by rule_id: several findings sharing one rule_id (one per room/floor/edge) share
    # one citation/remedy set and would otherwise repeat as near-identical cards -- group them
    # into one card with an instance count so a real multi-room drawing stays readable instead
    # of producing N duplicate blocks for the same bylaw provision.
    issues = [f for f in findings if f.status != "pass"]
    passes = [f for f in findings if f.status == "pass"]

    def _group(fs: list[Finding]) -> list[list[Finding]]:
        groups: dict[str, list[Finding]] = {}
        order: list[str] = []
        for f in fs:
            if f.rule_id not in groups:
                groups[f.rule_id] = []
                order.append(f.rule_id)
            groups[f.rule_id].append(f)
        return [groups[rid] for rid in order]

    issue_groups = sorted(_group(issues), key=lambda g: _STATUS_ORDER[g[0].status])

    lines.append(f"## Issues ({len(issues)})")
    lines.append("")
    if not issues:
        lines.append("*None — every enforced check either passed or could not be evaluated (see Bylaws checked above for what was actually run).*")
        lines.append("")
    import re as _re

    for group in issue_groups:
        f0 = group[0]
        title_doc = doc_titles.get(f0.citation.doc, {}).get("title", f0.citation.doc)
        titles = {f.title for f in group}
        if len(titles) > 1:
            # Titles differ only by a trailing "(front)"/"(floor 0)"-style qualifier -- show the
            # shared prefix in the header rather than one instance's qualifier standing in for
            # all of them; the per-instance table below still shows each one in full.
            heading_title = _re.sub(r"\s*\([^()]*\)\s*$", "", f0.title).rstrip()
        else:
            heading_title = f0.title
        count_suffix = f" — {len(group)} instances" if len(group) > 1 else ""
        lines.append(f"### {_STATUS_LABEL[f0.status]} — {heading_title}{count_suffix}")
        lines.append("")
        lines.append(f"- **Rule ID:** `{f0.rule_id}`")
        lines.append(f"- **Severity:** {f0.severity}")
        lines.append(
            f"- **Citation:** {title_doc}, clause §{f0.citation.clause} "
            f"(v{f0.citation.version}, `{f0.citation.status}`)"
        )
        if f0.ambiguity_class:
            lines.append(f"- **Ambiguity class:** `{f0.ambiguity_class}`")
        lines.append(f"- **Compoundable:** {'yes' if f0.compoundable else 'no'}")

        distinct = {(f.title, f.observed, f.required) for f in group}
        if len(group) == 1 or len(distinct) == 1:
            obs = "—" if f0.observed is None else f0.observed
            req = "—" if f0.required is None else f0.required
            lines.append(f"- **Observed:** {obs}  |  **Required:** {req}")
        else:
            lines.append("- **Instances:**")
            lines.append("")
            lines.append("  | Detail | Observed | Required |")
            lines.append("  |---|---|---|")
            for f in group:
                obs = "—" if f.observed is None else f.observed
                req = "—" if f.required is None else f.required
                lines.append(f"  | {f.title} | {obs} | {req} |")

        all_remedies = [(f, r) for f in group for r in f.remedies]
        if all_remedies:
            lines.append("- **Remedies:**")
            seen_desc = set()
            for _f, r in all_remedies:
                if r.description in seen_desc:
                    continue
                seen_desc.add(r.description)
                area = f" (~{r.area_lost_sqm} sq m)" if r.area_lost_sqm is not None else ""
                lines.append(f"  - `{r.kind}`{area}: {r.description}")
        lines.append("")

    # --- Passing checks (brief, also grouped) ------------------------------------------------
    pass_groups = _group(passes)
    lines.append(f"## Passing checks ({len(passes)})")
    lines.append("")
    if pass_groups:
        lines.append("| Rule ID | Title | Instances | Citation |")
        lines.append("|---|---|---|---|")
        for group in pass_groups:
            f0 = group[0]
            n = f" ×{len(group)}" if len(group) > 1 else ""
            lines.append(
                f"| `{f0.rule_id}` | {f0.title}{n} | {len(group)} | "
                f"{f0.citation.doc} §{f0.citation.clause} |"
            )
    else:
        lines.append("*None.*")
    lines.append("")

    # --- Assumptions -------------------------------------------------------------------------
    if ctx["assumptions"]:
        lines.append("## Assumptions made while reading the drawing")
        lines.append("")
        lines.append(
            "*Printed verbatim, per CLAUDE.md §5 — every silent inference the parser made is "
            "listed here rather than hidden.*"
        )
        lines.append("")
        for a in ctx["assumptions"]:
            lines.append(f"- {a}")
        lines.append("")

    # --- Footer --------------------------------------------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append(
        "**This is a pre-submission check only.** It is not an approval, not a sanction, and "
        "not a certificate of compliance by GMADA, PUDA, or any authority."
    )
    lines.append("")
    lines.append(
        "Numeric rule values are seeded from source clauses and carry their own verification "
        "status per finding (see each issue's citation above). Values not marked `verified` "
        "have not been independently diffed against the gazette and must be confirmed before "
        "submission."
    )
    lines.append("")
    lines.append("1 sq m = 1.196 sq yd. All internal computation is in metres/square metres.")
    lines.append("")

    text = "\n".join(lines)
    _assert_no_banned_language(text)
    return text


def render_html(model: BuildingModel, findings: list[Finding]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("report.html.j2")
    html = template.render(**_report_context(model, findings))
    _assert_no_banned_language(html)
    return html


def render_pdf(model: BuildingModel, findings: list[Finding]) -> bytes:
    """Render the same content as `render_html` as an actual PDF via reportlab platypus.

    reportlab was chosen over weasyprint because it's a pure-ish, quick-to-install wheel with no
    system library dependencies (weasyprint needs Pango/Cairo, which is a bad bet mid-hackathon
    on an unknown machine) — see the comment in packages/api/main.py for the same tradeoff on
    the web framework choice. This does not consume the Jinja2 HTML template; it builds the PDF
    structurally from the same `_report_context`, so both renderers are one function call away
    from the same underlying data and can't disagree on the numbers, only on layout.
    """
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    ctx = _report_context(model, findings)
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    normal = styles["Normal"]
    small = ParagraphStyle("small", parent=normal, fontSize=8, textColor=colors.HexColor("#475467"))
    footer_bold = ParagraphStyle(
        "footer_bold", parent=normal, fontSize=9, fontName="Helvetica-Bold"
    )
    banner_style = ParagraphStyle(
        "banner", parent=normal, fontSize=12, fontName="Helvetica-Bold", spaceAfter=10
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=ctx["report_title"],
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    story: list[Any] = []
    story.append(Paragraph(ctx["report_title"], title_style))
    story.append(Paragraph(f"Generated {ctx['generated_at']}", small))
    story.append(Spacer(1, 8))
    story.append(Paragraph(ctx["summary_line"], banner_style))

    j = ctx["jurisdiction"]
    meta_rows = [
        ["Authority", j.authority, "Rule pack", j.rule_pack],
        ["Sector / Plot", f"{j.sector or '?'} / {j.plot_no or '?'}", "Allotment date", str(j.allotment_date or "unknown")],
        [
            "Plot area",
            f"{ctx['plot_area_sqm']} sq m ({ctx['plot_area_sqyd']} sq yd)",
            "Zoned area on file",
            "yes" if ctx["zoned_area_present"] else "NO - containment check is unknown, not pass",
        ],
    ]
    meta_table = Table(meta_rows, colWidths=[32 * mm, 55 * mm, 32 * mm, 55 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"Findings ({len(findings)})", styles["Heading2"]))
    header = ["Status", "Sev.", "Rule", "Title", "Obs.", "Req.", "Citation", "Comp."]
    rows = [header]
    status_colors = {
        "violation": colors.HexColor("#d92d20"),
        "ambiguity": colors.HexColor("#b54708"),
        "unknown": colors.HexColor("#667085"),
        "advisory": colors.HexColor("#175cd3"),
        "pass": colors.HexColor("#027a48"),
    }
    for f in findings:
        title = f.title
        if f.ambiguity_class:
            title += f" (ambiguity: {f.ambiguity_class})"
        citation = f"{f.citation.doc} §{f.citation.clause} (v{f.citation.version}, {f.citation.status})"
        rows.append(
            [
                f.status,
                f.severity,
                f.rule_id,
                Paragraph(title, small),
                "—" if f.observed is None else str(f.observed),
                "—" if f.required is None else str(f.required),
                Paragraph(citation, small),
                "yes" if f.compoundable else "no",
            ]
        )

    findings_table = Table(
        rows,
        colWidths=[16 * mm, 12 * mm, 26 * mm, 42 * mm, 14 * mm, 14 * mm, 38 * mm, 12 * mm],
        repeatRows=1,
    )
    table_style_cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d5dd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, f in enumerate(findings, start=1):
        color = status_colors.get(f.status)
        if color:
            table_style_cmds.append(("TEXTCOLOR", (0, i), (0, i), color))
    findings_table.setStyle(TableStyle(table_style_cmds))
    story.append(findings_table)
    story.append(Spacer(1, 10))

    if ctx["assumptions"]:
        story.append(Paragraph("Assumptions made during parsing (printed verbatim)", styles["Heading3"]))
        for a in ctx["assumptions"]:
            story.append(Paragraph(f"• {a}", normal))
        story.append(Spacer(1, 10))

    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "This is a pre-submission check only. It is not an approval, not a sanction, and "
            "not a certificate of compliance by GMADA, PUDA, or any authority.",
            footer_bold,
        )
    )
    story.append(
        Paragraph(
            "Numeric rule values are seeded from source clauses and carry their own "
            "verification status per finding (verified / seed_unverified / conflict / "
            "not_stated) &mdash; see the citation column. Values not marked “verified” "
            "have not been diffed against the gazette and must be independently confirmed "
            "before submission.",
            small,
        )
    )
    story.append(
        Paragraph(
            "1 sq m = 1.196 sq yd. All internal computation is in metres/square metres; sq yd "
            "figures shown here are for display only.",
            small,
        )
    )

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


def _assert_no_banned_language(text: str) -> None:
    lowered = text.lower()
    for word in _BANNED_WORDS:
        if word in lowered:
            raise AssertionError(
                f"Report text contains banned sanction language {word!r} (CLAUDE.md §5). "
                "This is a bug in the template or render logic, not something to special-case."
            )
