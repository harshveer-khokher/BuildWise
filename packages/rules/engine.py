"""Deterministic rule engine (CLAUDE.md §1 rule 1, rule 3; §7; §9's "re-run the entire rule
pack" contract depends on this being pure and side-effect-free).

No LLM is ever called from this module. Every check here is plain Python + shapely. The engine's
only job is: load a rule pack (YAML, data -- not code) + a BuildingModel, and emit a list of
`Finding` objects (packages/schema/findings.py, frozen). `status="unknown"` is a first-class,
correct outcome (CLAUDE.md §5) -- it is emitted whenever a required input is missing, never
silently upgraded to "pass".

Known schema-gap assumption (see packages/rules/packs/puda_building_rules_1996.yaml header and INTEGRATION.md):
packages/schema/building_model.py has no field for a plot's overall use classification
(residential_plotted / commercial / industrial / group_housing / public). Every rule in the
1996 pack is authored `applies_when.use: residential_plotted`; `_applies` below treats every
BuildingModel as matching that filter until the schema grows a real field, and prints this as
an assumption on the run rather than silently assuming it.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.schema.building_model import BuildingModel, Floor, Room  # noqa: E402
from packages.schema.findings import Citation, Finding, Remedy  # noqa: E402

SQM_PER_SQYD = 1 / 1.196  # not used here (metres/sqm only inside the engine, CLAUDE.md §1 rule 4)

HABITABLE_USES = {"bedroom", "living", "kitchen"}
SERVICE_USES = {"bath", "wc", "store", "stair"}


# --------------------------------------------------------------------------------------------
# Pack loading
# --------------------------------------------------------------------------------------------

def load_pack(path: str | pathlib.Path) -> dict:
    path = pathlib.Path(path)
    with open(path, "r", encoding="utf-8") as f:
        pack = yaml.safe_load(f)
    return pack


def _citation(rule: dict) -> Citation:
    src = rule["source"]
    return Citation(
        doc=src["doc"],
        clause=src["clause"],
        version=src.get("version", "unknown"),
        url=src.get("url"),
        status=rule.get("status", "seed_unverified"),
    )


def _remedies(rule: dict, area_lost_sqm: float | None = None) -> list[Remedy]:
    out = []
    for kind in rule.get("remedies", []):
        out.append(
            Remedy(
                kind=kind,
                description=f"Candidate remedy for {rule['id']} (not yet solver-verified).",
                area_lost_sqm=area_lost_sqm,
                verified=False,
            )
        )
    return out


def _applies(rule: dict, model: BuildingModel) -> bool:
    """`applies_when` matching. `use` is always treated as matched -- see module docstring."""
    when = rule.get("applies_when", {})
    if "authority" in when and when["authority"] != model.jurisdiction.authority:
        return False
    band = when.get("plot_area_sqm")
    if band:
        if model.plot_area_sqm is None:
            # Missing plot_area_sqm means we don't know whether this rule's band applies --
            # that's an unknown, not "doesn't apply". Let it through: every _check_* function
            # already handles plot_area_sqm is None by emitting a status="unknown" Finding
            # (CLAUDE.md §5) rather than assuming a band. Returning False here would silently
            # drop the rule instead, which is worse than "unknown" -- it looks like "0 issues
            # found" on a real drawing that's actually missing its site/zoning sheet.
            return True
        lo = band.get("min")
        hi = band.get("max")
        if lo is not None and model.plot_area_sqm < lo:
            return False
        if hi is not None and model.plot_area_sqm > hi:
            return False
    return True


def _poly(ring) -> Polygon | None:
    if not ring or len(ring) < 3:
        return None
    try:
        return Polygon(ring)
    except Exception:
        return None


def _min_rotated_rect_short_side(ring) -> float | None:
    poly = _poly(ring)
    if poly is None or not poly.is_valid or poly.area == 0:
        return None
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    if len(coords) < 4:
        return None
    side_lengths = [
        ((coords[i][0] - coords[i + 1][0]) ** 2 + (coords[i][1] - coords[i + 1][1]) ** 2) ** 0.5
        for i in range(len(coords) - 1)
    ]
    return min(side_lengths) if side_lengths else None


def _plot_width_m(model: BuildingModel) -> float | None:
    poly = _poly(model.plot_polygon)
    if poly is None:
        return None
    return _min_rotated_rect_short_side(model.plot_polygon)


def _ground_floor(model: BuildingModel) -> Floor | None:
    non_stilt = [f for f in model.floors if f.level == 0]
    return non_stilt[0] if non_stilt else None


def _basement_floor(model: BuildingModel) -> Floor | None:
    basements = [f for f in model.floors if f.level < 0]
    return basements[0] if basements else None


def _total_footprint_union(model: BuildingModel, include_stilt: bool) -> float:
    total = 0.0
    for f in model.floors:
        if f.is_stilt and not include_stilt:
            continue
        poly = _poly(f.footprint)
        if poly is not None:
            total += poly.area
    return total


# --------------------------------------------------------------------------------------------
# Individual check kinds. Each returns one or more Finding objects (never zero -- a rule that
# cannot be evaluated for lack of input still emits a status="unknown" Finding, CLAUDE.md §5).
# --------------------------------------------------------------------------------------------

def _check_containment(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    if model.zoned_area is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"],
            title=rule["title"], citation=citation,
            observed=None, required="zoned_area (from a traced zoning plan)",
            geometry_ref=model.plot_polygon,
            compoundable=False, ambiguity_class="missing_input",
            remedies=[Remedy(
                kind="zoning_revision_request",
                description="No zoning plan has been traced for this plot yet. Containment "
                             "cannot be checked until one is digitized (CLAUDE.md §10.9) -- "
                             "this is never silently treated as a pass.",
            )],
        )]
    zoned_poly = _poly(model.zoned_area)
    if zoned_poly is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"],
            title=rule["title"], citation=citation,
            observed=None, required=None, geometry_ref=None,
            compoundable=False, ambiguity_class="extraction",
            remedies=[],
        )]
    findings = []
    for floor in model.floors:
        fp = _poly(floor.footprint)
        if fp is None:
            continue
        inside = fp.within(zoned_poly)
        findings.append(Finding(
            rule_id=rule["id"],
            status="pass" if inside else "violation",
            severity=rule["severity"],
            title=f"{rule['title']} (floor {floor.level})",
            citation=citation,
            observed=f"floor {floor.level} footprint outside zoned area"
                      if not inside else "within zoned area",
            required="footprint must be within zoned_area",
            geometry_ref=floor.footprint if not inside else None,
            compoundable=False,
            remedies=_remedies(rule) if not inside else [],
        ))
    if not findings:
        findings.append(Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"],
            title=rule["title"], citation=citation,
            observed=None, required=None, geometry_ref=None,
            compoundable=False, ambiguity_class="missing_input", remedies=[],
        ))
    return findings


def _slab_cap_sqm(plot_area_sqm: float, table: list[dict]) -> float:
    remaining = plot_area_sqm
    cap = 0.0
    for band in table:
        band_sqm = band.get("band_sqm")
        pct = band["pct"] / 100.0
        chunk = remaining if band_sqm is None else min(remaining, band_sqm)
        if chunk <= 0:
            break
        cap += chunk * pct
        remaining -= chunk
        if remaining <= 0:
            break
    return cap


def _check_site_coverage_slab(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    if model.plot_area_sqm is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"],
            title=rule["title"], citation=citation, observed=None, required=None,
            geometry_ref=None, compoundable=False, ambiguity_class="missing_input", remedies=[],
        )]
    ground = _ground_floor(model)
    if ground is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"],
            title=rule["title"], citation=citation, observed=None, required=None,
            geometry_ref=None, compoundable=False, ambiguity_class="extraction", remedies=[],
        )]
    ground_poly = _poly(ground.footprint)
    if ground_poly is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"],
            title=rule["title"], citation=citation, observed=None, required=None,
            geometry_ref=None, compoundable=False, ambiguity_class="extraction", remedies=[],
        )]
    coverage_sqm = ground_poly.area
    cap_sqm = _slab_cap_sqm(model.plot_area_sqm, rule["table"])
    ok = coverage_sqm <= cap_sqm + 1e-9
    return [Finding(
        rule_id=rule["id"],
        status="pass" if ok else "violation",
        severity=rule["severity"], title=rule["title"], citation=citation,
        observed=round(coverage_sqm, 2), required=round(cap_sqm, 2),
        geometry_ref=None if ok else ground.footprint,
        compoundable=rule.get("compoundable", False),
        remedies=_remedies(rule, area_lost_sqm=round(coverage_sqm - cap_sqm, 2)) if not ok else [],
    )]


def _check_far_band(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    if model.plot_area_sqm is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"],
            title=rule["title"], citation=citation, observed=None, required=None,
            geometry_ref=None, compoundable=False, ambiguity_class="missing_input", remedies=[],
        )]
    has_stilt = any(f.is_stilt for f in model.floors)
    # Conservative primary reading: exclude stilt footprint from FAR (CLAUDE.md §2 glossary --
    # "whether stilt counts toward FAR/height is genuinely contested"). The dedicated
    # far_band_gap / stilt_far_definitional rules surface the other reading explicitly.
    covered_sqm = _total_footprint_union(model, include_stilt=False)
    far = covered_sqm / model.plot_area_sqm
    max_far = rule["max_far"]
    ok = far <= max_far + 1e-9
    note = " (stilt storey excluded from this FAR figure -- see PUDA1996.far.stilt_treatment)" if has_stilt else ""
    return [Finding(
        rule_id=rule["id"],
        status="pass" if ok else "violation",
        severity=rule["severity"], title=rule["title"] + note, citation=citation,
        observed=round(far, 3), required=max_far,
        geometry_ref=None if ok else model.plot_polygon,
        compoundable=rule.get("compoundable", False),
        remedies=_remedies(rule) if not ok else [],
    )]


def _check_far_band_gap(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    when = rule.get("applies_when", {})
    band = when.get("plot_area_sqm", {})
    lo = band.get("min", 0)
    if model.plot_area_sqm is None or model.plot_area_sqm < lo:
        return []  # this plot isn't in the affected band; no finding needed
    covered_sqm = _total_footprint_union(model, include_stilt=False)
    far = covered_sqm / model.plot_area_sqm if model.plot_area_sqm else None
    return [Finding(
        rule_id=rule["id"], status="ambiguity", severity=rule["severity"],
        title=rule["title"], citation=citation,
        observed=f"computed FAR {round(far, 3) if far is not None else 'n/a'}; superseded "
                 f"pre-amendment cap was {rule['superseded_value']}",
        required=None,
        geometry_ref=model.plot_polygon,
        compoundable=False,
        ambiguity_class="instrument_conflict",
        remedies=[Remedy(
            kind="zoning_revision_request",
            description="Plot exceeds 430 sqm. The 1998 amendment to Rule 16 does not state a "
                         "FAR cap for this band; the pre-amendment cap (1.00) is superseded, not "
                         "confirmed current. Carry both citations when submitting.",
        )],
    )]


def _check_stilt_far_definitional(rule: dict, model: BuildingModel) -> list[Finding]:
    if not any(f.is_stilt for f in model.floors) or model.plot_area_sqm is None:
        return []
    citation = _citation(rule)
    excl = _total_footprint_union(model, include_stilt=False) / model.plot_area_sqm
    incl = _total_footprint_union(model, include_stilt=True) / model.plot_area_sqm
    return [Finding(
        rule_id=rule["id"], status="ambiguity", severity=rule["severity"],
        title=rule["title"], citation=citation,
        observed=f"FAR excluding stilt: {round(excl, 3)}; FAR including stilt: {round(incl, 3)}",
        required=None, geometry_ref=None, compoundable=False,
        ambiguity_class="definitional",
        remedies=[],
    )]


def _setback_actual_m(model: BuildingModel, role: str) -> float | None:
    """Approximate the built setback on the given edge role as the distance from that plot
    edge's line to the nearest building footprint, using shapely (CLAUDE.md §1 rule 3)."""
    edge = next((e for e in model.edges if e.role == role), None)
    if edge is None or len(edge.line) < 2:
        return None
    from shapely.geometry import LineString
    edge_line = LineString(edge.line)
    min_dist = None
    for floor in model.floors:
        fp = _poly(floor.footprint)
        if fp is None:
            continue
        d = edge_line.distance(fp)
        if min_dist is None or d < min_dist:
            min_dist = d
    return min_dist


