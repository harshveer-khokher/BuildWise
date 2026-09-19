"""Vector-PDF architectural sheet -> raw geometry + title-block text.

Track A (CLAUDE.md §4/§10.1). Both real cases supplied so far (packages/cases/real/h01, h02)
are vector-PDF sheet sets, not DXF (see INTEGRATION.md's Stage-0 handoff notes) -- Tier B per
CLAUDE.md §10.4. This module is the "read one sheet" step; semantics.py assembles several
sheets (plan + elevation, ideally + site/section) into one BuildingModel.

**What this does NOT do, on purpose (documented per the task's "good enough for a demo" scope,
not silently):**

- No true wall-polygon vectorisation. `pdfplumber`/PyMuPDF give thousands of raw path
  primitives per sheet (~40k on the sampled h01 ground floor, including material hatching,
  dimension ticks, north arrows, notes-block glyphs) and there is no layer separation in a
  flattened architectural PDF the way there is in DXF. Reconstructing true wall centrelines from
  that soup is a CAD-vision project of its own, out of hackathon budget. Instead:
  - the sheet's overall *drawing bounding box* (vector paths, minus an excluded title-block
    strip) stands in for the floor footprint, as an axis-aligned rectangle;
  - individual rooms are recovered from the office's own room-label convention on these sheets
    (`"ROOM NAME"` immediately followed by `"W' x H\""`), not from tracing their wall polygons,
    positioned at the label's text location and sized from the labelled dimension when it parses
    cleanly, else a small placeholder size keyed off room type.
  Every value produced this way is `confidence <= "medium"` and the approximation is spelled out
  in the returned `notes` list, which callers (semantics.py) are expected to fold into
  `BuildingModel.assumptions` verbatim (CLAUDE.md §5: "printed verbatim on the report").
- No scale bar / geo-reference exists on these sheets. Scale (points-per-metre) is *estimated*
  by matching the single largest clean "N'-M\"" dimension string found in the sheet's text layer
  against the longer axis of the drawing bounding box. This is a heuristic, tied to this specific
  office's drafting habits (The Architects Collaborative, S.C.O. 63 Phase-2, Mohali) — it is not
  a substitute for a digitized site/zoning sheet, and CLAUDE.md's rule stands unchanged: without
  a site sheet, plot_polygon/plot_area_sqm/zoned_area/edges must remain None/[] and any check
  needing them is `status=unknown`, never `pass`. This module only ever produces *per-floor*
  footprint/room geometry in an internally-consistent, sheet-local metre coordinate system; it
  never claims that coordinate system is anchored to the plot.
- Text extraction quality varies by source file: one sheet in h02 (`elevation_rear.pdf`) uses an
  embedded font whose text layer decodes to garbled characters (e.g. "TITLE:-" reads as
  "TIT.E:-"). Title-block parsing here is best-effort and returns `None` fields rather than
  guessing when a expected field doesn't match, and that garbling is exactly the kind of thing
  semantics.py's title/role cross-check should flag rather than trust silently.

Everything numeric returned here is plain, code-computed geometry -- no LLM involved
(CLAUDE.md §1 rule 1).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

_FEET_INCH_RE = re.compile(r"(\d+)'-(\d+)\"")
_FOOT_ONLY_RE = re.compile(r"(\d+)'(?!-?\d*\")")

FT_TO_M = 0.3048


def feet_inches_to_m(feet: int, inches: int) -> float:
    return (feet + inches / 12.0) * FT_TO_M


def _clean_dimension_values_m(text: str) -> list[float]:
    """All *cleanly parseable* `N'-M"` tokens in `text`, converted to metres.

    Deliberately conservative: these sheets embed fractional inches (e.g. 10'-10 1/2") using a
    glyph that PyMuPDF's text extraction sometimes splits across lines/tokens (observed on both
    h01 and h02) -- rather than guess at a mis-split fraction, this only trusts whole-inch
    matches and lets the fractional ones fall through as unparsed (callers fall back to a
    placeholder size for those).
    """
    values = []
    for feet_s, inches_s in _FEET_INCH_RE.findall(text):
        feet, inches = int(feet_s), int(inches_s)
        if inches < 12:  # sanity clamp -- a garbled fraction glyph can produce e.g. "101"
            values.append(feet_inches_to_m(feet, inches))
    return values


# ---------------------------------------------------------------------------
# Text layout
# ---------------------------------------------------------------------------


def _flatten_lines(page: "fitz.Page") -> list[tuple[str, fitz.Rect]]:
    """Reading-order (text, bbox) per line, bbox = union of that line's span rects."""
    out: list[tuple[str, fitz.Rect]] = []
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            rect = fitz.Rect(spans[0]["bbox"])
            for s in spans[1:]:
                rect |= fitz.Rect(s["bbox"])
            out.append((text, rect))
    return out


