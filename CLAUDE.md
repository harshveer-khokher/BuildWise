# mohali-check

Pre-submission compliance checker for building drawings in the Greater Mohali area.
Upload a drawing → get violations, ambiguities, and verified fixes, before it enters the
GMADA/PUDA approval loop.

**Hackathon build, agent-driven.** Read this whole file before writing code.

---

## 1. Non-negotiable rules

These override anything else in this file. If a task seems to require breaking one, stop and ask.

1. **No LLM ever produces a number or a verdict.** Models classify labels and write prose.
   All arithmetic, geometry, and pass/fail comes from deterministic code. A hallucinated
   setback value destroys the entire product's credibility.
   *One narrow exception, tightly fenced:* a model may **transcribe** a number that is
   physically present in a source document, during corpus extraction only (§6). Transcription
   is not generation — and it is only accepted when two independent passes agree exactly and
   the value is anchored to a `clause_id`. Everything else stays code.
2. **Every `Finding` carries a citation.** Rule id, document, clause, version. No citation → no finding.
3. **All geometry via `shapely`.** No hand-rolled polygon math, no trigonometry by hand.
4. **Internal units are metres and square metres.** Convert at the display layer only.
   Mohali practice uses sq yards: `1 sq m = 1.196 sq yd`. Both appear in output.
5. **Never output "approved" or "compliant."** Output is `pre-submission check: N issues found`.
   This tool is not a sanction. Say so in the UI and in the PDF footer.
6. **Numeric rule values are seeded, not verified.** Every value in a rule pack carries
   `status: seed_unverified` plus its clause reference until someone diffs it against the
   gazette. Surface this in the report. Fake precision is worse than declared uncertainty.
7. **Don't edit another track's package.** See §4. If you need a change in someone else's
   package, write the need into `INTEGRATION.md` at repo root instead.

---

## 2. Domain glossary

You will not know these. Get them right.

| Term | Meaning |
|---|---|
| **GMADA** | Greater Mohali Area Development Authority — the sanctioning body for Mohali sectors |
| **PUDA** | Punjab Urban Planning & Development Authority — parent body; publishes the Building Rules |
| **Building Rules 2021** | Current PUDA ruleset. Applies outside municipal limits |
| **Punjab Municipal Building Byelaws 2018** | Applies *instead*, inside MC areas (Kharar, Zirakpur). Jurisdiction routing is step zero |
| **Zoning plan** | Per-plot drawing issued by PUDA defining the **zoned area** and coverage clauses. Overrides generic setbacks. Published as PDFs, digitization incomplete |
| **Zoned area** | The polygon the building must sit inside. Containment against this is our flagship check — a polygon operation, not a numeric setback comparison |
| **Architectural Control Sheet** | Like a zoning plan but for commercial pockets; controls facade/height |
| **FAR** | Floor Area Ratio. Total covered area ÷ plot area. Often expressed as a % in Punjab |
| **Ground coverage** | Ground floor footprint as % of plot area |
| **ECS** | Equivalent Car Space — the parking unit |
| **Stilt** | Open ground-level parking storey. Whether it counts toward FAR/height is genuinely contested → ambiguity, not violation |
| **Mumty** | Stair head enclosure on the roof. Usually excluded from height and FAR |
| **Chajja** | Projecting sun shade over an opening. Has its own projection limits |
| **Setback** | Mandatory open space between plot line and building, per edge (front/rear/side) |
| **Compounding** | Paying a prescribed fee to regularise a violation instead of redrawing. PUDA has a composition policy. Some offences are compoundable, some are not — this distinction is product-critical |
| **Chargeable FAR** | Recent policy allows buying extra FAR at a fee tied to collector rate |
| **Periphery** | Punjab New Capital (Periphery) Control Act 1952 zone — a GIS constraint, not a drawing one |
| **Empanelled architect** | GMADA-approved architect who can self-certify residential plots up to 500 sq yd. **This is our buyer** — deemed approval puts liability on them |

---

## 3. Repo layout

