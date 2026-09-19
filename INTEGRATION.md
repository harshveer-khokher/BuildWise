# Integration notes

Cross-track requests go here. **Append, don't edit another track's package** (CLAUDE.md §1 rule 7,
§4). If you need something from another track, write the ask below with your track name and
what you need; the owning track picks it up.

---

## Stage 0 handoff (2026-09-19)

Schema is frozen (`packages/schema/building_model.py`, `packages/schema/findings.py`), six stubs
validated (`packages/cases/stubs/*.model.json`, `tests/test_stubs.py` passes), corpus ingested
(`corpus/extracted/*/clauses.jsonl` + `REPORT.md` for all four source PDFs). Everything below is
context every track should read before starting Stage 1.

### The corpus does not contain what CLAUDE.md's glossary names

CLAUDE.md's glossary says the current PUDA ruleset is "Building Rules 2021." The only base-rules
PDF actually supplied is **Punjab Urban Planning and Development Authority (Building) Rules,
1996** (`corpus/raw/puda_building_rules_1996.pdf`). No 2021 consolidated text and no intervening
amendment notifications were provided as separate documents. Do not name the rule pack
`puda_2021.yaml` — call it `puda_1996.yaml` and note the gap in the pack's own header. If a 2021
version or intervening amendments surface later, they ingest as their own `doc_id` with
`doc_type: amendment` per §6.8; until then, every rule sourced from 1996 text is at best a
plausible-but-outdated value, which is exactly what `status: seed_unverified` is for.

The other three PDFs are **not** building-dimension bylaws:
- `prtpd_general_rules_1995.pdf` — procedural (Board constitution, completion timelines, appeals).
  `doc_type: reference`. Can source procedural findings (e.g. completion-extension deadlines) but
  never a dimensional violation.
- `periphery_control_rules_1959.pdf` — Punjab New Capital (Periphery) Control Rules. This is the
  GIS/periphery constraint from the glossary, not a drawing check — feeds `gis/`, not the rules
  engine's pass/fail pack. Classified `doc_type: policy`.
- `papra_rules_1995.pdf` — apartment/plot allotment eligibility and promoter disclosure. Not
  related to building-dimension compliance; kept only in case an allotment-eligibility ambiguity
  ever needs a citation.

**No Municipal Building Byelaws 2018 (Kharar/Zirakpur) PDF was supplied.** Jurisdiction routing
(GMADA vs MC_KHARAR vs MC_ZIRAKPUR) can be implemented in `packages/schema`/`rules/engine.py`, but
`pmbb_2018.yaml` cannot be authored from real text yet — CLAUDE.md §7 calls a second pack "worth
more than five extra rules" for proving the engine is data-driven; that has to wait on the source
document, or be demonstrated instead with a hand-authored *placeholder* pack explicitly marked
`status: not_stated` end-to-end, not a real second jurisdiction.

### The 1996 building-rules PDF contains an embedded amendment to itself

