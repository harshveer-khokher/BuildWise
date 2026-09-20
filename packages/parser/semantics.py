"""Multi-sheet assembly (CLAUDE.md §10.1): one case's meta.json + its sheet files -> one
packages.schema.BuildingModel.

"Assembly is a required parser step, not an extra" -- a case is a *building*, not a file. This
module is the only place in Track A that imports packages.schema; dxf_ingest.py/pdf_ingest.py
stay schema-agnostic so they can be tested standalone.

Assembly assertions from §10.1, and what this module does when they fail (there is no
interactive user in this pipeline, so "ask for confirmation" becomes "record a structured note
in BuildingModel.assumptions and degrade to unknown/skip, never guess"):

  - every plan sheet maps to a distinct Floor.level          -> enforced, raises on collision
  - storey count from the section matches plan sheet count   -> no section sheet exists yet for
    h01/h02 (INTEGRATION.md); falls back to a heuristic elevation-based cross-check and notes
    the result either way, per the task's instruction to "surface it cleanly" rather than solve
    the general case
  - a section sheet is the preferred source for Floor.height_m -> section parsing isn't
    implemented (no section sheet has been supplied to develop it against yet). Height falls
    back to `pdf_ingest.extract_overall_height_m()`: an elevation sheet's own printed
    chain-dimension bracket (a labeled overall-height dimension, not a heuristic line count).
    This is a deliberate, confirmed exception to "elevations are cross-check only" -- verified
    against a real drawing against the actual as-built height (see INTEGRATION.md) -- and it
    stays narrowly scoped to that one extraction function; `estimate_storey_count_from_elevation`
    (arbitrary long-stroke counting) remains cross-check-only exactly as before, and multiple
    elevation sheets disagreeing on height is still surfaced as an ambiguity, never averaged or
    silently picked.
  - plan footprints share a common origin/datum with the site sheet -> no site sheet exists for
    h01/h02 either; each floor's footprint is left in ITS OWN sheet-local metre frame (see
    pdf_ingest module docstring), plot_polygon/zoned_area/edges are left None/[], and this is
    recorded in assumptions rather than guessed at by aligning bounding boxes (CLAUDE.md is
    explicit that bounding-box alignment is the wrong move here).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from packages.parser import dxf_ingest, pdf_ingest, sheet_ref, site_geometry
from packages.schema import BuildingModel, Edge, Floor, Jurisdiction, Room

# Known plan-sheet role names -> Floor.level. Extend as new offices' naming turns up.
_PLAN_LEVELS: dict[str, tuple[int, bool]] = {
    "basement": (-1, False),
    "stilt": (0, True),
    "ground": (0, False),
    "first": (1, False),
    "second": (2, False),
    "third": (3, False),
    "fourth": (4, False),
}
_ELEVATION_ROLE_RE = re.compile(r"^elevation")
_SITE_ROLES = {"site", "zoning"}
_SECTION_ROLE = "section"

_ELEVATION_TITLE_KEYWORDS = ("elevation",)

# Track A default when a case's own meta.json doesn't specify one. Per INTEGRATION.md's Stage-0
# handoff, the only supplied base-rules doc is the 1996 pack, NOT "puda_2021" as CLAUDE.md's
# glossary names it -- Track B renamed the pack id accordingly, so Track A matches that id here.
_DEFAULT_RULE_PACK = "puda_building_rules_1996"

# Elevation faces of one building routinely differ by a step in the parapet. Within this
# fraction of the tallest reading the difference is treated as real architecture and the
# tallest governs; beyond it the readings are treated as an extraction failure and no height
# is assigned at all.
_HEIGHT_SPREAD_LIMIT = 0.10


def _room_use_from_raw(raw_use: str) -> str:
    allowed = {
        "bedroom", "living", "kitchen", "bath", "wc", "store", "stair", "garage", "other"
    }
    return raw_use if raw_use in allowed else "other"


def _ingest_sheet(sheet_path: Path, layout: str | None = None) -> dict[str, Any]:
    """Dispatch to pdf_ingest or dxf_ingest by file extension and normalise the result shape to
    what the plan-assembly code below expects: {"footprint", "rooms", "title_block", "notes"}.

    `layout` selects a specific named paperspace layout inside a DXF (see
    dxf_ingest.list_layout_names) instead of its default modelspace -- used when one uploaded
    DWG/DXF file holds several sheets as separate layout tabs. Ignored for PDF, which has no
    equivalent concept.
    """
    suffix = sheet_path.suffix.lower()
    if suffix == ".pdf":
        raw = pdf_ingest.ingest_plan_sheet(sheet_path)
        return {
            "footprint": raw["footprint"],
            "rooms": raw["rooms"],
            "title_block": raw["title_block"],
            "notes": [f"[{sheet_path.name}] {n}" for n in raw["notes"]],
        }
    if suffix == ".dxf":
        raw = dxf_ingest.ingest_dxf(sheet_path, layout=layout)
        sheet_label = f"{sheet_path.name}#layout={layout}" if layout else sheet_path.name
        wall_polys = dxf_ingest.closed_polylines_by_category(raw, "wall")
        notes = [f"[{sheet_label}] dxf_ingest: found {len(wall_polys)} closed 'wall'-category polyline(s)."]
        footprint = None
        if wall_polys:
            # Largest-by-shoelace-area closed wall polyline stands in for the exterior footprint
            # -- deliberately simple (CLAUDE.md §1 rule 3 still applies: use shapely, not
            # hand-rolled area math, even for this heuristic pick).
            from shapely.geometry import Polygon

            footprint = max(wall_polys, key=lambda pts: Polygon(pts).area)
        else:
            notes.append(
                f"[{sheet_label}] dxf_ingest: no closed polyline on a 'wall' layer; "
                "footprint left unset for this sheet."
            )
        rooms = []
        room_categories = {
            "room_bedroom": "bedroom",
            "room_bath": "wc",
            "room_kitchen": "kitchen",
            "room_living": "living",
            "room_stair": "stair",
            "room_garage": "garage",
            "room_store": "store",
        }
        for category, use in room_categories.items():
            for poly in dxf_ingest.closed_polylines_by_category(raw, category):
                rooms.append(
                    {
                        "polygon": poly,
                        "use": use,
                        "openings_area_sqm": 0.0,
                        "confidence": "medium",
                        "label": category,
                        "size_source": "dxf_polyline",
                    }
                )
        return {
            "footprint": footprint,
            "rooms": rooms,
            "title_block": {},
            "notes": notes,
        }
    raise ValueError(f"semantics._ingest_sheet: unsupported sheet file type {sheet_path}")


def _classify_role(role: str) -> str:
    if role in _PLAN_LEVELS or role == "combined":
        return "plan"
    if _ELEVATION_ROLE_RE.match(role):
        return "elevation"
    if role in _SITE_ROLES:
        return "site"
    if role == _SECTION_ROLE:
        return "section"
    return "unknown"


def assemble_case(meta_path: str | Path) -> BuildingModel:
    """Assemble one case into a BuildingModel (see assemble_case_with_site for the site block)."""
    return assemble_case_with_site(meta_path)[0]


def assemble_case_with_site(
    meta_path: str | Path,
) -> tuple[BuildingModel, "site_geometry.SiteGeometry | None"]:
    """Assemble one case's meta.json + sheet files into a single BuildingModel.

    Never raises on a missing site/section sheet -- that is an expected, first-class outcome
    (CLAUDE.md §5: "None -> unknown, never PASS") and is recorded in `assumptions`. Raises only
    on things that indicate the *parser itself* is broken (e.g. two plan sheets mapping to the
    same Floor.level, per the §10.1 assembly assertion), since silently swallowing that would
    produce a wrong model, not an honestly-incomplete one.
    """
    meta_path = Path(meta_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    case_dir = meta_path.parent

    assumptions: list[str] = list(meta.get("known_gaps", []))
    sheets: dict[str, str] = meta["sheets"]

    floors: list[Floor] = []
    seen_levels: dict[int, str] = {}
    plan_title_blocks: list[dict[str, Any]] = []
    any_dxf = False
    any_pdf = False

    for role, ref in sheets.items():
        kind = _classify_role(role)
        if kind != "plan":
            continue
        if role == "combined":
            # A single uploaded file with no distinguishable sheet-role structure (no matching
            # layout tabs, no filename hint) -- see role_inference.guess_layout_roles / main.py's
            # single-file fallback. level=0 is an unverified placeholder, not a read result;
            # said explicitly below rather than silently presenting it as a confirmed ground
            # floor.
            level, is_stilt = 0, False
        elif role not in _PLAN_LEVELS:
            assumptions.append(f"assemble_case: plan role '{role}' not in the known level table; skipped.")
            continue
        else:
            level, is_stilt = _PLAN_LEVELS[role]

        if level in seen_levels:
            raise ValueError(
                f"assemble_case({meta_path}): both role '{seen_levels[level]}' and '{role}' map "
                f"to Floor.level={level} -- assembly assertion violated (CLAUDE.md §10.1: every "
                "plan sheet must map to a distinct level)."
            )

        filename, layout = sheet_ref.decode(ref)
        sheet_path = case_dir / filename
        ingested = _ingest_sheet(sheet_path, layout=layout)
        any_dxf = any_dxf or sheet_path.suffix.lower() == ".dxf"
        any_pdf = any_pdf or sheet_path.suffix.lower() == ".pdf"
        assumptions.extend(ingested["notes"])
        if ingested["title_block"]:
            plan_title_blocks.append(ingested["title_block"])

        if role == "combined":
            assumptions.append(
                "assemble_case: role 'combined' -- this file could not be split into distinct "
                "sheet roles (no layout tab or filename matched a known sheet type), so its "
                "geometry was used as a single best-effort floor (level=0) instead of rejecting "
                "the upload. This level assignment is NOT verified -- confirm it before trusting "
                "any per-floor result (coverage/FAR use the whole footprint either way, but "
                "storey-specific checks assume this really is the ground floor)."
            )

        if ingested["footprint"] is None:
            assumptions.append(
                f"assemble_case: role '{role}' ({filename}) produced no usable footprint; "
                f"Floor.level={level} omitted from the model rather than guessed."
            )
            continue

        rooms = [
            Room(
                polygon=r["polygon"],
                use=_room_use_from_raw(r["use"]),
                floor=level,
                openings_area_sqm=r.get("openings_area_sqm", 0.0),
                confidence=r.get("confidence", "low"),
            )
            for r in ingested["rooms"]
        ]

        floors.append(
            Floor(
                level=level,
                is_stilt=is_stilt,
                footprint=ingested["footprint"],
                height_m=None,  # may be overwritten below from a section or a verified elevation dimension.
                rooms=rooms,
            )
        )
        seen_levels[level] = role

    floors.sort(key=lambda f: f.level)

    # --- section sheet: the preferred source of Floor.height_m -----------------------------
    section_roles = [r for r in sheets if _classify_role(r) == "section"]
    if not section_roles:
        assumptions.append(
            "assemble_case: no 'section' role sheet supplied -- height will be attempted from "
            "an elevation sheet's own labeled overall-height dimension instead (see below). This "
            "is a deliberate, confirmed exception to 'elevations are cross-check only' (CLAUDE.md "
            "§10.1's original rule): it applies ONLY to a sheet's own printed chain-dimension "
            "bracket (extract_overall_height_m), never to the heuristic line-count estimate, "
            "which remains cross-check-only exactly as before. See INTEGRATION.md for why."
        )
    else:
        # Section parsing (extracting Floor.height_m, basement depth, stilt clearance from a
        # real section sheet) is not implemented in this build -- no section sheet has been
        # supplied for any case yet to develop it against. Flag loudly rather than silently
        # leaving heights None with no explanation, so this isn't mistaken for "no section".
        assumptions.append(
            f"assemble_case: section sheet(s) present ({section_roles}) but section-sheet "
            "height extraction is not yet implemented in this parser build; falling back to "
            "elevation-derived height below, same as when no section sheet exists at all."
        )

    # --- elevation cross-check: role sanity + storey-count hint + overall-height extraction -
    elevation_roles = [r for r in sheets if _classify_role(r) == "elevation"]
    valid_elevation_estimates: list[int] = []
    valid_heights_m: list[tuple[str, float, list]] = []  # (role, height_m, matched_segments)
    for role in elevation_roles:
        filename, layout = sheet_ref.decode(sheets[role])
        sheet_path = case_dir / filename
        suffix = sheet_path.suffix.lower()

        if suffix == ".pdf":
            raw = pdf_ingest.ingest_plan_sheet(sheet_path)  # title_block only; footprint/rooms unused
            title = raw["title_block"].get("sheet_title")
            role_ok = pdf_ingest.sheet_title_matches_role(title, _ELEVATION_TITLE_KEYWORDS)
            if not role_ok:
                # The formal title didn't confirm it, but a sheet can carry a separate view
                # caption printed directly on the drawing (e.g. formally titled "WOODEN JOINERY
                # DETAIL" with "FRONT ELEVATION" printed under the drawing it actually shows) --
                # role_inference.guess_role() already accepts this signal when first assigning
                # the role (packages/api/role_inference.py), so re-verifying against the title
                # alone here would silently undo that and discard a correctly-classified sheet.
                role_ok = pdf_ingest.page_text_matches_role(sheet_path, _ELEVATION_TITLE_KEYWORDS)
            if not role_ok:
                assumptions.append(
                    f"assemble_case: sheet role '{role}' ({filename}) is declared an elevation "
                    f"in meta.json, but its title-block text reads {title!r}, and no other "
                    "caption on the page confirms it either (extraction ambiguity: possible "
                    "sheet-role mismatch, CLAUDE.md §10.1 -- treat this sheet as unverified, do "
                    "not use it for the storey cross-check or height extraction below)."
                )
                continue
            count, note = pdf_ingest.estimate_storey_count_from_elevation(sheet_path)
            assumptions.append(f"assemble_case: [{role}] {note}")
            if count is not None:
                valid_elevation_estimates.append(count)

            height_m, segments, height_note = pdf_ingest.extract_overall_height_m(sheet_path)
            assumptions.append(f"assemble_case: [{role}] {height_note}")
            if height_m is not None:
                valid_heights_m.append((role, height_m, segments))

        elif suffix == ".dxf":
            # No title-block text to re-verify the declared role against for a bare filename
            # match, but when this sheet came from a named layout tab (layout is not None) that
            # tab name itself already IS the content-derived signal (role_inference.
            # guess_layout_roles) -- the declared role is trusted directly either way, same as
            # before. No storey-count heuristic exists for DXF yet (PDF's is itself just a rough
            # vector-line-density estimate; not built for DXF, not claimed to be equivalent).
            height_m, segments, height_note = dxf_ingest.extract_overall_height_m(sheet_path, layout=layout)
            assumptions.append(f"assemble_case: [{role}] {height_note}")
            if height_m is not None:
                valid_heights_m.append((role, height_m, segments))
        else:
            assumptions.append(
                f"assemble_case: sheet role '{role}' ({filename}) has an unrecognised "
                f"extension {suffix!r} -- skipped for storey-count/height cross-check."
            )

    plan_storey_count = len(floors)
    if valid_elevation_estimates:
        # Take the elevation sheets' own modal/first estimate; any disagreement between plan
        # count and the (heuristic) elevation estimate is exactly the extraction ambiguity
        # CLAUDE.md §10.1 calls for -- surfaced here as a structured note for the (future)
        # ambiguity engine (Track C) to pick up, not resolved by this parser.
        elevation_estimate = valid_elevation_estimates[0]
        if elevation_estimate != plan_storey_count:
            assumptions.append(
                "assemble_case: STOREY COUNT MISMATCH (extraction ambiguity candidate) -- "
                f"{plan_storey_count} plan sheet(s) assembled into floors, but the heuristic "
                f"elevation line-count estimate suggests {elevation_estimate} storey(s). Both "
                "numbers are approximate (the plan count can be short a level with no usable "
                "footprint; the elevation count is a rough vector-line heuristic, not a "
                "verified read) -- do not silently prefer one over the other."
            )
        else:
            assumptions.append(
                f"assemble_case: storey-count cross-check OK -- {plan_storey_count} plan "
                f"sheet(s) and the heuristic elevation estimate both agree on {plan_storey_count}."
            )
    else:
        assumptions.append(
            "assemble_case: storey-count cross-check inconclusive -- no elevation sheet both "
            "confirmed its role via title-block text AND produced a usable heuristic estimate."
        )

    # --- assign height from an elevation's own labeled overall-height dimension, if any -----
    if valid_heights_m:
        distinct_values = {round(h, 3) for _, h, _ in valid_heights_m}
        spread = max(distinct_values) - min(distinct_values)
        if len(distinct_values) > 1 and spread > max(distinct_values) * _HEIGHT_SPREAD_LIMIT:
            assumptions.append(
                "assemble_case: HEIGHT MISMATCH (extraction ambiguity candidate) -- elevation "
                f"sheets disagree on overall height: {[(r, round(h, 3)) for r, h, _ in valid_heights_m]}, "
                f"a spread of {spread:.2f}m. That is too wide to be a stepped parapet, so it "
                "reads as an extraction failure rather than a real difference between faces. "
                "Floor.height_m left None on every floor rather than picking one silently."
            )
        else:
            if len(distinct_values) > 1:
                # A small spread between faces is ordinary architecture (a stepped parapet, a
                # lower side wing), not a failed read. Discarding every height over six inches
                # of real variation left height, storey and height-derived setback rules
                # unresolved on drawings that plainly state their height -- so the TALLEST
                # reading is taken, which is the one that governs: a height limit regulates the
                # building's highest point, and a setback derived from height grows with it.
                # Announced, never silent, and erring towards the stricter requirement.
                valid_heights_m = sorted(valid_heights_m, key=lambda t: -t[1])
                assumptions.append(
                    "assemble_case: elevation sheets differ slightly on overall height "
                    f"({[(r, round(h, 3)) for r, h, _ in valid_heights_m]}, spread {spread:.2f}m) "
                    "-- consistent with a stepped parapet rather than a bad read. The TALLEST "
                    "was used, since that is the point a height limit regulates and the one a "
                    "height-derived setback is computed from; the others are recorded here."
                )
            height_m = valid_heights_m[0][1]
            agreeing_roles = [r for r, _, _ in valid_heights_m]
            segments = valid_heights_m[0][2] or []
            non_stilt_floors = [f for f in floors if not f.is_stilt]
            if non_stilt_floors and segments and len(segments) % len(non_stilt_floors) == 0:
                # Segments are ordered top-to-bottom on the sheet; floors are sorted ascending by
                # level (ground first). Pair the topmost segment group with the TOP floor, not
                # the ground floor -- reversed(non_stilt_floors) puts the highest level first.
                per_floor_n = len(segments) // len(non_stilt_floors)
                for i, floor in enumerate(reversed(non_stilt_floors)):
                    group = segments[i * per_floor_n:(i + 1) * per_floor_n]
                    floor.height_m = sum(s["value_m"] for s in group)
                assumptions.append(
                    f"assemble_case: height {round(height_m, 3)}m confirmed by {len(agreeing_roles)} "
                    f"elevation sheet(s) ({agreeing_roles}) via their own labeled overall-height "
                    "dimension (not a section, not a heuristic line count). The matched segment "
                    f"count divided evenly across the {len(non_stilt_floors)} assembled floor(s); "
                    "each floor's height_m was set to its own share, top floor matched to the "
                    "topmost segment group."
                )
            elif non_stilt_floors:
                non_stilt_floors[-1].height_m = height_m
                assumptions.append(
                    f"assemble_case: height {round(height_m, 3)}m confirmed by {len(agreeing_roles)} "
                    f"elevation sheet(s) ({agreeing_roles}) via their own labeled overall-height "
                    "dimension. Could not split it evenly across floors (the matched segment count "
                    f"doesn't divide the {len(non_stilt_floors)} assembled floor(s)) -- assigned the "
                    f"WHOLE total to the top floor (level={non_stilt_floors[-1].level}) only. Other "
                    "floors' height_m=None means 'not individually broken out', not 'zero height' "
                    "-- _building_height_m() still sums to the correct total either way."
                )
    else:
        assumptions.append(
            "assemble_case: no elevation sheet yielded a usable overall-height dimension -- "
            "Floor.height_m stays None for every floor."
        )

    # --- site/zoning: plot polygon, plot area, zoned area, edges ----------------------------
    # These do NOT need a dedicated site sheet. Real Mohali submissions draw the plot line and
    # the zoning line straight onto the floor-plan sheets, labelled and colour-coded, so the
    # ground-floor plan carries the plot boundary, the buildable envelope and the building all in
    # one coordinate frame -- see packages/parser/site_geometry.py. A site/zoning sheet is still
    # preferred when one exists; the plan sheets are the fallback that makes this work at all on
    # every real case supplied so far, none of which has a site sheet.
    site_geom = None
    ordered_site_candidates = (
        [r for r in sheets if _classify_role(r) == "site"]
        + [r for r in ("combined", "ground") if r in sheets]
        + [r for r in sheets if _classify_role(r) == "plan"]
    )
    for role in dict.fromkeys(ordered_site_candidates):
        filename, _layout = sheet_ref.decode(sheets[role])
        candidate_path = case_dir / filename
        if candidate_path.suffix.lower() != ".pdf":
            continue
        candidate = site_geometry.extract_site_geometry(candidate_path)
        if candidate.usable:
            site_geom = candidate
            assumptions.extend(candidate.notes)
            assumptions.append(
                f"assemble_case: plot and zoning geometry taken from the '{role}' sheet "
                f"({filename}), which carries both boundaries drawn on it."
            )
            break

    if site_geom is not None:
        # Re-anchor every plan sheet's footprint onto the plot line, using the one verified
        # scale. Until now each floor sat in its own sheet-local frame, which made any
        # plot-relative check (containment, setbacks) meaningless even when a plot existed.
        aligned, unaligned = 0, []
        for role, ref in sheets.items():
            if _classify_role(role) != "plan":
                continue
            level = 0 if role == "combined" else _PLAN_LEVELS.get(role, (None, None))[0]
            floor = next((f for f in floors if f.level == level), None)
            if floor is None:
                continue
            filename, _layout = sheet_ref.decode(ref)
            sheet_path = case_dir / filename
            if sheet_path.suffix.lower() != ".pdf":
                continue
            per_sheet = site_geometry.extract_site_geometry(
                sheet_path, scale_hint=site_geom.scale_pts_per_m
            )
            if per_sheet.usable and per_sheet.footprint_hull:
                floor.footprint = per_sheet.footprint_hull
                floor.footprint_is_upper_bound = True
                aligned += 1
            else:
                unaligned.append(role)
        if aligned:
            assumptions.append(
                f"assemble_case: {aligned} floor footprint(s) re-anchored onto the plot line and "
                "replaced with the convex hull of that sheet's own masonry, so plot, zoned area "
                "and building now share one coordinate frame and plot-relative checks are "
                "meaningful. Each is an UPPER BOUND on the real outline (it also encloses any "
                "boundary wall drawn on the plot line), and is flagged as such on the model -- "
                "the rules engine keeps a pass against it and downgrades a failure to an "
                "ambiguity needing confirmation, never reporting a violation off an over-estimate."
            )
        if unaligned:
            assumptions.append(
                f"assemble_case: plan sheet role(s) {unaligned} could not be anchored to the plot "
                "line (no plot boundary recoverable on that sheet); those floors keep their own "
                "sheet-local footprint and must not be compared against the plot."
            )

    if site_geom is None:
        assumptions.append(
            "assemble_case: no sheet yielded a usable plot boundary -- plot_polygon, "
            "plot_area_sqm, zoned_area and edges all left unset. Containment, coverage, FAR and "
            "setback checks must emit status=unknown, never pass. Per-floor footprints above are "
            "each in their OWN sheet-local metre frame (no shared plot datum exists to align "
            "them to) -- do not assume floor N and floor N+1 footprints share an origin with the "
            "plot, only with each other's sheet, and only approximately at that."
        )

    # --- jurisdiction: best-effort from whichever plan sheet's title block parsed ------------
    plot_no = None
    sector = None
    for tb in plan_title_blocks:
        plot_no = plot_no or tb.get("plot_no")
        sector = sector or tb.get("sector")
    authority = meta.get("authority") or "UNKNOWN"
    assumptions.append(
        f"assemble_case: jurisdiction.authority taken from meta.json ('{authority}') rather than "
        "inferred by this parser -- title-block text alone ('Mohali') is not sufficient to "
        "distinguish GMADA from MC_KHARAR/MC_ZIRAKPUR (jurisdiction routing is rules-engine "
        "territory per CLAUDE.md, not parser territory); plot_no/sector below ARE taken from the "
        "drawing's own title block when parseable."
    )
    rule_pack = meta.get("rule_pack") or _DEFAULT_RULE_PACK

    jurisdiction = Jurisdiction(
        authority=authority,
        sector=sector,
        plot_no=plot_no,
        allotment_date=meta.get("allotment_date"),
        rule_pack=rule_pack,
    )

    if any_dxf and not any_pdf:
        source = "dxf"
    else:
        source = meta.get("source_format", "vector_pdf")

    model_edges = []
    if site_geom is not None:
        for e in site_geom.edges:
            model_edges.append(Edge(
                line=e["line"],
                faces_road=e["faces_road"],
                road_width_m=e["road_width_m"],
                role=e["role"],
            ))

    model = BuildingModel(
        source=source,
        jurisdiction=jurisdiction,
        plot_polygon=site_geom.plot_polygon if site_geom else None,
        plot_area_sqm=(site_geom.plot_area_sqm if site_geom else None) or meta.get("plot_area_sqm"),
        zoned_area=site_geom.zoned_area if site_geom else None,
        edges=model_edges,
        floors=floors,
        projections=[],
        courtyards=[],
        mumty=None,
        parking_bays=[],
        boundary_wall_height_m=None,
        has_rwh=False,
        tree_count=0,
        assumptions=assumptions,
    )
    return model, site_geom
