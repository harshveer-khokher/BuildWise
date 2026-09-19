"""Thin adapter between the API and the rules engine (Track B, `packages/rules/engine.py`).

Contract (also written to INTEGRATION.md so Track B can match it without reading this file):

    # packages/rules/engine.py
    def run_checks(model: BuildingModel) -> list[Finding]:
        ...

`run_checks` here tries that real import first and falls back to a small set of hand-written
fixture Findings, so every other layer (API routes, overlay, PDF/HTML report, web UI) can be
built and tested against the real `Finding` schema today, and swapping in the real engine later
is a one-line import change, not a rewrite (per the Track D brief).

The fixture is not a rule pack and must never be mistaken for one: every fixture rule_id is
prefixed `FIXTURE.` and every fixture citation carries `status="not_stated"` or
`"seed_unverified"`, never `"verified"` (CLAUDE.md §1 rule 1 — no code here invents a verdict
that looks authoritative; it exists only to exercise the schema end to end). It does do real
geometry via shapely for the flagship containment check, because that's cheap, correct, and
exactly the kind of deterministic-code-only check CLAUDE.md §1 demands — it is not a substitute
for the real rule pack's citations and thresholds.
"""

from __future__ import annotations

import logging
import pathlib

from shapely.geometry import Polygon

from packages.schema import BuildingModel, Citation, Finding, Remedy

logger = logging.getLogger("mohali_check.api.checks")

_PACKS_DIR = pathlib.Path(__file__).resolve().parents[1] / "rules" / "packs"


def engine_available() -> bool:
    """True if Track B's real engine module can be imported and exposes a usable entry point.

    The documented contract (INTEGRATION.md) asked for `run_checks(model) -> list[Finding]`.
    What actually landed is `evaluate(model, pack) -> list[Finding]` and
    `evaluate_path(model, pack_path) -> list[Finding]` instead — this adapter accepts either
    without requiring Track B to rename anything, so integration stays a zero-edit swap on both
    sides. See `run_checks()` below for the resolution order.
    """
    return _find_real_entry_point() is not None


def _find_real_entry_point():
    try:
        import packages.rules.engine as engine_module  # type: ignore
    except Exception as exc:
        logger.info("packages.rules.engine not importable (%s)", exc)
        return None
    if hasattr(engine_module, "run_checks"):
        return ("run_checks", engine_module.run_checks)
    if hasattr(engine_module, "evaluate_path"):
        return ("evaluate_path", engine_module.evaluate_path)
    if hasattr(engine_module, "evaluate") and hasattr(engine_module, "load_pack"):
        return ("evaluate", (engine_module.evaluate, engine_module.load_pack))
    logger.info("packages.rules.engine has none of run_checks/evaluate_path/evaluate+load_pack")
    return None


def _resolve_pack_path(model: BuildingModel) -> pathlib.Path | None:
    """Best-effort match of `model.jurisdiction.rule_pack` to a file under rules/packs/.

    Naming isn't guaranteed to line up 1:1 (e.g. jurisdiction.rule_pack="puda_building_rules_1996"
    vs. a pack file named "puda_1996.yaml") since packs/ is Track B's namespace, not ours. Try an
    exact stem match first; if there's exactly one pack file in the whole directory, fall back to
    it rather than refuse to run — multiple packs with no match is left as "can't resolve" so we
    don't silently pick the wrong jurisdiction's rules.
    """
    if not _PACKS_DIR.exists():
        return None
    exact = _PACKS_DIR / f"{model.jurisdiction.rule_pack}.yaml"
    if exact.exists():
        return exact
    yaml_files = sorted(_PACKS_DIR.glob("*.yaml"))
    if len(yaml_files) == 1:
        logger.info(
            "no pack file matches rule_pack=%r; falling back to the only pack present (%s)",
            model.jurisdiction.rule_pack,
            yaml_files[0].name,
        )
        return yaml_files[0]
    return None


def run_checks(model: BuildingModel) -> list[Finding]:
    """The one seam the rest of Track D codes against. Real engine in, fixture engine out."""
    findings, _source, _error = run_checks_with_source(model)
    return findings


