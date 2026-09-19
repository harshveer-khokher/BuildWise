"""API skeleton for mohali-check (Track D, CLAUDE.md §4/§11 Stage 1).

Framework choice: FastAPI + uvicorn, not Flask. Reasoning (asked for in the brief): the frozen
schema (packages/schema) is already pydantic v2, so FastAPI gets automatic request/response
validation and OpenAPI docs against `BuildingModel`/`Finding`/`Remedy` for free with zero glue
code — a Flask app would need to hand-roll that validation, and getting it subtly wrong is
exactly how a bad BuildingModel slips past the model-confirmation screen. Both are already
importable in this environment (see requirements.txt); FastAPI was the smaller amount of code
for a schema-first API.

Endpoints (contract, also mirrored in INTEGRATION.md):

    GET  /health                        -> {"status": "ok", ...}
    POST /upload                        -> BuildingModel
        multipart/form-data with a `file` field -> real parser (Track A) if wired, else 501
        application/json body = a BuildingModel -> validated and echoed back (placeholder mode,
            CLAUDE.md §10.2 — tracks B/C/D never need the parser)
    POST /models/confirm                -> {"model": BuildingModel, "applied": int,
                                             "remaining_low_confidence": int}
        body: {"model": BuildingModel, "corrections": [RoomCorrection, ...]}
        Applies user corrections to low-confidence rooms (CLAUDE.md §5 Confidence semantics,
        exercised by stub s06_low_conf) and returns the corrected model.
    POST /checks/run                    -> {"summary": str, "engine_source": "real"|"fixture",
                                             "findings": [Finding, ...]}
        body: {"model": BuildingModel}
        Runs packages.api.checks.run_checks(model) — real packages.rules.engine if importable,
        else a small fixture set (see checks.py). `summary` is always
        "pre-submission check: N issues found" — CLAUDE.md §5 forbids "approved"/"compliant"
        anywhere in this API, including here.
    POST /overlay                       -> GeoJSON FeatureCollection
        body: {"model": BuildingModel, "findings": [Finding, ...] | omitted}
        If findings is omitted, runs run_checks(model) first. Thin wrapper over
        packages.report.overlay.build_overlay.
    POST /report/html                   -> text/html
    POST /report/pdf                    -> application/pdf
        Same body shape as /overlay. Thin wrapper over packages.report.render.

Every route return value is checked (in tests/test_api.py) to never contain the words
"approved" or "compliant" as a verdict — CLAUDE.md §5's non-negotiable.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, ValidationError

from packages.api import checks, parsing
from packages.report.overlay import build_overlay
from packages.report.render import render_html, render_markdown, render_pdf, summary_line
from packages.schema import BuildingModel, Confidence, Finding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mohali_check.api")

app = FastAPI(
    title="mohali-check API",
    description=(
        "Pre-submission compliance checker for Greater Mohali building drawings. "
        "This service never returns 'approved' or 'compliant' — see CLAUDE.md §5. "
        "Output is always framed as 'pre-submission check: N issues found'."
    ),
    version="0.1.0",
)

# Hackathon-simple CORS: the web/ Vite dev server runs on a different port than uvicorn.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------------------------
# Request/response shapes local to the API layer (not part of the frozen schema).
# --------------------------------------------------------------------------------------------

RoomUse = Literal[
    "bedroom", "living", "kitchen", "bath", "wc", "store", "stair", "garage", "other"
]


class RoomCorrection(BaseModel):
    """One user correction from the model-confirmation screen (CLAUDE.md §5, §10.5)."""

    floor_level: int
    room_index: int
    """Index of the room within `floor.rooms` for the matching `floor_level`."""
    use: RoomUse | None = None
    confidence: Confidence | None = None
    """If omitted, confirming a room (even with no `use` change) sets confidence to "high" —
    that's what "confirmed" means on this screen."""


class ConfirmRequest(BaseModel):
    model: BuildingModel
    corrections: list[RoomCorrection] = Field(default_factory=list)


class ChecksRunRequest(BaseModel):
    model: BuildingModel


class OverlayRequest(BaseModel):
    model: BuildingModel
    findings: list[Finding] | None = None