```
mohali-check/
  CLAUDE.md                     ← this file
  INTEGRATION.md                ← cross-track requests; append, don't edit others' code
  corpus/
    MANIFEST.json               ← doc_id, url, sha256, fetched_at, version
    raw/                        ← original PDFs, immutable, never edited
    extracted/<doc_id>/
      clauses.jsonl             ← the machine-readable source of truth
      tables/*.json             ← transcribed tables, two-pass agreed
      pages/*.png               ← rasterized pages, for vision transcription
      REPORT.md                 ← extraction health, auto-generated
  tools/
    extract.py  transcribe.py  verify.py  coverage.py
  packages/
    schema/     building_model.py  findings.py     ← FROZEN in Stage 0
    cases/      real/*.dxf  real/*.meta.json  synth/*.dxf  stubs/*.model.json
                truth/*.truth.json  mutate.py  gen_stub.py
    parser/     dxf_ingest.py  pdf_ingest.py  semantics.py
    rules/      engine.py  packs/puda_2021.yaml  packs/pmbb_2018.yaml  packs/zoning.yaml
    solver/     repair.py  remedies.py
    ambiguity/  classifier.py  dossier.py
    report/     overlay.py  render.py  templates/
    gis/        layers/*.geojson  lookup.py
    api/        main.py
  web/          React: upload → confirm model → findings → report
  tests/        test_eval.py
```

One package per track. This is what lets four sessions run in parallel without merge conflicts.

---

## 4. Track assignment

Run each in its own `git worktree` with its own Claude Code session.

```bash
git worktree add ../wt-parser  -b track/parser
git worktree add ../wt-rules   -b track/rules
git worktree add ../wt-solver  -b track/solver
git worktree add ../wt-report  -b track/report
```

| Track | Owns | Must not touch |
|---|---|---|
| **A — Parser** | `cases/`, `parser/` | everything else |
| **B — Rules** | `corpus/`, `tools/`, `rules/`, `gis/` | everything else |
| **C — Solver** | `solver/`, `ambiguity/` | everything else |
| **D — Surface** | `api/`, `report/`, `web/` | everything else |

`schema/` is written once in Stage 0, before the split, then frozen. Changing it mid-build blocks
three other people — if it's genuinely necessary, announce it before touching it.

Track A is the long pole. If you have three people, put two on it.

---

## 5. The frozen contract

Write this in Stage 0 into `packages/schema/`. Everything downstream codes against it.

```python
# building_model.py  — metres, square metres, degrees. Polygons are [[x,y], ...] closed rings.

Confidence = Literal["high", "medium", "low"]   # low → must be user-confirmed before rules run

class Jurisdiction:
    authority: Literal["GMADA", "MC_KHARAR", "MC_ZIRAKPUR", "UNKNOWN"]
    sector: str | None
    plot_no: str | None
    allotment_date: date | None          # decides which rule vintage applies
    rule_pack: str                       # e.g. "puda_2021"

class Edge:
    line: list[list[float]]
    faces_road: bool
    road_width_m: float | None
    role: Literal["front", "rear", "side_a", "side_b", "unknown"]

class Room:
    polygon: list[list[float]]
    use: Literal["bedroom","living","kitchen","bath","wc","store","stair","garage","other"]
    floor: int
    openings_area_sqm: float             # for light/ventilation ratio
    confidence: Confidence

class Floor:
    level: int                           # -1 basement, 0 stilt/ground, 1..n
    is_stilt: bool
    footprint: list[list[float]]
    height_m: float | None               # from section, if extractable
    rooms: list[Room]

class BuildingModel:
    source: Literal["dxf", "vector_pdf", "raster"]
    jurisdiction: Jurisdiction
    plot_polygon: list[list[float]]
    plot_area_sqm: float
    zoned_area: list[list[float]] | None # None → containment check is UNKNOWN, not PASS
    edges: list[Edge]
    floors: list[Floor]
    projections: list[dict]              # {type: chajja|balcony, polygon, floor}
    courtyards: list[list[list[float]]]
    mumty: dict | None
    parking_bays: list[dict]
    boundary_wall_height_m: float | None
    has_rwh: bool
    tree_count: int
    assumptions: list[str]               # printed verbatim on the report
```

```python
# findings.py

class Finding:
    rule_id: str
    status: Literal["violation", "ambiguity", "advisory", "pass", "unknown"]
    severity: Literal["blocking", "major", "minor"]
    title: str
    citation: dict          # {doc, clause, version, url}
    observed: float | str | None
    required: float | str | None
    geometry_ref: list[list[float]] | None    # what to highlight on the overlay
    compoundable: bool
    ambiguity_class: str | None               # see §7
    remedies: list["Remedy"]
```

