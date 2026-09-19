"""Run the pre-submission check end to end and print the findings, no server needed.

Usage:
    python tools/run_check.py h01                     # a real case under packages/cases/real/
    python tools/run_check.py h01 --authority GMADA    # override jurisdiction before checking
    python tools/run_check.py s02_setback_rear         # a stub under packages/cases/stubs/
    python tools/run_check.py h01 --json               # machine-readable output
    python tools/run_check.py h01 --authority GMADA --markdown -o report.md   # full report file

CLAUDE.md §5: this never prints "approved" or "compliant" -- only
"pre-submission check: N issues found".
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.rules.engine import run_checks  # noqa: E402
from packages.schema import BuildingModel  # noqa: E402

STATUS_ORDER = {"violation": 0, "ambiguity": 1, "unknown": 2, "advisory": 3, "pass": 4}


def load_model(name: str) -> BuildingModel:
    real_meta = ROOT / "packages" / "cases" / "real" / name / f"{name}.meta.json"
    stub_path = ROOT / "packages" / "cases" / "stubs" / f"{name}.model.json"

    if real_meta.exists():
        from packages.parser.semantics import assemble_case
        return assemble_case(real_meta)
    if stub_path.exists():
        return BuildingModel.model_validate(json.loads(stub_path.read_text(encoding="utf-8")))
    raise SystemExit(
        f"no case or stub named {name!r}. Real cases: "
        f"{[p.name for p in (ROOT/'packages'/'cases'/'real').glob('*') if p.is_dir()]}. "
        f"Stubs: {[p.stem.removesuffix('.model') for p in (ROOT/'packages'/'cases'/'stubs').glob('*.model.json')]}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="case name under packages/cases/real/, or stub name under packages/cases/stubs/")
    ap.add_argument("--authority", default=None, help="override jurisdiction.authority, e.g. GMADA (simulates confirming it on-screen)")
    ap.add_argument("--json", action="store_true", help="print findings as JSON instead of a table")
    ap.add_argument("--markdown", action="store_true", help="print a full Markdown report (bylaws cited + every issue) instead of a table")
    ap.add_argument("-o", "--out", default=None, help="write output to this file instead of stdout (works with --markdown or --json)")
    args = ap.parse_args()

    model = load_model(args.name)
    if args.authority:
        model.jurisdiction.authority = args.authority

    if model.assumptions:
        print(f"--- assumptions the parser recorded for {args.name} ---", file=sys.stderr)
        for a in model.assumptions:
            print(f"  - {a}", file=sys.stderr)
        print(file=sys.stderr)

    findings = run_checks(model)

    if args.markdown:
        from packages.report.render import render_markdown
        text = render_markdown(model, findings)
        if args.out:
            pathlib.Path(args.out).write_text(text, encoding="utf-8")
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            print(text)
        return

    if args.json:
        text = json.dumps([f.model_dump(mode="json") for f in findings], indent=2)
        if args.out:
            pathlib.Path(args.out).write_text(text, encoding="utf-8")
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            print(text)
        return

    issues = sum(1 for f in findings if f.status != "pass")
    print(f"pre-submission check: {issues} issues found  (total findings: {len(findings)})")
    print(dict(Counter(f.status for f in findings)))
    print()
    for f in sorted(findings, key=lambda f: STATUS_ORDER[f.status]):
        obs = round(f.observed, 3) if isinstance(f.observed, float) else f.observed
        req = round(f.required, 3) if isinstance(f.required, float) else f.required
        print(
            f"[{f.status.upper():9s}] {f.rule_id:42s} obs={str(obs):>10s} req={str(req):>10s}  "
            f"cite={f.citation.doc}:{f.citation.clause} ({f.citation.status})"
        )


if __name__ == "__main__":
    main()