# ---------------------------------------------------------------------------
# Title block
# ---------------------------------------------------------------------------

_TITLE_FIELD_PATTERNS = {
    # [ \t]* (not \s*) after the colon: these fields sit one per line in the flattened text, and
    # a blank field (e.g. CLIENT often is, in these redacted-title-block samples) must not let
    # \s* skip the newline and swallow the *next* label's line as this field's value.
    "sheet_title": re.compile(r"TITLE\s*:-[ \t]*(.*)", re.IGNORECASE),
    "date": re.compile(r"DATE\s*:-[ \t]*(.*)", re.IGNORECASE),
    "drawn_by": re.compile(r"DRAWN\s*BY\s*:-[ \t]*(.*)", re.IGNORECASE),
    "checked_by": re.compile(r"CHECKED\s*BY\s*:-[ \t]*(.*)", re.IGNORECASE),
    "client": re.compile(r"CLIENT\s*:-[ \t]*(.*)", re.IGNORECASE),
    "drawing_no": re.compile(r"DRAWING\s*NO\s*:-[ \t]*(.*)", re.IGNORECASE),
}
_PLOT_RE = re.compile(r"Plot\s*No\.?\s*(\S+)", re.IGNORECASE)
_PHASE_SECTOR_RE = re.compile(r"(Phase|Sector)\s*[-:]?\s*(\S+)", re.IGNORECASE)


_PHASE_SECTOR_WINDOW_CHARS = 60
"""How far past a "Plot No ..." match to look for its Phase/Sector. These sheets also print the
architect firm's own office address ("S.C.O. 63, Phase-2, Mohali") elsewhere on the same page,
which contains an unrelated Phase/Sector token -- observed on both h01 and h02, where the office
address (Phase-2) appears in the text *before* the project's actual "Plot No 351, Phase-4" /
"Plot No.1002, phase -4". A page-wide "first match wins" search silently picks up the office's
phase instead of the project's. The two are reliably adjacent in this office's convention
("Plot No <N>, Phase-<M>"), so anchoring the search to right after the plot-number match fixes
it without guessing -- if no Phase/Sector is found in that window, `sector` is left None rather
than falling back to a page-wide search that would reproduce the same bug."""


def extract_title_block(text: str) -> dict[str, Any]:
    """Best-effort key facts from a sheet's flattened text (title block is NOT a separate
    region in these PDFs -- it is a rotated strip whose text lands inline with everything
    else once PyMuPDF un-rotates the page, so this just regexes the whole page text).

    Returns None for any field not confidently matched; never fabricates a value.
    """
    fields: dict[str, Any] = {k: None for k in _TITLE_FIELD_PATTERNS}
    for key, pattern in _TITLE_FIELD_PATTERNS.items():
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            fields[key] = value or None

    plot_no = None
    sector = None
    m = _PLOT_RE.search(text)
    if m:
        plot_no = m.group(1).rstrip(",")
        window = text[m.end(): m.end() + _PHASE_SECTOR_WINDOW_CHARS]
        pm = _PHASE_SECTOR_RE.search(window)
        if pm:
            kind, val = pm.group(1), pm.group(2)
            sector = f"{kind.title()}-{val.rstrip(',')}"
    fields["plot_no"] = plot_no
    fields["sector"] = sector
    return fields


