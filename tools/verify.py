"""Rule synthesis pass 2: independent verification (CLAUDE.md §6.5) -- the pass that removes
the human from the loop.

STRICT CONTRACT (do not weaken this):
  - The verifier sees ONLY: the proposed rule's numeric value (+ unit + applies_to label) and
    the RAW clause text it claims to come from. It NEVER sees the transcriber's reasoning,
    its quoted_fragment justification, or any other proposed rule.
  - It answers exactly one of "match" / "mismatch" / "not_stated" per proposed fact.

Verdict -> status mapping (CLAUDE.md §6.5 table), applied by build_pack.py / by hand when
assembling a rule pack from this output:
    match      -> status: verified,        citation locked
    mismatch   -> status: conflict,        both values retained, rule DISABLED
    not_stated -> status: seed_unverified, rule runs but report says value is unconfirmed

Same replay/live-call structure as transcribe.py, for the same reason: this script never
invents a verdict itself, it only shapes the prompt and parses the model's JSON response.

Usage:
    python tools/verify.py puda_building_rules_1996 \
        --proposed corpus/extracted/puda_building_rules_1996/rule_synthesis/transcribe_pass1.json \
        --clauses 15#2,4#2,16,17,18,20,22,24,25,26 \
        --replay corpus/extracted/puda_building_rules_1996/rule_synthesis/verify_pass1.json \
        --out corpus/extracted/puda_building_rules_1996/rule_synthesis/verify_pass1.json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTRACTED_DIR = ROOT / "corpus" / "extracted"

VERIFY_SYSTEM_PROMPT = """You are an independent VERIFICATION pass. You have NOT seen any \
other agent's reasoning. Someone else proposed that a clause states a certain numeric value. \
Your only job is to check, from the raw clause text alone, whether that number is actually \
stated for that case. Answer exactly one of match / mismatch / not_stated. Do not use outside \
knowledge of building codes."""

VERDICT_TO_STATUS = {
    "match": "verified",
    "mismatch": "conflict",
    "not_stated": "seed_unverified",
}


def load_clauses(doc_id: str, numbers: list[str]) -> dict[str, dict]:
    path = EXTRACTED_DIR / doc_id / "clauses.jsonl"
    if not path.exists():
        raise SystemExit(f"no clauses.jsonl for {doc_id} -- run tools/extract.py first")
    wanted = set(numbers)
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        if c["number"] in wanted:
            out[c["clause_id"]] = c
    return out


def build_prompt(proposed: list[dict], clauses_by_id: dict[str, dict]) -> str:
    text_blocks = []
    seen = set()
    for p in proposed:
        cid = p["clause_id"]
        if cid in seen or cid not in clauses_by_id:
            continue
        seen.add(cid)
        text_blocks.append(f"[{cid}]\n{clauses_by_id[cid]['text']}")

    stripped = [
        {
            "clause_id": p["clause_id"],
            "proposed_rule_key": p["proposed_rule_key"],
            "value": p["value"],
            "unit": p.get("unit"),
            "applies_to": p.get("applies_to"),
        }
        for p in proposed
    ]

    return (
        "=== RAW CLAUSE TEXTS ===\n\n"
        + "\n\n".join(text_blocks)
        + "\n\n=== PROPOSED (clause_id, key, value, unit, applies_to) TO CHECK ===\n\n"
        + json.dumps(stripped, indent=2)
        + '\n\nRespond with ONLY a JSON array: '
          '{"clause_id": "...", "proposed_rule_key": "...", "verdict": "match|mismatch|not_stated", "note": "..."}'
    )


def call_verifier(prompt: str, replay_path: pathlib.Path | None) -> list[dict]:
    if replay_path is not None:
        if not replay_path.exists():
            raise SystemExit(f"--replay file not found: {replay_path}")
        return json.loads(replay_path.read_text(encoding="utf-8"))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "No ANTHROPIC_API_KEY set and no --replay cache given. This tool refuses to "
            "fabricate a verdict itself -- either set ANTHROPIC_API_KEY for a live pass, or "
            "pass --replay pointing at a recorded verification (see "
            "corpus/extracted/<doc_id>/rule_synthesis/verify_pass*.json)."
        )
    try:
        import anthropic  # type: ignore
    except ImportError:
        raise SystemExit("ANTHROPIC_API_KEY is set but the `anthropic` package is not installed.")

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-opus-4-5-20251101",
        max_tokens=4096,
        system=VERIFY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return json.loads(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id")
    ap.add_argument("--proposed", type=pathlib.Path, required=True)
    ap.add_argument("--clauses", required=True)
    ap.add_argument("--replay", type=pathlib.Path, default=None)
    ap.add_argument("--out", type=pathlib.Path, default=None)
    args = ap.parse_args()

    numbers = [n.strip() for n in args.clauses.split(",") if n.strip()]
    proposed = json.loads(args.proposed.read_text(encoding="utf-8"))
    clauses_by_id = load_clauses(args.doc_id, numbers)
    prompt = build_prompt(proposed, clauses_by_id)
    result = call_verifier(prompt, args.replay)

    out_path = args.out or (EXTRACTED_DIR / args.doc_id / "rule_synthesis" / "verify_pass1.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    counts = {}
    for r in result:
        s = VERDICT_TO_STATUS.get(r["verdict"], "unknown")
        counts[s] = counts.get(s, 0) + 1
    print(f"wrote {len(result)} verdicts -> {out_path.relative_to(ROOT)}")
    print(f"status breakdown: {counts}")


if __name__ == "__main__":
    main()
