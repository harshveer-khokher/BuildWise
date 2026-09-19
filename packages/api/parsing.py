"""Thin adapter between the API and the parser (Track A, `packages/parser/`).

Contract (also written to INTEGRATION.md): Track A should expose one of

    packages.parser.ingest.ingest(file_bytes: bytes, filename: str) -> BuildingModel
    packages.parser.dxf_ingest.ingest(file_bytes: bytes, filename: str) -> BuildingModel

`try_parse_file` tries both entry points, in that order, and returns None if neither is
available yet — the caller (packages/api/main.py) treats None as "parsing not wired up", not as
an error in the uploaded file, and responds accordingly (CLAUDE.md §10.2: this is exactly the
placeholder-mode seam the whole Stage 1 split is designed around).
"""

from __future__ import annotations

import logging
from typing import Callable

from packages.schema import BuildingModel

logger = logging.getLogger("mohali_check.api.parsing")

_CANDIDATE_ENTRY_POINTS = (
    "packages.parser.ingest",
    "packages.parser.dxf_ingest",
    "packages.parser.pdf_ingest",
)


def _find_real_ingest() -> Callable[[bytes, str], BuildingModel] | None:
    for module_path in _CANDIDATE_ENTRY_POINTS:
        try:
            module = __import__(module_path, fromlist=["ingest"])
        except Exception:
            continue
        ingest_fn = getattr(module, "ingest", None)
        if callable(ingest_fn):
            logger.info("parsing: found real ingest entry point at %s.ingest", module_path)
            return ingest_fn
    return None


def parser_available() -> bool:
    return _find_real_ingest() is not None


def try_parse_file(file_bytes: bytes, filename: str) -> BuildingModel | None:
    """Returns a BuildingModel if a real parser is wired up, else None (never raises for that)."""
    real_ingest = _find_real_ingest()
    if real_ingest is None:
        logger.info("parsing: no packages.parser ingest entry point available for %r", filename)
        return None
    logger.info("parsing: using real parser for %r", filename)
    return real_ingest(file_bytes, filename)