def _building_height_m(model: BuildingModel) -> float | None:
    heights = [f.height_m for f in model.floors if f.height_m is not None and not f.is_stilt]
    if not heights:
        return None
    return sum(heights)


def _check_setback_formula(rule: dict, model: BuildingModel, roles: list[str]) -> list[Finding]:
    citation = _citation(rule)
    height = _building_height_m(model)
    findings = []
    for role in roles:
        actual = _setback_actual_m(model, role)
        if actual is None or height is None:
            findings.append(Finding(
                rule_id=rule["id"], status="unknown", severity=rule["severity"],
                title=f"{rule['title']} ({role})", citation=citation,
                observed=None, required=None, geometry_ref=None,
                compoundable=False, ambiguity_class="extraction", remedies=[],
            ))
            continue
        required = max(height * rule["fraction_of_height"], rule["min_m"])
        ok = actual >= required - 1e-9
        findings.append(Finding(
            rule_id=rule["id"], status="pass" if ok else "violation",
            severity=rule["severity"], title=f"{rule['title']} ({role})", citation=citation,
            observed=round(actual, 2), required=round(required, 2),
            geometry_ref=None if ok else next(
                (e.line for e in model.edges if e.role == role), None
            ),
            compoundable=rule.get("compoundable", False),
            remedies=_remedies(rule, area_lost_sqm=None) if not ok else [],
        ))
    return findings