class ReportRequest(BaseModel):
    model: BuildingModel
    findings: list[Finding] | None = None


def _findings_for(model: BuildingModel, findings: list[Finding] | None) -> list[Finding]:
    return findings if findings is not None else checks.run_checks(model)


# --------------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "mohali-check-api",
        "rules_engine_available": checks.engine_available(),
        "parser_available": parsing.parser_available(),
    }


# --------------------------------------------------------------------------------------------
# Jurisdictions: a small, explicit registry rather than "one pack file = one jurisdiction"
# (a real jurisdiction may need more than a bare pack filename someday -- a display name,
# vintage rules, etc.). Static for now: exactly one real jurisdiction exists
# (corpus/MANIFEST.json / packages/rules/packs/puda_1996.yaml, Mohali/GMADA). Structured so
# adding a custom-bylaws-derived jurisdiction later (a real backend feature, not built in this
# pass -- see INTEGRATION.md) is an append to this list, not a response-shape change.
# --------------------------------------------------------------------------------------------

_JURISDICTIONS = [
    {
        "id": "mohali_gmada",
        "label": "Mohali (GMADA)",
        "authority": "GMADA",
        "rule_pack": "puda_building_rules_1996",
        "source_note": "Punjab Urban Planning and Development Authority (Building) Rules, 1996",
    },
]


@app.get("/jurisdictions")
def list_jurisdictions() -> list[dict]:
    return _JURISDICTIONS


@app.post("/upload", response_model=None)
async def upload(request: Request):
    """Accepts either a drawing file (multipart) or a BuildingModel JSON body directly.

    CLAUDE.md §10.2 placeholder mode: parsing isn't guaranteed to exist yet, so the JSON path is
    a first-class citizen here, not a fallback hack — it's exactly how tracks B/C/D were meant to
    exercise this API before track A's parser lands.
    """
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None:
            raise HTTPException(status_code=400, detail="multipart upload must include a 'file' field")
        file_bytes = await upload_file.read()
        model = parsing.try_parse_file(file_bytes, upload_file.filename or "upload")
        if model is None:
            raise HTTPException(
                status_code=501,
                detail=(
                    "Drawing parsing is not wired up yet (packages.parser has no ingest entry "
                    "point). This is not a rejection of your drawing — submit a BuildingModel "
                    "JSON body to /upload instead (see /docs) until the parser lands."
                ),
            )
        return model

    # JSON path: body is already expected to be a BuildingModel.
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not parse request body as JSON: {exc}") from exc
    try:
        model = BuildingModel.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"body is not a valid BuildingModel: {exc}") from exc
    return model


