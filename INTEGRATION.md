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
