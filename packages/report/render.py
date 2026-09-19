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
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from packages.schema import BuildingModel, Finding

SQM_TO_SQYD = 1.196
"""CLAUDE.md §1 rule 4. Mohali practice uses sq yards; both units appear in output."""

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

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
