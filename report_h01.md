# mohali-check pre-submission report

*Generated 2026-09-19 21:43 IST*

## pre-submission check: 22 issues found

> This is a **pre-submission check only**. It is not an approval, not a sanction, and not a certificate of compliance by GMADA, PUDA, or any authority.

## Plot & jurisdiction

| Field | Value |
|---|---|
| Authority | GMADA |
| Sector / Plot no. | Phase-4 / 351 |
| Rule pack | `puda_building_rules_1996` |
| Allotment date | *unknown* |
| Plot area | *unknown — no site/zoning sheet on file* |
| Zoned area on file | **no — containment check is `unknown`, never `pass`** |

## Bylaws checked

| Document | Version | Clauses cited | Findings | Verification status |
|---|---|---|---|---|
| Punjab Urban Planning and Development Authority (Building) Rules, 1996 (`puda_building_rules_1996`) | 1996-06-27 | §15#2, §17, §18, §20, §22, §24, §25, §26, §3, §4#2 | 31 | seed_unverified: 3, verified: 28 |

*Verification status per CLAUDE.md §6.5: `verified` = two independent transcription passes agreed exactly; `seed_unverified` = value transcribed but not yet independently confirmed against the gazette; `conflict` = passes disagreed, rule disabled; `not_stated` = the clause text does not state a number for this case.*

## Issues (22)

**At a glance, most severe first:**

| Severity | Count | Issues |
|---|---|---|
| 🔴 Blocking | 1 | Building footprint must sit inside the zoned area |
| 🟠 Major | 7 | Maximum ground coverage (slab bands by site area), Maximum FAR -- residential plotted, plots up to 225 sqm, Maximum FAR -- residential plotted, plots above 225 up to 325 sqm, Maximum FAR -- residential plotted, plots above 325 up to 430 sqm, Front/rear setback must be at least one-fourth of building height (min 2 m), Side setback must be at least one-fifth of building height (min 1.5 m), Building height must not exceed abutting road width plus setback width |
| 🟡 Minor | 3 | Habitable rooms must be at least 2.70 m high, WC / bathroom / store / stair mean height must be at least 2.25 m, Aggregate openable area must be at least one-tenth of room floor area |

### ⚪ Unknown — Building footprint must sit inside the zoned area

- **Rule ID:** `PUDA1996.containment.zoned_area`
- **Severity:** blocking
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §3 (v1996-06-27, `seed_unverified`)
- **Ambiguity class:** `missing_input`
- **Compoundable:** no
- **Observed:** —  |  **Required:** zoned_area (from a traced zoning plan)
- **Remedies:**
  - `zoning_revision_request`: No zoning plan has been traced for this plot yet. Containment cannot be checked until one is digitized (CLAUDE.md §10.9) -- this is never silently treated as a pass.

### ⚪ Unknown — Maximum ground coverage (slab bands by site area)

- **Rule ID:** `PUDA1996.site_coverage.slab`
- **Severity:** major
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §15#2 (v1996-06-27 (amended, see notes), `verified`)
- **Ambiguity class:** `missing_input`
- **Compoundable:** no
- **Observed:** —  |  **Required:** —

### ⚪ Unknown — Maximum FAR -- residential plotted, plots up to 225 sqm

- **Rule ID:** `PUDA1996.far.upto_225`
- **Severity:** major
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §4#2 (v1996-06-27 notification amending Rule 16 (dated 17.12.1998), `verified`)
- **Ambiguity class:** `missing_input`
- **Compoundable:** no
- **Observed:** —  |  **Required:** —

### ⚪ Unknown — Maximum FAR -- residential plotted, plots above 225 up to 325 sqm

- **Rule ID:** `PUDA1996.far.225_325`
- **Severity:** major
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §4#2 (v1996-06-27 notification amending Rule 16 (dated 17.12.1998), `verified`)
- **Ambiguity class:** `missing_input`
- **Compoundable:** no
- **Observed:** —  |  **Required:** —

### ⚪ Unknown — Maximum FAR -- residential plotted, plots above 325 up to 430 sqm

