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

import logging
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, ValidationError

from packages.api import checks, parsing
from packages.report.overlay import build_overlay
from packages.report.render import render_html, render_pdf, summary_line
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("packages.api.main:app", host="127.0.0.1", port=8000, reload=True)