# ---------------------------------------------------------------------------
# Drawing bounding box / scale
# ---------------------------------------------------------------------------

# These sheets place a title-block strip along the right ~15% of the drawing content.  Measured
# on h01/h02 ground-floor sheets: title-block text sits in the rightmost ~15% of the full
# vector-drawing extent. Tuned to this one office's template -- documented as an assumption, not
# treated as a general PDF-layout rule.
#
# NOTE ON COORDINATE FRAMES: these sheets are authored portrait (mediabox e.g. 1684x2384) with a
# /Rotate 270 flag to display landscape (page.rect reports 2384x1684). PyMuPDF's get_text() and
# get_drawings() were both observed to return coordinates in the *unrotated* mediabox frame
# (values up to ~2384 on the "y" axis, not the rotated page.rect's 1684) -- i.e. they agree with
# each other, just not with page.rect. Deriving the title-block cutoff as a fraction of the
# *observed* drawing extent (below), rather than of `page.rect.width`, sidesteps needing to know
# which frame is in play at all, and keeps text-position and drawing-bbox math in the same frame.
_TITLE_BLOCK_X_FRACTION = 0.85


def extract_drawing_bbox(page: "fitz.Page") -> tuple[fitz.Rect, str]:
    """Bounding box of vector paths, excluding the title-block strip.

    Returns (bbox, note). This is an *envelope*, not a traced outline -- it includes notes text,
    hatching, dimension lines, north arrow, everything left of the title-block cut, so it is
    always >= the true building footprint. Approximation is intentional; see module docstring.
    """
    drawings = page.get_drawings()
    if not drawings:
        note = "extract_drawing_bbox: no vector paths on this page at all; falling back to the full page rect (very low confidence)."
        return fitz.Rect(page.rect), note

    full_bbox = drawings[0]["rect"]
    for d in drawings[1:]:
        full_bbox |= d["rect"]

    cutoff_x = full_bbox.x0 + full_bbox.width * _TITLE_BLOCK_X_FRACTION
    rects = [d["rect"] for d in drawings if d["rect"].x0 < cutoff_x]
    if not rects:
        note = (
            "extract_drawing_bbox: no vector paths found left of the title-block cutoff "
            f"({cutoff_x:.0f}); falling back to the full drawing extent as the bbox "
            "(very low confidence)."
        )
        return full_bbox, note
    bbox = rects[0]
    for r in rects[1:]:
        bbox |= r
    note = (
        "extract_drawing_bbox: footprint approximated as the vector-drawing bounding box, "
        f"excluding vector paths starting past x={cutoff_x:.0f} (rightmost "
        f"{(1 - _TITLE_BLOCK_X_FRACTION) * 100:.0f}% of the {full_bbox.width:.0f}pt-wide drawing "
        "extent, i.e. the title-block strip). This is an envelope around notes/hatching/"
        "dimensions as well as the building outline, not a traced wall polygon -- treat as an "
        "upper-bound rectangle."
    )
    return bbox, note


def estimate_scale_pts_per_m(page: "fitz.Page", bbox: fitz.Rect) -> tuple[float | None, str]:
    """Estimate points-per-metre by matching the largest clean dimension string on the sheet
    to the longer axis of `bbox`.

    Returns (scale, note). scale is None if no clean dimension string was found at all -- callers
    must not fabricate a scale in that case.
    """
    text = page.get_text("text")
    values_m = _clean_dimension_values_m(text)
    if not values_m:
        return None, (
            "estimate_scale_pts_per_m: no cleanly-parseable feet-inch dimension string found on "
            "this sheet's text layer; scale could not be estimated. Geometry from this sheet is "
            "left in raw PDF points, not metres -- do not compare across sheets without a scale."
        )
    longest_axis_pts = max(bbox.width, bbox.height)
    max_dim_m = max(values_m)
    scale = longest_axis_pts / max_dim_m if max_dim_m > 0 else None
    note = (
        f"estimate_scale_pts_per_m: assumed the largest dimension string on the sheet "
        f"({max_dim_m:.2f} m) spans the longer axis of the drawing bbox ({longest_axis_pts:.0f} "
        f"pt) -> scale ~{scale:.1f} pt/m. Heuristic, not a scale bar; assumes uniform x/y scale "
        "and that the largest labelled dimension really is the building's overall extent."
    )
    return scale, note


