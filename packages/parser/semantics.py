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
  - a section sheet is required for Floor.height_m           -> enforced: height_m is only ever
    set from a `section` role sheet. Elevations are cross-check only (never height source), and
    this module does not implement section parsing yet (no section sheet has been supplied to
    parse) -- height_m stays None until one exists. This is the single most load-bearing rule in
    this file: it would be easy, and wrong, to eyeball a height off an elevation instead.
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

from packages.parser import dxf_ingest, pdf_ingest
from packages.schema import BuildingModel, Floor, Jurisdiction, Room

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


def _room_use_from_raw(raw_use: str) -> str:
    allowed = {
        "bedroom", "living", "kitchen", "bath", "wc", "store", "stair", "garage", "other"
    }
    return raw_use if raw_use in allowed else "other"


def _ingest_sheet(sheet_path: Path) -> dict[str, Any]:
    """Dispatch to pdf_ingest or dxf_ingest by file extension and normalise the result shape to
    what the plan-assembly code below expects: {"footprint", "rooms", "title_block", "notes"}.
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
        raw = dxf_ingest.ingest_dxf(sheet_path)
        wall_polys = dxf_ingest.closed_polylines_by_category(raw, "wall")
        notes = [f"[{sheet_path.name}] dxf_ingest: found {len(wall_polys)} closed 'wall'-category polyline(s)."]
        footprint = None
        if wall_polys:
            # Largest-by-shoelace-area closed wall polyline stands in for the exterior footprint
            # -- deliberately simple (CLAUDE.md §1 rule 3 still applies: use shapely, not
            # hand-rolled area math, even for this heuristic pick).
            from shapely.geometry import Polygon

            footprint = max(wall_polys, key=lambda pts: Polygon(pts).area)
        else:
            notes.append(
                f"[{sheet_path.name}] dxf_ingest: no closed polyline on a 'wall' layer; "
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
    if role in _PLAN_LEVELS:
        return "plan"
    if _ELEVATION_ROLE_RE.match(role):
        return "elevation"
    if role in _SITE_ROLES:
        return "site"
    if role == _SECTION_ROLE:
        return "section"
    return "unknown"


def assemble_case(meta_path: str | Path) -> BuildingModel:
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

    for role, filename in sheets.items():
        kind = _classify_role(role)
        if kind != "plan":
            continue
        if role not in _PLAN_LEVELS:
            assumptions.append(f"assemble_case: plan role '{role}' not in the known level table; skipped.")
            continue

        level, is_stilt = _PLAN_LEVELS[role]
        if level in seen_levels:
            raise ValueError(
                f"assemble_case({meta_path}): both role '{seen_levels[level]}' and '{role}' map "
                f"to Floor.level={level} -- assembly assertion violated (CLAUDE.md §10.1: every "
                "plan sheet must map to a distinct level)."
            )

        sheet_path = case_dir / filename
        ingested = _ingest_sheet(sheet_path)
        any_dxf = any_dxf or sheet_path.suffix.lower() == ".dxf"
        any_pdf = any_pdf or sheet_path.suffix.lower() == ".pdf"
        assumptions.extend(ingested["notes"])
        if ingested["title_block"]:
            plan_title_blocks.append(ingested["title_block"])

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
                height_m=None,  # CLAUDE.md §10.1: only ever set from a `section` sheet.
                rooms=rooms,
            )
        )
        seen_levels[level] = role

    floors.sort(key=lambda f: f.level)

    # --- section sheet: the only legitimate source of Floor.height_m -----------------------
    section_roles = [r for r in sheets if _classify_role(r) == "section"]
    if not section_roles:
        assumptions.append(
            "assemble_case: no 'section' role sheet supplied -- Floor.height_m left None for "
            "every floor, and total-height/storey-height rules must emit status=unknown, never "
            "pass (CLAUDE.md §10.1: elevations are cross-check only, never a height source)."
        )
    else:
        # Section parsing (extracting Floor.height_m, basement depth, stilt clearance from a
        # real section sheet) is not implemented in this build -- no section sheet has been
        # supplied for any case yet to develop it against. Flag loudly rather than silently
        # leaving heights None with no explanation, so this isn't mistaken for "no section".
        assumptions.append(
            f"assemble_case: section sheet(s) present ({section_roles}) but section-sheet "
            "height extraction is not yet implemented in this parser build; Floor.height_m left "
            "None pending that work -- treat as unknown, not as 'confirmed no height'."
        )

    # --- elevation cross-check: role sanity + heuristic storey-count hint -------------------
    elevation_roles = [r for r in sheets if _classify_role(r) == "elevation"]
    valid_elevation_estimates: list[int] = []
    for role in elevation_roles:
        sheet_path = case_dir / sheets[role]
        if sheet_path.suffix.lower() != ".pdf":
            continue
        raw = pdf_ingest.ingest_plan_sheet(sheet_path)  # title_block only; footprint/rooms unused
        title = raw["title_block"].get("sheet_title")
        role_ok = pdf_ingest.sheet_title_matches_role(title, _ELEVATION_TITLE_KEYWORDS)
        if not role_ok:
            assumptions.append(
                f"assemble_case: sheet role '{role}' ({sheets[role]}) is declared an elevation "
                f"in meta.json, but its title-block text reads {title!r}, which does not "
                "confirm that (extraction ambiguity: possible sheet-role mismatch, CLAUDE.md "
                "§10.1 -- treat this sheet as unverified, do not use it for the storey "
                "cross-check below)."
            )
            continue
        count, note = pdf_ingest.estimate_storey_count_from_elevation(sheet_path)
        assumptions.append(f"assemble_case: [{role}] {note}")
        if count is not None:
            valid_elevation_estimates.append(count)

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

    # --- site/zoning: plot polygon, plot area, zoned area, edges ----------------------------
    site_roles = [r for r in sheets if _classify_role(r) == "site"]
    if not site_roles:
        assumptions.append(
            "assemble_case: no 'site'/'zoning' role sheet supplied -- plot_polygon, "
            "plot_area_sqm, zoned_area and edges all left unset. Containment, coverage, FAR and "
            "setback checks must emit status=unknown, never pass. Per-floor footprints above are "
            "each in their OWN sheet-local metre frame (no shared plot datum exists to align "
            "them to) -- do not assume floor N and floor N+1 footprints share an origin with the "
            "plot, only with each other's sheet, and only approximately at that."
        )
    else:
        assumptions.append(
            f"assemble_case: site/zoning sheet role(s) present ({site_roles}) but site-sheet "
            "parsing (plot polygon / zoned area tracing) is not implemented in this parser build "
            "-- no such sheet has been supplied for any case yet to develop it against. "
            "plot_polygon/zoned_area left None pending that work."
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

    return BuildingModel(
        source=source,
        jurisdiction=jurisdiction,
        plot_polygon=None,
        plot_area_sqm=meta.get("plot_area_sqm"),
        zoned_area=None,
        edges=[],
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