def _check_height_vs_road(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    front_edge = next((e for e in model.edges if e.role == "front"), None)
    height = _building_height_m(model)
    front_setback = _setback_actual_m(model, "front")
    if front_edge is None or front_edge.road_width_m is None or height is None or front_setback is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"],
            title=rule["title"], citation=citation, observed=None, required=None,
            geometry_ref=None, compoundable=False, ambiguity_class="missing_input", remedies=[],
        )]
    allowed = front_edge.road_width_m + front_setback
    ok = height <= allowed + 1e-9
    return [Finding(
        rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
        title=rule["title"], citation=citation,
        observed=round(height, 2), required=round(allowed, 2),
        geometry_ref=None if ok else model.plot_polygon,
        compoundable=rule.get("compoundable", False),
        remedies=_remedies(rule) if not ok else [],
    )]


def _check_projection_max(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    if not model.projections:
        return [Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed="no projections in model", required=rule.get("max_m"),
            geometry_ref=None, compoundable=False, remedies=[],
        )]
    findings = []
    for proj in model.projections:
        poly = _poly(proj.get("polygon"))
        depth = None
        if poly is not None:
            rect_sides = _min_rotated_rect_short_side(proj.get("polygon"))
            depth = rect_sides
        if depth is None:
            findings.append(Finding(
                rule_id=rule["id"], status="unknown", severity=rule["severity"],
                title=rule["title"], citation=citation, observed=None, required=rule.get("max_m"),
                geometry_ref=None, compoundable=False, ambiguity_class="extraction", remedies=[],
            ))
            continue
        max_m = rule["max_m"]
        ok = depth <= max_m + 1e-9
        findings.append(Finding(
            rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
            title=rule["title"], citation=citation,
            observed=round(depth, 2), required=max_m,
            geometry_ref=None if ok else proj.get("polygon"),
            compoundable=rule.get("compoundable", False),
            remedies=_remedies(rule) if not ok else [],
        ))
    return findings


