"""`make eval` (CLAUDE.md §10.6, §12). Two things, kept separate because they fail for different
reasons: parser fidelity (parsed BuildingModel vs. frozen truth, per-field) and rule correctness
(findings vs. truth findings on mutated cases, precision on `violation` near 100%).

Metrics are segmented by provenance and NEVER pooled (CLAUDE.md §10.3). Headline numbers come
only from provenance in {"real", "mutated_real"}; synthetic is a smoke test, not a result.

This is the Stage-0 skeleton: it establishes the segmentation/banner contract so tracks A and B
can add real assertions in Stage 1+ without re-deciding this structure. It intentionally does not
yet compute precision/recall -- there are no truth files and no rule engine yet to evaluate.
"""

from __future__ import annotations

import json
import pathlib

CASES_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases"
TRUTH_DIR = CASES_DIR / "truth"


def _truth_cases_by_provenance() -> dict[str, list[pathlib.Path]]:
    by_provenance: dict[str, list[pathlib.Path]] = {"real": [], "mutated_real": [], "synthetic": []}
    if not TRUTH_DIR.exists():
        return by_provenance
    for path in TRUTH_DIR.glob("*.truth.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        prov = data.get("provenance", "synthetic")
        by_provenance.setdefault(prov, []).append(path)
    return by_provenance


def test_no_real_cases_banner():
    """Guards against ever reporting metrics without the loud banner CLAUDE.md §10.3 requires."""
    by_provenance = _truth_cases_by_provenance()
    real_count = len(by_provenance.get("real", [])) + len(by_provenance.get("mutated_real", []))
    if real_count == 0:
        print("\n" + "=" * 70)
        print("NO REAL CASES -- METRICS ARE NOT MEANINGFUL")
        print("=" * 70)
    # Not a failing assertion: the absence of real cases is expected pre-Stage-2 and is a status
    # to surface loudly, not a reason to fail the test suite outright.
    assert True


def test_metrics_never_pool_across_provenance():
    """Placeholder for the real precision/recall computation (Track A/B, Stage 4). Once
    packages/cases/truth/*.truth.json and packages/rules/engine.py exist, this should:
      1. Load each truth case's frozen BuildingModel and expected findings.
      2. Run the real parser (Track A) and rules engine (Track B) against it.
      3. Compute parser-fidelity and rule-correctness metrics SEPARATELY per provenance bucket.
      4. Assert precision on status="violation" is near 100% for the "real"+"mutated_real"
         buckets specifically (a false positive here is the failure CLAUDE.md §10.6 calls out
         as unacceptable) -- never assert it against a pooled/blended number.
    """
    by_provenance = _truth_cases_by_provenance()
    assert set(by_provenance.keys()) >= {"real", "mutated_real", "synthetic"}
