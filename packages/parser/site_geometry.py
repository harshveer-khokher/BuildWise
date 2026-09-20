"""Plot boundary, zoning envelope and per-edge setbacks, read off a plan sheet's own drawing.

This closes the gap that forced `plot_polygon`, `plot_area_sqm`, `zoned_area` and `edges` to stay
None/[] on every real case, which in turn forced containment, coverage, FAR and setback rules to
emit `status: unknown` instead of a real result (CLAUDE.md §5 -- correct behaviour given no data,
but the data turned out to be *in the drawings all along*).

Real Mohali submissions draw both boundaries directly on the floor-plan sheet, labelled and
colour-coded:

  * **PLOT LINE**  -- the plot boundary (magenta on the sheets seen so far)
  * **ZONING LINE** -- the buildable envelope the zoning plan permits (orange)

The labels are ordinary text; the boundaries are long runs of short dashes. What links them is
**stroke colour**: the label text is drawn in the same colour as the line it names. So this module
never hardcodes a colour — it reads the label, takes *that label's own colour*, and collects the
vector segments drawn in it. A different office using different colours works unchanged; an
office that doesn't label its lines at all yields nothing rather than a guess.

Scale comes out of the same geometry and is **cross-verified in two directions**: the plot
rectangle's pixel width and height are matched against dimension strings printed on the sheet, and
a scale is only accepted when a dimension exists for *both* axes and the two agree. That is a
genuine two-reading agreement in the sense CLAUDE.md §6.3 uses the term, not a heuristic — and it
replaces `estimate_scale_pts_per_m`'s "assume the largest dimension spans the longer axis" guess
for any sheet that carries a plot line.

Verified against `packages/cases/real/violation/GROUND FLOOR PLAN.pdf`: derived plot
27.54m x 15.52m = 427.5 sqm (511 sq yd, i.e. a standard 500 sq yd Mohali plot), front setback
3.98m and rear setback 5.97m -- against the *printed* 90', 51'-1½", 13' and 19'-6" on that sheet.

The building extent is recovered too, but only as an explicit **upper bound**. Tracing a faithful
footprint polygon out of PDF vector soup is not reliable -- walls are broken by every door and
window, and the obvious "thin and long" fill heuristics confidently select the floor hatching
instead. What does work is physical: walls are the shapes whose *modal* thickness converts, at the
already-verified scale, to a real masonry dimension (23cm for a 9" brick wall, 11cm for a 4.5"
half-brick partition). `footprint_hull` is then the convex hull of those shapes, which encloses
the real building rather than tracing it -- and also encloses any boundary wall standing on the
plot line.

That one-sidedness is the point, and the rules engine relies on it (see
`Floor.footprint_is_upper_bound` and `engine._soften_upper_bound_failures`): a check that PASSES
against a shape larger than the building passes against the building, while a check that FAILS may
be failing against something that isn't the house. So passes are kept as real results and failures
are downgraded to ambiguities needing confirmation. CLAUDE.md is explicit that a false positive
sends an architect redrawing for nothing and loses the account permanently, while a false negative
is merely the status quo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

FT_TO_M = 0.3048

# A label is only trusted as a colour source when it is drawn in a *chromatic* colour. These
# sheets also carry black and grey "plot line"/"zoning line" leader annotations that name the line
# without being drawn in its colour (h01 labels its plot line in plain grey), and an achromatic
# label identifies nothing -- grey and black are the two most common colours on any drawing, so
# following one would collect the entire sheet.
_ACHROMATIC_SPREAD = 24

# The label and the line it names are not always byte-identical: h02 labels its plot line
# #e600e6 but draws it #db00db, a colour-management shift introduced somewhere in that office's
# export. Colours within this per-channel distance of the label are treated as candidates for the
# same line, nearest first -- wide enough to absorb that drift, far too narrow to reach the
# orange zoning line from the magenta plot label.
_COLOUR_MATCH_TOL = 40

_PLOT_LABELS = ("plot line",)
_ZONING_LABELS = ("zoning line",)

# Feet-and-inches (5'-6") and foot-only (90'). pdf_ingest._clean_dimension_values_m handles only
# the first form; overall plot dimensions are routinely written in the second ("90'"), which is
# exactly the token needed here, so both are parsed.
_FEET_INCH_RE = re.compile(r"(\d+)'\s*-\s*(\d+)\"")
_FOOT_ONLY_RE = re.compile(r"(\d+)'(?!\s*-?\s*\d*\s*\")")

# A dash segment shorter than this is ignored as noise; a line is "axis aligned" when its off-axis
# extent is under _AXIS_TOL points.
_MIN_SEG_PT = 0.6
_AXIS_TOL_PT = 1.0
# Dashes belonging to one drawn line scatter by well under a point; 1pt bucketing merges them
# without merging two genuinely different lines (the closest real pair seen is ~280pt apart).
_LINE_BUCKET_PT = 1.0

# A zoning line is treated as bounding the whole envelope only when it spans most of the plot in
# its own direction. Shorter runs are real (they mark stepped pockets, e.g. a permitted rear
# outbuilding) but turning one into a full half-plane cut would wrongly shrink the envelope, so
# they are counted and surfaced instead of modelled.
_MAJOR_LINE_FRACTION = 0.70

# Two dimension readings are accepted as agreeing when within this relative tolerance. 3% absorbs
# the rounding in a printed "51'-1½"" against a plot drawn to the half-inch without being loose
# enough to match an unrelated dimension.
_SCALE_AGREEMENT_TOL = 0.03


# Masonry comes in standard thicknesses -- a 9" full brick wall and a 4.5" half-brick partition
# are what these plans are built from. Requiring the candidate's *modal* thickness to land in
# this band, measured through the already-verified scale, is what separates walls from floor
# hatching and furniture: an earlier attempt that scored candidates on "thin and long" alone
# confidently picked the floor tiling instead.
_WALL_THICKNESS_MIN_M = 0.08
_WALL_THICKNESS_MAX_M = 0.45
_WALL_THICKNESS_CONSISTENCY = 0.30
_WALL_MIN_SHAPES = 12
_WALL_MIN_ASPECT = 2.5
_WALL_MIN_LENGTH_PT = 15.0


@dataclass
class SiteGeometry:
    """Everything recoverable about the plot from one plan sheet. Every field is independently
    optional: a sheet with a plot line but no zoning line yields the plot and says so."""

    plot_polygon: list[list[float]] | None = None
    plot_area_sqm: float | None = None
    zoned_area: list[list[float]] | None = None
    zoned_area_sqm: float | None = None
    edges: list[dict[str, Any]] = field(default_factory=list)
    scale_pts_per_m: float | None = None
    unmodelled_zoning_steps: int = 0
    notes: list[str] = field(default_factory=list)

    # Building extent, derived from masonry geometry. `footprint_hull` is deliberately an
    # OVER-estimate (the convex hull of everything drawn as a wall inside the plot), which is
    # what makes it safe to check against: anything that fits inside the hull certainly fits
    # inside the real building outline, so a rule that PASSES against it genuinely passes, while
    # a rule that fails may be failing against a boundary wall rather than the house and must be
    # confirmed rather than reported as a settled violation.
    footprint_hull: list[list[float]] | None = None
    wall_thickness_m: float | None = None

    @property
    def usable(self) -> bool:
        return self.plot_polygon is not None


# ---------------------------------------------------------------------------
# colour <- label, geometry <- colour
# ---------------------------------------------------------------------------


def _channels(colour: int) -> tuple[int, int, int]:
    return (colour >> 16) & 0xFF, (colour >> 8) & 0xFF, colour & 0xFF


def _is_achromatic(colour: int) -> bool:
    r, g, b = _channels(colour)
    return max(r, g, b) - min(r, g, b) < _ACHROMATIC_SPREAD


def _colour_distance(a: int, b: int) -> int:
    return max(abs(x - y) for x, y in zip(_channels(a), _channels(b)))


def _label_colour(page: "fitz.Page", keywords: tuple[str, ...]) -> tuple[int | None, int]:
    """The dominant *chromatic* colour of any text span containing one of `keywords`.

    Returns (colour, n_labels_found). A sheet that names the line but only ever in black or grey
    gives (None, n) -- the label exists, its colour identifies nothing, and the caller reports
    that rather than falling back to a guessed colour.
    """
    counts: dict[int, int] = {}
    found = 0
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip().lower()
                if not any(k in text for k in keywords):
                    continue
                found += 1
                colour = span.get("color", 0)
                if not _is_achromatic(colour):
                    counts[colour] = counts.get(colour, 0) + 1
    if not counts:
        return None, found
    return max(counts, key=lambda c: counts[c]), found


def _rgb_int(colour_float: tuple[float, ...] | None) -> int | None:
    if colour_float is None:
        return None
    r, g, b = (int(round(v * 255)) for v in colour_float[:3])
    return (r << 16) | (g << 8) | b


def _nearby_stroke_colours(page: "fitz.Page", target: int) -> list[int]:
    """Stroke colours on this page within `_COLOUR_MATCH_TOL` of `target`, nearest first."""
    seen: set[int] = set()
    for path in page.get_drawings():
        colour = _rgb_int(path.get("color"))
        if colour is not None and not _is_achromatic(colour):
            seen.add(colour)
    near = [c for c in seen if _colour_distance(c, target) <= _COLOUR_MATCH_TOL]
    near.sort(key=lambda c: _colour_distance(c, target))
    return near


@dataclass
class _Line:
    """One reconstructed straight line: its position on the perpendicular axis, the extent it
    actually spans, and how much ink it is made of (dashes leave gaps, so span > ink)."""

    pos: float
    lo: float
    hi: float
    ink: float

    @property
    def span(self) -> float:
        return self.hi - self.lo


def _axis_lines(page: "fitz.Page", colour: int) -> tuple[list[_Line], list[_Line]]:
    """All horizontal and vertical lines drawn in `colour`, rebuilt from their dash segments."""
    h_buckets: dict[float, list[tuple[float, float]]] = {}
    v_buckets: dict[float, list[tuple[float, float]]] = {}

    for path in page.get_drawings():
        if _rgb_int(path.get("color")) != colour:
            continue
        for item in path["items"]:
            if item[0] == "l":
                (x0, y0), (x1, y1) = item[1], item[2]
            elif item[0] == "re":
                rect = item[1]
                x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
            else:
                continue
            dx, dy = abs(x1 - x0), abs(y1 - y0)
            if dy <= _AXIS_TOL_PT and dx > _MIN_SEG_PT:
                key = round((y0 + y1) / 2 / _LINE_BUCKET_PT) * _LINE_BUCKET_PT
                h_buckets.setdefault(key, []).append((min(x0, x1), max(x0, x1)))
            elif dx <= _AXIS_TOL_PT and dy > _MIN_SEG_PT:
                key = round((x0 + x1) / 2 / _LINE_BUCKET_PT) * _LINE_BUCKET_PT
                v_buckets.setdefault(key, []).append((min(y0, y1), max(y0, y1)))

    def collapse(buckets: dict[float, list[tuple[float, float]]]) -> list[_Line]:
        out = []
        for pos, segs in buckets.items():
            out.append(_Line(
                pos=pos,
                lo=min(s[0] for s in segs),
                hi=max(s[1] for s in segs),
                ink=sum(b - a for a, b in segs),
            ))
        out.sort(key=lambda ln: -ln.ink)
        return out

    return collapse(h_buckets), collapse(v_buckets)


def _plot_rect(h_lines: list[_Line], v_lines: list[_Line]) -> tuple[float, float, float, float] | None:
    """The plot rectangle: the two strongest horizontals and two strongest verticals.

    Requires exactly the shape a rectangle makes -- at least two of each, and the two of each
    pair carrying comparable ink (a plot boundary is drawn uniformly all the way round). Anything
    less returns None rather than a partial rectangle completed by assumption.
    """
    if len(h_lines) < 2 or len(v_lines) < 2:
        return None
    hs, vs = h_lines[:2], v_lines[:2]
    for pair in (hs, vs):
        weaker, stronger = sorted(ln.ink for ln in pair)
        if stronger <= 0 or weaker / stronger < 0.5:
            return None
    y0, y1 = sorted(ln.pos for ln in hs)
    x0, x1 = sorted(ln.pos for ln in vs)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return x0, y0, x1, y1


# ---------------------------------------------------------------------------
# scale
# ---------------------------------------------------------------------------


def _dimension_tokens(page: "fitz.Page") -> list[tuple[float, float, float]]:
    """Every parseable dimension on the sheet as (metres, centre_x, centre_y)."""
    tokens: list[tuple[float, float, float]] = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"]
                x0, y0, x1, y1 = span["bbox"]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                for feet_s, inches_s in _FEET_INCH_RE.findall(text):
                    if int(inches_s) < 12:  # a split fraction glyph can yield "101"
                        tokens.append(((int(feet_s) + int(inches_s) / 12.0) * FT_TO_M, cx, cy))
                for feet_s in _FOOT_ONLY_RE.findall(text):
                    tokens.append((int(feet_s) * FT_TO_M, cx, cy))
    return tokens


# An overall plot dimension is drawn just outside the plot, centred on the axis it measures (the
# "90'" on the violation sheet sits beside the plot, level with its mid-depth). Requiring that
# placement is what separates it from a room dimension that happens to share the plot's aspect
# ratio -- without it, an upper-floor sheet that never prints the overall size will "verify" a
# scale off two interior dimensions and report a 34 sqm plot with total confidence.
_SPAN_CENTRE_TOL = 0.20   # of the measured extent
_SPAN_OUTSIDE_TOL = 0.35  # of the perpendicular extent


def _spans_axis(
    token: tuple[float, float, float],
    rect: tuple[float, float, float, float],
    axis: str,
) -> bool:
    _v, cx, cy = token
    x0, y0, x1, y1 = rect
    width, height = x1 - x0, y1 - y0
    if axis == "y":
        centred = abs(cy - (y0 + y1) / 2) <= height * _SPAN_CENTRE_TOL
        alongside = (x0 - width * _SPAN_OUTSIDE_TOL) <= cx <= (x1 + width * _SPAN_OUTSIDE_TOL)
    else:
        centred = abs(cx - (x0 + x1) / 2) <= width * _SPAN_CENTRE_TOL
        alongside = (y0 - height * _SPAN_OUTSIDE_TOL) <= cy <= (y1 + height * _SPAN_OUTSIDE_TOL)
    return centred and alongside


def _verified_scale(
    rect: tuple[float, float, float, float], tokens: list[tuple[float, float, float]]
) -> tuple[float | None, str]:
    """Scale in points-per-metre, accepted only when dimensions printed on the sheet account for
    BOTH plot axes and the two agree.

    For each printed dimension, assume it labels one plot axis; that fixes a scale; then require
    a *different* printed dimension to match the other axis under that same scale. The pair whose
    two dimensions are largest wins -- overall plot dimensions are the biggest numbers on the
    sheet, while small ones (a 3'-0" door) produce absurd scales that coincidentally pair up.
    """
    if not tokens:
        return None, (
            "site_geometry: no scale accepted -- no parseable dimension strings on this sheet."
        )
    width_pt, height_pt = rect[2] - rect[0], rect[3] - rect[1]
    # Physical invariant: nothing drawn on a floor plan is longer than the plot it sits on, so a
    # scale implying a plot smaller than the largest dimension printed on the sheet is wrong by
    # construction.
    longest_printed = max(v for v, _, _ in tokens)

    candidates: list[tuple[float, float, float]] = []  # (sum of the two dims, scale, err)
    for token in tokens:
        value = token[0]
        if value < 3.0:
            continue
        for axis, span, other_axis, other in (
            ("y", height_pt, "x", width_pt),
            ("x", width_pt, "y", height_pt),
        ):
            if not _spans_axis(token, rect, axis):
                continue
            scale = span / value
            if max(width_pt, height_pt) / scale < longest_printed * 0.98:
                continue
            expected = other / scale
            best = None
            for other_token in tokens:
                other_value = other_token[0]
                if other_value < 3.0 or not _spans_axis(other_token, rect, other_axis):
                    continue
                err = abs(other_value - expected) / expected
                if err <= _SCALE_AGREEMENT_TOL and (best is None or err < best[1]):
                    best = (other_value, err)
            if best is not None:
                candidates.append((value + best[0], scale, best[1]))
    if not candidates:
        return None, (
            "site_geometry: no scale accepted -- this sheet does not print an overall dimension "
            "against both plot axes (each must be a dimension drawn alongside the plot and "
            "centred on the extent it measures), so no two-way agreement was possible. Plot "
            "geometry is not converted to metres on a one-sided guess."
        )
    candidates.sort(key=lambda c: (-c[0], c[2]))
    _, scale, err = candidates[0]
    return scale, (
        f"site_geometry: scale {scale:.2f} pt/m, verified in both directions -- printed "
        f"dimensions account for the plot's width and its depth and agree to within "
        f"{err * 100:.2f}%."
    )


# ---------------------------------------------------------------------------
# zoning envelope
# ---------------------------------------------------------------------------


def _zoned_rect(
    plot: tuple[float, float, float, float],
    h_lines: list[_Line],
    v_lines: list[_Line],
) -> tuple[tuple[float, float, float, float], int]:
    """Clip the plot rectangle by every zoning line that spans most of it.

    A zoning line that runs the full width/depth of the plot is a boundary of the buildable
    envelope, so it clips. Shorter runs mark stepped pockets and are counted, not applied --
    applying one as a full cut would shrink the envelope below what the zoning plan actually
    permits, which is how a false violation gets manufactured.

    An axis with no zoning line at all is left at the plot boundary, which is the correct reading:
    nothing was set back on that side.
    """
    px0, py0, px1, py1 = plot
    width, height = px1 - px0, py1 - py0
    x0, y0, x1, y1 = plot
    steps = 0

    for line in h_lines:
        if line.span >= width * _MAJOR_LINE_FRACTION:
            mid = (py0 + py1) / 2
            if py0 < line.pos < mid:
                y0 = max(y0, line.pos)
            elif mid <= line.pos < py1:
                y1 = min(y1, line.pos)
        elif line.ink > _MIN_SEG_PT * 4:
            steps += 1

    for line in v_lines:
        if line.span >= height * _MAJOR_LINE_FRACTION:
            mid = (px0 + px1) / 2
            if px0 < line.pos < mid:
                x0 = max(x0, line.pos)
            elif mid <= line.pos < px1:
                x1 = min(x1, line.pos)
        elif line.ink > _MIN_SEG_PT * 4:
            steps += 1

    return (x0, y0, x1, y1), steps


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def _wall_shapes(
    page: "fitz.Page", plot: tuple[float, float, float, float], scale: float
) -> tuple[list[tuple[float, float, float, float]], float | None]:
    """Shapes drawn as masonry inside the plot, plus the modal wall thickness in metres.

    Candidate colours are scored on whether their *modal* thickness is a real masonry dimension
    once converted through the verified scale. That is a physical check, not a shape heuristic:
    on the sheets seen so far it lands on 23cm (a 9" brick wall) and 11cm (a 4.5" half-brick
    partition), and nothing else on either sheet comes close to the band.
    """
    from collections import Counter

    px0, py0, px1, py1 = plot
    per_colour: dict[int, list[tuple[float, tuple[float, float, float, float]]]] = {}
    for path in page.get_drawings():
        for key in ("fill", "color"):
            colour = _rgb_int(path.get(key))
            if colour is None:
                continue
            rect = path["rect"]
            if rect.x0 < px0 - 2 or rect.y0 < py0 - 2 or rect.x1 > px1 + 2 or rect.y1 > py1 + 2:
                break
            width, height = rect.x1 - rect.x0, rect.y1 - rect.y0
            if width <= 0 or height <= 0:
                break
            thin, long_side = min(width, height), max(width, height)
            if long_side >= _WALL_MIN_ASPECT * thin and long_side > _WALL_MIN_LENGTH_PT:
                per_colour.setdefault(colour, []).append(
                    (thin, (rect.x0, rect.y0, rect.x1, rect.y1))
                )
            break

    best: tuple[int, float] | None = None
    for colour, items in per_colour.items():
        if len(items) < _WALL_MIN_SHAPES:
            continue
        modal_pt, modal_n = Counter(round(t) for t, _ in items).most_common(1)[0]
        # Classify on the whole-point mode (robust to sub-point jitter), but report the median of
        # the shapes in that mode -- rounding to whole points would otherwise publish a wall as
        # 24.4cm when it is drawn 22.9cm, and a reported number should be the measured one.
        matching = sorted(t for t, _ in items if round(t) == modal_pt)
        thickness_m = matching[len(matching) // 2] / scale
        if not (_WALL_THICKNESS_MIN_M <= thickness_m <= _WALL_THICKNESS_MAX_M):
            continue
        if modal_n / len(items) < _WALL_THICKNESS_CONSISTENCY:
            continue
        if best is None or len(items) > len(per_colour[best[0]]):
            best = (colour, thickness_m)

    if best is None:
        return [], None
    colour, thickness_m = best
    return [r for _, r in per_colour[colour]], thickness_m


def _ring(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def _to_metres(
    rect: tuple[float, float, float, float],
    origin: tuple[float, float],
    scale: float,
) -> list[list[float]]:
    """PDF points -> metres, anchored at the plot's own corner.

    Every polygon this module emits shares that anchor, so footprints, plot and zoned area all
    land in one frame and shapely comparisons between them are meaningful. PDF's y axis grows
    downward; it is flipped here so the result reads as an ordinary maths frame.
    """
    ox, oy = origin
    x0, y0, x1, y1 = rect
    return _ring(
        (x0 - ox) / scale, (oy - y1) / scale,
        (x1 - ox) / scale, (oy - y0) / scale,
    )


def _edges_from_rects(
    plot_m: list[list[float]],
    zoned_m: list[list[float]] | None,
    frontage_axis: str | None,
    built_setbacks: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """One Edge per plot side, each carrying the setback the zoning line leaves on that side."""
    xs = [p[0] for p in plot_m[:4]]
    ys = [p[1] for p in plot_m[:4]]
    px0, px1, py0, py1 = min(xs), max(xs), min(ys), max(ys)

    if zoned_m is not None:
        zxs = [p[0] for p in zoned_m[:4]]
        zys = [p[1] for p in zoned_m[:4]]
        zx0, zx1, zy0, zy1 = min(zxs), max(zxs), min(zys), max(zys)
    else:
        zx0 = zx1 = zy0 = zy1 = None

    sides = [
        ("bottom", [[px0, py0], [px1, py0]], None if zy0 is None else zy0 - py0, "horizontal"),
        ("top", [[px0, py1], [px1, py1]], None if zy1 is None else py1 - zy1, "horizontal"),
        ("left", [[px0, py0], [px0, py1]], None if zx0 is None else zx0 - px0, "vertical"),
        ("right", [[px1, py0], [px1, py1]], None if zx1 is None else px1 - zx1, "vertical"),
    ]

    notes: list[str] = []
    setbacks = {name: s for name, _, s, _ in sides}
    zero_edges = [n for n, s in setbacks.items() if s is not None and s < 0.05]
    open_edges = [n for n, s in setbacks.items() if s is not None and s >= 0.05]

    if frontage_axis is not None:
        road_parallel = "horizontal" if frontage_axis == "x" else "vertical"
        front_rear = [s[0] for s in sides if s[3] == road_parallel]
        flank = [s[0] for s in sides if s[3] != road_parallel]
        basis = "the frontage axis supplied by the caller"
    elif len(zero_edges) == 2 and len(open_edges) == 2:
        # The zoning line running flush with the plot boundary on exactly two opposite edges is
        # the signature of a side boundary: Mohali plotted development builds up to the side
        # lines and sets back only from the road and the rear. That is read off the geometry,
        # not assumed about the road.
        front_rear, flank = open_edges, zero_edges
        basis = "the two edges where the zoning line leaves no setback at all (side boundaries)"
    else:
        front_rear = flank = []
        basis = ""

    if not front_rear:
        roles = {name: "unknown" for name, _, _, _ in sides}
        notes.append(
            "site_geometry: plot edges were recovered but their roles are 'unknown' -- the "
            "zoning setbacks do not fall into the two-open/two-flush pattern that identifies "
            "which pair are the side boundaries, and nothing on this sheet says which way the "
            "road is. Setback rules keyed to a specific edge role stay unresolved rather than "
            "being answered against a guessed orientation."
        )
    else:
        front_rear = sorted(front_rear, key=lambda n: setbacks[n] if setbacks[n] is not None else 0)
        roles = {front_rear[0]: "front", front_rear[1]: "rear",
                 flank[0]: "side_a", flank[1]: "side_b"}
        notes.append(
            f"site_geometry: side boundaries identified from {basis}. Of the remaining pair, the "
            "edge with the SMALLER zoning setback was taken as the front and the larger as the "
            "rear -- that last step is a convention, not something this sheet states, so if the "
            "plot faces the other way the front and rear setback findings are swapped (the "
            "measured distances themselves are unaffected)."
        )

    built_setbacks = built_setbacks or {}
    edges = []
    for name, line, setback, _orient in sides:
        built = built_setbacks.get(name)
        edges.append({
            "line": line,
            "faces_road": roles[name] == "front",
            "road_width_m": None,
            "role": roles[name],
            "zoning_setback_m": None if setback is None else round(setback, 3),
            "built_setback_m": None if built is None else round(built, 3),
        })
    return edges, notes


def extract_site_geometry(
    pdf_path: str | Path,
    frontage_axis: str | None = None,
    scale_hint: float | None = None,
) -> SiteGeometry:
    """Read plot boundary, zoning envelope and per-edge setbacks off one plan sheet.

    `frontage_axis` ("x" or "y") says which plot axis runs along the road, if a caller has
    established it independently (e.g. from the front elevation's drawn width). Without it, edge
    roles stay "unknown" rather than being assigned by guesswork.

    Never raises on a sheet that simply doesn't carry these lines -- returns a SiteGeometry whose
    `usable` is False, with notes explaining exactly which signal was missing.
    """
    path = Path(pdf_path)
    result = SiteGeometry()
    try:
        doc = fitz.open(str(path))
        page = doc[0]
    except Exception as exc:
        result.notes.append(f"site_geometry: could not open {path.name}: {exc}")
        return result

    try:
        plot_colour, plot_labels = _label_colour(page, _PLOT_LABELS)
        if plot_colour is None:
            result.notes.append(
                f"site_geometry: [{path.name}] no coloured 'plot line' label found "
                f"({plot_labels} plain-black mention(s) seen) -- plot boundary not recovered, so "
                "plot area, coverage, FAR and setbacks stay unresolved for this sheet."
            )
            return result

        # The plot rectangle is only accepted when the sheet's own printed dimensions confirm
        # both of its axes. That doubles as the tie-break between near-identical colours (h02
        # draws extension lines in #ff00ff right next to the #db00db plot line): a rectangle the
        # dimensions don't corroborate is not a plot boundary, whatever colour it is drawn in.
        tokens = _dimension_tokens(page)
        rect = scale = None
        scale_note = ""
        tried: list[str] = []
        for candidate in _nearby_stroke_colours(page, plot_colour):
            cand_rect = _plot_rect(*_axis_lines(page, candidate))
            if cand_rect is None:
                tried.append(f"#{candidate:06x}: no rectangle")
                continue
            cand_scale, cand_note = _verified_scale(cand_rect, tokens)
            if cand_scale is None and scale_hint is not None:
                # Upper-floor sheets in a set carry the same plot line but rarely re-print the
                # overall dimensions, so they cannot verify a scale of their own. Given the scale
                # already verified from a sheet that does, the plot line becomes the shared datum
                # CLAUDE.md §10.1 asks for: every floor lands in one frame instead of each in its
                # own sheet-local one.
                cand_scale = scale_hint
                cand_note = (
                    f"site_geometry: scale {scale_hint:.2f} pt/m carried over from another sheet "
                    "in this set (this sheet prints no overall dimension of its own); its own "
                    "plot line is used as the shared datum."
                )
            if cand_scale is None:
                tried.append(f"#{candidate:06x}: rectangle not confirmed by printed dimensions")
                continue
            rect, scale, scale_note = cand_rect, cand_scale, cand_note
            if candidate != plot_colour:
                result.notes.append(
                    f"site_geometry: [{path.name}] the PLOT LINE label is drawn #{plot_colour:06x} "
                    f"but the line itself is #{candidate:06x} -- matched on colour proximity "
                    "(an export-side colour shift), then confirmed against the sheet's printed "
                    "dimensions before being accepted."
                )
            break

        if rect is None:
            detail = "; ".join(tried) if tried else "no line of that colour on the sheet"
            result.notes.append(
                f"site_geometry: [{path.name}] a 'plot line' label was found (colour "
                f"#{plot_colour:06x}) but no boundary could be confirmed from it ({detail}) -- "
                "not completing a partial boundary by assumption."
            )
            return result

        px0, py0, px1, py1 = rect
        width_pt, height_pt = px1 - px0, py1 - py0
        result.notes.append(f"[{path.name}] {scale_note}")
        result.scale_pts_per_m = scale

        origin = (px0, py1)  # bottom-left in maths orientation after the y flip
        result.plot_polygon = _to_metres(rect, origin, scale)
        result.plot_area_sqm = round((width_pt / scale) * (height_pt / scale), 2)
        result.notes.append(
            f"site_geometry: [{path.name}] plot boundary read from the sheet's own labelled "
            f"PLOT LINE: {height_pt / scale:.2f}m x {width_pt / scale:.2f}m = "
            f"{result.plot_area_sqm:.1f} sqm ({result.plot_area_sqm * 1.196:.0f} sq yd)."
        )

        zone_colour, zone_labels = _label_colour(page, _ZONING_LABELS)
        zoned_m = None
        if zone_colour is None:
            result.notes.append(
                f"site_geometry: [{path.name}] no coloured 'zoning line' label on this sheet "
                f"({zone_labels} plain-black mention(s)) -- the buildable envelope is not "
                "recoverable here, so containment stays unknown rather than defaulting to the "
                "plot boundary (which would wrongly permit building to the plot edge)."
            )
        else:
            # Same colour-proximity allowance as the plot line, for the same export-side reason.
            zone_h: list[_Line] = []
            zone_v: list[_Line] = []
            for candidate in _nearby_stroke_colours(page, zone_colour):
                cand_h, cand_v = _axis_lines(page, candidate)
                if cand_h or cand_v:
                    zone_h, zone_v = cand_h, cand_v
                    break
            zrect, steps = _zoned_rect(rect, zone_h, zone_v)
            result.unmodelled_zoning_steps = steps
            if zrect == rect:
                result.notes.append(
                    f"site_geometry: [{path.name}] 'zoning line' segments were found but none "
                    "spans enough of the plot to bound the envelope -- zoned area not derived."
                )
            else:
                zoned_m = _to_metres(zrect, origin, scale)
                result.zoned_area = zoned_m
                zw, zh = (zrect[2] - zrect[0]) / scale, (zrect[3] - zrect[1]) / scale
                result.zoned_area_sqm = round(zw * zh, 2)
                result.notes.append(
                    f"site_geometry: [{path.name}] buildable envelope read from the sheet's own "
                    f"labelled ZONING LINE: {zh:.2f}m x {zw:.2f}m = {result.zoned_area_sqm:.1f} "
                    f"sqm, i.e. {result.zoned_area_sqm / result.plot_area_sqm * 100:.1f}% of the "
                    "plot."
                )
                if steps:
                    result.notes.append(
                        f"site_geometry: [{path.name}] {steps} shorter zoning-line run(s) were "
                        "also found. These mark steps in the envelope (a permitted rear "
                        "outbuilding pocket, typically) and are NOT included in the rectangle "
                        "above, so the real permitted envelope is this size or larger, never "
                        "smaller. Treat a containment failure driven by this envelope as needing "
                        "confirmation against the zoning plan, not as a settled violation."
                    )

        # Building extent from masonry, in the same plot-anchored metre frame as everything else.
        wall_rects, thickness_m = _wall_shapes(page, rect, scale)
        built_setbacks: dict[str, float] = {}
        if wall_rects:
            from shapely.geometry import LineString, box
            from shapely.ops import unary_union

            wall_union = unary_union([box(*r) for r in wall_rects])
            result.wall_thickness_m = round(thickness_m, 3) if thickness_m else None
            hull = wall_union.convex_hull
            if hull.geom_type == "Polygon":
                ox, oy = origin
                result.footprint_hull = [
                    [(x - ox) / scale, (oy - y) / scale] for x, y in hull.exterior.coords
                ]
            for name, line in (
                ("bottom", [(px0, py1), (px1, py1)]),
                ("top", [(px0, py0), (px1, py0)]),
                ("left", [(px0, py0), (px0, py1)]),
                ("right", [(px1, py0), (px1, py1)]),
            ):
                built_setbacks[name] = LineString(line).distance(wall_union) / scale
            result.notes.append(
                f"site_geometry: [{path.name}] building extent taken from {len(wall_rects)} "
                f"masonry shape(s) whose modal thickness is {thickness_m * 100:.0f}cm -- a real "
                "wall dimension at this sheet's verified scale, which is what identifies them as "
                "walls rather than floor hatching. The extent is an UPPER BOUND: it is the "
                "convex hull of everything drawn as masonry inside the plot, so it also swallows "
                "any boundary/compound wall standing on the plot line. A rule that passes "
                "against it genuinely passes; a rule that fails against it must be confirmed "
                "against the drawing before being treated as a violation."
            )
        else:
            result.notes.append(
                f"site_geometry: [{path.name}] no masonry-thickness shape group found inside the "
                "plot -- building extent not derived, so setbacks and containment stay "
                "unresolved rather than being measured against a guessed outline."
            )

        edges, edge_notes = _edges_from_rects(
            result.plot_polygon, zoned_m, frontage_axis, built_setbacks
        )
        result.edges = edges
        result.notes.extend(f"site_geometry: [{path.name}] {n}" if not n.startswith("site_geometry")
                            else n for n in edge_notes)

        described = ", ".join(
            f"{e['role']}={e['zoning_setback_m']}m" for e in edges
            if e["zoning_setback_m"] is not None
        )
        if described:
            result.notes.append(
                f"site_geometry: [{path.name}] setbacks the zoning line leaves, per edge: "
                f"{described}."
            )
        return result
    finally:
        doc.close()