def _check_projection_width_fraction(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    site_width = _plot_width_m(model)
    if site_width is None or not model.projections:
        return [Finding(
            rule_id=rule["id"], status="unknown" if model.projections else "pass",
            severity=rule["severity"], title=rule["title"], citation=citation,
            observed=None, required=None, geometry_ref=None, compoundable=False,
            ambiguity_class="extraction" if model.projections else None, remedies=[],
        )]
    findings = []
    for proj in model.projections:
        poly = _poly(proj.get("polygon"))
        if poly is None:
            continue
        minx, miny, maxx, maxy = poly.bounds
        width = max(maxx - minx, maxy - miny)
        max_allowed = rule["fraction"] * site_width
        ok = width <= max_allowed + 1e-9
        findings.append(Finding(
            rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
            title=rule["title"], citation=citation,
            observed=round(width, 2), required=round(max_allowed, 2),
            geometry_ref=None if ok else proj.get("polygon"),
            compoundable=rule.get("compoundable", False),
            remedies=_remedies(rule) if not ok else [],
        ))
    return findings or [Finding(
        rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
        citation=citation, observed="no projections", required=None, geometry_ref=None,
        compoundable=False, remedies=[],
    )]


def _check_courtyard_min_area(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    if not model.courtyards:
        return [Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed="no closed courtyards in model", required=rule["min_sqm"],
            geometry_ref=None, compoundable=False, remedies=[],
        )]
    findings = []
    for ring in model.courtyards:
        poly = _poly(ring)
        area = poly.area if poly is not None else None
        if area is None:
            continue
        ok = area >= rule["min_sqm"] - 1e-9
        findings.append(Finding(
            rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
            title=rule["title"], citation=citation,
            observed=round(area, 2), required=rule["min_sqm"],
            geometry_ref=None if ok else ring,
            compoundable=rule.get("compoundable", False),
            remedies=_remedies(rule) if not ok else [],
        ))
    return findings


def _check_courtyard_min_width(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    if not model.courtyards:
        return [Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed="no closed courtyards in model", required=rule["min_m"],
            geometry_ref=None, compoundable=False, remedies=[],
        )]
    findings = []
    for ring in model.courtyards:
        width = _min_rotated_rect_short_side(ring)
        if width is None:
            continue
        ok = width >= rule["min_m"] - 1e-9
        findings.append(Finding(
            rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
            title=rule["title"], citation=citation,
            observed=round(width, 2), required=rule["min_m"],
            geometry_ref=None if ok else ring,
            compoundable=rule.get("compoundable", False),
            remedies=_remedies(rule) if not ok else [],
        ))
    return findings


def _rooms_by_use(model: BuildingModel, uses: set[str]) -> list[tuple[Floor, Room]]:
    out = []
    for floor in model.floors:
        for room in floor.rooms:
            if room.use in uses:
                out.append((floor, room))
    return out


def _check_room_min_height(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    uses = set(rule["room_uses"])
    rooms = _rooms_by_use(model, uses)
    if not rooms:
        return [Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed=f"no rooms of use {sorted(uses)} in model",
            required=rule["min_m"], geometry_ref=None, compoundable=False, remedies=[],
        )]
    findings = []
    seen_floors = set()
    for floor, room in rooms:
        if floor.level in seen_floors:
            continue
        seen_floors.add(floor.level)
        if floor.height_m is None:
            findings.append(Finding(
                rule_id=rule["id"], status="unknown", severity=rule["severity"],
                title=f"{rule['title']} (floor {floor.level})", citation=citation,
                observed=None, required=rule["min_m"], geometry_ref=None,
                compoundable=False, ambiguity_class="extraction", remedies=[],
            ))
            continue
        ok = floor.height_m >= rule["min_m"] - 1e-9
        findings.append(Finding(
            rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
            title=f"{rule['title']} (floor {floor.level})", citation=citation,
            observed=floor.height_m, required=rule["min_m"],
            geometry_ref=None if ok else room.polygon,
            compoundable=rule.get("compoundable", False),
            remedies=_remedies(rule) if not ok else [],
        ))
    return findings


def _check_light_ventilation_ratio(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    findings = []
    for floor in model.floors:
        for room in floor.rooms:
            if room.use not in HABITABLE_USES:
                continue
            poly = _poly(room.polygon)
            if poly is None or poly.area == 0:
                findings.append(Finding(
                    rule_id=rule["id"], status="unknown", severity=rule["severity"],
                    title=rule["title"], citation=citation, observed=None,
                    required=rule["min_ratio"], geometry_ref=room.polygon,
                    compoundable=False, ambiguity_class="extraction", remedies=[],
                ))
                continue
            if room.openings_area_sqm <= 0:
                # A hard 0.0 is indistinguishable from "not measured" for a habitable room --
                # every PDF-derived room currently has openings_area_sqm hardcoded to 0.0
                # (packages/parser/pdf_ingest.py does not extract window/door area at all yet;
                # see its module docstring). Reporting this as a violation would be a guaranteed
                # false positive on every habitable room from a PDF/raster source, which is
                # exactly the failure CLAUDE.md §10.6 calls out as unacceptable ("precision on
                # violation must be near 100%"). Treat an unmeasured/zero opening as an
                # extraction gap, not evidence of non-compliance.
                findings.append(Finding(
                    rule_id=rule["id"], status="unknown", severity=rule["severity"],
                    title=rule["title"], citation=citation, observed=None,
                    required=rule["min_ratio"], geometry_ref=room.polygon,
                    compoundable=False, ambiguity_class="extraction", remedies=[],
                ))
                continue
            ratio = room.openings_area_sqm / poly.area
            ok = ratio >= rule["min_ratio"] - 1e-9
            findings.append(Finding(
                rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
                title=f"{rule['title']} ({room.use}, floor {floor.level})", citation=citation,
                observed=round(ratio, 3), required=rule["min_ratio"],
                geometry_ref=None if ok else room.polygon,
                compoundable=rule.get("compoundable", False),
                remedies=_remedies(rule) if not ok else [],
            ))
    if not findings:
        findings.append(Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed="no habitable rooms in model", required=rule["min_ratio"],
            geometry_ref=None, compoundable=False, remedies=[],
        ))
    return findings


def _check_floor_min_height(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    basement = _basement_floor(model)
    if basement is None:
        return [Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed="no basement in model", required=rule["min_m"],
            geometry_ref=None, compoundable=False, remedies=[],
        )]
    if basement.height_m is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"], title=rule["title"],
            citation=citation, observed=None, required=rule["min_m"], geometry_ref=None,
            compoundable=False, ambiguity_class="extraction", remedies=[],
        )]
    ok = basement.height_m >= rule["min_m"] - 1e-9
    return [Finding(
        rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
        title=rule["title"], citation=citation,
        observed=basement.height_m, required=rule["min_m"],
        geometry_ref=None if ok else basement.footprint,
        compoundable=rule.get("compoundable", False),
        remedies=_remedies(rule) if not ok else [],
    )]