- **Rule ID:** `PUDA1996.far.325_430`
- **Severity:** major
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §4#2 (v1996-06-27 notification amending Rule 16 (dated 17.12.1998), `verified`)
- **Ambiguity class:** `missing_input`
- **Compoundable:** no
- **Observed:** —  |  **Required:** —

### ⚪ Unknown — Front/rear setback must be at least one-fourth of building height (min 2 m) — 2 instances

- **Rule ID:** `PUDA1996.setback.front_rear_formula`
- **Severity:** major
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §17 (v1996-06-27, `verified`)
- **Ambiguity class:** `extraction`
- **Compoundable:** no
- **Instances:**

  | Detail | Observed | Required |
  |---|---|---|
  | Front/rear setback must be at least one-fourth of building height (min 2 m) (front) | — | — |
  | Front/rear setback must be at least one-fourth of building height (min 2 m) (rear) | — | — |

### ⚪ Unknown — Side setback must be at least one-fifth of building height (min 1.5 m) — 2 instances

- **Rule ID:** `PUDA1996.setback.side_formula`
- **Severity:** major
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §17 (v1996-06-27, `verified`)
- **Ambiguity class:** `extraction`
- **Compoundable:** no
- **Instances:**

  | Detail | Observed | Required |
  |---|---|---|
  | Side setback must be at least one-fifth of building height (min 1.5 m) (side_a) | — | — |
  | Side setback must be at least one-fifth of building height (min 1.5 m) (side_b) | — | — |

### ⚪ Unknown — Building height must not exceed abutting road width plus setback width

- **Rule ID:** `PUDA1996.height.max_vs_road_setback`
- **Severity:** major
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §17 (v1996-06-27, `seed_unverified`)
- **Ambiguity class:** `missing_input`
- **Compoundable:** no
- **Observed:** —  |  **Required:** —

### ⚪ Unknown — Habitable rooms must be at least 2.70 m high — 3 instances

- **Rule ID:** `PUDA1996.room.habitable_min_height`
- **Severity:** minor
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §22 (v1996-06-27, `verified`)
- **Ambiguity class:** `extraction`
- **Compoundable:** no
- **Instances:**

  | Detail | Observed | Required |
  |---|---|---|
  | Habitable rooms must be at least 2.70 m high (floor 0) | — | 2.7 |
  | Habitable rooms must be at least 2.70 m high (floor 1) | — | 2.7 |
  | Habitable rooms must be at least 2.70 m high (floor 2) | — | 2.7 |

### ⚪ Unknown — WC / bathroom / store / stair mean height must be at least 2.25 m — 3 instances

- **Rule ID:** `PUDA1996.room.service_min_mean_height`
- **Severity:** minor
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §22 (v1996-06-27, `verified`)
- **Ambiguity class:** `extraction`
- **Compoundable:** no
- **Instances:**

  | Detail | Observed | Required |
  |---|---|---|
  | WC / bathroom / store / stair mean height must be at least 2.25 m (floor 0) | — | 2.25 |
  | WC / bathroom / store / stair mean height must be at least 2.25 m (floor 1) | — | 2.25 |
  | WC / bathroom / store / stair mean height must be at least 2.25 m (floor 2) | — | 2.25 |

### ⚪ Unknown — Aggregate openable area must be at least one-tenth of room floor area — 6 instances

- **Rule ID:** `PUDA1996.room.light_ventilation_ratio`
- **Severity:** minor
- **Citation:** Punjab Urban Planning and Development Authority (Building) Rules, 1996, clause §22 (v1996-06-27, `verified`)
- **Ambiguity class:** `extraction`
- **Compoundable:** no
- **Observed:** —  |  **Required:** 0.1

## Passing checks (9)