def run_checks_with_source(model: BuildingModel) -> tuple[list[Finding], str, str | None]:
    """Same as `run_checks`, plus which path executed for *this* call and any error swallowed.

    Used by the API so `/checks/run`'s reported `engine_source` can never disagree with what the
    accompanying `findings` list was actually produced by (a single static `engine_available()`
    probe elsewhere in the request wouldn't know that a real engine was found but its pack
    couldn't be resolved for this particular model, and would misreport "real").

    Also catches any exception the real engine raises while evaluating a specific model (not
    just import failures) and falls back to fixture findings rather than 500ing the whole
    request — one bad rule in someone else's in-progress pack (e.g. a Remedy.kind value that
    doesn't match the frozen schema's Literal) shouldn't take down /checks/run, /overlay and both
    report endpoints simultaneously. This is not "fabricate a pass to hide the error" (CLAUDE.md
    §10.1) — the fallback findings are still clearly labeled FIXTURE.* and never claim
    "verified", and the real exception is returned in `error` for the caller/tests to see.
    """
    entry = _find_real_entry_point()
    if entry is None:
        logger.info("run_checks: packages.rules.engine not available -> fixture findings")
        return _fixture_findings(model), "fixture", None

    kind, fn = entry
    try:
        if kind == "run_checks":
            logger.info("run_checks: using real packages.rules.engine.run_checks")
            return fn(model), "real", None

        pack_path = _resolve_pack_path(model)
        if pack_path is None:
            logger.warning(
                "run_checks: packages.rules.engine is available but no pack file resolves for "
                "rule_pack=%r -> fixture findings",
                model.jurisdiction.rule_pack,
            )
            return _fixture_findings(model), "fixture", None

        if kind == "evaluate_path":
            logger.info("run_checks: using real packages.rules.engine.evaluate_path(%s)", pack_path.name)
            return fn(model, pack_path), "real", None

        # kind == "evaluate": fn is (evaluate, load_pack)
        evaluate_fn, load_pack_fn = fn
        logger.info("run_checks: using real packages.rules.engine.evaluate() with pack %s", pack_path.name)
        pack = load_pack_fn(pack_path)
        return evaluate_fn(model, pack), "real", None
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        logger.error(
            "run_checks: packages.rules.engine raised %r evaluating model (plot_no=%s) -> "
            "falling back to fixture findings for this request",
            exc,
            model.jurisdiction.plot_no,
            exc_info=True,
        )
        return _fixture_findings(model), "fixture", f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------------------------
# Fixture findings. Deliberately small, deliberately labeled, deliberately not a rule pack.
# --------------------------------------------------------------------------------------------


def _safe_polygon(ring: list[list[float]] | None) -> Polygon | None:
    if not ring:
        return None
    poly = Polygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def _polygon_area_sqm(ring: list[list[float]] | None) -> float | None:
    poly = _safe_polygon(ring)
    return None if poly is None else abs(poly.area)


def _unsolved_remedy(kind: str, note: str) -> Remedy:
    """A remedy placeholder that names the *kind* of fix without inventing a number.

    packages/solver/repair.py (Track C) is the only thing allowed to produce a verified numeric
    remedy (CLAUDE.md §9) — until it's wired up, `verified` stays False and `area_lost_sqm` /
    `edit_ref` stay None rather than guessing.
    """
    return Remedy(kind=kind, description=note, area_lost_sqm=None, edit_ref=None, verified=False)


def _fixture_citation(clause: str, status: str = "not_stated", rule_pack: str | None = None) -> Citation:
    return Citation(
        doc=rule_pack or "FIXTURE",
        clause=clause,
        version="fixture",
        status=status,  # type: ignore[arg-type]
        url=None,
    )


def _containment_finding(model: BuildingModel) -> Finding:
    """The flagship check (CLAUDE.md §7 priority 1): footprint within zoned_area.

    zoned_area is None -> status=unknown, never pass (CLAUDE.md §5, the single most important
    regression this whole API guards, per the Track D brief).
    """
    citation = _fixture_citation("zoning.containment", status="not_stated")
    if model.zoned_area is None:
        return Finding(
            rule_id="FIXTURE.zoned_area_containment",
            status="unknown",
            severity="blocking",
            title="Zoned-area containment (flagship check) — no zoning plan on file",
            citation=citation,
            observed=None,
            required=None,
            geometry_ref=model.plot_polygon,
            compoundable=False,
            ambiguity_class=None,
        )

    zoned_poly = _safe_polygon(model.zoned_area)
    outside_footprint: list[list[float]] | None = None
    for floor in model.floors:
        fp_poly = _safe_polygon(floor.footprint)
        if fp_poly is not None and zoned_poly is not None and not fp_poly.within(zoned_poly):
            outside_footprint = floor.footprint
            break

    if outside_footprint is None:
        return Finding(
            rule_id="FIXTURE.zoned_area_containment",
            status="pass",
            severity="blocking",
            title="Zoned-area containment (flagship check)",
            citation=citation,
            observed="all floor footprints within zoned area",
            required="within zoned area",
            geometry_ref=model.zoned_area,
            compoundable=False,
        )
    return Finding(
        rule_id="FIXTURE.zoned_area_containment",
        status="violation",
        severity="blocking",
        title="Zoned-area containment (flagship check) — footprint extends outside zoned area",
        citation=citation,
        observed="footprint outside zoned area",
        required="within zoned area",
        geometry_ref=outside_footprint,
        compoundable=False,
        remedies=[
            _unsolved_remedy(
                "zoning_revision_request",
                "Pull the footprint back inside the zoned area. packages/solver is not wired up "
                "yet, so no verified numeric edit is offered here — this only names the remedy "
                "class.",
            )
        ],
    )