# ---------------------------------------------------------------------------
# Room labels
# ---------------------------------------------------------------------------

_ROOM_LABEL_RE = re.compile(r"^[A-Z][A-Z /\-]{2,25}$")

# Outdoor/yard labels seen on these sheets that are not enclosed rooms per the Room schema --
# detected so they can be reported, not silently coerced into a Room.use value.
_NON_ROOM_LABELS = {"BACKYARD", "FRONTYARD", "GREEN", "PARKING HALL"}

# label keyword -> (Room.use, default WxH placeholder in metres) used when the labelled
# dimension string doesn't parse cleanly (fractional-inch glyph splitting, see module docstring).
_ROOM_USE_RULES: list[tuple[tuple[str, ...], str, tuple[float, float]]] = [
    (("MASTER", "MBR"), "bedroom", (4.0, 4.0)),
    (("BED",), "bedroom", (3.5, 3.5)),
    (("MAID",), "other", (2.5, 2.5)),
    (("TOILET", "WC", "BATH"), "wc", (2.0, 1.5)),
    (("KITCHEN",), "kitchen", (3.0, 2.5)),
    (("LIVING", "DRAWING", "LOUNGE", "FOYER"), "living", (4.0, 3.5)),
    (("DINING",), "other", (3.5, 3.0)),
    (("STORE", "STORAGE", "LAUNDRY", "UTILITY"), "store", (2.0, 2.0)),
    (("STAIR",), "stair", (2.5, 4.0)),
    (("GARAGE", "PARKING", "CARPORT"), "garage", (5.0, 3.0)),
    (("LIFT",), "other", (1.5, 1.5)),
    (("UGSR",), "other", (2.0, 2.0)),
]


def _classify_room_label(label: str) -> tuple[str, tuple[float, float]] | None:
    if label in _NON_ROOM_LABELS:
        return None
    for keywords, use, default_size in _ROOM_USE_RULES:
        if any(k in label for k in keywords):
            return use, default_size
    return None