| Rule ID | Title | Instances | Citation |
|---|---|---|---|
| `PUDA1996.projection.chajja_balcony_max` | Chajja/balcony/cantilever projection must not exceed 2 m beyond the building line | 1 | puda_building_rules_1996 §18 |
| `PUDA1996.projection.row_house_small_site_max` | Projection on row houses / adjoining buildings capped at 1 m when site area < 250 sqm | 1 | puda_building_rules_1996 §18 |
| `PUDA1996.projection.max_width_vs_site_width` | Projection width must not exceed one-fourth of the site width | 1 | puda_building_rules_1996 §18 |
| `PUDA1996.courtyard.min_area` | Closed courtyard onto which habitable rooms abut must be at least 9 sqm | 1 | puda_building_rules_1996 §20 |
| `PUDA1996.courtyard.min_width` | Closed courtyard minimum width in any direction must be at least 2.5 m | 1 | puda_building_rules_1996 §20 |
| `PUDA1996.basement.min_height` | Basement clear height must be at least 2.50 m | 1 | puda_building_rules_1996 §24 |
| `PUDA1996.basement.coverage_not_exceeding_ground_floor` | Basement covered area must not exceed the ground floor's covered area | 1 | puda_building_rules_1996 §24 |
| `PUDA1996.staircase.min_width_residential` | Residential staircase (single/two-family, >1 storey) must be at least 0.70 m wide | 1 | puda_building_rules_1996 §25 |
| `PUDA1996.roof_projection.recede` | Roof-level structures over 2.25 m must recede from the facade by at least their own height | 1 | puda_building_rules_1996 §26 |

## Assumptions made while reading the drawing

*Printed verbatim, per CLAUDE.md §5 — every silent inference the parser made is listed here rather than hidden.*