@app.post("/cases/assemble", response_model=None)
async def assemble_case_route(request: Request):
    """General file upload -> one BuildingModel, via Track A's real assembly logic
    (packages.parser.semantics.assemble_case). This is the real gap identified during frontend
    scoping: /upload's JSON-only path exists because CLAUDE.md's own architecture treats a
    building as a *sheet set* (ground/first/second/elevations/site/section), never one file
    (§10.1: "assembly is a required parser step, not an extra"). This route is a thin adapter,
    not new core logic -- it writes the uploaded files to a temp directory, synthesizes the
    meta.json assemble_case() already expects, and calls it unchanged.

    multipart/form-data:
      - repeated field named "files": any number of drawing files, role auto-inferred from each
        file's own content (packages.api.role_inference) -- this is the normal path, so the user
        never has to know or declare which sheet is which.
      - any OTHER file field name that matches a known role (e.g. "ground", "elevation_front")
        is treated as an explicit override for that role, taking precedence over auto-inference
        -- kept for programmatic/API callers who already know their sheet roles.
      - plain text fields: "authority" (e.g. "GMADA") and optionally "rule_pack" override.
      - optional plain text fields "plot_width_m" and "plot_length_m" (already converted to
        metres by the caller -- CLAUDE.md §1 rule 4, unit conversion happens at the display
        layer, not here): when BOTH are given, also computes an advisory
        packages.rules.estimated_envelope estimate (see that module's docstring) using this
        upload's own ground-floor and front-elevation sheets. Never touches BuildingModel.
        zoned_area or the real containment check either way.

    Response: {"model": BuildingModel, "resolved_roles": {filename: role},
               "unresolved": [{"filename", "reason"}, ...],
               "estimated_envelope": dict | None}
    A file that couldn't be classified is never silently dropped or guessed at -- it's reported
    in "unresolved" so the user can see it wasn't used, same "unknown over fake precision"
    principle as everywhere else in this project (CLAUDE.md §1 rule 6).
    """
    import tempfile
    from pathlib import Path

    from packages.api.role_inference import RoleGuess, assign_roles, guess_role

    try:
        from packages.parser import semantics
    except Exception as exc:
        raise HTTPException(
            status_code=501,
            detail=f"multi-sheet assembly is not available in this environment: {exc}",
        ) from exc

    form = await request.form()
    sheets: dict[str, str] = {}  # role -> temp filename, on disk under tmp_path
    auto_uploads: list[tuple[str, Any]] = []  # (original_filename, UploadFile), field name "files"
    authority = None
    rule_pack = None
    plot_width_m: float | None = None
    plot_length_m: float | None = None

    with tempfile.TemporaryDirectory(prefix="buildwise_upload_") as tmpdir:
        tmp_path = Path(tmpdir)

        for field_name, value in form.multi_items():
            if hasattr(value, "read"):  # an UploadFile
                if field_name == "files":
                    auto_uploads.append((value.filename or f"upload_{len(auto_uploads)}", value))
                    continue
                # A field named after a specific role is an explicit override for that role.
                filename = value.filename or f"{field_name}.pdf"
                suffix = Path(filename).suffix.lower() or ".pdf"
                if suffix not in (".pdf", ".dxf"):
                    raise HTTPException(
                        status_code=422,
                        detail=f"sheet '{field_name}': unsupported file type {suffix!r} (only .pdf and .dxf are ingested today)",
                    )
                dest = tmp_path / f"{field_name}{suffix}"
                dest.write_bytes(await value.read())
                sheets[field_name] = dest.name
            elif field_name == "authority":
                authority = value
            elif field_name == "rule_pack":
                rule_pack = value
            elif field_name == "plot_width_m":
                plot_width_m = float(value)
            elif field_name == "plot_length_m":
                plot_length_m = float(value)

        # Save every auto-upload to a safe temp filename and classify it from its own content.
        original_to_safe: dict[str, str] = {}
        guesses: dict[str, RoleGuess] = {}
        for idx, (original_filename, upload_file) in enumerate(auto_uploads):
            suffix = Path(original_filename).suffix.lower() or ".pdf"
            if suffix not in (".pdf", ".dxf"):
                guesses[original_filename] = RoleGuess(
                    None, "filename",
                    f"unsupported file type {suffix!r} (only .pdf and .dxf are ingested today)",
                )
                continue
            safe_name = f"auto_{idx}{suffix}"
            (tmp_path / safe_name).write_bytes(await upload_file.read())
            original_to_safe[original_filename] = safe_name
            guesses[original_filename] = guess_role(tmp_path / safe_name, original_filename)

        auto_role_map, unresolved = assign_roles(guesses)  # role -> original_filename

        resolved_roles: dict[str, str] = {}
        for role, original_filename in auto_role_map.items():
            if role in sheets:
                # An explicit override for this role already won -- report the unused guess
                # rather than silently dropping it (never guess past a stated conflict).
                unresolved.append({
                    "filename": original_filename,
                    "reason": f"inferred as '{role}', but that role was already explicitly provided -- this file was not used",
                })
                continue
            sheets[role] = original_to_safe[original_filename]
            resolved_roles[original_filename] = role

        if not sheets:
            raise HTTPException(
                status_code=400,
                detail="no usable sheet files were included -- upload at least one recognizable drawing (PDF or DXF)",
            )

        meta = {
            "case_id": "upload",
            "provenance": "real",
            "sheets": sheets,
            "known_gaps": [],
        }
        if authority:
            meta["authority"] = authority
        if rule_pack:
            meta["rule_pack"] = rule_pack

        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        try:
            model = semantics.assemble_case(meta_path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"could not assemble uploaded sheets: {exc}") from exc

        estimated_envelope = None
        if plot_width_m is not None and plot_length_m is not None:
            ground_role = "ground" if "ground" in sheets else None
            front_role = "elevation_front" if "elevation_front" in sheets else next(
                (r for r in sheets if r.startswith("elevation")), None
            )
            if ground_role is None or front_role is None:
                estimated_envelope = {
                    "available": False,
                    "reason": "need both a ground floor plan and a front (or any) elevation sheet to compute this estimate.",
                }
            else:
                from packages.rules.estimated_envelope import estimate_buildable_envelope

                estimated_envelope = estimate_buildable_envelope(
                    model=model,
                    front_elevation_path=tmp_path / sheets[front_role],
                    plot_width_m=plot_width_m,
                    plot_length_m=plot_length_m,
                )

    return {
        "model": model,
        "resolved_roles": resolved_roles,
        "unresolved": unresolved,
        "estimated_envelope": estimated_envelope,
    }


