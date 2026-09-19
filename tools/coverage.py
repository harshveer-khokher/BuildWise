"""corpus/extracted/<doc_id>/REPORT.md generator (CLAUDE.md §6.6).

The only thing a human is meant to read out of the whole `make corpus` pipeline. Reports, per
document: rules by status, orphan clauses (numeric/measurement content no rule consumes yet --
"what did we miss"), OCR pages, and table-transcription disagreements once tables.py exists.

Safe to run before any rule YAML exists (Stage 0): it then reports 0 rules authored and lists
every clause with numeric content as a to-do for rule synthesis, which is the honest state of
the pipeline at that point.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTRACTED_DIR = ROOT / "corpus" / "extracted"
PACKS_DIR = ROOT / "packages" / "rules" / "packs"

NUMERIC_HINT = re.compile(r"\d+(\.\d+)?\s*(%|per\s?cent|meter|metre|sq\.?\s?m|sqm|sq\.?\s?yd|storey|storeys)", re.IGNORECASE)


def load_clauses(doc_id: str) -> list[dict]:
    path = EXTRACTED_DIR / doc_id / "clauses.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_rule_clause_ids() -> set[str]:
    """Best-effort: scan pack YAML text for `clause:` values without requiring pyyaml, since
    tracks other than B may run this before pyyaml is on their machine."""
    clause_ids = set()
    if not PACKS_DIR.exists():
        return clause_ids
    for pack_path in PACKS_DIR.glob("*.yaml"):
        for line in pack_path.read_text(encoding="utf-8").splitlines():
            m = re.search(r'clause:\s*"?([\w:.#-]+)"?', line)
            if m:
                clause_ids.add(m.group(1))
    return clause_ids


def report_for_doc(doc_id: str, referenced_clause_ids: set[str]) -> str:
    health_path = EXTRACTED_DIR / doc_id / "extract_health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
    clauses = load_clauses(doc_id)

    numeric_clauses = [c for c in clauses if NUMERIC_HINT.search(c["text"])]
    orphans = [c for c in numeric_clauses if c["clause_id"] not in referenced_clause_ids]

    lines = [f"# Extraction health: {doc_id}", ""]
    lines.append(f"- doc_type: `{health.get('doc_type', 'unknown')}`")
    lines.append(f"- sha256: `{health.get('sha256', 'unknown')}`")
    lines.append(f"- pages: {health.get('page_count', '?')}")
    lines.append(f"- clauses extracted: {len(clauses)}")
    lines.append(f"- OCR-required pages: {health.get('ocr_pages', [])}")
    lines.append("")
    lines.append("## Numbering anomalies")
    lines.append("")
    anomalies = health.get("anomalies", [])
    if anomalies:
        for a in anomalies:
            lines.append(f"- {a}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Rule coverage")
    lines.append("")
    lines.append(f"- rules referencing this doc: {len(referenced_clause_ids & {c['clause_id'] for c in clauses})}")
    lines.append(f"- clauses with numeric/measurement content: {len(numeric_clauses)}")
    lines.append(f"- **orphan clauses (numeric content, no rule yet -- the to-do list): {len(orphans)}**")
    lines.append("")
    if orphans:
        for c in orphans:
            heading = c["heading"] or "(no heading)"
            lines.append(f"- `{c['clause_id']}` (p.{c['page']}) {heading}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    referenced = load_rule_clause_ids()
    doc_ids = [p.name for p in EXTRACTED_DIR.iterdir() if p.is_dir()] if EXTRACTED_DIR.exists() else []
    if not doc_ids:
        print("no extracted/<doc_id> directories found -- run tools/extract.py first", file=sys.stderr)
        return
    for doc_id in sorted(doc_ids):
        report = report_for_doc(doc_id, referenced)
        out_path = EXTRACTED_DIR / doc_id / "REPORT.md"
        out_path.write_text(report, encoding="utf-8")
        print(f"wrote {out_path.relative_to(ROOT)}")

    if not referenced:
        print(
            "\nNOTE: 0 rules found under packages/rules/packs/*.yaml. Every numeric clause "
            "above is listed as an orphan because rule synthesis (tools/transcribe.py + "
            "verify.py) has not run yet -- this is expected at Stage 0/early Stage 1, not a bug."
        )


if __name__ == "__main__":
    main()