- No site/zoning sheet supplied: plot_polygon, plot_area_sqm and zoned_area cannot be assembled. Containment, coverage, FAR and setback checks will emit status=unknown, not pass, per CLAUDE.md §5/§10.1.
- No section sheet supplied: Floor.height_m is not recoverable per §10.1 (elevations are cross-check only, never the primary height source). Height and storey-count rules will emit status=unknown.
- Storey count from plan sheets (ground/first/second = 3 levels) should be checked against elevation sheets on ingest; mismatch raises an extraction ambiguity per §10.1.
- [ground.pdf] extract_drawing_bbox: footprint approximated as the vector-drawing bounding box, excluding vector paths starting past x=1420 (rightmost 15% of the 1651pt-wide drawing extent, i.e. the title-block strip). This is an envelope around notes/hatching/dimensions as well as the building outline, not a traced wall polygon -- treat as an upper-bound rectangle.
- [ground.pdf] estimate_scale_pts_per_m: assumed the largest dimension string on the sheet (11.73 m) spans the longer axis of the drawing bbox (2329 pt) -> scale ~198.5 pt/m. Heuristic, not a scale bar; assumes uniform x/y scale and that the largest labelled dimension really is the building's overall extent.
- [ground.pdf] extract_rooms: used a placeholder default size (not the sheet's own dimension text, which failed to parse cleanly) for rooms labelled: ['TOILET', 'LAUNDRY', 'FOYER', 'STAIRCASE', 'PARKING']. openings_area_sqm was not extracted for any room (set to 0.0) -- light/ventilation checks against these rooms will be unreliable until a real value is supplied.
- [ground.pdf] extract_rooms: skipped outdoor/yard labels not representable as an enclosed Room per schema: ['PARKING HALL', 'BACKYARD', 'FRONTYARD', 'FRONTYARD', 'GREEN'].
- [first.pdf] extract_drawing_bbox: footprint approximated as the vector-drawing bounding box, excluding vector paths starting past x=1420 (rightmost 15% of the 1651pt-wide drawing extent, i.e. the title-block strip). This is an envelope around notes/hatching/dimensions as well as the building outline, not a traced wall polygon -- treat as an upper-bound rectangle.
- [first.pdf] estimate_scale_pts_per_m: assumed the largest dimension string on the sheet (10.52 m) spans the longer axis of the drawing bbox (2329 pt) -> scale ~221.5 pt/m. Heuristic, not a scale bar; assumes uniform x/y scale and that the largest labelled dimension really is the building's overall extent.
- [first.pdf] extract_rooms: used a placeholder default size (not the sheet's own dimension text, which failed to parse cleanly) for rooms labelled: ['TOILET', 'DINING / LOBBY', 'BATHING', 'BEDROOM']. openings_area_sqm was not extracted for any room (set to 0.0) -- light/ventilation checks against these rooms will be unreliable until a real value is supplied.
- [second.pdf] extract_drawing_bbox: footprint approximated as the vector-drawing bounding box, excluding vector paths starting past x=1420 (rightmost 15% of the 1651pt-wide drawing extent, i.e. the title-block strip). This is an envelope around notes/hatching/dimensions as well as the building outline, not a traced wall polygon -- treat as an upper-bound rectangle.
- [second.pdf] estimate_scale_pts_per_m: assumed the largest dimension string on the sheet (10.52 m) spans the longer axis of the drawing bbox (2329 pt) -> scale ~221.5 pt/m. Heuristic, not a scale bar; assumes uniform x/y scale and that the largest labelled dimension really is the building's overall extent.
- [second.pdf] extract_rooms: used a placeholder default size (not the sheet's own dimension text, which failed to parse cleanly) for rooms labelled: ['PAPA BEDROOM']. openings_area_sqm was not extracted for any room (set to 0.0) -- light/ventilation checks against these rooms will be unreliable until a real value is supplied.
- assemble_case: no 'section' role sheet supplied -- Floor.height_m left None for every floor, and total-height/storey-height rules must emit status=unknown, never pass (CLAUDE.md §10.1: elevations are cross-check only, never a height source).
- assemble_case: [elevation_front] estimate_storey_count_from_elevation(elevation_front.pdf): 5 candidate long horizontal strokes clustered -> heuristic estimate of 4 storeys. This counts any long thin stroke (could include a plinth line, a coping line, a hatch boundary), not verified structural slab lines -- treat as a cross-check hint only, never as the source of Floor.height_m or an authoritative storey count.
- assemble_case: [elevation_rear] estimate_storey_count_from_elevation(elevation_rear.pdf): 5 candidate long horizontal strokes clustered -> heuristic estimate of 4 storeys. This counts any long thin stroke (could include a plinth line, a coping line, a hatch boundary), not verified structural slab lines -- treat as a cross-check hint only, never as the source of Floor.height_m or an authoritative storey count.
- assemble_case: [elevation_side] estimate_storey_count_from_elevation(elevation_side.pdf): 7 candidate long horizontal strokes clustered -> heuristic estimate of 6 storeys. This counts any long thin stroke (could include a plinth line, a coping line, a hatch boundary), not verified structural slab lines -- treat as a cross-check hint only, never as the source of Floor.height_m or an authoritative storey count.
- assemble_case: STOREY COUNT MISMATCH (extraction ambiguity candidate) -- 3 plan sheet(s) assembled into floors, but the heuristic elevation line-count estimate suggests 4 storey(s). Both numbers are approximate (the plan count can be short a level with no usable footprint; the elevation count is a rough vector-line heuristic, not a verified read) -- do not silently prefer one over the other.
- assemble_case: no 'site'/'zoning' role sheet supplied -- plot_polygon, plot_area_sqm, zoned_area and edges all left unset. Containment, coverage, FAR and setback checks must emit status=unknown, never pass. Per-floor footprints above are each in their OWN sheet-local metre frame (no shared plot datum exists to align them to) -- do not assume floor N and floor N+1 footprints share an origin with the plot, only with each other's sheet, and only approximately at that.
- assemble_case: jurisdiction.authority taken from meta.json ('UNKNOWN') rather than inferred by this parser -- title-block text alone ('Mohali') is not sufficient to distinguish GMADA from MC_KHARAR/MC_ZIRAKPUR (jurisdiction routing is rules-engine territory per CLAUDE.md, not parser territory); plot_no/sector below ARE taken from the drawing's own title block when parseable.

---

**This is a pre-submission check only.** It is not an approval, not a sanction, and not a certificate of compliance by GMADA, PUDA, or any authority.

Numeric rule values are seeded from source clauses and carry their own verification status per finding (see each issue's citation above). Values not marked `verified` have not been independently diffed against the gazette and must be confirmed before submission.

1 sq m = 1.196 sq yd. All internal computation is in metres/square metres.