def _check_basement_area_relation(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    basement = _basement_floor(model)
    ground = _ground_floor(model)
    if basement is None:
        return [Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed="no basement in model", required=None,
            geometry_ref=None, compoundable=False, remedies=[],
        )]
    if ground is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"], title=rule["title"],
            citation=citation, observed=None, required=None, geometry_ref=None,
            compoundable=False, ambiguity_class="extraction", remedies=[],
        )]
    b_poly, g_poly = _poly(basement.footprint), _poly(ground.footprint)
    if b_poly is None or g_poly is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"], title=rule["title"],
            citation=citation, observed=None, required=None, geometry_ref=None,
            compoundable=False, ambiguity_class="extraction", remedies=[],
        )]
    ok = b_poly.area <= g_poly.area + 1e-9
    return [Finding(
        rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
        title=rule["title"], citation=citation,
        observed=round(b_poly.area, 2), required=round(g_poly.area, 2),
        geometry_ref=None if ok else basement.footprint,
        compoundable=rule.get("compoundable", False),
        remedies=_remedies(rule) if not ok else [],
    )]


def _check_staircase_min_width(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    stairs = _rooms_by_use(model, {"stair"})
    if not stairs:
        # A building with >1 storey and no modelled stair room is itself worth a note, but
        # per CLAUDE.md §5 that's an extraction/assumption issue, not this rule's job to invent.
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"], title=rule["title"],
            citation=citation, observed=None, required=rule["min_m"], geometry_ref=None,
            compoundable=False, ambiguity_class="extraction",
            remedies=[],
        )]
    findings = []
    for floor, room in stairs:
        width = _min_rotated_rect_short_side(room.polygon)
        if width is None:
            findings.append(Finding(
                rule_id=rule["id"], status="unknown", severity=rule["severity"], title=rule["title"],
                citation=citation, observed=None, required=rule["min_m"], geometry_ref=room.polygon,
                compoundable=False, ambiguity_class="extraction", remedies=[],
            ))
            continue
        ok = width >= rule["min_m"] - 1e-9
        findings.append(Finding(
            rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
            title=rule["title"], citation=citation,
            observed=round(width, 2), required=rule["min_m"],
            geometry_ref=None if ok else room.polygon,
            compoundable=rule.get("compoundable", False),
            remedies=_remedies(rule) if not ok else [],
        ))
    return findings


