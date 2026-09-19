"""Rule synthesis pass 1: clause text -> proposed numeric rule facts (CLAUDE.md §6.4).

STRICT CONTRACT (do not weaken this):
  - Input to the model is ONLY the clause's own text (and its table, if any). Never the whole
    PDF, never neighbouring clauses, never the model's own prior output.
  - Output is transcription, not synthesis: every number must be traceable to a short quoted
    fragment of the clause text. If the clause doesn't state a number for some case, the model
    must emit {"value": null, "status": "not_stated"} for that case -- never infer from a
    neighbouring clause, another jurisdiction's bylaws, or general knowledge (CLAUDE.md §1 rule 1).
  - One clause may yield several proposed rule facts (one per plot-size band / room type / etc).
    One proposed fact never spans clauses.

This script does not itself embed a hardcoded numeric value anywhere -- it only shapes the
prompt and parses the model's JSON response. The actual model call is delegated to
`call_transcriber()`, which either:
  (a) calls a live LLM via the `anthropic` SDK if ANTHROPIC_API_KEY is set, or
  (b) replays a previously recorded response from a JSON cache file (--replay), which is how
      this repo's own `packages/rules/packs/puda_1996.yaml` was produced: two independent
      Claude Code subagent calls (see corpus/extracted/puda_building_rules_1996/rule_synthesis/
      transcribe_pass1.json and verify_pass1.json) with the exact prompts this script builds.

Usage:
    python tools/transcribe.py puda_building_rules_1996 --clauses 15#2,4#2,16,17,18,20,22,24,25,26 \
        --replay corpus/extracted/puda_building_rules_1996/rule_synthesis/transcribe_pass1.json \
        --out corpus/extracted/puda_building_rules_1996/rule_synthesis/transcribe_pass1.json

Without --replay and without ANTHROPIC_API_KEY set, the script exits with instructions rather
than silently fabricating a value (that would violate CLAUDE.md §1 rule 1 from the tooling side,
not just the model side).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTRACTED_DIR = ROOT / "corpus" / "extracted"

TRANSCRIBE_SYSTEM_PROMPT = """You are performing PURE TRANSCRIPTION of numeric values from legal \
clause text. You are NOT a legal expert, NOT a domain expert, and you must NOT infer, estimate, \
interpolate, or bring in outside knowledge of any other building code. Your only job: read the \
clause text given and extract every numeric requirement it states, verbatim, into structured \
JSON. If the clause text does NOT explicitly state a number for some case, you MUST emit that \
case with "value": null and "status": "not_stated" -- never guess, never borrow a value from a \
neighbouring clause or general knowledge of Indian building codes."""


def load_clauses(doc_id: str, numbers: list[str]) -> list[dict]:
    path = EXTRACTED_DIR / doc_id / "clauses.jsonl"
    if not path.exists():
        raise SystemExit(f"no clauses.jsonl for {doc_id} -- run tools/extract.py first")
    wanted = set(numbers)
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        if c["number"] in wanted:
            out.append(c)
    missing = wanted - {c["number"] for c in out}
    if missing:
        raise SystemExit(f"clause number(s) not found in {doc_id}: {sorted(missing)}")
    return out


def build_prompt(clauses: list[dict]) -> str:
    blocks = []
    for c in clauses:
        blocks.append(f"===CLAUSE {c['clause_id']}===\n{c['text']}\n===END===")
    schema_note = """
Respond with ONLY a JSON array (no prose, no markdown fences). Each element:
{
  "clause_id": "<the clause_id given>",
  "proposed_rule_key": "<short snake_case key for this specific numeric fact>",
  "description": "<one-line plain-English description>",
  "value": <number, or null>,
  "unit": "<percent|sqm|metres|ratio|centimetres|fraction_of_height|other>",
  "applies_to": "<condition this value applies under>",
  "status": "stated" or "not_stated",
  "quoted_fragment": "<exact short fragment (<=25 words) the number came from, verbatim>"
}
If a clause states several numbers for different bands/cases, emit one element per number.
"""
    return "\n\n".join(blocks) + "\n" + schema_note


def call_transcriber(prompt: str, replay_path: pathlib.Path | None) -> list[dict]:
    if replay_path is not None:
        if not replay_path.exists():
            raise SystemExit(f"--replay file not found: {replay_path}")
        return json.loads(replay_path.read_text(encoding="utf-8"))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "No ANTHROPIC_API_KEY set and no --replay cache given. Per CLAUDE.md §1 rule 1, "
            "this tool refuses to fabricate a value itself -- it only ever parses a model's "
            "transcription. Either set ANTHROPIC_API_KEY to run a live pass, or pass --replay "
            "pointing at a previously recorded transcription (see "
            "corpus/extracted/<doc_id>/rule_synthesis/transcribe_pass*.json)."
        )
    try:
        import anthropic  # type: ignore
    except ImportError:
        raise SystemExit("ANTHROPIC_API_KEY is set but the `anthropic` package is not installed.")

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-opus-4-5-20251101",
        max_tokens=4096,
        system=TRANSCRIBE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return json.loads(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id")
    ap.add_argument("--clauses", required=True, help="comma-separated clause numbers, e.g. 15#2,4#2,17")
    ap.add_argument("--replay", type=pathlib.Path, default=None)
    ap.add_argument("--out", type=pathlib.Path, default=None)
    args = ap.parse_args()

    numbers = [n.strip() for n in args.clauses.split(",") if n.strip()]
    clauses = load_clauses(args.doc_id, numbers)
    prompt = build_prompt(clauses)
    result = call_transcriber(prompt, args.replay)

    out_path = args.out or (EXTRACTED_DIR / args.doc_id / "rule_synthesis" / "transcribe_pass1.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {len(result)} proposed rule facts -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
