# BuildWise

Pre-submission compliance checker for building drawings in Punjab (GMADA/PUDA) and Chandigarh
(UT). Upload a drawing, get back violations, ambiguities, and verified fixes — before it enters
the official approval loop.

BuildWise never outputs "approved" or "compliant." It is not a sanction, and it never claims to
be one. Every run instead reports **`pre-submission check: N issues found`**, with a citation
(rule id, source document, clause, version) attached to every single finding.

## Why this exists

Submitting a building plan to GMADA/PUDA or a Chandigarh authority is a slow, opaque loop: you
submit, wait weeks, and get objections back that a second pass over the bylaws would have caught.
BuildWise runs that second pass *before* submission — real geometry checks against the actual
rule text, not a generic checklist.

The target user is an **empanelled architect** (GMADA-approved, able to self-certify residential
plots up to 500 sq yd under deemed approval) — someone who carries real liability for what they
submit and needs to know, concretely, what a reviewer would flag.

## Non-negotiable design rules

These constrain every line of code in this repo, not just the pitch:

1. **No LLM ever produces a number or a verdict.** Every pass/fail, every setback, every area
   comes from deterministic code (`shapely` geometry, plain arithmetic). Models are only used to
   classify labels and write prose — with one narrow, tightly-fenced exception: transcribing a
   number that's physically printed in a source PDF, and only when two independent transcription
   passes agree exactly.
2. **Every finding carries a citation.** No citation, no finding.
3. **All geometry goes through `shapely`.** No hand-rolled polygon math or trigonometry.
4. **Internal units are metres and square metres.** Punjab practice uses sq yards; the conversion
   happens at the display layer only, and both units are shown in output.
5. **Never say "approved" or "compliant."** See above.
6. **Numeric rule values are seeded, not trusted, until verified.** Every rule pack value carries
   a `status` (`verified` / `seed_unverified` / `conflict` / `not_stated`) plus its source clause.
   Declared uncertainty beats fake precision.
7. **A missing input is `status: unknown`, never a silent pass.** No zoning plan on file? The
   containment check reports `unknown`, not `pass`.

The full specification these rules come from is [`CLAUDE.md`](CLAUDE.md) — the project's own
build brief, kept in the repo because every design decision below traces back to it.

## What it actually checks

Rules are authored as data (YAML), not code, so adding a jurisdiction means writing a rule pack,
not branching the engine:

| Jurisdiction | Rule pack | Rules | Enforced today |
|---|---|---|---|
| Mohali (GMADA) | Punjab Urban Planning & Development Authority (Building) Rules, 1996 | 30 | 22 |
| Chandigarh (UT) | Chandigarh Building Rules (Urban), 2017 | 20 | 6 |

"Enforced" vs. total is disclosed, not hidden — a rule that's transcribed and two-pass verified
but blocked on a genuine ambiguity (e.g. marla/kanal plot-size bands) stays in the pack as
`enforced: false` with the reason recorded, rather than being silently dropped or guessed at.

The flagship check is **zoned-area containment**: does the building footprint sit inside the
polygon PUDA's zoning plan actually allows, not just a generic front/rear/side setback formula.
Coverage, FAR, height/storeys, room minimums, light & ventilation ratio, staircase dimensions,
and more follow the same pattern — see `packages/rules/packs/*.yaml`.

## Ambiguity, not just violation

A big share of the value here isn't the pass/fail list — it's the cases where the rules
themselves are genuinely unclear, and BuildWise says so explicitly instead of guessing:
`missing_input`, `instrument_conflict` (e.g. the 2021 rules vs. a plot's own zoning plan vs. a
later circular), `vintage` (which rule generation applies to an older allotment), `discretionary`
("may be permitted by the competent authority"), and `definitional` (does a stilt count toward
FAR?). Each one gets a dossier: both readings, which is safer, and a submission-ready
justification paragraph the architect can attach.

## Architecture