`status: unknown` is a first-class outcome. Missing zoning plan → `unknown`, never `pass`.

---

## 6. Corpus: PDF in, verified rule pack out

The bylaw PDF is supplied. Extract it **once**, into a machine-readable form, then never open the
PDF again during the build. Everything downstream cites `clause_id`, not page numbers.

Target: one command, no human in the loop except reading the final health report.

```bash
make corpus     # ingest → chunk → transcribe → verify → coverage
```

### 6.1 Ingest (`tools/extract.py`)

1. Record the file in `MANIFEST.json`: `doc_id`, source path/url, `sha256`, `fetched_at`,
   `version`. The sha is the citation anchor — if the PDF changes, every rule derived from it
   is invalidated automatically.
2. Probe the text layer per page (`pdftotext` / PyMuPDF). Empty or near-empty → that page is a
   scan. Mark it `ocr_required: true` and OCR it, but **flag every value from an OCR'd page as
   low-trust** and never let it auto-verify. Old PUDA and zoning PDFs are frequently scans.
3. Rasterize every page to `pages/p0042.png` at ~200 dpi. Needed for table transcription and
   for spot-checking.

### 6.2 Clause chunking

Emit `clauses.jsonl`, one object per clause. This file *is* the source of truth for rule authoring.

```json
{"clause_id": "puda_2021:7.3.2",
 "doc_id": "puda_2021",
 "number": "7.3.2",
 "heading": "Setbacks for residential plotted development",
 "text": "...",
 "page": 42,
 "has_table": true,
 "table_ref": "tables/t017.json",
 "ocr": false,
 "parent": "puda_2021:7.3"}
```

Chunk on the numbering pattern, not on token count. Punjab drafting uses `7.`, `7.3`, `7.3.2`,
`(a)`, `(i)` — write the regex against the actual document, then assert every clause has a
parent that exists and that numbering is monotonic. Gaps in the sequence mean the chunker
missed something; fail loudly rather than silently dropping a clause.

### 6.3 Tables — where the numbers actually live

Coverage, FAR, setbacks, height and ECS are all in grid tables, and `pdfplumber` mangles merged
cells and multi-row headers routinely. So:

- Try `pdfplumber.extract_table()` first.
- Independently, hand the **rasterized page image** to a vision pass and ask for the table as
  JSON, with a strict instruction: transcribe only, emit `null` for any cell you cannot read,
  never interpolate a missing row.
- **Compare the two.** Exact agreement → `verified`. Disagreement or any `null` → the cell is
  written as `seed_unverified` with both candidate readings preserved.

Two independent transcriptions agreeing on a plot-size band's setback value is a far stronger
guarantee than a single pass nobody checks. Where they disagree, you learn about it from the
health report instead of from a wrong finding in the demo.

### 6.4 Rule synthesis (`tools/transcribe.py`)

A subagent turns clauses into YAML. Strict contract:

- Input: **only** the clause text and its table, never the whole PDF.
- Output: YAML only. Every rule carries the `clause_id` it came from.
- If the clause does not state a value, emit `value: null, status: not_stated`. **Never infer a
  number from a neighbouring clause, another state's bylaws, or general knowledge.**
- One clause may yield several rules (one per plot-size band). One rule never spans clauses.

### 6.5 Verification loop (`tools/verify.py`) — the thing that removes the human

A second subagent, **fresh context**, sees only: the proposed rule's numeric value, and the raw
clause text it claims to come from. It answers one of `match` / `mismatch` / `not_stated`. It
never sees the first agent's reasoning.

| Verdict | Action |
|---|---|
| `match` | `status: verified`, citation locked |
| `mismatch` | `status: conflict`, both values retained, rule **disabled** |
| `not_stated` | `status: seed_unverified`, rule runs but the report says the value is unconfirmed |

A disabled rule produces `status: unknown` findings, not silent passes. That is the correct
behaviour anyway — see §5.

### 6.6 Coverage report (`tools/coverage.py` → `extracted/<doc_id>/REPORT.md`)

Auto-generated, and the only thing a human reads:

- rules by status: verified / seed_unverified / conflict / not_stated
- **orphan clauses** — clauses containing a number or a table that no rule consumed. This is your
  "what did we miss" list, and it's the highest-value output of the whole pipeline
- pages that needed OCR
- table cells where the two transcriptions disagreed