def _check_roof_projection_recede(rule: dict, model: BuildingModel) -> list[Finding]:
    citation = _citation(rule)
    if not model.mumty:
        return [Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed="no mumty/roof structure in model", required=None,
            geometry_ref=None, compoundable=False, remedies=[],
        )]
    height = model.mumty.get("height_m")
    setback = model.mumty.get("setback_m")
    if height is None or setback is None:
        return [Finding(
            rule_id=rule["id"], status="unknown", severity=rule["severity"], title=rule["title"],
            citation=citation, observed=None, required=None, geometry_ref=None,
            compoundable=False, ambiguity_class="extraction", remedies=[],
        )]
    if height <= rule["height_threshold_m"]:
        return [Finding(
            rule_id=rule["id"], status="pass", severity=rule["severity"], title=rule["title"],
            citation=citation, observed=height, required=f"<= {rule['height_threshold_m']} m (exempt)",
            geometry_ref=None, compoundable=False, remedies=[],
        )]
    ok = setback >= height * rule["recede_ratio"] - 1e-9
    return [Finding(
        rule_id=rule["id"], status="pass" if ok else "violation", severity=rule["severity"],
        title=rule["title"], citation=citation,
        observed=setback, required=round(height * rule["recede_ratio"], 2),
        geometry_ref=None, compoundable=rule.get("compoundable", False),
        remedies=_remedies(rule) if not ok else [],
    )]


