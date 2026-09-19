"""Stage 0 exit criterion (CLAUDE.md §11): the six stubs must validate against the frozen
schema. This is deliberately not test_eval.py (CLAUDE.md §10.6/§12) -- eval measures parser
fidelity and rule correctness against truth files, which only exist once real/mutated cases
are labeled. This just guards the contract stubs/ and downstream tracks build against.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from packages.schema import BuildingModel

STUB_DIR = pathlib.Path(__file__).resolve().parents[1] / "packages" / "cases" / "stubs"

EXPECTED_STUBS = {
    "s01_clean_250",
    "s02_setback_rear",
    "s03_far_over",
    "s04_stilt4_500",
    "s05_no_zoning",
    "s06_low_conf",
}


def test_all_expected_stubs_present():
    found = {p.stem.removesuffix(".model") for p in STUB_DIR.glob("*.model.json")}
    assert EXPECTED_STUBS <= found, f"missing stubs: {EXPECTED_STUBS - found}"


def test_stubs_validate_against_frozen_schema():
    for path in STUB_DIR.glob("*.model.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        BuildingModel.model_validate(data)  # raises on any contract violation


def test_s05_has_no_zoned_area():
    data = json.loads((STUB_DIR / "s05_no_zoning.model.json").read_text(encoding="utf-8"))
    assert data["zoned_area"] is None, "s05 must exercise the missing-zoning-plan path"


def test_s06_has_low_confidence_rooms():
    data = json.loads((STUB_DIR / "s06_low_conf.model.json").read_text(encoding="utf-8"))
    confidences = {r["confidence"] for f in data["floors"] for r in f["rooms"]}
    assert "low" in confidences, "s06 must exercise the confirmation-screen path"