Skim it once. Fix nothing by hand unless it blocks the hero drawing.

### 6.7 Citations

`Finding.citation` resolves through `clause_id`, so it always carries `{doc, clause number, page,
version, sha256, status}`. In the user-facing PDF, **cite the clause number and paraphrase the
requirement** — don't paste long clause text into the report. Short quoted fragments only where
exact wording is what's in dispute (which is precisely the `definitional` ambiguity class, §8).

### 6.8 Multiple documents — precedence and conflict

The corpus is many PDFs, not one. Each ingests independently under its own `doc_id`; they
parallelise. Classify each on ingest:

| `doc_type` | Examples | Notes |
|---|---|---|
| `base_rules` | PUDA Building Rules 2021 | The default pack |
| `byelaws` | Punjab Municipal Building Byelaws 2018 | Applies *instead* inside MC limits |
| `amendment` | Notifications, gazette corrigenda | Supersedes specific clauses of a base doc |
| `circular` | Policy letters, memos | Short, dated, and high-value per page — ingest these first |
| `policy` | Compounding/composition policy, chargeable FAR | Drives remedies, not pass/fail |
| `zoning` | Per-plot zoning plans, Architectural Control Sheets | Plot-specific, overrides generic setbacks |
| `reference` | NBC, Model Building Byelaws | Persuasive, not binding. Never the sole basis for a violation |

Precedence, highest first: **zoning plan for the plot → amendment/circular (latest effective date)
→ base_rules or byelaws per jurisdiction → reference.**

Two hard rules:

1. Precedence decides which value a rule *uses*. It does **not** let us discard the loser silently.
   When two binding instruments give different values for the same check, the finding is emitted
   with `ambiguity_class: instrument_conflict`, both values, both citations, and which one we
   applied. That's not a workaround — it's literally the product (§8).
2. Every doc carries `effective_from` and, where known, `effective_to`. A rule only applies if the
   plot's allotment/submission date falls in range. An amendment with no clear effective date is
   `seed_unverified`, never assumed current.

A `reference` doc can never produce `status: violation` on its own — at most `advisory`. NBC minima
quoted as a binding requirement is exactly the kind of wrong-but-confident finding that loses an
architect's trust permanently.

Amendments are the trap: a two-page circular can invalidate a whole verified table.
Ingest circulars and notifications **before** the big base-rules PDF, so the base values arrive
already knowing what supersedes them.

### 6.9 Zoning plans

Per-plot, frequently scanned, and amended by individual memos over the years. Do not try to batch
automate these in this build. Each is a **dated snapshot**, not a fact: store `{sector, plot_range,
issued, amended_by[]}` alongside the traced polygon.

The zoned area comes from the in-app tracing UI (§11, Stage 3). And note: PUDA warns that editing
an approved zoning plan and submitting it is an offence — so we read them, trace our own geometry,
and every overlay we render is labelled as a derived drawing, never presented as a zoning plan.

---

## 7. Rule packs are data, not code

```yaml
- id: PUDA2021.ground_coverage.250_350
  title: Maximum ground coverage
  source: {doc: "PUDA Building Rules 2021", clause: "TBD", version: "2021", url: "..."}
  status: seed_unverified
  applies_when:
    authority: GMADA
    use: residential_plotted
    plot_area_sqm: {min: 250, max: 350}
  check: "ground_coverage_pct <= 60"
  severity: major
  compoundable: true
  remedies: [reduce_footprint, purchase_chargeable_far]
```

Ship ~20 rules. Priority order — build top-down, stop when budget runs out:

1. **Zoned-area containment** (`footprint.within(zoned_area)`) — the flagship
2. Ground coverage
3. FAR
4. Front / rear / side setbacks
5. Max height and storeys (incl. stilt handling)
6. Projections beyond the building line
7. Basement extent and level count
8. Room minimum area and minimum dimension
9. Light & ventilation ratio (opening area ÷ floor area)
10. Staircase width, tread, riser, headroom
11. Courtyard minimum dimension
12. Parking ECS count by plot band
13. Boundary wall height
14. Rainwater harvesting required above 100 sq m
15. One tree per 80 sq m for plots above 100 sq m

GIS-layer checks (`gis/`, not from the drawing): periphery control zone, defence establishment
NOC radius, Mullanpur no-development zone, highway control lines. Point-in-polygon against plot location.