@app.post("/models/confirm")
def confirm_model(payload: ConfirmRequest) -> dict:
    """Apply model-confirmation-screen corrections (CLAUDE.md §5 Confidence semantics).

    Low-confidence rooms (stub s06_low_conf) must be confirmed here before /checks/run is
    meaningful — the rules engine is free to run on an unconfirmed model (nothing in the schema
    stops it), but the product story is: confirm first, then check.
    """
    corrected = payload.model.model_copy(deep=True)
    applied = 0
    errors: list[str] = []

    floors_by_level = {f.level: f for f in corrected.floors}
    for i, correction in enumerate(payload.corrections):
        floor = floors_by_level.get(correction.floor_level)
        if floor is None:
            errors.append(f"correction[{i}]: no floor at level {correction.floor_level}")
            continue
        if not (0 <= correction.room_index < len(floor.rooms)):
            errors.append(
                f"correction[{i}]: room_index {correction.room_index} out of range for floor "
                f"{correction.floor_level} (has {len(floor.rooms)} rooms)"
            )
            continue
        room = floor.rooms[correction.room_index]
        if correction.use is not None:
            room.use = correction.use
        room.confidence = correction.confidence if correction.confidence is not None else "high"
        applied += 1

    if errors:
        # Fail loudly rather than silently dropping a correction (CLAUDE.md §10.1 ethos).
        raise HTTPException(status_code=400, detail={"message": "some corrections could not be applied", "errors": errors})

    remaining_low_confidence = sum(
        1 for floor in corrected.floors for room in floor.rooms if room.confidence == "low"
    )
    return {
        "model": corrected,
        "applied": applied,
        "remaining_low_confidence": remaining_low_confidence,
    }


@app.post("/checks/run")
def run_checks_route(payload: ChecksRunRequest) -> dict:
    findings, engine_source, engine_error = checks.run_checks_with_source(payload.model)
    response = {
        "summary": summary_line(findings),
        "engine_source": engine_source,
        "findings": findings,
    }
    if engine_error:
        # The real engine raised evaluating this model and we fell back to fixture findings
        # (see checks.run_checks_with_source's docstring) — surface it rather than hide it.
        response["engine_error"] = engine_error
    return response


@app.post("/overlay")
def overlay_route(payload: OverlayRequest) -> dict:
    findings = _findings_for(payload.model, payload.findings)
    return build_overlay(payload.model, findings)


@app.post("/report/html", response_class=HTMLResponse)
def report_html_route(payload: ReportRequest) -> HTMLResponse:
    findings = _findings_for(payload.model, payload.findings)
    html = render_html(payload.model, findings)
    return HTMLResponse(content=html)


@app.post("/report/pdf")
def report_pdf_route(payload: ReportRequest) -> Response:
    findings = _findings_for(payload.model, payload.findings)
    pdf_bytes = render_pdf(payload.model, findings)
    return Response(content=pdf_bytes, media_type="application/pdf")


@app.post("/report/markdown")
def report_markdown_route(payload: ReportRequest) -> Response:
    findings = _findings_for(payload.model, payload.findings)
    text = render_markdown(payload.model, findings)
    return Response(
        content=text,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="buildwise-report.md"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("packages.api.main:app", host="127.0.0.1", port=8000, reload=True)