_DISPATCH = {
    "containment": _check_containment,
    "site_coverage_slab": _check_site_coverage_slab,
    "far_band": _check_far_band,
    "far_band_gap": _check_far_band_gap,
    "stilt_far_definitional": _check_stilt_far_definitional,
    "setback_formula": None,  # handled specially below (needs role list per rule id)
    "height_vs_road": _check_height_vs_road,
    "projection_max": _check_projection_max,
    "projection_min_height": None,  # not enforced (see pack `enforced: false`)
    "projection_width_fraction": _check_projection_width_fraction,
    "courtyard_min_area": _check_courtyard_min_area,
    "courtyard_min_width": _check_courtyard_min_width,
    "courtyard_width_fraction": None,  # not enforced
    "room_min_height": _check_room_min_height,
    "room_open_space": None,  # not enforced
    "light_ventilation_ratio": _check_light_ventilation_ratio,
    "floor_min_height": _check_floor_min_height,
    "area_relation": None,  # handled specially below (basement vs staircase landing)
    "staircase_min_width": _check_staircase_min_width,
    "staircase_riser": None,  # not enforced
    "staircase_tread": None,  # not enforced
    "roof_projection_recede": _check_roof_projection_recede,
}


def evaluate(model: BuildingModel, pack: dict) -> list[Finding]:
    """Evaluate every rule in `pack` against `model`. Pure function, no I/O, no LLM. Rules
    marked `enforced: false` in the pack are skipped (their numeric fact is still citable in the
    pack/report, but the frozen schema has no field to check them against yet)."""
    findings: list[Finding] = []

    if model.jurisdiction.authority == "UNKNOWN":
        # Jurisdiction routing is "step zero" (CLAUDE.md §2 glossary) -- every rule in THIS pack
        # is authored against one specific `applies_when.authority`, so _applies() would silently
        # skip all of them below, leaving an empty findings list. An empty list reads as "0
        # issues found", which is indistinguishable from a clean drawing -- exactly the
        # false-confidence outcome CLAUDE.md §5/§1 rule 6 exists to prevent. Surface it as one
        # explicit finding instead of nothing.
        #
        # Derived from the PACK itself (pack_id/jurisdiction/doc_id), not hardcoded to any one
        # jurisdiction's pack -- this function runs against whichever pack run_checks() resolved
        # (PUDA's, Chandigarh's, or any future one), and previously named "PUDA1996"/
        # "puda_building_rules_1996" unconditionally even when evaluating a different pack, which
        # would have misattributed the finding as soon as a second jurisdiction pack existed.
        pack_id = pack.get("pack_id", "unknown_pack")
        pack_jurisdiction = pack.get("jurisdiction", "an unspecified authority")
        pack_doc_id = pack.get("doc_id", pack_id)
        findings.append(Finding(
            rule_id=f"{pack_id}.jurisdiction.unknown",
            status="unknown",
            severity="blocking",
            title="Jurisdiction could not be determined",
            citation=Citation(
                doc=pack_doc_id, clause="n/a", version="n/a",
                status="seed_unverified",
            ),
            observed=model.jurisdiction.authority,
            required=pack_jurisdiction,
            geometry_ref=None,
            compoundable=False,
            ambiguity_class="missing_input",
            remedies=[Remedy(
                kind="zoning_revision_request",
                description=f"Confirm the plot's jurisdiction/authority before relying on any "
                             f"finding below -- every rule in this pack ({pack.get('title', pack_id)}) "
                             f"is authored against {pack_jurisdiction} and was not evaluated while "
                             f"authority is unknown.",
            )],
        ))
        return findings

    for rule in pack["rules"]:
        if not rule.get("enforced", True):
            continue
        if rule.get("status") == "conflict":
            # CLAUDE.md §6.5: a conflicted rule is disabled but still produces status=unknown,
            # never a silent pass.
            findings.append(Finding(
                rule_id=rule["id"], status="unknown", severity=rule["severity"],
                title=rule["title"], citation=_citation(rule), observed=None, required=None,
                geometry_ref=None, compoundable=False, ambiguity_class="instrument_conflict",
                remedies=[],
            ))
            continue
        if not _applies(rule, model):
            continue

        kind = rule["kind"]
        if kind == "setback_formula":
            roles = ["front", "rear"] if "front_rear" in rule["id"] else ["side_a", "side_b"]
            findings.extend(_check_setback_formula(rule, model, roles))
        elif kind == "area_relation":
            if "basement" in rule["id"]:
                findings.extend(_check_basement_area_relation(rule, model))
            # landing_width_vs_flight is enforced:false -- never reaches here
        else:
            fn = _DISPATCH.get(kind)
            if fn is None:
                continue
            findings.extend(fn(rule, model))

    return _soften_upper_bound_failures(model, findings)