**Adding a second pack (`pmbb_2018.yaml`) is worth more than five extra rules** — it proves the
engine is data-driven rather than hardcoded, which is the whole architectural claim.

---

## 8. Ambiguity engine — this is the USP

Ambiguity is a classified outcome, not "low confidence." Classes:

| Class | Trigger |
|---|---|
| `extraction` | Couldn't read a dimension reliably |
| `missing_input` | Zoning plan not digitized; allotment date unknown |
| `instrument_conflict` | Rules 2021 vs zoning plan clause vs NBC vs later circular |
| `vintage` | Which FAR regime applies to an older allotment; stilt+4 applies to new urban areas only |
| `discretionary` | Clause says "may be permitted by the competent authority" |
| `definitional` | Does the stilt / balcony / mumty count toward FAR |
| `practice_divergence` | Rule permits it, this office routinely objects |

Each ambiguity produces a **dossier**: both readings, which is safer, the exact document to carry
as proof, and a **submission-ready justification paragraph** the architect can attach. The LLM writes
the prose. The classification and the underlying numbers come from the engine.

That justification paragraph is the thing people would pay for. Give it real time.

---

## 9. Solver — brute force, fully verified

Not a CSP. A grid search:

1. Enumerate parameterized edits per violation: shrink a wall in 0.1 m steps, trim a projection,
   reclassify a room, shift the stair, reduce the basement footprint.
2. Apply the edit to a copy of the `BuildingModel`.
3. **Re-run the entire rule pack.** Fixing a setback routinely breaks FAR or room minimums —
   a one-rule-at-a-time fixer gives actively bad advice.
4. Keep only candidates where nothing regressed. Rank by area lost.
5. Add non-geometric remedies where the rule allows: chargeable FAR purchase, compounding,
   NOC route, zoning revision request.

A few thousand candidates evaluates in seconds and is genuinely correct. The LLM then narrates
each verified fix in architect language with tradeoffs — it never invents a number the solver
didn't produce.

---

## 10. Test cases: stubs now, real drawings when they land

Real Mohali drawings are coming but may not be there at the start. Build against placeholders, swap in
real data the moment it arrives, and make it **structurally impossible** for the placeholders to
silently survive into the metrics or the demo.

### 10.1 A case is a building, not a file

Drawings arrive as **sheet sets**: ground floor plan, upper floor plans, section, elevation, site
plan — 4–5 files for one building. One case = one building = one `BuildingModel`.

```
cases/real/h01/            # one building
  ground.dxf  first.dxf  section.dxf  elevation.dxf  site.dxf
  h01.meta.json            # includes sheets: {role → file}
```

Assembly is a required parser step, not an extra:

| Sheet role | Contributes |
|---|---|
| `site` / `zoning` | Plot polygon, road edges, zoned area |
| `plan` (per level) | Footprint, rooms, openings, projections for that `Floor.level` |
| `section` | **`Floor.height_m`, total height, basement depth, stilt clearance** — available nowhere else |
| `elevation` | Cross-check on total height and storey count only |

Infer sheet role from filename and title-block text, then **have the user confirm the role mapping**
on the confirmation screen before assembly runs. A section misread as a plan produces a
catastrophically wrong model, and it's a one-click fix if you ask.

Assembly assertions — fail loudly, don't guess:
- every `plan` sheet maps to a distinct `level`
- plan footprints share a common origin/datum with the site sheet; if they don't, ask for the
  reference point rather than aligning by bounding box
- storey count from the section matches the number of plan sheets; mismatch → `extraction` ambiguity

If height cannot be recovered from the section, height and FAR rules emit `unknown`, never `pass`.

### 10.2 Placeholder mode — unblocks three tracks quickly

Tracks B (rules), C (solver) and D (report/UI) never touch a DXF. They consume a `BuildingModel`.
So they don't need synthetic *drawings* — they need synthetic **models**.

`cases/gen_stub.py` hand-writes six `stubs/*.model.json` conforming to §5:

| Stub | Exercises |
|---|---|
| `s01_clean_250` | All-pass baseline |
| `s02_setback_rear` | Rear wall 1.2 m into setback; a 0.4 m fix exists |
| `s03_far_over` | FAR exceeded, compoundable |
| `s04_stilt4_500` | Stilt+4 → FAR-treatment ambiguity (`definitional`) |
| `s05_no_zoning` | `zoned_area: null` → containment must return `unknown`, never `pass` |
| `s06_low_conf` | Low-confidence room labels → confirmation UI path |