def _ground_coverage_finding(model: BuildingModel) -> Finding | None:
    ground_floors = [f for f in model.floors if f.level == 0]
    if not ground_floors or not model.plot_area_sqm:
        return None
    footprint_area = sum((_polygon_area_sqm(f.footprint) or 0.0) for f in ground_floors)
    coverage_pct = round(footprint_area / model.plot_area_sqm * 100, 2)
    threshold_pct = 60.0  # placeholder only; real bands live in packages/rules/packs/*.yaml
    citation = _fixture_citation("15", status="seed_unverified", rule_pack=model.jurisdiction.rule_pack)
    is_violation = coverage_pct > threshold_pct
    return Finding(
        rule_id="FIXTURE.ground_coverage",
        status="violation" if is_violation else "pass",
        severity="major",
        title="Maximum ground coverage (placeholder 60% threshold, not the real rule pack)",
        citation=citation,
        observed=coverage_pct,
        required=threshold_pct,
        geometry_ref=ground_floors[0].footprint,
        compoundable=True,
        remedies=[
            _unsolved_remedy(
                "geometric_edit",
                "Shrink the ground-floor footprint until coverage falls at or below the "
                "threshold shown. packages/solver is not wired up yet, so no verified numeric "
                "edit is offered here.",
            )
        ]
        if is_violation
        else [],
    )


def _rwh_finding(model: BuildingModel) -> Finding | None:
    if not model.plot_area_sqm or model.plot_area_sqm <= 100:
        return None
    citation = _fixture_citation("rwh", status="not_stated", rule_pack=model.jurisdiction.rule_pack)
    return Finding(
        rule_id="FIXTURE.rainwater_harvesting",
        status="pass" if model.has_rwh else "violation",
        severity="minor",
        title="Rainwater harvesting required above 100 sq m plot area (CLAUDE.md §7 priority 14)",
        citation=citation,
        observed=model.has_rwh,
        required=True,
        geometry_ref=None,
        compoundable=True,
    )


def _stilt_ambiguity_finding(model: BuildingModel) -> Finding | None:
    stilt_floors = [f for f in model.floors if f.is_stilt]
    if not stilt_floors:
        return None
    citation = _fixture_citation("16", status="seed_unverified", rule_pack=model.jurisdiction.rule_pack)
    return Finding(
        rule_id="FIXTURE.stilt_far_treatment",
        status="ambiguity",
        severity="major",
        title="Whether the stilt floor counts toward FAR is contested under the stilt+4 policy",
        citation=citation,
        observed="stilt floor present",
        required=None,
        geometry_ref=stilt_floors[0].footprint,
        compoundable=False,
        ambiguity_class="definitional",
    )


def _height_unknown_finding(model: BuildingModel) -> Finding | None:
    if not model.floors or not any(f.height_m is None for f in model.floors):
        return None
    citation = _fixture_citation("17", status="not_stated", rule_pack=model.jurisdiction.rule_pack)
    return Finding(
        rule_id="FIXTURE.total_height",
        status="unknown",
        severity="major",
        title="Total height / storey count cannot be verified (no section-sheet height for one or more floors)",
        citation=citation,
        observed=None,
        required=None,
        geometry_ref=None,
        compoundable=False,
    )


def _tree_advisory_finding(model: BuildingModel) -> Finding | None:
    if not model.plot_area_sqm or model.plot_area_sqm <= 100:
        return None
    required_trees = max(1, int(model.plot_area_sqm // 80))
    citation = _fixture_citation("tree_planting", status="not_stated", rule_pack=model.jurisdiction.rule_pack)
    return Finding(
        rule_id="FIXTURE.tree_planting",
        status="advisory",
        severity="minor",
        title="Recommended: one tree per 80 sq m plot area (advisory pending clause verification)",
        citation=citation,
        observed=model.tree_count,
        required=required_trees,
        geometry_ref=None,
        compoundable=False,
    )


def _fixture_findings(model: BuildingModel) -> list[Finding]:
    candidates = [
        _containment_finding(model),
        _ground_coverage_finding(model),
        _rwh_finding(model),
        _stilt_ambiguity_finding(model),
        _height_unknown_finding(model),
        _tree_advisory_finding(model),
    ]
    return [f for f in candidates if f is not None]