Clauses at `puda_building_rules_1996:4#2` (p.22) and `puda_building_rules_1996:2#5` (p.24) read
"In the said Rules, for Rule 16, the following shall be substituted..." — i.e. later pages of the
*same PDF* amend Rule 16 (Floor Area Ratio) and Rule 15 (Site Coverage) from earlier pages. Track
B: when authoring FAR/coverage rules, use the amended text from these later clauses, not the
original Rule 15/16 text, and cite whichever clause the rules engine actually applies per the
precedence rule in CLAUDE.md §6.8 (still show both, both citations, if space allows — this is
close to a real `instrument_conflict` case even though it's self-contained in one file).

### Numeric tables collapsed into prose during extraction

`tools/extract.py` uses PyMuPDF's plain-text extraction, which flattens Site Coverage's plot-size
band table into a single run-on sentence (see `puda_building_rules_1996:15`: "For the first 210
Square meters 65% ... For the next 210 square meters 50% ... For the remaining area 40%"). The
numbers are present and legible, but this is exactly the merged-cell/multi-row-header failure mode
CLAUDE.md §6.3 warns about. `tools/transcribe.py` / a table-specific pass (pdfplumber first, vision
second, compare) still needs to run on these bands before any coverage/FAR/height/setback/ECS rule
can be marked `verified` rather than `seed_unverified`.

### Clause-numbering anomalies (see each doc's `REPORT.md`)

- `puda_building_rules_1996`: rule numbers 1/2/3 are reused across Parts (Part I's "3. Short
  title" vs. Part II's own "3. Erection or Re-erection..."). The chunker disambiguates as `3`,
  `3#2`, `3#3`, etc. — verify against the gazette before treating these as independent rules; the
  priority-list rules (site coverage=15, FAR=16, height/setback=17, projections=18, courtyard=20,
  room/light=22, basement=24, staircase=25, roof setback=26) all chunked cleanly with correct
  headings and no reuse, so §7's priority order should transcribe straightforwardly.
- `periphery_control_rules_1959`: heavy renumbering (47 anomalies) — this document restarts
  numbering repeatedly for fee schedules/forms. Track B should treat this doc's clause boundaries
  as unreliable below the top level and expect to hand-correct before authoring GIS-layer rules
  from it.
- `prtpd_general_rules_1995` and `papra_rules_1995` chunked cleanly (1 and 0 anomalies).

### Real drawings: house 1 / house 2 (`packages/cases/real/h01`, `h02`)

Both are **vector PDF sheet sets** (CAD-exported, real vector paths + text, not scans) — no
DXF/DWG was supplied, so per CLAUDE.md §10.4 these are **Tier B**, not the primary DWG/DXF set.

Both are missing:
- **A site/zoning sheet.** No plot polygon, no plot area, no zoned area. Per §5/§10.1, the
  containment check and every check that needs plot_area_sqm (coverage, FAR) must emit
  `status: unknown`, never guessed from the visible footprint.
- **A section sheet.** Per §10.1, `Floor.height_m` is only ever taken from a section; elevations
  are cross-check only. Height and storey-count rules will also be `unknown` for both houses as
  supplied.

h01 has 3 plan sheets (ground/first/second) + 3 elevations (front/rear/side). h02 has 3 plan
sheets + 2 elevations (no side elevation). Both are real, so they still count toward Tier B
metrics once truth files exist — but **do not expect a demo-able findings list out of either case
until a site/zoning plan and a section sheet are added**; that's a project-level gap, not
something to paper over in the parser (§10.3: never silently promote a guess to a pass). If a
zoning plan or section for either house shows up, drop it into `packages/cases/real/h0X/` and
update `h0X.meta.json`'s `missing_sheets`/`known_gaps`.

### Track A note: mutation source

Since neither real case has a digitized DXF (only vector PDF), `packages/cases/mutate.py`
(CLAUDE.md §10.5, works on DXF) cannot run against h01/h02 as supplied. Either convert one to DXF,
or generate the single required `synth/*.dxf` smoke file first and use it to validate the mutation
harness, then extend to h01/h02 once/if DXF versions arrive.

---

*(Append new entries below this line as Stage 1 proceeds.)*

---

## Advisory setback-formula buildable-envelope estimate (2026-09-20)

`packages/rules/estimated_envelope.py::estimate_buildable_envelope` -- a SEPARATE, clearly-labeled
estimate of the buildable envelope, computed from clause 17's generic setback formula (front/rear
>= max(height*0.25, 2m), side >= max(height*0.2, 1.5m), read live from the verified pack, never
duplicated as literals) applied to the user's entered plot width x length, now that a real
confirmed height exists (see the height-extraction entry below).

**This never touches `BuildingModel.zoned_area` or the real containment check.** CLAUDE.md's
glossary is explicit that the official, GMADA-issued zoning plan can override generic setbacks
(corner-plot rules, road-widening reservations, etc.) -- populating the real `zoned_area` field
with a formula-derived guess would make the flagship containment check look "solved" by an
unverified approximation. This is exposed as its own `estimated_envelope` object instead
(`available: true/false` + numbers + a note spelling out exactly how it was computed), for
`POST /cases/assemble` to return alongside (not instead of) the real model when the caller also
supplies `plot_width_m`/`plot_length_m`.

**Orientation is inferred, never asked of the user** (per explicit instruction): the ground
floor's own footprint has a width and a depth; the front elevation's own drawn width (real-world,
via the same `extract_drawing_bbox`/`estimate_scale_pts_per_m` already used for plan sheets) says
which of those is the road-facing one (a front elevation is a face-on view of exactly that
dimension); whichever of the user's entered plot width/length is numerically closer to that same
real-world figure is inferred as the plot's frontage edge. Verified on h01: footprint 8.32m x
11.73m, front elevation drawn width 7.45m -> correctly resolves to the FOOTPRINT'S WIDTH axis
being road-facing (7.45 is far closer to 8.32 than to 11.73), and for a 12.5m x 20.0m plot,
correctly resolves to the plot's *width* input as frontage. If either the footprint or the front
elevation can't be read cleanly, this returns `available: false` with the reason -- never a guess.

**A claim considered and rejected during this work**: a screenshot showed `lvl -90"` labels on
h01's front elevation, and it was suggested these might be a road-setback distance. They are not,
and can't be -- an elevation is a frontal projection (width x height only); the depth axis (how
far back from the road the building sits) is not represented in that view at all, from any
elevation. `-90"` is almost certainly another entry in the same per-floor `lvl` vertical-level
convention documented in the height-extraction entry below (probably a stone-clad wainscot/plinth
band's bottom edge), not a horizontal distance. Not implemented; flagged here so it isn't
mistakenly revisited as if it were a real, extractable setback value.

**Wired into `POST /cases/assemble`** (`packages/api/main.py`): optional `plot_width_m`/
`plot_length_m` text fields (already-converted-to-metres by the caller, per CLAUDE.md §1 rule 4)
trigger the estimate inline, using that same upload's own `ground`/`elevation_front`-role sheets
(still on disk in the request's temp directory at that point) -- response gains an
`estimated_envelope` key (`null` if plot size wasn't given). Tested end-to-end against real h01
sheets via the actual HTTP-shaped multipart flow, plus 5 direct unit tests for the underlying
function (orientation correctness, honest failure when setbacks exceed the plot, honest failure
without a confirmed height, and that the setback constants are read live from the pack rather than
hardcoded). Full suite: 103/103.

**Not yet done**: no frontend UI surfaces this estimate. The backend contract exists and is
tested; wiring a results-screen panel for it is a natural, comparatively small follow-up.

## Height from an elevation's own labeled dimension, confirmed against the real building (2026-09-20)

**Reverses the earlier "keep elevations cross-check only" decision recorded above (2026-09-19) --
on new evidence, not a casual override.** That earlier decision was about *heuristically* reading
a height off an elevation (counting arbitrary long strokes, or eyeballing an ambiguous `lvl ±0`
callout that turns out to recur at multiple different physical heights on the same sheet --
almost certainly a per-floor local datum, not one building-wide reference). This is different: a
real, *explicitly printed* overall-height dimension in the standard chain-dimension convention (a
run of small segments -- clear height, slab thickness, repeat -- bracketed by one larger "check"
dimension spanning a contiguous subset of them).

Found on h01's rear elevation: a left-margin chain reads `9" / 7' / 9" / 10'-3" / 9" / 10'-3" /
9" / 10'-3" / 2'-3"`, and a separate `"33'"` label matches the sum of the middle six segments
exactly (`9"+10'-3"+9"+10'-3"+9"+10'-3" = 396" = 33'-0"`). **The project owner independently
confirmed 33'-0" / 10.06m is the real, correct height of this building** before this was
implemented -- this was not assumed from the drawing alone. The excluded segments line up with
real features: the `7'+9"` above the bracket sits on the small rooftop mumty/tank (`lvl -111"` /
`-120"` labels) -- at 7' (2.13m) it's under the bylaw's own 2.25m mumty/tank exclusion (clause
§3); the `2'-3"` below the bracket is the plinth-to-road offset, and CLAUDE.md's height definition
starts measuring *at* plinth, not at road level.

**Implementation** (`packages/parser/pdf_ingest.py::extract_overall_height_m`): transforms text
positions into true display-space coordinates first (these sheets carry a `/Rotate 270` flag;
raw PyMuPDF coordinates are pre-rotation and would silently mis-order top/bottom -- verified
against known reference points, the two `ROAD lvl` labels landing at the bottom of the sheet post-
transform). Clusters dimension tokens sharing an x-position into vertical chains, then looks for
any *other* nearby token whose value equals the sum of a contiguous run of >=2 chain segments
(single-segment matches are excluded outright -- a regression caught during development where a
coincidental duplicate value elsewhere on the sheet trivially "matched" one lone chain segment and
returned a tiny wrong height; now the largest valid multi-segment match wins). Returns `(None,
None, note)` -- never a guess -- when no such bracket exists.

**Verified independently three times**: h01's front, rear, and side elevations all separately
yield the identical 10.0584m via their own chain/bracket, cross-validating both the confirmed
ground truth and the extraction method itself. h02's readable sheets yield a different but
internally-consistent 11.8872m (39') -- not independently confirmed against h02's real height,
so treat that one with more caution than h01's.

**Wired into `packages/parser/semantics.py`**: only trusts an elevation sheet for this if its
title block passes the same role-verification gate already used for the storey-count cross-check
(`sheet_title_matches_role`) -- this correctly excludes h02's `elevation_front.pdf`, which despite
its meta.json role is actually a "WOODEN JOINERY DETAIL" sheet (a real mismatch Track A found
earlier, not a new bug). Multiple elevation sheets disagreeing on height is surfaced as an
extraction ambiguity and `Floor.height_m` stays `None` on every floor rather than silently picking
one. When they agree and the matched segment count divides evenly across the assembled floors,
each floor gets its own share (top floor matched to the topmost segment group); otherwise the
whole total is assigned to the top floor only, since `_building_height_m()` sums non-`None`
values and either approach produces the correct total either way.

Updated: `packages/schema/building_model.py`'s `Floor.height_m` docstring (comment-only, not a
structural schema change) and `packages/parser/semantics.py`'s module docstring, both to state
this narrow exception plainly rather than the blanket "never from elevations" they said before.
`estimate_storey_count_from_elevation` (arbitrary long-stroke counting) is unaffected and remains
cross-check-only exactly as before -- this exception applies only to `extract_overall_height_m`'s
labeled-bracket match.

**Downstream effect, verified**: h01's room-min-height checks (`PUDA1996.room.
habitable_min_height`, `.service_min_mean_height`) now return real `pass` results (observed
3.3528m against a 2.7m/2.25m requirement) instead of `unknown` -- the first real, non-fixture
findings this pipeline has produced from actual computed geometry plus a section-adjacent height
source, not just structural/missing-input outcomes. `tests/test_parser.py`'s h01 assembly test
was updated accordingly (it previously asserted `height_m is None` for every floor, encoding the
now-superseded policy) plus two new direct tests for `extract_overall_height_m` itself.

## Automatic sheet-role inference (2026-09-19): /cases/assemble no longer requires manual tagging

`POST /cases/assemble` now accepts files under a generic repeated `files` field with no
caller-declared role at all -- `packages/api/role_inference.py` reads each PDF's own title block
(`packages.parser.pdf_ingest.extract_title_block`) and matches it against a keyword table
(ground/first/second/.../elevation_front/rear/side/site/zoning/section) to assign the role
itself. DXF files (no title-block reader exists for DXF -- CLAUDE.md scope, dxf_ingest works off
layer/entity geometry) fall back to filename keyword matching, explicitly lower-trust.

**Response shape changed**: `/cases/assemble` now returns `{"model": BuildingModel,
"resolved_roles": {filename: role}, "unresolved": [{"filename", "reason"}, ...]}` instead of a
bare `BuildingModel`. A file whose role can't be confidently read is never guessed at or silently
dropped -- it's reported in `unresolved` with the actual reason (e.g. the title block text that
didn't match anything), same "declared uncertainty over fake precision" principle as every
`status=unknown` Finding elsewhere in this project. The explicit named-role field path (e.g. a
field literally named `ground`) still works unchanged and takes precedence over an auto-guess for
the same role, for programmatic callers that already know their roles.

Verified against real h01 (6 files, zero manual tags, all 6 including three differently-named
elevations resolved correctly) and h02 (correctly left `elevation_front.pdf` unresolved --
Track A's parser had already found its title block actually reads "WOODEN JOINERY DETAIL", a
real sheet-role mismatch in that case's own files, not a bug). Tests in `tests/test_api.py`
generate a synthetic title-blocked PDF in-process rather than depending on gitignored real files.

---

## BuildWise frontend rebuild (2026-09-19): backend adapters added, custom-bylaws deferred

Scoped a full frontend redesign ("BuildWise" branding) against this project's real API. Three
small adapters added to `packages/api/main.py` (no rule-engine/parser logic changed, only new
thin routes reusing existing functions):

- `GET /jurisdictions` -- static list (today: just Mohali/GMADA/`puda_building_rules_1996`),
  structured so a future custom-bylaws-derived entry is an append, not a shape change.
- `POST /report/markdown` -- mirrors `/report/html`/`/report/pdf` exactly, wraps
  `packages.report.render.render_markdown` (added a few conversations ago, previously only
  reachable via `tools/run_check.py --markdown`).
- `POST /cases/assemble` -- the real gap: `/upload`'s multipart path was a hard 501 because
  `packages.api.parsing.try_parse_file` expects a single-file `ingest(bytes, filename)` entry
  point that doesn't exist, while CLAUDE.md's actual architecture (§10.1) is multi-sheet
  (`packages.parser.semantics.assemble_case(meta_path)`, which reads a meta.json + sibling files
  from disk). `/cases/assemble` is a thin adapter: multipart fields whose value is a file are
  treated as one sheet each (field name = role, e.g. `ground`, `elevation_front`, `site`),
  written to a `tempfile.TemporaryDirectory`, a `meta.json` is synthesized, and
  `assemble_case()` is called unchanged. Verified end-to-end against real h01 sheets (4 files ->
  valid BuildingModel -> `/checks/run` -> 22 issues, matching `tools/run_check.py`'s output) and
  tested in `tests/test_api.py` against the committed synth DXF (real drawings are gitignored,
  so tests can't depend on them).

**Deliberately NOT built this pass** (flagged to the user as a real backend feature, not a
frontend task, before starting): live custom-bylaws ingestion for an "Other" location -- running
the full extract -> two-pass-LLM-transcribe -> verify pipeline on user-submitted bylaws and
registering a new jurisdiction on the fly. This needs async job tracking (the pipeline takes
real LLM calls, likely minutes) and a persistent jurisdiction registry beyond the static list
above. User confirmed treating this as a separate follow-up task. `GET /jurisdictions`'s shape
is intentionally forward-compatible with it (an id/label/authority/rule_pack list a background
ingestion job could later append to), but no ingestion endpoint exists yet.

**Plot-size fallback** (width x length + unit, entered when a drawing has no site/zoning sheet):
implemented client-side only, no backend change -- the frontend computes a rectangle
`plot_polygon` and `plot_area_sqm` from the user's input and merges it into the BuildingModel
JSON before calling `/checks/run`, adding an `assumptions` entry noting it's user-entered, not
traced. This unblocks coverage/FAR checks (which only need `plot_area_sqm`) but explicitly NOT
the containment check (which needs `zoned_area`, the buildable envelope -- a different polygon
than the plot rectangle, not derivable from plot dimensions alone). The frontend must not
conflate the two.

---

## Follow-up (2026-09-19): yard-zone labels are a real, unextracted setback signal

`packages/parser/pdf_ingest.py::_NON_ROOM_LABELS` currently discards `FRONTYARD`, `BACKYARD`,
`GREEN`, `PARKING HALL` labels entirely (CLAUDE.md-style honesty: not representable as an
enclosed `Room`). But their labeled dimensions are real, legible text on the sheet and are
plausible setback distances -- e.g. h01's `BACKYARD 10'-10½" x 24'-1½"` (≈3.3m) and front
`GREEN 9'-9" x 13'-10½"` (≈3.0m) sit exactly in the range CLAUDE.md's setback-formula rules
expect. If a yard zone spans the full distance from building wall to plot line (the standard
convention for showing setback compliance on a plan), its shorter/perpendicular dimension IS the
setback -- this is not confirmed geometrically here, just a plausible reading of labeled text,
same trust level as the room-label dimensions already used elsewhere in this file.

**Not implemented, deliberately, for now**: `PUDA1996.setback.front_rear_formula` and
`.side_formula` need *both* an actual distance and `_building_height_m(model)` (the formula is
`height × fraction`). Height stays `None` without a section sheet (confirmed as the intended
behavior in this session -- elevation-derived height was explicitly considered and rejected as a
substitute, see below), so extracting the yard-zone distance today would sit unused with zero
visible effect on any finding. Revisit this once a section sheet exists for either house; at that
point, wiring `FRONTYARD`/`BACKYARD` zone depth into `_setback_actual_m()` as a low-confidence
candidate (clearly flagged as "yard-label-derived, not a plot-line measurement") should unblock
real setback findings on both houses without needing full plot-boundary vector tracing.

## Follow-up (2026-09-19): elevation-derived height considered and rejected

Confirmed a real, legible vertical dimension chain exists on h01's `elevation_front.pdf`
(`10'-3", 2'-3", 7', 10'-3"...`, sheet explicitly states "all levels are in feet & inch") that
could technically be parsed into a height estimate (h02's equivalent sheet has the same
font-encoding corruption already flagged elsewhere in this file, so it's h01-only regardless).
Asked whether to trust this as a height source when no section sheet exists (with `confidence:
low` and an explicit "from elevation, not section" citation note) versus keeping CLAUDE.md's
current rule that elevations are cross-check only, never a height source. **Decision: keep the
current rule as-is.** Height (and everything gated on it -- room min height, setback formulas,
height-vs-road, roof projection recede) stays `status=unknown` on both real houses until an actual
section sheet is supplied. Do not revisit this without asking again -- it was a deliberate
product-risk call, not an oversight.

---

## Stage 2 integration (2026-09-19): first real end-to-end run, two engine bugs found and fixed

Ran `packages/parser/semantics.assemble_case()` -> `packages/rules/engine.run_checks()` against
both real cases (h01, h02) for the first time with all four tracks merged. This is exactly what
CLAUDE.md §11 Stage 2 predicts: "Expect breakage; that's the point of doing it now." Two real bugs
surfaced, both now fixed in `packages/rules/engine.py`, full suite still green (79/79):

1. **`_applies()` treated `plot_area_sqm is None` as "rule doesn't apply" (skip, no Finding) instead
   of "can't be evaluated" (emit `status=unknown`).** Every individual `_check_*` function already
   handled `plot_area_sqm is None` correctly and would have emitted a proper `unknown` Finding --
   but the top-level gate short-circuited before any of them ran, for every plot-size-banded rule
   in the pack. Fixed by letting the band check through (`return True`) when `plot_area_sqm` is
   `None`, so the existing per-check `unknown` handling actually executes.
2. **Every rule in `puda_1996.yaml` gates on `applies_when.authority: GMADA`, and h01/h02 both have
   `jurisdiction.authority == "UNKNOWN"`** (deliberately left unresolved in their meta.json since
   no title-block jurisdiction inference was done -- see Stage 0 handoff notes above). This meant
   the *entire* pack silently evaluated to zero findings for both real cases -- indistinguishable
   from "clean drawing" in the UI despite nothing having actually been checked, which is the exact
   false-confidence failure CLAUDE.md §5/§1 rule 6 exists to prevent. Fixed in `evaluate()`: when
   `jurisdiction.authority == "UNKNOWN"`, emit exactly one explicit
   `PUDA1996.jurisdiction.unknown` Finding (`status=unknown`, `severity=blocking`,
   `ambiguity_class=missing_input`, cited to clause 3 -- the pack's own applicability clause --
   with a remedy telling the user to confirm jurisdiction on the model-confirmation screen) instead
   of returning an empty list.

**Result after both fixes**, h01 with jurisdiction manually confirmed to GMADA (simulating what the
confirmation screen is for): 31 findings -- 6 violation, 9 pass, 16 unknown (mostly
`missing_input` for the absent site/zoning/section sheets, exactly as predicted in the Stage 0
handoff above). With jurisdiction left as `UNKNOWN` (i.e. exactly what the parser produces from
these sheets today, unconfirmed): 1 finding, the jurisdiction-unknown blocker, and nothing else --
which is the honest and correct output, not a bug, given no jurisdiction was actually established.

**Follow-up for whoever builds real jurisdiction routing** (CLAUDE.md §2: "jurisdiction routing is
step zero"): today `packages/parser` deliberately does not infer `jurisdiction.authority` from
title-block text alone (see Track A's handoff), so every real case starts at `UNKNOWN` until a
human confirms it on-screen. `packages/api/checks.py`'s `/models/confirm` endpoint already supports
correcting arbitrary model fields via its general confirmation flow -- confirm jurisdiction is
wired through the same path as the room-confidence corrections, or add a dedicated field if it
isn't already.

---

## Track A — Parser, Stage 1 report (2026-09-19)

Built `packages/parser/dxf_ingest.py`, `packages/parser/pdf_ingest.py`, `packages/parser/semantics.py`,
`packages/cases/gen_synth_smoke.py` (+ `packages/cases/synth/s_smoke.dxf`), and
`packages/cases/mutate.py` (+ two demonstration mutations under `packages/cases/synth/mutated/`
and `packages/cases/truth/s_smoke_m01.truth.json` / `s_smoke_m02.truth.json`). Tests in
`tests/test_parser.py` (26 tests, all passing together with `tests/test_stubs.py`). Added `ezdxf`
to `requirements.txt`.

### The actual BuildingModel shape produced for h01/h02

`packages/parser/semantics.py::assemble_case()` runs end-to-end against both real cases without
crashing and produces a schema-valid `BuildingModel` in both cases. Concretely, for h01 (and
h02, same shape):

- `source = "vector_pdf"`.
- `jurisdiction.authority = "UNKNOWN"` (taken straight from meta.json — jurisdiction routing is
  rules-engine territory, not parser territory, per CLAUDE.md); `plot_no`/`sector` ARE recovered
  from each sheet's own title-block text (h01: plot_no="351", sector="Phase-2"; h02:
  plot_no="1002"). `rule_pack` defaults to `"puda_building_rules_1996"` (matching Track B's
  renamed pack id from the Stage-0 handoff above, not the "puda_2021" name in CLAUDE.md's
  glossary).
- `plot_polygon = None`, `zoned_area = None`, `plot_area_sqm = None`, `edges = []` — no
  site/zoning sheet exists for either case, so these are correctly left unset rather than
  guessed (verified by `test_assemble_case_h01_produces_valid_building_model_with_known_gaps`).
- `floors`: one per plan sheet, `level` 0/1/2 for ground/first/second, `is_stilt=False`,
  **`height_m = None` for every floor** (no section sheet; elevations are cross-check only, never
  used to set height — this is the one rule in this module I'd flag as the most
  important-not-to-regress).
- Each floor's `footprint` is a **rectangle** (the vector-drawing bounding box, minus an excluded
  title-block strip) in a **sheet-local metre coordinate system** — NOT anchored to the plot, and
  not necessarily sharing an origin with any other floor's sheet beyond "both start near (0,0)".
  This is a deliberate approximation (documented at length in `pdf_ingest.py`'s module
  docstring): there is no wall-polygon tracing, no shared plot datum, and no scale bar on these
  sheets — scale is estimated per-sheet by matching the largest clean `N'-M"` dimension string in
  the sheet's own text layer to the longer axis of its drawing bbox.
- `rooms`: recovered from this office's own `"ROOM NAME"` + `"W' x H\""` label convention, positioned
  at the label's text location, sized from the parsed dimension when it parses cleanly (several
  do: e.g. h01 ground `PARKING HALL 38'-6" x 19'-6"`) else a placeholder size keyed by room-use
  category. Every room's `confidence` is `"low"` or `"medium"`, never `"high"`. `openings_area_sqm`
  is always `0.0` for PDF-derived rooms — not extracted at all in this build; light/ventilation
  checks against these rooms will be meaningless until that's implemented.
- `assumptions` (16–20 entries for h01/h02) is where every one of the above approximations is
  spelled out verbatim, plus two things worth Track B/C/D knowing about specifically:
  1. **A genuine sheet-role mismatch was caught in h02's own meta.json**: the file mapped to
     role `"elevation_front"` is actually titled "WOODEN JOINERY DETAIL" in its own title block
     (not an elevation at all), and `"elevation_rear"`'s text layer decodes to garbled characters
     (`"TIT.E:-"` instead of `"TITLE:-"`, an embedded-font encoding issue) so its role can't be
     confirmed either. `semantics.py` detects both automatically via
     `pdf_ingest.sheet_title_matches_role()` and excludes them from the storey-count cross-check
     rather than trusting the meta.json label — but does NOT correct `h02.meta.json` itself
     (not this track's call, and the file may need a human to look at what
     `elevation_front.pdf` / `elevation_rear.pdf` actually are before it's fixed).
  2. **h01 has a real plan-vs-elevation storey-count mismatch**: 3 plan sheets assemble into 3
     floors, but the (heuristic, approximate — see `pdf_ingest.estimate_storey_count_from_elevation`)
     elevation line-count estimate suggests 4. Surfaced as a structured
     `"STOREY COUNT MISMATCH (extraction ambiguity candidate)"` note in `assumptions`, ready for
     Track C's ambiguity engine to pick up as `ambiguity_class="extraction"` once it exists —
     not resolved by the parser.

### Deferred / not implemented in this build

- Section-sheet parsing (the only legitimate source of `Floor.height_m`, per CLAUDE.md §10.1) is
  **not implemented** — no section sheet has been supplied for any case yet to develop it
  against. If/when one lands for h01 or h02 (or a new case), `semantics.py`'s section-handling
  branch needs actual implementation, not just the current "flag that it's missing" logic.
- Site/zoning-sheet parsing (plot polygon, zoned area tracing) is likewise **not implemented**
  for the same reason (none supplied yet). CLAUDE.md §11/§3 assigns the zoning-plan *tracing UI*
  to Stage 3 / Track D anyway (user traces the zoned area over the uploaded PDF) — this parser
  only handles the "read an already-digitized site sheet" half, which has nothing to read yet.
- `jurisdiction.authority` is never inferred from drawing content (deliberately — GMADA vs.
  MC_KHARAR vs. MC_ZIRAKPUR is a rules-engine/jurisdiction-routing decision per CLAUDE.md, and
  title-block text alone ("Mohali") doesn't disambiguate it).
- Vector-PDF footprint/room extraction is explicitly an "envelope + label-positioned rectangle"
  approximation, not real vectorization — see the long caveat block at the top of
  `packages/parser/pdf_ingest.py` for the full reasoning. Good enough to unblock Track B/C/D's
  FAR/coverage/room-count math with plausible numbers, not good enough to trust a specific wall
  position for an overlay without a user confirming it first.
- `mutate.py`'s two ops (`offset_edge`, `shrink_room`) only support axis-aligned rectangles
  (true of the synth smoke file's geometry) and assert that precondition rather than silently
  mis-transforming a non-rectangular polygon. Demonstrated only against
  `packages/cases/synth/s_smoke.dxf` per CLAUDE.md §10.5 (no real approved DXF exists yet — h01/h02
  are PDF-only); the resulting truth files are `provenance: "synthetic"` and assert no
  `rule_id`/pass-fail verdict (the synth case has no plot/zoned_area for a rule to check against)
  — they exist purely to prove the harness mechanics (declarative params -> exact derived truth
  via shapely, no hand-labeling, no LLM).

### Heads-up for Track B / Track D: a cross-track schema mismatch, not caused by Track A

Running the full `tests/` suite (not just `test_parser.py`) turned up 7 pre-existing failures in
`tests/test_api.py` and `tests/test_rules_engine.py`, all the same root cause and unrelated to
anything Track A touched: `packages/rules/packs/*.yaml` rules list remedy kinds like
`"reduce_footprint"` (matching CLAUDE.md §7's own example YAML!), but `Remedy.kind` in the frozen
`packages/schema/findings.py` only allows `"geometric_edit" | "purchase_chargeable_far" |
"compounding" | "noc_route" | "zoning_revision_request"` — so `packages/rules/engine.py`'s
`_remedies()` raises a `pydantic.ValidationError` building the `Remedy` for any rule whose pack
YAML uses `"reduce_footprint"` (or similar non-enum strings). Since CLAUDE.md itself is the
source of the mismatched example, this probably needs either a kind-mapping layer in
`rules/engine.py` (e.g. `"reduce_footprint"` -> `"geometric_edit"`) or an amendment request for
`Remedy.kind`'s literal set — not something Track A should fix unilaterally in someone else's
package. Flagging here since it's currently failing tests outside Track A's own suite.


---

## Track D handoff (2026-09-19): API contracts for Tracks A/B/C to plug into

Stage 1 scope done: `packages/api/main.py` (FastAPI), `packages/report/overlay.py`,
`packages/report/render.py` + `packages/report/templates/report.html.j2`, and a Vite React app
in `web/`. All built and tested against the six frozen stubs only — no dependency on
`packages/parser`, `packages/rules`, `packages/solver`, or `packages/ambiguity`, per §4.
`python -m pytest tests/test_api.py tests/test_stubs.py` passes (19/19). Route contracts below
are the seams the other three tracks plug into; each is a one-line import swap on Track D's side.

### The two adapter seams — implement these function signatures and Track D picks them up automatically

**Track B → `packages/rules/engine.py`:**
```python
def run_checks(model: BuildingModel) -> list[Finding]:
    ...
```
`packages/api/checks.py::engine_available()` probes for `packages.rules.engine.run_checks` at
call time (no caching, no restart needed) and `packages/api/checks.py::run_checks()` calls it
directly if present. Until then, every route falls back to a small **fixture** finding set (rule
ids prefixed `FIXTURE.`, citation `status` always `not_stated`/`seed_unverified`, never
`verified`) that does real shapely containment against `zoned_area` plus four static
ground-coverage/RWH/stilt/height/tree checks — enough to exercise every `Finding.status` value
(`violation`, `ambiguity`, `advisory`, `pass`, `unknown`) end to end. **Do not treat the fixture
rule_ids or thresholds as real** — they're schema exercisers, not a rule pack.

**Track A → `packages/parser/` (any of, tried in order):**
```python
packages.parser.ingest.ingest(file_bytes: bytes, filename: str) -> BuildingModel
packages.parser.dxf_ingest.ingest(file_bytes: bytes, filename: str) -> BuildingModel
packages.parser.pdf_ingest.ingest(file_bytes: bytes, filename: str) -> BuildingModel
```
Probed by `packages/api/parsing.py::try_parse_file()`. Until one exists, `POST /upload` with a
multipart file returns **501** (not a fake model, not a silent pass) explaining that a
BuildingModel JSON body should be used instead.

**Track C → `packages/solver/repair.py` and `packages/ambiguity/dossier.py`: not yet wired into
the API.** No route currently calls these. If you want an endpoint before Track D circles back,
the natural shape (matching the `checks.py` pattern) would be:
```python
# packages/solver/repair.py
def find_remedies(model: BuildingModel, finding: Finding) -> list[Remedy]:
    ...
# packages/ambiguity/dossier.py
def build_dossier(model: BuildingModel, finding: Finding) -> dict:  # or a frozen-schema type if you add one to findings.py's Remedy-adjacent shape
    ...
```
say so here and Track D will add `POST /remedies` / `POST /ambiguity/dossier` the same way the
other two adapters work. Today, `Finding.remedies` on violation fixture findings only names the
remedy *kind* (`geometric_edit`, `zoning_revision_request`) with `verified=False` and no
`area_lost_sqm`/`edit_ref` — CLAUDE.md §9 reserves inventing those numbers for the real solver.

### Full route contract (`packages/api/main.py`)

```
GET  /health
  -> {"status": "ok", "service": "mohali-check-api",
      "rules_engine_available": bool, "parser_available": bool}

POST /upload
  multipart/form-data, field "file"  -> BuildingModel (200) if a parser is wired, else 501
  application/json body = BuildingModel -> validated + echoed back (200), or 422 on schema violation

POST /models/confirm
  body: {"model": BuildingModel,
         "corrections": [{"floor_level": int, "room_index": int,
                           "use": <Room.use literal> | null, "confidence": Confidence | null}]}
  -> {"model": BuildingModel, "applied": int, "remaining_low_confidence": int}
  400 (fails loudly, not silently) if a correction references a nonexistent floor_level/room_index.
  Omitting "confidence" on a correction defaults it to "high" (confirming = no longer low-confidence).

POST /checks/run
  body: {"model": BuildingModel}
  -> {"summary": "pre-submission check: N issues found",   # NEVER "approved"/"compliant" (CLAUDE.md §5)
      "engine_source": "real" | "fixture",
      "findings": [Finding, ...]}

POST /overlay
  body: {"model": BuildingModel, "findings": [Finding, ...] | omitted (runs run_checks internally)}
  -> GeoJSON FeatureCollection: one feature per plot_outline/zoned_area/floor_footprint (context)
     plus one feature per finding (geometry=null if the finding has no geometry_ref).
     top-level "properties": {"zoned_area_present": bool, "plot_area_sqm": float | null}

POST /report/html   -> text/html  (same body shape as /overlay)
POST /report/pdf    -> application/pdf, filename mohali-check-report.pdf (same body shape)
```

Every response was tested (`tests/test_api.py`) to never contain "approved" or "compliant" as a
verdict, anywhere including error `detail` strings. `s05_no_zoning`'s containment finding is
asserted `status="unknown"` on every checks/run call — this is the regression most worth
re-checking if you touch `checks.py`.

### Report rendering (`packages/report/render.py`, `packages/report/overlay.py`)

- `render_html(model, findings) -> str` and `render_pdf(model, findings) -> bytes` (reportlab
  platypus — chosen over weasyprint because it installs from a wheel with no system Pango/Cairo
  dependency, which is a bad bet mid-hackathon). Both share one `_report_context()` so the HTML
  and PDF can't disagree on numbers or the mandatory footer language.
- `summary_line(findings)` counts every finding with `status != "pass"` as an "issue" (violation +
  ambiguity + advisory + unknown all count — an unresolved `unknown` is not safe to submit on).
- Unit conversion (`SQM_TO_SQYD = 1.196`) happens only inside `render.py`, never upstream —
  matches CLAUDE.md §1 rule 4.
- `build_overlay(model, findings)` in `overlay.py` does all polygon/line/point handling through
  `shapely` (construct + `buffer(0)` repair on invalid rings), never hand-rolled — CLAUDE.md §1
  rule 3.

### Web app (`web/`) — actually runs

Scaffolded with `npm create vite@latest . -- --template react`, `npm install` completed
(`web/node_modules` present), **`npm run build` succeeds** (verified — `vite build` produced
`web/dist/` with no errors). Start it with:
```bash
cd web && npm run dev      # Vite dev server, default http://localhost:5173
```
It expects the API at `http://127.0.0.1:8000` by default (override with `VITE_API_BASE` env var
at dev/build time). **Honesty note:** the dev server itself was not started and click-tested in a
browser in this session (a long-running `npm run dev` foreground process would block the agent
session) — verification was `npm run build` (compiles/bundles cleanly, catches JSX/import/JSON
errors) plus a live `uvicorn` smoke test on a throwaway port confirming `/health` and
`/checks/run` work over real HTTP (not just FastAPI's TestClient) for `s05_no_zoning`, returning
`FIXTURE.zoned_area_containment: unknown` as expected. If someone runs `npm run dev` + `uvicorn
packages.api.main:app` and hits a runtime-only bug (vs. a build-time one), that's the gap this
note is flagging.

Flow implemented: `web/src/App.jsx` — step 1 `UploadScreen` (pick one of six local fixture
copies of `packages/cases/stubs/*.model.json` under `web/src/fixtures/`, paste raw JSON, or a
file input that hits the real multipart path and surfaces the 501 honestly) → step 2
`ConfirmScreen` (wired against `s06_low_conf`'s shape: lists every non-"high"-confidence room,
lets the user pick a corrected `use`, POSTs to `/models/confirm`) → step 3 `FindingsScreen` (POSTs
`/checks/run` + `/overlay`, renders a findings table sorted worst-first, an `OverlaySvg` plain-SVG
renderer of the GeoJSON, and buttons for the HTML/PDF report). No component library; plain
`fetch()` in `web/src/api.js`.

### Known gaps / honest status

- Fixture findings in `packages/api/checks.py` are illustrative only, not a rule pack — Track B's
  real `run_checks` supersedes them the moment it's importable, with zero API-layer changes needed.
- No endpoint yet for Track C's solver/ambiguity outputs (see above) — flag here if you want one
  before Track D returns to it.
- `render_pdf`'s reportlab table doesn't paginate `geometry_ref` visuals (text-only report); the
  overlay/GeoJSON is the visual surface today, consumed by the web app's `OverlaySvg`, not by the
  PDF.
- Web app's live browser behavior (as opposed to build-time correctness) is unverified in this
  session — see the honesty note above.

### Update (2026-09-19, later same day): real rules engine is now live end-to-end through the API

`packages/rules/engine.py` landed mid-session exposing `evaluate(model, pack)` and
`evaluate_path(model, pack_path)` (not the `run_checks(model)` name in the original contract
above). `packages/api/checks.py::_find_real_entry_point()` now detects and calls whichever of
`run_checks` / `evaluate_path` / `evaluate`+`load_pack` is present, and
`_resolve_pack_path()` matches `model.jurisdiction.rule_pack` ("puda_building_rules_1996") to the
actual pack file (`packages/rules/packs/puda_1996.yaml`) by falling back to "the only pack file
present" when the names don't match exactly (they don't, today — Track B, if/when you add a
second pack, name a file matching the string tracks actually put in
`jurisdiction.rule_pack`, or tell Track D and this heuristic gets replaced with an explicit map).

Verified live (not fixture) for all six stubs — `checks.run_checks_with_source()` returns
`source="real"` with no error for `s01`..`s06`, including `s05_no_zoning`'s containment finding
(`PUDA1996.containment.zoned_area`) correctly at `status="unknown"`. Full suite
(`python -m pytest tests/`) is 78/78 green.

Also hit and worked around (see Track A's identical finding above, "cross-track schema
mismatch"): `packages/rules/engine.py`'s `_remedies()` briefly raised `pydantic.ValidationError`
on `Remedy(kind="reduce_footprint", ...)` for `s03_far_over`, since `reduce_footprint` isn't in
`Remedy.kind`'s frozen Literal set — this has since been fixed on Track B's side (all tests
including `tests/test_rules_engine.py::test_s03_flags_far_and_is_compoundable` pass now). Track D
added defense-in-depth regardless: `checks.run_checks_with_source()` wraps every real-engine call
in `try/except Exception`, and on any runtime error (not just an import failure) falls back to
the labeled `FIXTURE.*` findings for that request rather than 500ing `/checks/run`, `/overlay`,
`/report/html` and `/report/pdf` simultaneously. The swallowed exception is surfaced back to the
caller as an `"engine_error"` field on `/checks/run`'s response when this happens, so it's visible
rather than silently masked. This is now dormant (no error currently triggers it) but stays in
place so one bad rule in a future pack edit can't take down the whole API surface again.

---

## Track C — Solver + Ambiguity engine handoff (2026-09-19)

`packages/solver/` (repair.py, remedies.py) and `packages/ambiguity/` (classifier.py,
dossier.py) are implemented and tested: `python -m pytest tests/test_solver.py
tests/test_ambiguity.py tests/test_stubs.py` is green (29 tests), and the full suite
(`tests/`, including test_eval.py) is green at 46 tests. Nothing outside
`packages/solver/`, `packages/ambiguity/`, and the two new test files was touched.

### Dependency on Track B's rules engine — how the gap was handled

`packages/rules/engine.py` did not exist yet at the time of this work (only
`packages/rules/packs/` exists, empty). `packages/solver/repair.py` never imports
`packages.rules.engine` at module scope. Instead:

- Every solver entry point (`search_repairs`, `solve`) takes an injected
  `evaluate_fn: Callable[[BuildingModel], list[Finding]]`.
- `repair.default_evaluate_fn()` will lazily `import packages.rules.engine` and look for one
  of `evaluate` / `run` / `check` / `evaluate_model` as the callable, **only when explicitly
  called** — never at import time. It raises a clear `ImportError` telling the caller to pass
  `evaluate_fn` explicitly if the engine isn't ready or doesn't expose one of those names.
  **Track B: once `engine.py` lands, either name its entry point one of those four, or tell
  Track C/D the actual name so `default_evaluate_fn()` can be updated** (one-line change).
- `tests/test_solver.py` defines its own `fixture_evaluate_fn` (zoned-area containment via
  shapely + a residential-plotted FAR cap using the real 1.65/1.40/1.25/1.00 bands from
  `corpus/extracted/puda_building_rules_1996/clauses.jsonl` clause `4#2`) so solver logic is
  fully verified without waiting on Track B. This fixture is **not** part of
  `packages/solver` — it's test-only scaffolding matching the brief.
- **Ask for Track B**: `enumerate_edits()` in `repair.py` maps a violated `Finding` to an
  edit strategy (shrink a wall vs. trim a projection vs. reduce a basement, etc.) using
  keyword matching over `rule_id`/`title` (`"setback"`, `"far"`, `"coverage"`,
  `"projection"`, `"basement"`, `"room"`/`"light"`, since no stable convention existed yet to
  code against). **If Track B settles on a stable `rule_id` prefix convention (e.g.
  `*.setback.*`, `*.far.*`, `*.basement.*`), please note it here or in a comment in
  `engine.py`** — it turns this heuristic into an exact dispatch and removes a source of
  missed-candidate risk before the demo.

### Shape of `repair.py`'s output (for Track D's report renderer)

```python
search_repairs(model, violations, evaluate_fn) -> dict[str, list[RepairCandidate]]
# key = Finding.rule_id of the violation being targeted

@dataclass
class RepairCandidate:
    edit_ref: dict            # e.g. {"op": "shrink_wall", "floor": 0, "edge": "rear", "delta_m": 0.4}
    description: str          # architect-facing prose, numbers only from area_lost_sqm/edit_ref
    model: BuildingModel      # the edited copy (deep copy of the input model)
    target_rule_id: str
    cleared_rule_ids: set[str]  # every rule_id that stopped being a violation, may be >1
    area_lost_sqm: float
    verified: bool = True     # always True by construction -- only survivors of a full re-run are kept

RepairCandidate.to_remedy() -> Remedy   # kind="geometric_edit", per the frozen schema

solve(model, findings, evaluate_fn=None, top_n=3) -> dict[str, list[Remedy]]
# key = violated Finding.rule_id; value = top_n geometric Remedies (cheapest area-loss first)
# followed by applicable non-geometric Remedies (remedies.py), in that order.
```

`edit_ref` ops implemented: `shrink_wall`, `shrink_wall_all_floors`, `trim_projection`,
`reduce_basement_footprint`, `reclassify_room`, `shift_stair` — matches CLAUDE.md §9 point 1's
list exactly.

**Known geometry limitation**: all edit ops assume axis-aligned, simple-rectangle-ish
footprints and axis-aligned plot edges (true of every stub, and of the one planned synth DXF
per the naming-chaos brief — but not guaranteed for a real DXF with non-rectangular
footprints). `shrink_wall` will raise if an edge isn't (roughly) axis-aligned. **Ask for
Track A**: if/when real DXF geometry comes in with non-rectangular footprints, this needs a
buffer/offset-based generalization of `shrink_wall` (shapely supports this — `polygon.buffer`
on one side is more involved than the current bounds-based rectangle shrink, budget time for
it before Stage 3 if real footprints are irregular).

`remedies.non_geometric_remedies_for_finding(finding, model) -> list[Remedy]` returns
`purchase_chargeable_far` / `compounding` / `noc_route` / `zoning_revision_request` Remedies
that apply, using only `finding.observed`/`finding.required`/`finding.compoundable`/
`finding.citation` — no fee schedule or percentage cap is stated because **no
compounding/composition-policy or chargeable-FAR circular has been ingested into the corpus**
(per the Stage 0 handoff above, only 4 PDFs were supplied and none is a policy/fee doc for
these two remedies). If such a document arrives, wire its verified values into these two
functions — until then they name the mechanism and, where computable, the excess area, but
never a fee.

### Shape of `dossier.py`'s output (for Track D's report renderer)

```python
classify_all(model, findings=None, vintage_cutoffs=None, discretionary_clauses=None,
             definitional_far_clause=None, objection_history=None) -> list[AmbiguityTrigger]

@dataclass
class AmbiguityTrigger:
    ambiguity_class: str       # one of CLAUDE.md §8's seven
    reason: str                # legible one-liner, why it fired
    evidence: dict             # deterministic facts, not prose
    rule_id: str | None

build_dossier(trigger, model, far_cap=None, narrate_fn=None) -> Dossier

@dataclass
class Dossier:
    ambiguity_class: str
    rule_id: str | None
    title: str
    readings: list[Reading]           # Reading(label, description, outcome=None, citation=None)
    safer_reading_label: str | None
    safer_reason: str
    proof_document: dict | None       # citation(s) to carry into the submission
    justification_paragraph: str      # submission-ready prose, grounded only in `facts`
    facts: dict                       # every number the paragraph cites, computed via shapely/plain python
    is_confirmation_flag: bool = False  # True => route to confirmation UI, not a GMADA dossier
```

`narrate_fn: Callable[[dict], str]` is pluggable per call — defaults to hand-written templates
in `dossier.py` (one per ambiguity class), swappable later for a live LLM call (e.g. from
`packages/api`) with the exact same `facts` contract, so the grounding guarantee doesn't
change when a real model starts writing the prose.

**Judgment call on s06 (low-confidence room labels)**: classified as `extraction`
(`AmbiguityTrigger.evidence["source"] == "low_confidence_label"`), but `build_dossier` routes
this case to a **lightweight confirmation flag** (`is_confirmation_flag=True`, no
`proof_document`, one-line rationale) rather than a full GMADA-submission dossier. Reasoning:
there is no legal ambiguity or clause in dispute here — it's an OCR/vision-extraction
confidence problem that CLAUDE.md's own schema already routes through the model-confirmation
screen (`Confidence` semantics in §5) before any rule runs. Writing a justification paragraph
architects could submit to GMADA about *our own extraction uncertainty* would be nonsensical;
Track D should render `is_confirmation_flag=True` dossiers as a "confirm this on-screen"
prompt, not as an ambiguity card in the findings report.

### Flagship example generated (s04_stilt4_500, definitional ambiguity)

Computed facts (via shapely on the actual stub geometry, footprint 14m x 14m = 196 sqm per
floor, 4 upper floors + 1 stilt floor, 500 sqm plot, FAR cap 1.00 per
`puda_building_rules_1996` clause `4#2`'s >430 sqm band):

- Reading A (exclude stilt): covered area 784.0 sqm, FAR 1.568, excess 284.0 sqm over cap
- Reading B (include stilt): covered area 980.0 sqm, FAR 1.960, excess 480.0 sqm over cap
- Safer reading for submission: B (literal reading — no stilt-exclusion circular is in the
  verified corpus, so relying on the unwritten "stilt+4" concession is the riskier position)

Full generated justification paragraph:

> This design places an open, columns-only stilt storey below 4 upper floors on a 500 sqm
> plot. Whether that stilt storey's footprint counts toward covered area for floor area ratio
> purposes is not settled by the text on file: puda_building_rules_1996 clause 4#2 defines
> floor area ratio for residential plotted development by plot-size band but does not mention
> a stilt, or any other open, non-habitable ground storey, anywhere in its text. Reading A --
> exclude the stilt storey (treat it as the open parking storey the 'stilt+4' concession
> common in more recent GMADA/PUDA practice contemplates, even though that concession is not
> itself present in the rule text on file): covered area is 784.0 sqm, giving a floor area
> ratio of 1.568. Reading B -- include the stilt storey (the literal reading of the clause,
> which defines the ratio without any stilt carve-out): covered area is 980.0 sqm, giving a
> floor area ratio of 1.960. Against the 1.00 cap that applies to this plot's size band under
> puda_building_rules_1996 clause 4#2, Reading A leaves 284.0 sqm of covered area in excess
> and Reading B leaves 480.0 sqm in excess -- both readings are over the cap on the numbers as
> drawn, so the choice between them changes the magnitude of the shortfall and which remedy
> (footprint reduction, chargeable-FAR purchase, or compounding) is realistic, not whether a
> violation exists at all. Because no circular or amendment codifying a stilt exclusion is
> present in the verified corpus for this jurisdiction, Reading B -- the literal, no-carve-out
> reading -- is the safer basis for this submission: it does not rely on an unwritten
> concession an examining officer may or may not extend, and it does not understate the
> covered area on record. Reading A remains worth raising, in writing, as the basis for a
> discretionary relaxation request if the office's current practice is understood to allow it
> -- but it should be argued for explicitly, not assumed.

Note this is honest rather than maximally dramatic: on the actual stub numbers, **both**
readings are FAR violations (cap is 1.00 either way for a >430 sqm plot), so the dossier does
not claim the stilt question flips pass/fail — it correctly frames the real stake as
violation *magnitude* and which remedy (footprint cut vs. chargeable-FAR purchase vs.
compounding) is realistic. If the demo wants a version where the ambiguity flips the verdict,
that needs either a smaller plot (different FAR band) or a higher FAR cap band value once
those numbers are verified against the gazette — flagging this so whoever wires the demo
script picks the plot size deliberately.

### Other ambiguity classes — grounding used

- `vintage`: demonstrated against a real cutoff actually present in the corpus — Rule 16(ii)
  (`puda_building_rules_1996:4#2`) ties charges to whether allotment predates 30-6-1997.
  `classify_vintage()` takes the cutoff/citation as explicit arguments rather than hardcoding
  bylaw knowledge this module wasn't given.
- `discretionary`: keyword-triggered on phrases actually seen in Punjab drafting style ("may
  be permitted", "at the discretion of", "competent authority may", etc.) — pass the real
  clause text once Track B's rule-authoring surfaces a discretionary clause; none was
  hardcoded from the current 4-doc corpus since none of the priority-list clauses (15-26)
  were fully read for this phrase during this pass.
- `instrument_conflict`: fires on 2+ Findings sharing the same `title` (proxy for "same
  conceptual check") whose citations disagree in `(doc, clause)` and `required` value. **Ask
  for Track B**: a stable `check_family` field (separate from `rule_id`, which differs per
  pack) would replace the title-matching proxy with something exact.
- `practice_divergence`: requires an explicit `objection_history` list (real casework, e.g.
  from a rejected-drawing + objection-memo pair per CLAUDE.md §10.4) — never inferred from a
  BuildingModel alone. No such casework exists in this repo yet; the trigger and dossier are
  tested against a synthetic history record and ready to wire in real objection-memo data
  under `packages/cases/real/` when it lands (Track A/D).

### Blockers / open items

- None blocking. The two integration asks above (rule_id naming convention;
  `default_evaluate_fn()`'s expected entry-point name) are conveniences, not blockers — the
  pluggable-`evaluate_fn` design means Track C's code runs today against a fixture and will
  run unchanged against the real engine once it's wired in by whoever assembles the pipeline
  in Stage 2.

---

## Track B — Rules handoff (2026-09-19)

Built the corpus rule-synthesis pipeline (`tools/transcribe.py`, `tools/verify.py`), extended
`tools/coverage.py` (had a real bug, see below), authored `packages/rules/packs/puda_1996.yaml`
(21 rule entries, 18 `enforced: true`), `packages/rules/engine.py` (pure shapely-based
evaluation), and `packages/gis/` (placeholder periphery layer + lookup). Tests in
`tests/test_rules_engine.py` (16 tests) plus the existing `tests/test_stubs.py` are green; full
repo suite (`pytest tests/`, 79 tests including `test_api.py`) is green.

### How the two-pass transcribe/verify discipline was actually run (CLAUDE.md §1 rule 1, §6.4/§6.5)

Per the task brief, transcription and verification were each done as one real, fresh Claude
subagent call (via the Agent tool) rather than hand-typed:

- **Transcription pass**: one subagent given *only* the raw clause text of the 9 priority
  clauses (15#2, 4#2, 16, 17, 18, 20, 22, 24, 25, 26 — note 16 is the *original* pre-amendment
  Rule 16 text, kept only for the instrument-conflict comparison) with a strict
  transcribe-don't-infer prompt. Output saved verbatim at
  `corpus/extracted/puda_building_rules_1996/rule_synthesis/transcribe_pass1.json` (58 proposed
  numeric facts).
- **Verification pass**: a *second, fresh* subagent call, given only the raw clause texts again
  plus the stripped `(clause_id, key, value, unit, applies_to)` tuples — explicitly NOT the
  transcriber's `quoted_fragment` or reasoning — asked to answer match/mismatch/not_stated per
  item. Output saved at `.../rule_synthesis/verify_pass1.json`.
- **Result**: 0 `mismatch` verdicts (source text was clean), but the verifier correctly
  **downgraded 2 of the transcriber's "stated" claims to `not_stated`** — `basement_max_coverage_
  vs_ground_floor` and `landing_min_width_vs_staircase` — because clause 24 and clause 25 state a
  *relation* ("shall not exceed the area on the ground floor" / "shall not be less than the width
  of the staircase"), not a bare number, and the transcriber had encoded that as a literal "100%"
  which the text does not say. This is exactly the failure mode the two-pass discipline exists to
  catch. Both rules are still enforced in the engine, but as direct shapely/geometry relational
  checks (no numeric constant used) with `status: seed_unverified`.
- `tools/transcribe.py` / `tools/verify.py` are real, rerunnable scripts implementing the same
  contract (strict prompts, replay-from-cache or live `ANTHROPIC_API_KEY` call) — see their
  module docstrings. Neither script fabricates a value itself if no key and no `--replay` cache
  are given; it exits with an explanation instead (CLAUDE.md §1 rule 1 applies to the tooling,
  not just the model).

### Rule status breakdown (`packages/rules/packs/puda_1996.yaml`, 21 rules)

- **verified** (18): site coverage slab bands (15#2); FAR bands upto_225/225_325/325_430 (4#2);
  front/rear + side setback formulas (17); height-vs-road relation is actually
  `seed_unverified` (see below, no bare number); chajja/balcony max projection, row-house small-
  site cap, door/window max, min clear height above plinth, max width vs site width (18);
  courtyard min area, min width (20); habitable room min height, service room min height, light/
  ventilation ratio (22); basement min height (24); staircase min width residential,
  commercial/public, max riser, min tread (25); roof projection recede (26).
- **seed_unverified** (2): `PUDA1996.containment.zoned_area` (structural, no bare number to
  verify), `PUDA1996.height.max_vs_road_setback` (pure relational paraphrase of clause 17(1), no
  numeric constant), plus the two relational rules the verifier downgraded (basement coverage
  relation, landing width relation) and the courtyard-vs-mean-height fraction — **note**: several
  of the "verified" numbers above (fraction_of_height, min_m values in the setback/projection
  rules) came from clause 17/18/20/22 text directly and did pass verification; only the *specific*
  connecting relations without their own bare number are seed_unverified. See the pack file's own
  per-rule `status` field for the authoritative list — this paragraph is a summary, not a
  substitute for reading it.
- **conflict** (0): none — clean source text this run. The engine still handles this status
  correctly if it ever occurs (`status="unknown"`, `ambiguity_class="instrument_conflict"`,
  never a silent pass) — see `test_conflict_rules_never_silently_pass` in
  `tests/test_rules_engine.py`.
- **not_stated** (1, deliberately): `PUDA1996.far.above_430_gap` — the 1998 amendment to Rule 16
  (clause `4#2`) substitutes the *entire* rule and simply does not restate a FAR cap for plots
  above 430 sqm (the original Rule 16(c)(iv) had 1.00). Modeled as a real
  `ambiguity_class="instrument_conflict"` finding carrying both the superseded value and the gap,
  never a silent carryover of 1.00 and never a silent skip.

### What Track C (solver/ambiguity) should know

- **Ambiguity-producing rule_ids from this engine**: `PUDA1996.far.above_430_gap`
  (`ambiguity_class="instrument_conflict"`, fires only for plot_area_sqm >= 430) and
  `PUDA1996.far.stilt_treatment` (`ambiguity_class="definitional"`, fires whenever any
  `Floor.is_stilt` is True). Both are emitted *in addition to* the normal FAR band
  pass/violation finding (computed conservatively excluding the stilt footprint) — they don't
  replace it. `PUDA1996.far.stilt_treatment`'s `observed` field is a string containing both
  computed FAR readings, e.g. `"FAR excluding stilt: 1.568; FAR including stilt: 1.96"` — parse
  it if you want the two numbers programmatically rather than re-deriving them (or just recompute
  from `model.floors[i].is_stilt`/`.footprint`, both are cheap via shapely).
- **rule_id naming convention** (per your ask): every rule_id in this pack is
  `PUDA1996.<family>.<band_or_variant>`, e.g. `PUDA1996.setback.front_rear_formula`,
  `PUDA1996.far.225_325`, `PUDA1996.courtyard.min_area`. Families used: `containment`,
  `site_coverage`, `far`, `setback`, `height`, `projection`, `courtyard`, `room`, `basement`,
  `staircase`, `roof_projection`. This should make `repair.py`'s keyword-matching heuristic exact
  if you want to switch to prefix dispatch (`rule_id.split(".")[1]`).
- **`run_checks(model) -> list[Finding]` now exists** in `packages/rules/engine.py` (single
  BuildingModel argument, resolves the pack from `model.jurisdiction.rule_pack` automatically —
  same resolution order as `packages/api/checks.py`'s `_resolve_pack_path`). `default_evaluate_fn`
  in `repair.py` currently looks for `evaluate` / `run` / `check` / `evaluate_model` — none of
  those match. Either add `"run_checks"` to that list, or call
  `packages.rules.engine.run_checks` directly; it's the simplest single-argument entry point and
  is now also what `packages/api/checks.py` finds when it probes for `run_checks` first.
- **No `check_family` field was added** to the pack (your ask for `instrument_conflict`
  detection) — the `PUDA1996.<family>.*` rule_id prefix convention above should already give you
  a exact split without a new field, but shout if you need something more structured (e.g. two
  rules in *different* packs sharing a family) once a second jurisdiction pack exists.

### What Track D (report/API) should know

- Confirmed working end-to-end: `packages/api/checks.py`'s `_find_real_entry_point()` finds
  `evaluate_path` and `evaluate`+`load_pack` on `packages.rules.engine` and both resolve
  correctly via `_resolve_pack_path()` (exact match on `puda_1996.yaml` since it's the only pack
  file). `run_checks(model)` (see above) is also now available as a third, simpler option if you
  want to drop the `_find_real_entry_point` probing logic later — same single-argument shape you
  originally documented as the contract.
- **The `test_api.py` failures Track A flagged are now fixed.** Root cause was exactly what Track
  A's note above says: `packages/rules/packs/*.yaml` used `remedies: [reduce_footprint, ...]`
  (matching CLAUDE.md §7's own — inconsistent with the frozen schema — example), but
  `Remedy.kind`'s `Literal` in `packages/schema/findings.py` doesn't include `"reduce_footprint"`.
  Fixed by using `"geometric_edit"` everywhere in `puda_1996.yaml` instead (shrinking a footprint
  *is* a geometric edit; no schema change needed, no new remedy kind invented). Full repo test
  suite (`pytest tests/`) is green at 79/79, `test_api.py` at 15/15.
- Every `Finding` this engine emits carries a real `Citation` (`doc`, `clause`, `version`,
  `status`) resolved straight from the pack's `source` field — no finding without one, per
  CLAUDE.md §1 rule 2. `citation.status` mirrors the rule's pack-level `status`
  (verified/seed_unverified/conflict/not_stated), so the report layer can style them differently
  without a second lookup.
- `geometry_ref` is populated on violations where a specific ring/line is implicated (footprint,
  courtyard ring, projection polygon, plot polygon for FAR/coverage/height) and left `None` when
  a finding isn't about one specific shape (e.g. the stilt-FAR ambiguity, which concerns two
  computed numbers, not a location).

### Schema-gap asks (frozen schema not touched, per CLAUDE.md §1 rule 7 — filing the need here)

`packages/schema/building_model.py` has no field for a plot/building's **use classification**
(residential_plotted / commercial / industrial / group_housing / public). Every rule in
`puda_1996.yaml` is authored `applies_when.use: residential_plotted`, and
`packages/rules/engine.py::_applies()` currently treats this filter as always-true (documented
assumption, printed in the pack header) since there's nothing to check it against. If a schema
revision ever happens, adding something like `Jurisdiction.building_use` (or a top-level
`BuildingModel.building_use`) would let the engine actually gate commercial/industrial/public
rules (several already sit in the pack with `enforced: false` for exactly this reason: FAR/
coverage bands for those uses were transcribed and verified but have nowhere to attach).

Also **not enforced today for lack of a schema field** (numeric facts are verified and sitting in
the pack, ready the moment a field exists): door/window projection width, projection height-
above-plinth, courtyard-width-vs-abutting-wall-height, habitable-room-open-space-width,
commercial/public staircase width, staircase riser/tread, landing width. None of these block the
demo priority list (CLAUDE.md §7 items 1-5 are all `enforced: true`).

### GIS (`packages/gis/`) — kept intentionally minimal per the task brief's priority order

`packages/gis/layers/periphery.geojson` is an explicitly-labeled **illustrative placeholder**
polygon (not a digitized Periphery Control Act 1952 boundary — no GIS source data was supplied,
only the legal text in `periphery_control_rules_1959.pdf`). `packages/gis/lookup.py::
check_periphery(lon, lat)` does real point-in-polygon via shapely but always returns
`confidence: "low"` and a note explaining the placeholder status. Not wired into the rules engine
or Findings — `BuildingModel` has no real-world lon/lat field to feed it (only a local metric
`plot_polygon`), so this needs a geocoding step from Track A/D before it can produce a Finding.
Left as a standalone module for whoever adds that step.

### Files changed/added (all inside this track's packages per CLAUDE.md §4)

- `tools/transcribe.py`, `tools/verify.py` (new)
- `tools/coverage.py` (bugfix: `load_rule_clause_ids()` was building bare clause numbers instead
  of `"<doc_id>:<clause>"` ids, so it never matched anything in `clauses.jsonl` and reported
  "rules referencing this doc: 0" even after rules existed — fixed to pair `doc:`/`clause:` on
  the same YAML line)
- `packages/rules/__init__.py`, `packages/rules/engine.py`, `packages/rules/packs/puda_1996.yaml` (new)
- `packages/gis/__init__.py`, `packages/gis/layers/periphery.geojson`, `packages/gis/lookup.py` (new)
- `corpus/extracted/puda_building_rules_1996/rule_synthesis/{transcribe_pass1.json,verify_pass1.json}` (new — the audit trail)
- `corpus/extracted/*/REPORT.md` (regenerated via `python tools/coverage.py`; puda_building_rules_1996's
  orphan list dropped from 15 numeric clauses to 3 — the 3 remaining are genuinely out of this
  pack's scope: manholes/absorption-pits drainage clauses and the IT-park FSI relaxation clause)
- `tests/test_rules_engine.py` (new, 16 tests)

## Second jurisdiction: Chandigarh corpus ingest, step 1 of N (2026-09-20)

User confirmed Mohali/GMADA work is done for now and asked to move to Chandigarh as a **second,
separate jurisdiction** -- explicit instruction: this must not interfere with the Mohali/PUDA
pipeline or the frontend in any way. This entry covers only corpus ingest (CLAUDE.md §6.1/§6.2),
the first of several planned steps -- no rule pack, no schema change, no engine/API/frontend
change yet.

**What was added, all purely additive:**
- `corpus/raw/chandigarh_building_rules_urban_2017.pdf` -- the actual source PDF (user pasted it
  directly into `corpus/raw/`, not reconstructed from chat text -- deliberately asked for the
  real file rather than re-typing 123 pages of dense numeric tables from the conversation
  transcript, since a citation-anchored pipeline shouldn't run against a hand-reconstructed
  approximation of its own source of truth).
- `corpus/MANIFEST.json` -- new entry, `doc_type: base_rules`, sha256-anchored. Notes field flags
  two things worth reading before the rule-pack step: (1) this introduces a jurisdiction/authority
  value ("Chandigarh") that doesn't exist yet in the frozen `Jurisdiction.authority` enum
  (`GMADA`/`MC_KHARAR`/`MC_ZIRAKPUR`/`UNKNOWN`) -- extending that enum is a deliberate future step
  per CLAUDE.md §4's "announce before touching schema," not done here; (2) clause 2(vi) of this
  document makes NBC/MBBL-2016 an *incorporated-by-reference fallback* for this jurisdiction
  specifically ("where these rules are silent... NBC/MBBL-2016... shall prevail") -- different
  from CLAUDE.md §6.8's general rule that a `reference`-type doc can never be the sole basis for
  a violation; worth resolving explicitly when a Chandigarh rule pack gets authored, not silently
  defaulting to the general rule.
- `tools/extract.py` -- added `chunk_clauses_chandigarh()` + `_chandigarh_locate_top_headings()`,
  dispatched **only** for `doc_id == "chandigarh_building_rules_urban_2017"` (checked: `git
  status` after re-running `python tools/coverage.py` on all 5 docs shows the 4 existing
  `REPORT.md` files byte-identical -- confirmed non-interference, not just assumed). The existing
  `chunk_clauses()` (PUDA-tuned) is untouched.
  - **Why a separate chunker at all**: this document's numbering is far more heterogeneous than
    the other four -- top-level sections are bare "N HEADING" with no period (sometimes spaced
    letter-by-letter, e.g. "D E F I N I T I O N S", "1 0   M I S C E L L A N E O U S..."), clause
    3's ~95 definitions restart numbering at "1)" without decimal anchors, and real sub-clauses
    use ordinary dotted decimals (4.1, 11.1.1, 12.2.7) that also appear as page-reference numbers
    in the Table of Contents. CLAUDE.md §6.2 says explicitly to write the chunking regex against
    the real document rather than force one pattern across all of them -- confirmed necessary by
    trying the existing regex first: it produced ~40 spurious "repeated number" anomalies before
    any rework, because table "Sr. No" columns and clause-3 definitions are structurally
    indistinguishable from top-level clause markers by local pattern alone.
  - Top-level sections (1-15) are located by whitespace/punctuation-insensitive substring search
    against known heading text taken from the document's own Table of Contents, not a regex --
    the ONLY reliable way found to handle the inconsistent letter-spacing. Sub-clauses (dotted
    decimals) use a real per-line regex, since that pattern doesn't collide with table data.
  - Three real bugs found and fixed during this work (all covered by
    `tests/test_extract_chandigarh.py`): (1) sub-headings split across two lines ("4.2\nResidential
    (GROUP HOUSING)") were originally missed entirely, silently merging 4.2 into 4.1's text; (2) a
    high-tension clearance-zone table row ("High voltage lines above 11 KV...") was matched as a
    fake sub-clause "11.50", stealing the rest of that table away from the real clause 11.2.3 --
    fixed with a plausibility bound (no real sub-clause in this document nests past a low single
    digit) and the rejection is now logged as an anomaly rather than silently dropped or silently
    wrong; (3) heading extraction was splitting on any hyphen, truncating "Re-Validation of
    Building Plans" down to "Re" -- fixed to only trim a trailing ":-"/":"/"." suffix.
  - One known, documented gap left as-is rather than chased down: clause "12.2 PROVISIONS FOR HIGH
    RISE DEVELOPMENT" has no entry of its own because the source PDF itself typesets its heading
    malformed ("12 . 2PROV ISIONS...") -- its brief intro folds into 12.1's text; its numbered
    children (12.2.1-12.2.7) are captured correctly and unaffected. Recorded as an anomaly in
    `REPORT.md`, not silently missing.
- `corpus/extracted/chandigarh_building_rules_urban_2017/{clauses.jsonl,extract_health.json,
  REPORT.md,pages/}` -- 88 clauses, 4 genuinely-blank OCR-flagged pages (verified by hand, not
  scans -- just blank divider pages in the original), 2 anomalies (both documented above), 33
  orphan clauses with numeric content flagged as the rule-authoring to-do list (0 rules reference
  this doc yet -- expected and correct at this stage, same as CLAUDE.md's own description of
  Stage 0/early Stage 1 for any freshly-ingested document).
- `tests/test_extract_chandigarh.py` (new, 5 tests) -- regression guards for the three bugs above
  plus a top-level/annexure completeness check and a duplicate-clause-id check.

**Verified non-interference**: full suite 109/109 (104 pre-existing + 5 new) after this work;
`git status` confirms the four existing corpus documents' extracted output is byte-identical to
before. Nothing under `packages/rules/`, `packages/api/`, or `web/` was touched.

**Not done yet** (future steps in this jurisdiction's onboarding, not started): table
transcription (§6.3, needs a two-pass vision transcription like PUDA's), rule synthesis + verify
(§6.4/§6.5, `tools/transcribe.py`/`tools/verify.py`), a `chandigarh_2017.yaml` rule pack, extending
`Jurisdiction.authority` to include a Chandigarh value, and any engine/API/frontend wiring to
actually let a user select Chandigarh as a jurisdiction. None of these were requested yet --
this entry covers ingest only, per the user's own "this is the first step."

## Second jurisdiction: Chandigarh rule pack + schema/engine wiring, step 2 (2026-09-20)

User asked to "create whatever's required" so a real Chandigarh house drawing can be tested the
moment it's uploaded. This is everything downstream of the ingest-only step above: a real,
two-pass-verified rule pack, the schema extension that step deliberately deferred, two shared
`packages/rules/engine.py` bugs found and fixed (both would have broken the moment a second pack
existed, whether or not this specific work happened), and jurisdiction registration. Frontend:
zero code changes needed -- confirmed by checking `IntakeScreen.jsx`'s jurisdiction dropdown,
which already renders `/jurisdictions` generically; Chandigarh appears there automatically now
that the API returns it.

**Schema** (`packages/schema/building_model.py`): `Jurisdiction.authority` literal gained
`"CHANDIGARH"`, announced here per CLAUDE.md §4 rather than silently changed. No other field
touched.

**Two shared-engine bugs found and fixed** (both were real bugs, not Chandigarh-specific -- a
second pack of ANY kind would have hit them):
1. **Pack resolution silently depended on a filename that didn't match its own `rule_pack`
   value.** `packages/rules/packs/puda_1996.yaml` was named differently from the string
   `"puda_building_rules_1996"` every `Jurisdiction.rule_pack` field actually holds, so every
   resolution in `packages/rules/engine.py::run_checks`, `packages/api/checks.py::
   _resolve_pack_path`, and this session's own `packages/rules/estimated_envelope.py::
   _setback_formula_constants` was silently going through the "exactly one pack file exists,
   use it" fallback path, never the real exact-match path the code was actually written to
   prefer. Renamed the file to `puda_building_rules_1996.yaml` so exact-match resolution
   actually resolves exact matches; the fallback is now a genuine fallback again. Updated the
   one test with a hardcoded path (`tests/test_rules_engine.py::PACK_PATH`) and every docstring
   reference. Full suite passed unchanged before and after -- this was a latent bug with zero
   observable effect until a second pack existed, exactly the kind of thing worth fixing
   proactively rather than leaving for the first person who adds a third pack to debug blind.
2. **`evaluate()`'s jurisdiction-unknown fallback hardcoded `"PUDA1996"` / `"puda_building_rules_
   1996"` / `"GMADA, MC_KHARAR, or MC_ZIRAKPUR"` regardless of which pack was actually being
   evaluated.** Would have produced a Chandigarh-pack Finding falsely claiming to be a PUDA rule
   citing the wrong document the moment any Chandigarh case had `authority: UNKNOWN`. Fixed to
   read `pack_id`/`jurisdiction`/`doc_id`/`title` from the pack dict itself. Covered by
   `tests/test_rules_engine_chandigarh.py::test_jurisdiction_unknown_reports_this_packs_own_
   identity_not_puda`.

**Also fixed**: `packages/rules/estimated_envelope.py::_setback_formula_constants`'s docstring
and one test (`tests/test_estimated_envelope.py`) updated for the now-correct behaviour --
an unresolved `rule_pack` id returns `None` rather than silently falling back to "the sole pack"
now that two packs genuinely exist. Added a test confirming Chandigarh's own pack correctly
returns `None` too (no `kind: setback_formula` rule exists in it at all -- see below).

**New rule pack** (`packages/rules/packs/chandigarh_building_rules_urban_2017.yaml`), scope:
clause 4.1 "Residential (PLOTTED)" only, mirroring PUDA's own residential-plotted scope. Built
through the real two-pass transcribe+verify discipline (CLAUDE.md §6.4/§6.5) via two separate,
fresh Claude subagent calls -- the verifier saw only the proposed value + raw clause text, never
the transcriber's reasoning or quoted-fragment justification, per the strict contract in
`tools/transcribe.py`/`tools/verify.py`. Audit trail committed:
`corpus/extracted/chandigarh_building_rules_urban_2017/rule_synthesis/{transcribe_pass1.json,
verify_pass1.json}`. Result: 102 proposed facts, 97 `match` (-> verified), 5 `not_stated` (->
seed_unverified: the Set Backs row itself, and three MARLA-band "Optional, no capacity stated"
cells for RWH/solar-water/solar-PV/servant-quarter). Zero `mismatch`/conflict verdicts.

**20 rules in the pack; only 6 enforced today**, and that split is deliberate, not partial work
abandoned:
- **Enforced** (the engine actually runs these against a real BuildingModel): zoned-area
  containment (correctly `unknown` without a real zoning plan, same as PUDA), habitable-room +
  kitchen min height (2.75 m, via `Floor.height_m` as proxy, room_uses=[bedroom,living,kitchen]),
  bath/WC/toilet min height (2.29 m, room_uses=[bath,wc] -- Room.use has no "toilet"/
  "powder_room" value, a disclosed mapping), light/ventilation ratio (1/8), basement min height
  (2.4 m), staircase min width (1.0 m). Verified end-to-end through the real HTTP `/checks/run`
  route (not just the engine function directly) against a retargeted Mohali stub -- real
  pass/violation/unknown verdicts came back, `engine_source: "real"`.
- **Verified but `enforced: false`** (the number is confirmed accurate; the engine can't safely
  apply it yet, for two different disclosed reasons, never silently guessed around):
  1. *Plot-size band boundary unresolved*: ground coverage (65/50/45/35%), FAR (2.0/1.5/1.25/
     1.0), height (10.06m Phase-I / 9.83m Phase-II / 10.67m for Kanal+), storeys (3), and
     parking (1/2/3/6 ECS) all vary by plot-size CATEGORY (MARLA / ONE KANAL / TWO KANAL /
     ABOVE TWO KANAL), but clause 4.1 never states the sq-metre boundary of each category
     anywhere in its own text -- marla/kanal-to-sqm is a land-measurement-unit fact, not
     something this clause states, and this document elsewhere expresses areas in sq yards for
     other categories (Annexure-2, Group Housing's "600 Sq. yds.") which is a specific reason
     not to assume a generic Punjab-revenue marla/kanal conversion applies unmodified to
     Chandigarh's own residential-plotted categories without checking. Per CLAUDE.md §1 rule 1
     ("never infer a number... from general knowledge"), this boundary is left unresolved rather
     than assumed. **Concrete next step if/when this is worth resolving**: find an authoritative
     Chandigarh-specific marla/kanal-to-sqm definition (ideally from this same corpus or a
     Chandigarh Estate Office source) and run it through the same two-pass discipline, then flip
     `enforced: true` on the 13 affected rules and add `plot_area_sqm: {min, max}` bands to each
     (the engine's `site_coverage_slab`/`far_band` kinds already support banding generically --
     see how PUDA1996.far.* does it -- no engine code change needed, only the YAML).
  2. *No matching engine `kind` exists yet*: MARLA-band height's Phase-I/Phase-II ambiguity would
     need this anyway even with a resolved band (which Phase applies to a given plot is an
     external, area-specific fact -- an `ambiguity_class: vintage`-shaped question, not a
     transcription problem), plus storeys-max, staircase riser/tread all have no generic
     `_check_*`/`_DISPATCH` handler in `packages/rules/engine.py` -- same category of gap as
     PUDA's own `courtyard.width_vs_mean_height`/`room.open_space_min_width`/`staircase.riser`/
     `staircase.tread` rows, which are also verified-but-unenforced for the identical reason.
  Every one of these stays fully citable in the pack and in any generated report -- `enforced:
  false` only stops the ENGINE from applying it; it does not hide the verified fact.

**Genuinely missing, not deferred**: setbacks. Unlike PUDA1996 clause 17 (a fraction-of-height
formula), clause 4.1's Set Backs row states only "As per Zoning/ Frame Control" -- there is no
formula in this jurisdiction's residential-plotted rules at all. `estimated_envelope.py`'s
`_setback_formula_constants()` correctly returns `None` for this pack (no `kind:
setback_formula` rule exists in it), so the setback-estimate feature (built for Mohali earlier
this session) is honestly unavailable for Chandigarh cases -- not a bug, a real jurisdictional
difference, covered by `test_setback_constants_none_for_a_pack_with_no_setback_formula_at_all`.

**Jurisdiction registered** (`packages/api/main.py::_JURISDICTIONS`): `{"id": "chandigarh_ut",
"label": "Chandigarh (UT)", "authority": "CHANDIGARH", "rule_pack":
"chandigarh_building_rules_urban_2017", ...}`, with a `source_note` that discloses the enforced/
verified-only split above rather than presenting it as equivalent to the Mohali pack. `GET
/jurisdictions` now returns both; verified via `POST /checks/run` end-to-end against the real
HTTP route (not just calling the engine function directly).

**New tests**: `tests/test_rules_engine_chandigarh.py` (7 tests: pack loads with correct
citations, enforced/unenforced split matches the documented gaps exactly, every finding cites
the Chandigarh doc, containment is honestly unknown without a zoning plan, room/staircase/
basement checks produce real pass/violation verdicts on a clean stub, unenforced rules never
leak a finding, and the jurisdiction-unknown regression test above). Updated
`tests/test_estimated_envelope.py` (2 tests fixed/added for the new pack-resolution behaviour).
Full suite: 117/117 (110 pre-existing + 7 new).

**What actually changes for the user's real Chandigarh test**: once their drawing is uploaded
with jurisdiction set to Chandigarh, they will now get real room-height, light/ventilation,
basement, and staircase-width findings (not "0 rules loaded"), an honest `unknown` for
containment (same as Mohali until a zoning plan exists), and no ground-coverage/FAR/height/
parking findings at all yet -- those numbers are sitting verified in the pack, just not wired to
fire until the plot-size-band question above is resolved. This is a real, if partial, checking
capability, not a placeholder.