That's the whole unblock. Tracks B/C/D can run to completion on these and never need the parser.

Track A additionally gets **one** minimal `synth/*.dxf` as an ingest smoke test. Write its layer
names deliberately ugly and inconsistent (`WALL`, `wall-ext`, `A-WALL-EXTR`, `BDRM-1`, `MBR`,
`TOIL`) so nobody is tempted to treat clean naming as the norm. One file, not a generator suite —
the parser's real problem is naming chaos across offices, and no generator reproduces that.

### 10.3 Provenance discipline — the part that matters

Every case carries `provenance: synthetic | real | mutated_real`. Then:

- `make eval` reports metrics **segmented by provenance**, never pooled
- **Headline numbers are computed from `real` and `mutated_real` only.** Synthetic accuracy is a
  smoke test, not a result — reporting it as accuracy is self-deception
- If zero real cases are loaded, `make eval` prints a loud banner:
  `NO REAL CASES — METRICS ARE NOT MEANINGFUL` and every downstream report inherits the flag
- **Never demo on a synthetic case.** The hero drawing is real. If drawings haven't arrived by
  Stage 4, that's a project-level escalation, not something to paper over at freeze
- When real drawings land, synthetic demotes to smoke tests permanently. Do not delete them —
  they're useful regression fixtures — but they stop counting

The failure mode this prevents is specific and common: you tune the parser until synthetic cases
pass, the numbers look great, and then the first real drawing from an office with different layer
conventions parses into garbage. Segmented metrics make that visible instead of flattering.

### 10.4 The real set

Variance over volume. Ten drawings from one office is roughly one drawing.

- 12 minimum, 20–25 ideal, spanning **4–5 different drafters/offices**
- Plot-size bands: several ≤125 sq yd, several 250, several 500, one large if available
- Feature coverage: at least one stilt, one basement, one courtyard, one corner plot
- DWG/DXF primary. Any PDF-only drawings become the Tier B test set, not the majority

Worth more than another ten clean files:

| Asset | Why |
|---|---|
| Rejected drawing **+ its objection memo** | Ground truth for what GMADA actually objects to. Seed corpus for the `practice_divergence` ambiguity class (§8). Two or three of these beat twenty compliant plans |
| Zoning plan PDF for the same plot | Containment runs against a real zoned area, not an invented polygon |
| Approval status + date | Determines which rule vintage applies |

Each drawing gets a `real/<id>.meta.json`: provenance, sector, plot no., plot area, allotment date,
authority, outcome (`approved` / `rejected` / `unknown`), objection memo path, zoning plan path.

### 10.5 Getting ground truth cheaply

Hand-labeling 20 drawings is budget we shouldn't spend. Two moves remove it:

**Mutation.** Take a drawing that was approved and perturb it in DXF — shift the rear wall 1.2 m
inward, extend a projection, add a floor, enlarge the footprint. Real geometry, real layer names,
synthetic defect with **exactly known truth**. One compliant drawing yields a dozen labeled
violation cases.

```python
# cases/mutate.py
mutate("real/d03.dxf", op="offset_edge", edge="rear", delta=-1.2)
  # → truth/d03_m01.truth.json : {rule_id: "...setback.rear", status: "violation",
  #                               observed: 1.8, required: 3.0, fix_exists: true}
```

Mutations are declarative and the expected finding is derived from the mutation parameters, not
written by hand. Keep the mutation spec next to the case so the truth file regenerates.

**The confirmation UI is the labeling tool.** Track D is already building a screen where the user
corrects low-confidence labels on a parsed `BuildingModel` (§5). Add a **"freeze as truth"** button:
the confirmed model is written to `truth/<id>.model.json`. Labeling becomes a two-minute pass per
drawing inside the product we're shipping anyway. Build this button in Stage 2, not Stage 4.

### 10.6 Two things the eval measures

Keep these separate — they fail for different reasons and conflating them hides both.

1. **Parser fidelity** — parsed `BuildingModel` vs. frozen truth model. Per-field. This is where
   real-world layer variance shows up, and it's the number that predicts whether the tool works on
   a drawing nobody on the team has seen.
2. **Rule correctness** — findings vs. truth findings on mutated cases. Precision on `violation`
   must be near 100%. A false positive sends an architect redrawing for nothing and loses the
   account permanently; a false negative is merely the status quo.