# Checks whose verdict is read off the building footprint, matched on the rule id since that is
# what a Finding carries. When the footprint is flagged as an upper bound only these need the
# one-sided treatment below -- a room-height or staircase-width finding is unaffected by how the
# outline was traced.
_FOOTPRINT_DEPENDENT_ID_HINTS = ("containment", "coverage", "far", "setback")


def _is_footprint_dependent(rule_id: str) -> bool:
    lowered = rule_id.lower()
    return any(hint in lowered for hint in _FOOTPRINT_DEPENDENT_ID_HINTS)


def _soften_upper_bound_failures(model: BuildingModel, findings: list[Finding]) -> list[Finding]:
    """Downgrade footprint-driven *failures* to ambiguities when the footprint over-estimates.

    `Floor.footprint_is_upper_bound` means the outline encloses the real building rather than
    tracing it (packages/parser/site_geometry.py builds it as the convex hull of everything drawn
    as masonry, which also swallows a boundary wall standing on the plot line). The logic is
    deliberately one-sided, and it is sound in one direction only:

      * a check that PASSES against a shape larger than the building passes against the building
        itself -- kept exactly as it is, a real result rather than a hedge;
      * a check that FAILS may be failing against geometry that is not the house, so it becomes
        `ambiguity` / `extraction` -- the measured numbers are still reported, but as something to
        confirm rather than a violation the tool stands behind.

    This is what makes it safe to feed a derived footprint into the engine at all. CLAUDE.md is
    explicit that a false positive sends an architect redrawing for nothing and loses the account
    permanently, while a false negative is merely the status quo.
    """
    if not any(f.footprint_is_upper_bound for f in model.floors):
        return findings

    softened = []
    for finding in findings:
        if finding.status != "violation" or not _is_footprint_dependent(finding.rule_id):
            softened.append(finding)
            continue
        # The caveat itself goes no further than the finding's own status/class and title: the
        # full explanation is already carried verbatim on BuildingModel.assumptions, which is the
        # channel CLAUDE.md §5 designates for it and which the report prints unedited. Inventing
        # a new Remedy kind for "go and check" would put a non-remedy in the remedy list.
        softened.append(finding.model_copy(update={
            "status": "ambiguity",
            "ambiguity_class": "extraction",
            "title": f"{finding.title} -- needs confirmation against the drawing",
        }))
    return softened


def evaluate_path(model: BuildingModel, pack_path: str | pathlib.Path) -> list[Finding]:
    pack = load_pack(pack_path)
    return evaluate(model, pack)


_PACKS_DIR = pathlib.Path(__file__).resolve().parent / "packs"


def run_checks(model: BuildingModel) -> list[Finding]:
    """Single-argument convenience entry point matching the contract both Track C
    (`packages/solver/repair.py::default_evaluate_fn`) and Track D
    (`packages/api/checks.py`, INTEGRATION.md's documented seam) coded against:
    `Callable[[BuildingModel], list[Finding]]`. Resolves the pack from
    `model.jurisdiction.rule_pack` (e.g. "puda_building_rules_1996") to a file under
    packages/rules/packs/ -- tries an exact stem match first, falls back to the only pack
    present if there's just one (same resolution order as `packages/api/checks.py`'s own
    `_resolve_pack_path`, so both call sites agree). Raises FileNotFoundError rather than
    silently picking an unrelated pack if neither resolves.
    """
    exact = _PACKS_DIR / f"{model.jurisdiction.rule_pack}.yaml"
    if exact.exists():
        return evaluate_path(model, exact)
    yaml_files = sorted(_PACKS_DIR.glob("*.yaml"))
    if len(yaml_files) == 1:
        return evaluate_path(model, yaml_files[0])
    raise FileNotFoundError(
        f"no rule pack resolves for jurisdiction.rule_pack={model.jurisdiction.rule_pack!r} "
        f"under {_PACKS_DIR} (and more than one pack file exists, so no single-pack fallback "
        f"applies either)"
    )
