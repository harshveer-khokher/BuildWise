"""Infer which sheet-role an uploaded file is, from its own content, instead of requiring the
caller to pre-tag it. This exists so the frontend can offer a single "drop your files" uploader
(CLAUDE.md's own §10.1 assembly design still applies underneath -- a case is a sheet set, not one
file -- this module just removes the need for a human to manually name each sheet's role).

Never guesses past what the title block actually says: a file whose role can't be confidently
read is reported as unclassified rather than assigned a role that might be wrong (CLAUDE.md §1
rule 6 -- fake precision is worse than declared uncertainty -- applies just as much to "which
sheet is this" as it does to a numeric rule value).
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import fitz  # PyMuPDF

from packages.parser import dxf_ingest
from packages.parser.pdf_ingest import extract_title_block

# Ordered most-specific-first: "front elevation" must match before generic "elevation" would.
_ROLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("basement", ("basement",)),
    ("stilt", ("stilt",)),
    ("ground", ("ground floor",)),
    ("first", ("first floor",)),
    ("second", ("second floor",)),
    ("third", ("third floor",)),
    ("fourth", ("fourth floor",)),
    ("elevation_front", ("front elevation",)),
    ("elevation_rear", ("rear elevation", "back elevation")),
    ("elevation_side", ("side elevation", "left elevation", "right elevation")),
    ("elevation", ("elevation",)),
    ("site", ("site plan",)),
    ("zoning", ("zoning plan", "zoning")),
    ("section", ("section",)),
]

# Roles that legitimately may repeat across a sheet set (e.g. front/rear/side elevations, or a
# generic "elevation" title with no direction) -- these get an auto-numbered suffix on collision
# instead of being rejected. Plan levels (ground/first/...) and site/section must be unique;
# semantics.assemble_case() itself enforces that for plan levels and raises if violated.
_MULTI_OK_ROLE_PREFIXES = ("elevation",)


class RoleGuess(NamedTuple):
    role: str | None
    """None if unclassified."""
    source: str
    """"title_block" (read from the file itself) or "filename" (DXF fallback, lower trust)."""
    detail: str
    """Human-readable reason, always present -- shown to the user either way."""


def _match_keywords(text: str) -> str | None:
    lowered = text.lower()
    for role, keywords in _ROLE_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return role
    return None


def guess_role(file_path: Path, original_filename: str) -> RoleGuess:
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        try:
            doc = fitz.open(str(file_path))
            text = doc[0].get_text()
            doc.close()
        except Exception as exc:
            return RoleGuess(None, "title_block", f"could not read this PDF's contents: {exc}")

        title_block = extract_title_block(text)
        sheet_title = title_block.get("sheet_title")
        if sheet_title:
            role = _match_keywords(sheet_title)
            if role:
                return RoleGuess(role, "title_block", f"title block reads {sheet_title!r}")
            return RoleGuess(
                None, "title_block",
                f"title block reads {sheet_title!r}, which doesn't match a known sheet type "
                "(floor plan / elevation / site / zoning / section)",
            )
        # No TITLE:- field parsed -- last resort, try the whole page text (some sheets put the
        # sheet description elsewhere, e.g. as a heading rather than in a formal title block).
        role = _match_keywords(text[:2000])
        if role:
            return RoleGuess(role, "title_block", "matched from page text (no formal title block field found)")
        return RoleGuess(None, "title_block", "no title block or recognizable sheet heading found in this PDF")

    if suffix == ".dxf":
        # dxf_ingest.py does not read title-block text (CLAUDE.md scope: DXF ingest works off
        # layer/entity geometry, not text blocks) -- filename is the only signal available, and
        # it is explicitly lower-trust than reading the sheet itself.
        role = _match_keywords(original_filename.replace("_", " ").replace("-", " "))
        if role:
            return RoleGuess(role, "filename", f"guessed from filename {original_filename!r} (DXF has no readable title block)")
        return RoleGuess(None, "filename", f"filename {original_filename!r} doesn't suggest a known sheet type, and DXF has no readable title block")

    return RoleGuess(None, "filename", f"unsupported file type {suffix!r} (only .pdf, .dxf, and .dwg are ingested)")


def guess_layout_roles(file_path: Path) -> dict[str, RoleGuess]:
    """For a DXF holding multiple named paperspace layout tabs (a single DWG/DXF containing a
    whole sheet set as separate layouts -- "GROUND FLOOR PLAN", "ELEVATION FRONT" -- rather than
    as separate uploaded files), guess each layout's role from its own tab name.

    This is higher-trust than the filename fallback above: a layout tab name is content the
    drafter wrote into the file itself, the DXF/DWG analogue of a PDF's title block, not metadata
    about the upload. Returns {layout_name: RoleGuess}; empty if the file has no non-empty
    paperspace layouts (the common case -- most drawings are a single flat modelspace)."""
    guesses: dict[str, RoleGuess] = {}
    for name in dxf_ingest.list_layout_names(file_path):
        role = _match_keywords(name.replace("_", " ").replace("-", " "))
        if role:
            guesses[name] = RoleGuess(
                role, "layout_name", f"guessed from this file's own layout tab name {name!r}"
            )
        else:
            guesses[name] = RoleGuess(
                None, "layout_name",
                f"layout tab {name!r} doesn't match a known sheet type "
                "(floor plan / elevation / site / zoning / section)",
            )
    return guesses


def assign_roles(guesses: dict[str, RoleGuess]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """filename -> RoleGuess for every uploaded file -> (sheets dict for assemble_case,
    unresolved list). Handles collisions: a repeatable role (elevation*) gets auto-numbered; any
    other collision keeps the first file and reports every later one as unresolved rather than
    silently overwriting it (CLAUDE.md: never silently drop a clause/sheet -- surface it)."""
    sheets: dict[str, str] = {}
    used_roles: set[str] = set()
    unresolved: list[dict[str, str]] = []

    for filename, guess in guesses.items():
        if guess.role is None:
            unresolved.append({"filename": filename, "reason": guess.detail})
            continue

        role_key = guess.role
        if role_key in used_roles:
            if role_key.startswith(_MULTI_OK_ROLE_PREFIXES):
                n = 2
                while f"{role_key}_{n}" in used_roles:
                    n += 1
                role_key = f"{role_key}_{n}"
            else:
                unresolved.append({
                    "filename": filename,
                    "reason": (
                        f"looked like another '{guess.role}' sheet, but one was already assigned "
                        f"from a different file -- only one is used per level; remove the "
                        f"duplicate or check these aren't the same sheet twice"
                    ),
                })
                continue

        sheets[role_key] = filename
        used_roles.add(role_key)

    return sheets, unresolved