`tests/test_eval.py` reports both. Put both on the demo slide — nobody else will have numbers.

### 10.7 Hygiene

Real drawings carry owner names, plot numbers and architect seals. Gitignore `cases/real/` and
keep it out of any public repo; commit only `truth/` and the mutation specs. If you demo a real
plot, redact the title block.

---

## 11. Stages

Ordered by dependency, not by clock. Each stage has an **exit criterion** — don't advance until it
holds. The ordering exists because integrating late is how this kind of build fails: four tracks
that each work alone and have never been run together is not a working system.

**Stage 0 — Contracts.** Single session, no parallelism. Write `packages/schema/`, this file,
`make stubs`. Kick off `make corpus` ingest in the background; it runs unattended while everything
else proceeds. Set up the four worktrees.
*Exit: schema frozen and committed; six stubs validate against it.*

**Stage 1 — Parallel build.** Four sessions, one per worktree (§4).
- A: DXF ingest — real drawings if present, else the synth smoke file — then the mutation harness
- B: corpus pipeline → rule engine → first pack
- C: solver core
- D: API skeleton, upload, model-confirmation screen, overlay renderer

*Exit: each track passes its own tests against the stubs, in isolation.*

**Stage 2 — First integration.** Merge all four to main. Run drawing → parser → rules → findings
end to end. Ship the *freeze as truth* button here and label whatever real drawings exist.
Expect breakage; that's the point of doing it now rather than after the depth work.
*Exit: one drawing produces a findings list with citations, start to finish.*

**Stage 3 — Depth.** Zoning-plan tracing UI (user traces the zoned area over the uploaded PDF in
four clicks — turns the weakest dependency into a feature), GIS layers, ambiguity dossiers,
suggestion narration, PDF report.
*Exit: the hero drawing produces a violation, a verified fix, and an ambiguity dossier.*

**Stage 4 — Breadth.** Vector-PDF input (Tier B), eval numbers segmented by provenance, second
jurisdiction pack, rule-version diffing.
*Exit: `make eval` prints real precision/recall with no missing-real-cases banner.*

**Stage 5 — Harden.** Hero drawing pinned, caches warm, backup video recorded, demo script written.
*Exit: the demo has been run start to finish, twice, without a code change between runs.*

**Stage 6 — Freeze. Do not add features.** Only fixes to things the demo touches.

Two ordering rules that override any eagerness to skip ahead: Stage 2 happens before Stage 3 even
if a track feels unfinished, and nothing from Stage 4 enters the demo path unless it survived a
full run in Stage 5.

---

## 12. Commands

```bash
make corpus       # PDF → clauses.jsonl → tables → rule YAML → verify → REPORT.md
make stubs        # write cases/stubs/*.model.json — run this first, unblocks B/C/D
make cases        # regenerate mutations + truth files from cases/real/
make eval         # run findings against truth, print precision/recall
make demo         # end-to-end on the hero drawing, opens the PDF
make dev          # api + web
```

`make corpus` is idempotent and keyed on the PDF's sha256 — rerun it freely. If the sha changes,
every derived rule drops to `seed_unverified` until re-verified. That's intentional.

Define a `/check` slash command that runs `make eval`. Every agent runs it before declaring done.

---

## 13. Cut list, in order

Raster/photo input (Tier C). Fire and egress rules. Elevation-sheet parsing beyond height
extraction. Commercial plots and Architectural Control Sheets. Auth and multi-user. Anything that
does not appear in the hero drawing.

**Not cuttable:** multi-sheet assembly (§10.1). Heights live only in the section and per-floor
footprints live on separate sheets — without assembly, height, storeys and FAR cannot be checked
at all.

---

## 14. Demo narrative

Write this in Stage 0, not at the end.

> Upload DWG → model confirmation screen catches one mislabelled room → findings overlay, rear
> wall glowing red → click the FAR violation, see the clause citation → suggestion panel: *pull
> the rear wall 0.4 m, costs 3.1 sq m, clears all rules — verified* → ambiguity card: *stilt FAR
> treatment is contested under the new stilt+4 policy; here is the safer reading and a draft
> justification note for your submission* → export PDF →
> **"and this plan would have come back from GMADA in six weeks with two objection memos."**

That last line is the pitch. Everything else is proof.