def extract_rooms(
    page: "fitz.Page", scale_pts_per_m: float, origin: tuple[float, float]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Approximate rooms from this office's "LABEL" + "W' x H\"" text convention.

    Each room polygon is an axis-aligned rectangle anchored at the label's text position
    (top-left corner, in the sheet-local metre frame defined by `scale_pts_per_m`/`origin`) and
    sized either from a cleanly-parsed adjacent dimension string, or -- when that fails to parse
    (see module docstring) -- a fixed placeholder size for the room's `use` category. This is
    NOT wall tracing; positions are approximate and every room gets confidence "low" or "medium"
    accordingly, never "high".

    Returns (rooms, notes) where each room dict is:
        {"polygon": Ring, "use": str, "openings_area_sqm": 0.0, "confidence": "low"|"medium",
         "label": str, "size_source": "parsed"|"placeholder"}
    """
    lines = _flatten_lines(page)
    rooms: list[dict[str, Any]] = []
    placeholder_labels: list[str] = []
    skipped_non_room: list[str] = []

    for i, (text, rect) in enumerate(lines):
        label = text.strip()
        if not _ROOM_LABEL_RE.match(label):
            continue
        classification = _classify_room_label(label)
        if label in _NON_ROOM_LABELS:
            skipped_non_room.append(label)
            continue
        if classification is None:
            continue

        use, default_size = classification

        # Look at the next couple of lines for a "W' x H\"" style dimension string.
        lookahead = " ".join(t for t, _ in lines[i + 1 : i + 3])
        dims_m = _clean_dimension_values_m(lookahead)
        if len(dims_m) >= 2:
            w_m, h_m = dims_m[0], dims_m[1]
            confidence = "medium"
            size_source = "parsed"
        else:
            w_m, h_m = default_size
            confidence = "low"
            size_source = "placeholder"
            placeholder_labels.append(label)

        x0 = (rect.x0 - origin[0]) / scale_pts_per_m
        y0 = (rect.y0 - origin[1]) / scale_pts_per_m
        polygon = [
            [x0, y0],
            [x0 + w_m, y0],
            [x0 + w_m, y0 + h_m],
            [x0, y0 + h_m],
            [x0, y0],
        ]
        rooms.append(
            {
                "polygon": polygon,
                "use": use,
                "openings_area_sqm": 0.0,
                "confidence": confidence,
                "label": label,
                "size_source": size_source,
            }
        )

    notes = []
    if placeholder_labels:
        notes.append(
            "extract_rooms: used a placeholder default size (not the sheet's own dimension "
            f"text, which failed to parse cleanly) for rooms labelled: {placeholder_labels}. "
            "openings_area_sqm was not extracted for any room (set to 0.0) -- light/ventilation "
            "checks against these rooms will be unreliable until a real value is supplied."
        )
    if skipped_non_room:
        notes.append(
            "extract_rooms: skipped outdoor/yard labels not representable as an enclosed Room "
            f"per schema: {skipped_non_room}."
        )
    return rooms, notes


# ---------------------------------------------------------------------------
# Top-level per-sheet ingest
# ---------------------------------------------------------------------------


def ingest_plan_sheet(path: str | Path) -> dict[str, Any]:
    """Best-effort ingest of one vector-PDF architectural plan sheet.

    Returns:
        {
          "path": str,
          "page_rect": [w, h],
          "title_block": {...},           # see extract_title_block
          "scale_pts_per_m": float | None,
          "footprint": Ring | None,       # metres, sheet-local origin; None if no scale found
          "rooms": [...],                 # see extract_rooms; [] if no scale found
          "notes": [str, ...],            # fold verbatim into BuildingModel.assumptions
        }
    """
    path = Path(path)
    doc = fitz.open(str(path))
    page = doc[0]
    notes: list[str] = []

    raw_text = page.get_text("text")
    title_block = extract_title_block(raw_text)

    bbox, bbox_note = extract_drawing_bbox(page)
    notes.append(bbox_note)

    scale, scale_note = estimate_scale_pts_per_m(page, bbox)
    notes.append(scale_note)

    footprint = None
    rooms: list[dict[str, Any]] = []
    if scale:
        origin = (bbox.x0, bbox.y0)
        footprint = [
            [0.0, 0.0],
            [(bbox.x1 - bbox.x0) / scale, 0.0],
            [(bbox.x1 - bbox.x0) / scale, (bbox.y1 - bbox.y0) / scale],
            [0.0, (bbox.y1 - bbox.y0) / scale],
            [0.0, 0.0],
        ]
        rooms, room_notes = extract_rooms(page, scale, origin)
        notes.extend(room_notes)
    else:
        notes.append(
            "ingest_plan_sheet: skipped room extraction entirely -- no scale, so text-position "
            "-> metre conversion is undefined for this sheet."
        )

    result = {
        "path": str(path),
        "page_rect": [page.rect.width, page.rect.height],
        "title_block": title_block,
        "scale_pts_per_m": scale,
        "footprint": footprint,
        "rooms": rooms,
        "notes": notes,
    }
    doc.close()
    return result


# ---------------------------------------------------------------------------
# Elevation sheets: role sanity check + a heuristic storey-count cross-check
# ---------------------------------------------------------------------------


def sheet_title_matches_role(sheet_title: str | None, expected_keywords: tuple[str, ...]) -> bool:
    """True if `sheet_title` (from extract_title_block) plausibly matches the sheet role the
    case's meta.json declared for it (e.g. role "elevation_front" -> expected ("elevation",)).

    Used by semantics.py to catch a case's meta.json mis-mapping a sheet role (CLAUDE.md §10.1:
    "a section misread as a plan produces a catastrophically wrong model, and it's a one-click
    fix if you ask" -- automated here as a flag, since there is no interactive user to ask).
    Returns False (mismatch) both when the title contradicts the role AND when no title could be
    read at all -- callers should treat "no title" as "unverified", not "verified".
    """
    if not sheet_title:
        return False
    lowered = sheet_title.lower()
    return any(k in lowered for k in expected_keywords)


def estimate_storey_count_from_elevation(path: str | Path) -> tuple[int | None, str]:
    """Heuristic-only storey count from an elevation sheet, for cross-checking against the
    number of plan sheets (CLAUDE.md §10.1). This is NOT a substitute for a section sheet and
    is not used to set Floor.height_m anywhere (elevations are cross-check only, per CLAUDE.md).

    Method: cluster near-horizontal, long vector strokes (candidate floor/slab/roof lines) by
    y-position and count clusters, minus one (N slab lines ~ N-1 storeys). Very approximate --
    picks up any long horizontal stroke, not just structural lines -- so the result is only ever
    offered as a cross-check hint, never as ground truth. Returns (None, note) when the sheet
    doesn't look like an elevation at all (e.g. h02's "elevation_front.pdf", which title-block
    text shows is actually a joinery detail sheet) or the estimate is out of a sane range.
    """
    path = Path(path)
    doc = fitz.open(str(path))
    page = doc[0]
    drawings = page.get_drawings()
    if not drawings:
        doc.close()
        return None, f"estimate_storey_count_from_elevation({path.name}): no vector paths found."

    full_bbox = drawings[0]["rect"]
    for d in drawings[1:]:
        full_bbox |= d["rect"]

    long_axis = max(full_bbox.width, full_bbox.height)
    horizontal_ys: list[float] = []
    for d in drawings:
        r = d["rect"]
        is_long = max(r.width, r.height) > 0.5 * long_axis
        is_thin = min(r.width, r.height) < 0.01 * long_axis + 1
        if is_long and is_thin:
            horizontal_ys.append(round((r.y0 + r.y1) / 2, 0))
    doc.close()

    if not horizontal_ys:
        return None, (
            f"estimate_storey_count_from_elevation({path.name}): no long, thin (candidate "
            "slab/roof line) strokes found; cannot estimate."
        )

    horizontal_ys.sort()
    bucket_tol = long_axis * 0.01
    clusters: list[float] = []
    for y in horizontal_ys:
        if not clusters or y - clusters[-1] > bucket_tol:
            clusters.append(y)

    storeys = len(clusters) - 1
    if not (1 <= storeys <= 8):
        return None, (
            f"estimate_storey_count_from_elevation({path.name}): found {len(clusters)} candidate "
            f"horizontal lines -> {storeys} storeys, outside a sane 1-8 range; treating as "
            "inconclusive rather than trusting it."
        )
    return storeys, (
        f"estimate_storey_count_from_elevation({path.name}): {len(clusters)} candidate long "
        f"horizontal strokes clustered -> heuristic estimate of {storeys} storeys. This counts "
        "any long thin stroke (could include a plinth line, a coping line, a hatch boundary), "
        "not verified structural slab lines -- treat as a cross-check hint only, never as the "
        "source of Floor.height_m or an authoritative storey count."
    )


# ---------------------------------------------------------------------------
# Overall height from an elevation's own labeled dimension chain
# ---------------------------------------------------------------------------
#
# This is NOT the same thing as estimate_storey_count_from_elevation above (which counts
# arbitrary long strokes and stays a cross-check hint forever, per CLAUDE.md). This instead reads
# an *explicit, printed* overall-height dimension off the sheet -- the standard chain-dimension
# convention where a run of small segments (clear height, slab thickness, clear height, ...) is
# bracketed by a single larger "check" dimension spanning a contiguous subset of them. Verified
# against a real drawing (h01's rear elevation, confirmed correct by the project owner against
# the real building): a left-margin chain reads 9" / 7' / 9" / 10'-3" / 9" / 10'-3" / 9" /
# 10'-3" / 2'-3", and a separate "33'" label matches the sum of the middle six segments (9" +
# 10'-3" + 9" + 10'-3" + 9" + 10'-3" = 396" = 33'-0") exactly. That match is the signal: it means
# those six segments are "the building" and the 7'+9" above / 2'-3" below are something else
# (here: a sub-2.25m mumty/tank the bylaw's own height definition excludes, and a plinth-to-road
# offset that sits below where the height definition even starts measuring).
#
# This intentionally does NOT try to interpret the "lvl ±0" / "lvl +42" style callouts elsewhere
# on these sheets -- those turned out to recur at multiple different physical heights on the same
# elevation (almost certainly a per-floor local datum, not one building-wide reference), and
# guessing at that convention risked a confidently wrong number. The dimension chain + matching
# bracket approach here never guesses: if no bracket value matches a contiguous run of a chain to
# within half an inch, it returns None rather than picking the closest thing.

_DIM_FEET_INCH_EXACT_RE = re.compile(r"^(\d+)'-(\d+)\"$")
_DIM_FEET_ONLY_EXACT_RE = re.compile(r"^(\d+)'$")
_DIM_INCH_ONLY_EXACT_RE = re.compile(r"^(\d+)\"$")

_CHAIN_X_TOLERANCE_PT = 15
"""How close two dimension tokens' x-centers must be (in display-space points) to belong to the
same vertical dimension chain. Tuned against the ~28pt gap observed between h01's main chain
(x=620) and its bracket label (x=592) -- comfortably separates the two into different clusters."""

_BRACKET_MAX_INCH_TOLERANCE = 0.5
"""A bracket's value must match a contiguous run's sum to within this many inches to count as a
match -- whole-inch dimension strings only, no fractional-inch rounding slop expected."""


def _dimension_token_to_inches(text: str) -> float | None:
    """Exact-match version of the module's `_clean_dimension_values_m` -- this needs to classify
    one whole text run as a dimension-or-not, not scan for dimensions embedded in a larger
    string, so it anchors the whole token rather than searching within it."""
    text = text.strip()
    m = _DIM_FEET_INCH_EXACT_RE.match(text)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    m = _DIM_FEET_ONLY_EXACT_RE.match(text)
    if m:
        return int(m.group(1)) * 12
    m = _DIM_INCH_ONLY_EXACT_RE.match(text)
    if m:
        return int(m.group(1))
    return None


def _display_space_tokens(page: "fitz.Page") -> list[tuple[str, float, float, float]]:
    """(text, inches, center_x, center_y) for every text run on `page` that is a clean dimension
    token, in DISPLAY-space coordinates (i.e. matching what a human sees when the page is
    rendered the right way up) -- these sheets carry a /Rotate flag, and PyMuPDF's get_text()
    returns coordinates in the pre-rotation mediabox frame (see module docstring), so raw
    coordinates would silently mis-order "top" and "bottom". `~page.derotation_matrix` maps a
    raw-frame point into display space; empirically verified against known reference points
    (the two "ROAD lvl" labels on h01's rear elevation land at the bottom of the sheet, and the
    small rooftop mumty's labels land at the top, exactly matching the rendered image)."""
    inv = ~page.derotation_matrix
    tokens: list[tuple[str, float, float, float]] = []
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            inches = _dimension_token_to_inches(text)
            if inches is None:
                continue
            rect = fitz.Rect(spans[0]["bbox"])
            for s in spans[1:]:
                rect |= fitz.Rect(s["bbox"])
            p0 = fitz.Point(rect.x0, rect.y0) * inv
            p1 = fitz.Point(rect.x1, rect.y1) * inv
            cx, cy = (p0.x + p1.x) / 2, (p0.y + p1.y) / 2
            tokens.append((text, inches, cx, cy))
    return tokens


def extract_overall_height_m(path: str | Path) -> tuple[float | None, list[dict] | None, str]:
    """Find a vertical dimension chain plus a bracket dimension matching a contiguous run of it,
    per the module docstring above.

    Returns (height_m, matched_segments, note). `matched_segments` is the list of {"text",
    "inches"} dicts the bracket's contiguous run consisted of (in top-to-bottom sheet order) --
    callers that also know the floor count can use its length to attempt a per-floor breakdown;
    this function itself only produces one whole-building total. `height_m` is None (with `note`
    explaining why) whenever no bracket cleanly matches a contiguous run -- never a best guess.
    """
    path = Path(path)
    doc = fitz.open(str(path))
    page = doc[0]
    tokens = _display_space_tokens(page)
    doc.close()

    if not tokens:
        return None, None, f"extract_overall_height_m({path.name}): no clean dimension tokens found on this sheet."

    tokens_sorted = sorted(tokens, key=lambda t: t[2])
    clusters: list[list[tuple[str, float, float, float]]] = []
    for tok in tokens_sorted:
        for cluster in clusters:
            if abs(cluster[0][2] - tok[2]) < _CHAIN_X_TOLERANCE_PT:
                cluster.append(tok)
                break
        else:
            clusters.append([tok])

    chains = [sorted(c, key=lambda t: t[3]) for c in clusters if len(c) >= 3]
    if not chains:
        return None, None, (
            f"extract_overall_height_m({path.name}): no vertical dimension chain (3+ tokens "
            "sharing an x-position) found -- this sheet may not have a running dimension string, "
            "or its tokens didn't parse cleanly (e.g. fractional inches split across lines)."
        )

    # Collect every valid match across every chain/bracket-candidate pair, then take the LARGEST
    # one -- a bracket matching only a single segment is almost certainly a coincidental
    # duplicate value elsewhere on the sheet, not a genuine chain-dimension bracket (which by
    # convention spans multiple segments), so those are excluded outright rather than being
    # returned just because they were found first.
    MIN_SPAN = 2
    best: tuple[float, list, str] | None = None  # (value_in, included_tokens, label)

    for chain in chains:
        chain_ids = {id(t) for t in chain}
        chain_x = sum(t[2] for t in chain) / len(chain)
        bracket_candidates = [
            t for t in tokens
            if id(t) not in chain_ids and _CHAIN_X_TOLERANCE_PT <= abs(t[2] - chain_x) < 120
        ]
        for label, value_in, _bx, _by in bracket_candidates:
            for start in range(len(chain)):
                running = 0.0
                for end in range(start, len(chain)):
                    running += chain[end][1]
                    if running > value_in + _BRACKET_MAX_INCH_TOLERANCE:
                        break
                    if (
                        end - start + 1 >= MIN_SPAN
                        and abs(running - value_in) <= _BRACKET_MAX_INCH_TOLERANCE
                        and (best is None or value_in > best[0])
                    ):
                        best = (value_in, chain[start:end + 1], label)

    if best is None:
        return None, None, (
            f"extract_overall_height_m({path.name}): found a dimension chain but no separate "
            "bracket value matched the sum of any contiguous run of 2+ of its segments -- not "
            "guessing at which segments would represent the building height."
        )

    value_in, included, label = best
    note = (
        f"extract_overall_height_m({path.name}): bracket '{label}' ({value_in:.0f}in) matches "
        f"the sum of chain segments {[t[0] for t in included]} exactly -- treated as the "
        "plinth-to-parapet height. This is a real labeled dimension on the sheet, not a "
        "heuristic guess -- but it is still an ELEVATION, not a section; confirm on site if this "
        "matters for a compounding/appeal decision."
    )
    segments = [{"text": t[0], "inches": t[1]} for t in included]
    return value_in * 0.0254, segments, note
