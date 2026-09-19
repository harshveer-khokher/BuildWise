"""Brute-force grid-search repair solver. CLAUDE.md §9.

Explicitly NOT a CSP. For each violation we enumerate small, parameterized edits (shrink a
wall in 0.1 m steps, trim a projection, reclassify a room, shift the stair, reduce the
basement footprint), apply each to a *copy* of the BuildingModel, and re-run the ENTIRE rule
pack against the edited copy -- not just the rule that was originally violated. Fixing a
setback routinely breaks FAR or a room minimum, so a candidate is only kept if nothing that
previously passed regresses into a violation (CLAUDE.md §9 point 3-4). Candidates are ranked
by area lost; the caller decides how many to surface.

Dependency on the rules engine (Track B)
-----------------------------------------
Track B's ``packages/rules/engine.py`` is being built concurrently and its exact call
signature was not settled at the time this module was written. To avoid a hard, possibly
broken import at module load time, this module takes the rule check as an injected
``evaluate_fn: Callable[[BuildingModel], list[Finding]]`` -- it never imports
``packages.rules.engine`` at module scope. ``default_evaluate_fn()`` below *lazily* attempts
that import only when explicitly asked for a default, and raises a clear error if the engine
isn't importable yet or doesn't expose the expected entry point. Tests in
``tests/test_solver.py`` build a small fixture ``evaluate_fn`` (mirroring the geometry a real
engine would check: zoned-area containment and a simple FAR cap) so solver logic can be
verified in isolation of Track B's timeline.

Geometry scope / known limitation
----------------------------------
All edit operations below assume axis-aligned, simple-rectangle-ish footprints and
axis-aligned plot edges -- true of every stub in packages/cases/stubs and a reasonable
starting point for a hackathon build. Real DXF footprints with non-rectangular geometry will
need a buffer/offset-based generalisation of ``shrink_wall``; that gap is logged in
INTEGRATION.md for Track A. All polygon math goes through shapely (CLAUDE.md §1 rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

from shapely.geometry import Polygon
from shapely.affinity import translate as shapely_translate

from packages.schema.building_model import BuildingModel, Floor, Room
from packages.schema.findings import Finding, Remedy

EvaluateFn = Callable[[BuildingModel], list[Finding]]

# ---------------------------------------------------------------------------
# Grid-search parameters (CLAUDE.md §9: "shrink a wall in 0.1 m steps")
# ---------------------------------------------------------------------------
STEP_M = 0.1
MAX_DELTA_M = 3.0
MAX_CANDIDATES_PER_VIOLATION = 2000


def default_evaluate_fn() -> EvaluateFn:
    """Lazily resolve Track B's rule engine. Only called if a caller explicitly wants the
    real engine and doesn't want to wire evaluate_fn themselves. Raises ImportError with a
    clear message if packages.rules.engine isn't ready yet -- callers should catch this and
    fall back to their own evaluate_fn (e.g. a test fixture) rather than let solver silently
    run against nothing.
    """
    try:
        from packages.rules import engine as _engine  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only once engine.py lands
        raise ImportError(
            "packages.rules.engine is not importable yet (Track B in progress). "
            "Pass an explicit evaluate_fn to search_repairs()/solve() instead."
        ) from exc

    for name in ("evaluate", "run", "check", "evaluate_model"):
        fn = getattr(_engine, name, None)
        if callable(fn):
            return fn  # type: ignore[return-value]
    raise ImportError(
        "packages.rules.engine was importable but exposes none of the expected entry points "
        "(evaluate/run/check/evaluate_model). Update default_evaluate_fn() once Track B's "
        "call signature is settled, or pass evaluate_fn explicitly."
    )


# ---------------------------------------------------------------------------
# Small geometry helpers -- all via shapely
# ---------------------------------------------------------------------------

def _ring_area_sqm(ring: list[list[float]]) -> float:
    return abs(Polygon(ring).area)


def _plot_centroid(model: BuildingModel) -> tuple[float, float]:
    pt = Polygon(model.plot_polygon).centroid
    return (pt.x, pt.y)


def _rect_ring(minx: float, miny: float, maxx: float, maxy: float) -> list[list[float]]:
    return [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]


def _clip_room_to_bounds(room: Room, bounds: tuple[float, float, float, float]) -> Room:
    """Best-effort: intersect a room polygon with the new footprint bounds so a shrink never
    leaves a room hanging outside the building envelope. If the intersection is degenerate,
    the room polygon is left untouched (edit-application still proceeds; downstream rule
    checks -- e.g. room-in-footprint containment -- would then flag it, which is correct
    behaviour rather than silently repairing rooms the geometric edit didn't ask about).
    """
    minx, miny, maxx, maxy = bounds
    envelope = Polygon(_rect_ring(minx, miny, maxx, maxy))
    room_poly = Polygon(room.polygon)
    clipped = room_poly.intersection(envelope)
    if clipped.is_empty or clipped.area <= 0:
        return room
    if clipped.geom_type != "Polygon":
        return room
    new_ring = [list(c) for c in clipped.exterior.coords]
    return room.model_copy(update={"polygon": new_ring})


def _edge_axis(edge_line: list[list[float]]) -> str:
    (x0, y0), (x1, y1) = edge_line[0], edge_line[-1]
    return "y" if abs(y1 - y0) >= abs(x1 - x0) else "x"
    # "y"-axis edge means the edge runs mostly horizontal (constant-ish y) -> it bounds the
    # footprint's y-extent (front/rear). "x" means it bounds the x-extent (side_a/side_b).


# ---------------------------------------------------------------------------
# Edit operations (CLAUDE.md §9 point 1)
# ---------------------------------------------------------------------------

def shrink_wall(model: BuildingModel, floor_level: int, edge_role: str, delta_m: float) -> BuildingModel:
    """Move the wall of `floor_level`'s footprint facing plot edge `edge_role` inward by
    delta_m. Axis-aligned rectangle footprints only (see module docstring)."""
    new_model = model.model_copy(deep=True)
    floor = next(f for f in new_model.floors if f.level == floor_level)
    edge = next(e for e in new_model.edges if e.role == edge_role)
    poly = Polygon(floor.footprint)
    minx, miny, maxx, maxy = poly.bounds
    axis = _edge_axis(edge.line)
    cx, cy = _plot_centroid(model)

    if axis == "y":
        edge_y = (edge.line[0][1] + edge.line[-1][1]) / 2
        if edge_y >= cy:
            maxy -= delta_m
        else:
            miny += delta_m
    else:
        edge_x = (edge.line[0][0] + edge.line[-1][0]) / 2
        if edge_x >= cx:
            maxx -= delta_m
        else:
            minx += delta_m

    if minx >= maxx or miny >= maxy:
        raise ValueError("shrink_wall: delta_m too large, footprint would collapse")

    new_ring = _rect_ring(minx, miny, maxx, maxy)
    floor.footprint = new_ring
    floor.rooms = [_clip_room_to_bounds(r, (minx, miny, maxx, maxy)) for r in floor.rooms]
    return new_model


def shrink_wall_all_floors(model: BuildingModel, edge_role: str, delta_m: float, levels: list[int] | None = None) -> BuildingModel:
    """Apply shrink_wall to every (or a specified subset of) floor levels sharing the same
    plan -- used for FAR/coverage fixes, where trimming a single floor's wall doesn't move
    the total covered area enough (CLAUDE.md §9 point 3: fixes must survive a full re-run)."""
    new_model = model
    target_levels = levels if levels is not None else [f.level for f in model.floors]
    for level in target_levels:
        new_model = shrink_wall(new_model, level, edge_role, delta_m)
    return new_model


def trim_projection(model: BuildingModel, projection_index: int, delta_m: float) -> BuildingModel:
    """Shrink a projection (chajja/balcony) polygon inward by delta_m via a negative buffer.
    If the projection is buffered out of existence, it is dropped entirely."""
    new_model = model.model_copy(deep=True)
    proj = dict(new_model.projections[projection_index])
    poly = Polygon(proj["polygon"])
    shrunk = poly.buffer(-delta_m, join_style=2)
    if shrunk.is_empty or shrunk.area <= 0:
        new_model.projections = [p for i, p in enumerate(new_model.projections) if i != projection_index]
        return new_model
    if shrunk.geom_type != "Polygon":
        shrunk = max(shrunk.geoms, key=lambda g: g.area)
    proj["polygon"] = [list(c) for c in shrunk.exterior.coords]
    new_model.projections = [
        proj if i == projection_index else p for i, p in enumerate(new_model.projections)
    ]
    return new_model


def reclassify_room(model: BuildingModel, floor_level: int, room_index: int, new_use: str) -> BuildingModel:
    """Relabel a room's use (e.g. 'other' -> 'store'). No area lost -- useful when a
    violation is driven by a use-dependent rule (light/ventilation ratio, minimum area) that a
    corrected label resolves, rather than by real geometry."""
    new_model = model.model_copy(deep=True)
    floor = next(f for f in new_model.floors if f.level == floor_level)
    room = floor.rooms[room_index]
    floor.rooms[room_index] = room.model_copy(update={"use": new_use})
    return new_model


def shift_stair(model: BuildingModel, floor_level: int, room_index: int, dx_m: float, dy_m: float) -> BuildingModel:
    """Translate a stair room polygon within its floor. Rejected by the caller (via the
    regression check) if the shift moves the stair outside the footprint -- this function
    only rejects moves that are geometrically nonsensical (stair ends up outside the plot
    entirely)."""
    new_model = model.model_copy(deep=True)
    floor = next(f for f in new_model.floors if f.level == floor_level)
    room = floor.rooms[room_index]
    poly = Polygon(room.polygon)
    moved = shapely_translate(poly, xoff=dx_m, yoff=dy_m)
    plot = Polygon(model.plot_polygon)
    if not plot.contains(moved):
        raise ValueError("shift_stair: shifted stair falls outside the plot")
    floor.rooms[room_index] = room.model_copy(update={"polygon": [list(c) for c in moved.exterior.coords]})
    return new_model


def reduce_basement_footprint(model: BuildingModel, delta_m: float) -> BuildingModel:
    """Uniformly shrink the basement (level == -1) footprint by delta_m via negative buffer."""
    new_model = model.model_copy(deep=True)
    floor = next((f for f in new_model.floors if f.level == -1), None)
    if floor is None:
        raise ValueError("reduce_basement_footprint: model has no basement (level == -1) floor")
    poly = Polygon(floor.footprint)
    shrunk = poly.buffer(-delta_m, join_style=2)
    if shrunk.is_empty or shrunk.area <= 0:
        raise ValueError("reduce_basement_footprint: delta_m too large, basement would vanish")
    if shrunk.geom_type != "Polygon":
        shrunk = max(shrunk.geoms, key=lambda g: g.area)
    new_ring = [list(c) for c in shrunk.exterior.coords]
    floor.footprint = new_ring
    minx, miny, maxx, maxy = shrunk.bounds
    floor.rooms = [_clip_room_to_bounds(r, (minx, miny, maxx, maxy)) for r in floor.rooms]
    return new_model


# ---------------------------------------------------------------------------
# Violation -> candidate-edit dispatch
# ---------------------------------------------------------------------------
# Track B's rule_id naming convention wasn't finalized when this was written, so dispatch is
# done on best-effort keyword matching over rule_id/title. This is logged as an integration
# ask: a stable rule_id prefix convention (e.g. "*.setback.*", "*.far.*") would make this
# exact instead of heuristic. See INTEGRATION.md.

def _violation_edges(finding: Finding, model: BuildingModel) -> list[str]:
    """Which plot edge role(s) a setback-shaped violation concerns. Falls back to all edges
    if we can't tell, so the grid search just tries each."""
    text = f"{finding.rule_id} {finding.title}".lower()
    roles = [e.role for e in model.edges]
    hit = [r for r in roles if r != "unknown" and r in text]
    return hit or [r for r in roles if r != "unknown"]


def enumerate_edits(
    model: BuildingModel,
    violation: Finding,
    step_m: float = STEP_M,
    max_delta_m: float = MAX_DELTA_M,
) -> Iterator[tuple[dict, BuildingModel]]:
    """Yield (edit_ref, edited_model) candidates for a single violation, cheapest edits
    first. edit_ref is a small machine-checkable dict describing the op (matches
    Remedy.edit_ref in packages/schema/findings.py)."""
    text = f"{violation.rule_id} {violation.title}".lower()
    deltas = [round(step_m * n, 2) for n in range(1, int(max_delta_m / step_m) + 1)]

    is_setback_or_containment = any(k in text for k in ("setback", "zon", "containment", "envelope"))
    is_far_or_coverage = any(k in text for k in ("far", "floor area ratio", "coverage"))
    is_projection = any(k in text for k in ("projection", "chajja", "balcony"))
    is_basement = "basement" in text
    is_room_or_light = any(k in text for k in ("room", "light", "ventilation", "dimension"))

    if is_setback_or_containment:
        for edge_role in _violation_edges(violation, model):
            for floor in model.floors:
                for delta in deltas:
                    try:
                        edited = shrink_wall(model, floor.level, edge_role, delta)
                    except (ValueError, StopIteration):
                        break
                    yield (
                        {"op": "shrink_wall", "floor": floor.level, "edge": edge_role, "delta_m": delta},
                        edited,
                    )

    if is_far_or_coverage:
        for edge_role in [e.role for e in model.edges if e.role != "unknown"]:
            for delta in deltas:
                try:
                    edited = shrink_wall_all_floors(model, edge_role, delta)
                except (ValueError, StopIteration):
                    break
                yield (
                    {"op": "shrink_wall_all_floors", "edge": edge_role, "delta_m": delta},
                    edited,
                )

    if is_projection:
        for idx in range(len(model.projections)):
            for delta in deltas:
                try:
                    edited = trim_projection(model, idx, delta)
                except (ValueError, IndexError):
                    break
                yield ({"op": "trim_projection", "projection_index": idx, "delta_m": delta}, edited)

    if is_basement:
        for delta in deltas:
            try:
                edited = reduce_basement_footprint(model, delta)
            except ValueError:
                break
            yield ({"op": "reduce_basement_footprint", "delta_m": delta}, edited)

    if is_room_or_light:
        for floor in model.floors:
            for ridx, room in enumerate(floor.rooms):
                for new_use in ("bedroom", "living", "store", "other"):
                    if new_use == room.use:
                        continue
                    edited = reclassify_room(model, floor.level, ridx, new_use)
                    yield (
                        {"op": "reclassify_room", "floor": floor.level, "room_index": ridx, "new_use": new_use},
                        edited,
                    )
                if room.use == "stair":
                    for dx in (-0.3, -0.1, 0.1, 0.3):
                        for dy in (-0.3, -0.1, 0.1, 0.3):
                            try:
                                edited = shift_stair(model, floor.level, ridx, dx, dy)
                            except ValueError:
                                continue
                            yield (
                                {"op": "shift_stair", "floor": floor.level, "room_index": ridx, "dx_m": dx, "dy_m": dy},
                                edited,
                            )


# ---------------------------------------------------------------------------
# Search + ranking
# ---------------------------------------------------------------------------

@dataclass
class RepairCandidate:
    edit_ref: dict
    description: str
    model: BuildingModel
    target_rule_id: str
    cleared_rule_ids: set[str]
    area_lost_sqm: float
    verified: bool = True  # by construction: only candidates that survive the full re-run are kept

    def to_remedy(self) -> Remedy:
        return Remedy(
            kind="geometric_edit",
            description=self.description,
            area_lost_sqm=round(self.area_lost_sqm, 3),
            edit_ref=self.edit_ref,
            verified=self.verified,
        )


def _total_footprint_area(model: BuildingModel) -> float:
    return sum(_ring_area_sqm(f.footprint) for f in model.floors)


def _describe_edit(edit_ref: dict, area_lost_sqm: float) -> str:
    op = edit_ref["op"]
    if op == "shrink_wall":
        return (
            f"Pull the {edit_ref['edge']} wall on floor {edit_ref['floor']} inward by "
            f"{edit_ref['delta_m']:.1f} m. Loses {area_lost_sqm:.2f} sqm of floor area on "
            f"that floor; verified against the full rule pack with nothing else regressing."
        )
    if op == "shrink_wall_all_floors":
        return (
            f"Pull the {edit_ref['edge']} wall inward by {edit_ref['delta_m']:.1f} m on every "
            f"floor. Loses {area_lost_sqm:.2f} sqm of total covered area; verified against the "
            f"full rule pack with nothing else regressing."
        )
    if op == "trim_projection":
        return (
            f"Trim projection #{edit_ref['projection_index']} by {edit_ref['delta_m']:.1f} m. "
            f"Loses {area_lost_sqm:.2f} sqm of projection area; verified against the full rule "
            f"pack with nothing else regressing."
        )
    if op == "reduce_basement_footprint":
        return (
            f"Reduce the basement footprint uniformly by {edit_ref['delta_m']:.1f} m. Loses "
            f"{area_lost_sqm:.2f} sqm of basement area; verified against the full rule pack "
            f"with nothing else regressing."
        )
    if op == "reclassify_room":
        return (
            f"Relabel room #{edit_ref['room_index']} on floor {edit_ref['floor']} from its "
            f"current use to '{edit_ref['new_use']}'. No floor area lost; verified against the "
            f"full rule pack with nothing else regressing."
        )
    if op == "shift_stair":
        return (
            f"Shift the stair on floor {edit_ref['floor']} by ({edit_ref['dx_m']:.1f} m, "
            f"{edit_ref['dy_m']:.1f} m). No floor area lost; verified against the full rule "
            f"pack with nothing else regressing."
        )
    return f"Apply edit {edit_ref}. Loses {area_lost_sqm:.2f} sqm; verified against the full rule pack."


def search_repairs(
    model: BuildingModel,
    violations: list[Finding],
    evaluate_fn: EvaluateFn,
    step_m: float = STEP_M,
    max_delta_m: float = MAX_DELTA_M,
    max_candidates_per_violation: int = MAX_CANDIDATES_PER_VIOLATION,
) -> dict[str, list[RepairCandidate]]:
    """For each violation, grid-search edits and keep only candidates that (a) clear the
    targeted violation and (b) introduce no new violation anywhere in the full re-run
    (CLAUDE.md §9 points 2-4). Returns {rule_id: [candidates sorted by area lost, cheapest
    first]}.
    """
    baseline_findings = evaluate_fn(model)
    baseline_violation_ids = {f.rule_id for f in baseline_findings if f.status == "violation"}

    results: dict[str, list[RepairCandidate]] = {}
    for violation in violations:
        candidates: list[RepairCandidate] = []
        seen = 0
        for edit_ref, edited_model in enumerate_edits(model, violation, step_m, max_delta_m):
            seen += 1
            if seen > max_candidates_per_violation:
                break
            new_findings = evaluate_fn(edited_model)
            new_violation_ids = {f.rule_id for f in new_findings if f.status == "violation"}

            if violation.rule_id in new_violation_ids:
                continue  # didn't clear the targeted violation
            regressed = new_violation_ids - baseline_violation_ids
            if regressed:
                continue  # something that wasn't violated before now is -- reject (§9 pt 4)

            cleared = baseline_violation_ids - new_violation_ids
            area_lost = abs(_total_footprint_area(model) - _total_footprint_area(edited_model))
            candidates.append(
                RepairCandidate(
                    edit_ref=edit_ref,
                    description=_describe_edit(edit_ref, area_lost),
                    model=edited_model,
                    target_rule_id=violation.rule_id,
                    cleared_rule_ids=cleared,
                    area_lost_sqm=area_lost,
                )
            )
        candidates.sort(key=lambda c: c.area_lost_sqm)
        results[violation.rule_id] = candidates
    return results


def solve(
    model: BuildingModel,
    findings: list[Finding],
    evaluate_fn: EvaluateFn | None = None,
    top_n: int = 3,
) -> dict[str, list[Remedy]]:
    """Convenience entry point: geometric repairs (this module) + non-geometric remedies
    (remedies.py), merged per violated rule_id, geometric candidates first (cheapest area
    loss), non-geometric after. Lazily imports remedies.py to avoid any import-order
    surprises.
    """
    from . import remedies as _remedies

    if evaluate_fn is None:
        evaluate_fn = default_evaluate_fn()

    violations = [f for f in findings if f.status == "violation"]
    repair_results = search_repairs(model, violations, evaluate_fn)

    out: dict[str, list[Remedy]] = {}
    for violation in violations:
        geometric = [c.to_remedy() for c in repair_results.get(violation.rule_id, [])[:top_n]]
        non_geometric = _remedies.non_geometric_remedies_for_finding(violation, model)
        out[violation.rule_id] = geometric + non_geometric
    return out