```
corpus/     PDF bylaws -> clauses.jsonl -> transcribed + two-pass-verified rule YAML
packages/
  schema/   The frozen contract every other package codes against (BuildingModel, Finding)
  parser/   DXF/PDF/DWG ingestion, multi-sheet assembly (a "case" is a building, not a file)
  rules/    The rule engine + jurisdiction packs (data-driven, not hardcoded per jurisdiction)
  solver/   Brute-force, fully-re-verified fix search (fixing one violation can't be allowed
            to silently break another rule)
  ambiguity/  Classification + submission-ready justification dossiers
  report/   Overlay/PDF/HTML rendering
  api/      FastAPI backend
web/        React frontend (upload -> confirm model -> findings -> report)
tests/      143 tests, segmented so synthetic fixtures never get reported as real accuracy
```

### From upload to findings

1. **Ingest**: a DXF, vector PDF, or DWG (converted server-side via the free
   [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)) is parsed for
   geometry. A DXF/DWG with multiple named layout tabs (a whole sheet set in one file) is split
   automatically by reading each tab's own name — no manual labeling required.
2. **Assemble**: a building is a *sheet set*, not a file — ground/upper plans, section,
   elevations, and a site/zoning sheet are combined into one `BuildingModel`, in metres, with
   every uncertain inference recorded verbatim in `assumptions` rather than silently resolved.
3. **Confirm**: low-confidence extractions (a mislabeled room, an unverified sheet role) are
   surfaced for a one-click human confirmation before any rule runs against them.
4. **Check**: the rule engine evaluates the model against the jurisdiction's pack. Every result is
   a `Finding` — `violation` / `ambiguity` / `advisory` / `pass` / `unknown` — each with its
   citation.
5. **Fix**: for violations with a known remedy shape, a grid-search solver proposes geometric
   edits (shrink a wall, trim a projection) and **re-runs the entire rule pack** against each
   candidate, keeping only ones that don't regress a different rule elsewhere.
6. **Report**: findings, the overlay, and (where relevant) ambiguity dossiers export to PDF/HTML,
   always with the "pre-submission check" framing, never a verdict.

## Running it

```bash
# Backend
pip install -r requirements.txt
python -m packages.api.main          # http://127.0.0.1:8000

# Frontend (separate terminal)
cd web
npm install
npm run dev                          # prints its local URL, typically http://localhost:5173
```

DWG uploads require the [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
installed on the machine running the backend (a free, official, non-pip-installable desktop tool
— no open-source library reads native DWG). PDF and DXF need nothing extra. If the converter
isn't found, a DWG upload fails loudly with install instructions rather than silently skipping
the file; point `CHD_ODA_CONVERTER_PATH` at it directly if it isn't in a default install location.

```bash
python -m pytest tests/ -q           # 143 tests
make corpus                          # re-run PDF -> clauses -> rule YAML -> verify -> REPORT.md
make eval                            # findings vs. truth, precision/recall (segmented by provenance)
```

## Status

Past first integration (Stage 2 of the build plan in `CLAUDE.md` §11): upload → parse → assemble
→ confirm → check → report runs end to end on real drawings, across two jurisdictions, with real
DWG/DXF/PDF ingestion.

Known, disclosed gaps rather than silent ones:

- Site/zoning sheet parsing (plot polygon + zoned-area tracing) isn't implemented yet — containment
  correctly reports `unknown` rather than a guessed pass.
- Several Chandigarh rules (ground coverage, FAR, height/storeys by plot-size band) are
  transcribed and verified but held at `enforced: false` pending marla/kanal band resolution.
- `make eval`'s headline numbers are computed from real and mutated-real cases only — synthetic
  fixtures are a smoke test, never reported as accuracy (`packages/cases/real/` is gitignored;
  real drawings carry owner names and plot numbers and never enter version control).

See [`INTEGRATION.md`](INTEGRATION.md) for the detailed, dated log of what was built, what broke,
and why — kept as the running record between the project's parallel work tracks.
