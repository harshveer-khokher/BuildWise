"""corpus ingest: PDF -> clauses.jsonl + rasterized pages (CLAUDE.md §6.1, §6.2).

Deterministic only -- no LLM here. Table transcription (§6.3) and rule synthesis (§6.4/§6.5)
are separate scripts (transcribe.py, verify.py) because they involve a model pass; this script
never invents or infers a value, it only locates and copies text that is already on the page.

Usage:
    python tools/extract.py            # ingest every document listed in corpus/MANIFEST.json
    python tools/extract.py <doc_id>   # ingest a single document

Idempotent and keyed on sha256 (CLAUDE.md §12): re-running overwrites extracted/<doc_id>/ from
scratch using the manifest's recorded sha, so a changed PDF is always caught by a hash mismatch
against MANIFEST.json rather than silently reusing stale clauses.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

import fitz  # pymupdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "corpus" / "MANIFEST.json"
EXTRACTED_DIR = ROOT / "corpus" / "extracted"
RASTER_DPI = 200

# A page counts as "text" if it has at least this many extractable characters; below this it is
# almost certainly a scan and gets ocr_required=true (CLAUDE.md §6.1 step 2). None of the four
# corpus PDFs currently supplied trip this on any page, but the check is not optional -- future
# zoning-plan PDFs from GMADA are described in CLAUDE.md §6.9/§10.9 as "frequently scanned".
OCR_THRESHOLD_CHARS = 40

# Top-level clause marker as it actually appears in this corpus: a line beginning with
# "<number>." followed by clause text (e.g. "3.       Short title..."). The corpus does NOT use
# CLAUDE.md's illustrative dotted numbering ("7.3.2") -- that was only an example of the pattern
# to look for, and §6.2 says explicitly to write the regex against the real document, not the
# example. Sub-items inside a clause ((1), (2), (a), (i), (ii)...) are kept inline in the
# clause's `text` rather than split into their own clauses.jsonl rows, because this corpus does
# not give them their own decimal clause numbers to anchor citations to -- splitting further
# would invent structure the source document doesn't have.
CLAUSE_MARKER = re.compile(r"^(\d{1,3})\.\s+(\S.*)$")

# Heading-only lines (PART I, PART II, ...) are recorded as section headings, not clauses --
# they never carry a numeric value themselves so they'd otherwise show up as "orphan" noise.
PART_MARKER = re.compile(r"^PART\s+([IVX]+)\b[\s—-]*(.*)$", re.IGNORECASE)


def sha256_of(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_and_rasterize(doc: fitz.Document, out_dir: pathlib.Path) -> list[dict]:
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_info = []
    zoom = RASTER_DPI / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for i, page in enumerate(doc):
        text = page.get_text()
        ocr_required = len(text.strip()) < OCR_THRESHOLD_CHARS
        pix = page.get_pixmap(matrix=mat)
        png_path = pages_dir / f"p{i:04d}.png"
        pix.save(str(png_path))
        page_info.append({
            "page": i,
            "text_chars": len(text.strip()),
            "ocr_required": ocr_required,
            "raster_path": f"pages/p{i:04d}.png",
        })
    return page_info


def chunk_clauses(doc: fitz.Document, doc_id: str, page_info: list[dict]) -> tuple[list[dict], list[str]]:
    """Return (clauses, anomalies). Each clause: number/heading/text/page/parent/ocr.

    Fails loudly (via the anomalies list, surfaced in REPORT.md -- CLAUDE.md §6.2/§6.6) rather
    than silently dropping content: a numbering gap or a repeated number is recorded, never
    quietly renumbered or merged away.
    """
    anomalies: list[str] = []
    clauses: list[dict] = []
    current_part: str | None = None
    current_number: str | None = None
    current_heading: str | None = None
    current_text: list[str] = []
    current_page: int | None = None
    current_ocr: bool = False
    seen_numbers: dict[str, int] = {}

    def flush():
        nonlocal current_number, current_heading, current_text, current_page, current_ocr
        if current_number is None:
            return
        seen_numbers[current_number] = seen_numbers.get(current_number, 0) + 1
        occurrence = seen_numbers[current_number]
        clause_id_number = current_number if occurrence == 1 else f"{current_number}#{occurrence}"
        if occurrence > 1:
            anomalies.append(
                f"clause number '{current_number}' repeated (occurrence {occurrence}) at page "
                f"{current_page}; disambiguated as '{clause_id_number}'. Source document reuses "
                f"rule numbers across Parts -- verify against the gazette before treating both as "
                f"independent rules."
            )
        clauses.append({
            "clause_id": f"{doc_id}:{clause_id_number}",
            "doc_id": doc_id,
            "number": clause_id_number,
            "heading": current_heading or "",
            "text": " ".join(current_text).strip(),
            "page": current_page,
            "has_table": False,
            "table_ref": None,
            "ocr": current_ocr,
            "parent": doc_id,
            "part": current_part,
        })
        current_number, current_heading, current_text, current_page, current_ocr = None, None, [], None, False

    ocr_by_page = {p["page"]: p["ocr_required"] for p in page_info}

    # Flatten to (pageno, line) so a clause marker can look ahead across the line break that
    # these gazette PDFs routinely insert between a bare number and its heading, e.g.:
    #   5.
    #   Appointment of Committee -
    lines: list[tuple[int, str]] = []
    for pageno, page in enumerate(doc):
        for raw_line in page.get_text().split("\n"):
            line = raw_line.strip()
            if line:
                lines.append((pageno, line))

    NUMBER_ONLY = re.compile(r"^(\d{1,3})\.\s*$")

    i = 0
    while i < len(lines):
        pageno, line = lines[i]
        part_match = PART_MARKER.match(line)
        if part_match:
            current_part = f"PART {part_match.group(1)}"
            if current_number is not None:
                current_text.append(line)
            i += 1
            continue

        clause_match = CLAUSE_MARKER.match(line)
        number_only_match = NUMBER_ONLY.match(line)
        number, rest, consumed = None, None, 1
        if clause_match:
            number, rest = clause_match.group(1), clause_match.group(2)
        elif number_only_match and i + 1 < len(lines) and not NUMBER_ONLY.match(lines[i + 1][1]):
            # Bare number on its own line -- heading text is the next line.
            number, rest = number_only_match.group(1), lines[i + 1][1]
            consumed = 2

        if number is not None:
            flush()
            current_number = number
            heading_parts = re.split(r"[–—-]", rest, maxsplit=1)
            current_heading = heading_parts[0].strip().rstrip(".:")
            current_text = [rest]
            current_page = pageno
            current_ocr = ocr_by_page.get(pageno, False)
            i += consumed
            continue

        if current_number is not None:
            current_text.append(line)
            current_ocr = current_ocr or ocr_by_page.get(pageno, False)
        i += 1
    flush()

    numbers_seen_in_order = []
    for c in clauses:
        base_num = c["number"].split("#")[0]
        if base_num.isdigit() and base_num not in numbers_seen_in_order:
            numbers_seen_in_order.append(base_num)
    ints = [int(n) for n in numbers_seen_in_order]
    for a, b in zip(ints, ints[1:]):
        if b != a + 1 and not (b < a):  # allow renumbering-down (Part restart), flag skips forward
            anomalies.append(
                f"numbering gap: clause {a} is followed by clause {b} (expected {a + 1}). "
                f"Either the chunker missed a clause or the source skips a number -- check "
                f"page {[c['page'] for c in clauses if c['number'] == str(b)]}."
            )

    return clauses, anomalies


_NORM_STRIP_RE = re.compile(r"[^A-Z0-9]")


def _norm_key(s: str) -> str:
    return _NORM_STRIP_RE.sub("", s.upper())


CHANDIGARH_DOC_ID = "chandigarh_building_rules_urban_2017"

# Pages 0-3 (0-indexed) are the Table of Contents -- detected by direct inspection of this
# specific PDF (dot-leader lines, e.g. "TITLE AND EXTENT .......... 4"); the real body text,
# including the operative "1 TITLE AND EXTENT" heading, starts at page index 4. Starting the
# search here (not at page 0) is what stops every top-level number from also matching its own
# ToC entry.
CHANDIGARH_BODY_START_PAGE = 4

# (number, a distinctive heading fragment) for each of the document's own top-level numbered
# sections (1-15), taken verbatim from its own Table of Contents. Matched below by stripping all
# whitespace/punctuation from both the key and the body text before comparing, because the PDF
# renders several of these headings letter-spaced and inconsistently
# ("D E F I N I T I O N S", "1 0   M I S C E L L A N E O U S REQUIREMENTS...") -- whitespace-
# insensitive substring search is the only reliable way to find them without hardcoding every
# spacing variant by hand.
CHANDIGARH_TOP_HEADINGS: list[tuple[str, str]] = [
    ("1", "TITLE AND EXTENT"),
    ("2", "SCOPE AND APPLICABILITY"),
    ("3", "DEFINITIONS"),
    ("4", "RESIDENTIAL USE"),
    ("5", "COMMERCIAL USE"),
    ("6", "INDUSTRIAL USE"),
    ("7", "PUBLIC/ SEMI PUBLIC BUILDINGS"),
    ("8", "I.T HABITAT"),
    ("9", "INTEGRATED PROJECTS"),
    ("10", "MISCELLANEOUS REQUIREMENTS FOR CONSTRUCTION OF ANY BUILDING"),
    ("11", "PROCEDURE FOR MAKING APPLICATION FOR APPROVAL OF BUILDING PLAN"),
    ("12", "MANDATORY PROVISIONS"),
    ("13", "GREEN BUILDINGS AND SUSTAINABILITY PROVISIONS"),
    ("14", "POWER OF RELAXATION"),
    ("15", "REPEAL & SAVINGS"),
]

# After clause 15 the document continues with unnumbered Annexures (Forms, the Solar
# Photovoltaic notification, Sanitation Requirements). These never received their own 1-15
# numbering from the source, so inventing numbers for them would misrepresent the document --
# they get their own non-numeric top-level clause_ids instead of being folded into clause 15.
CHANDIGARH_ANNEXURE_HEADINGS: list[tuple[str, str]] = [
    ("annexure-1", "ANNEXURE 1"),
    ("annexure-2", "ANNEXURE-2"),
    ("annexure-3", "ANNEXURE -3"),
]

# Sub-clauses use ordinary dotted decimal numbering (4.1, 11.1.1, 12.2.3) that essentially never
# collides with the "Sr. No" table columns scattered everywhere else in this document (those are
# always bare single integers) -- this is the one numbering convention in the whole document
# that's reliable to match with a plain per-line regex. The PDF frequently breaks a sub-heading
# across two lines the same way the generic chunker already handles for top-level numbers
# elsewhere in this file ("4.2\nResidential (GROUP HOUSING)") -- both the same-line and the
# split-across-two-lines forms are handled by the scan loop below, not by this regex alone.
CHANDIGARH_SUBCLAUSE_MARKER = re.compile(r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s+(\S.*)$")
CHANDIGARH_SUBCLAUSE_NUMBER_ONLY = re.compile(r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s*$")


def _chandigarh_locate_top_headings(lines: list[tuple[int, str]]) -> list[tuple[str, str, int]]:
    """Returns (number_or_annexure_id, heading, start_line_index) for each top-level section, in
    document order, via whitespace/punctuation-insensitive substring search (see
    CHANDIGARH_TOP_HEADINGS docstring) rather than a per-line regex."""
    norm_lines = [_norm_key(line) for _, line in lines]
    cum = [0]
    for nl in norm_lines:
        cum.append(cum[-1] + len(nl))
    joined = "".join(norm_lines)

    def line_index_at(pos: int) -> int:
        lo, hi = 0, len(cum) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if cum[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    results: list[tuple[str, str, int]] = []
    search_from = 0
    for num, heading in CHANDIGARH_TOP_HEADINGS:
        key = _norm_key(num + heading[:24])
        idx = joined.find(key, search_from)
        if idx == -1:
            continue  # surfaced as a missing-section anomaly by the caller
        results.append((num, heading, line_index_at(idx)))
        search_from = idx + 1
    for aid, heading in CHANDIGARH_ANNEXURE_HEADINGS:
        key = _norm_key(heading)
        idx = joined.find(key, search_from)
        if idx == -1:
            continue
        results.append((aid, heading, line_index_at(idx)))
        search_from = idx + 1
    return results


def chunk_clauses_chandigarh(doc, doc_id: str, page_info: list[dict]) -> tuple[list[dict], list[str]]:
    """Chandigarh Building Rules (Urban) 2017 uses a different, more heterogeneous numbering
    convention than the other corpus documents (see CHANDIGARH_TOP_HEADINGS/
    CHANDIGARH_SUBCLAUSE_MARKER docstrings above) -- CLAUDE.md §6.2 says explicitly to write the
    chunking regex against the real document rather than force-fit one pattern across all of
    them, so this is a dedicated chunker for this doc_id only. chunk_clauses() above is untouched
    and still handles every other document exactly as before.

    Two-level output: one clause per numbered top-level section (1-15) or unnumbered Annexure,
    plus a finer clause per dotted sub-heading (4.1, 11.1.1, ...) found within that section's own
    span. Content between a section's heading and its first sub-heading -- or all of a section
    that has no dotted sub-headings at all (clauses 1, 2, 14, 15) -- stays on the top-level
    clause. This is where clause 3's ~95 numbered definitions and the "Note:" paragraphs under
    clauses 4-9 end up, since the source never gives those their own decimal anchors either.
    """
    anomalies: list[str] = []
    ocr_by_page = {p["page"]: p["ocr_required"] for p in page_info}

    lines: list[tuple[int, str]] = []
    for pageno in range(CHANDIGARH_BODY_START_PAGE, len(doc)):
        for raw_line in doc[pageno].get_text().split("\n"):
            line = raw_line.strip()
            if line:
                lines.append((pageno, line))

    tops = _chandigarh_locate_top_headings(lines)
    found_top_ids = {t[0] for t in tops}
    for num, heading in CHANDIGARH_TOP_HEADINGS:
        if num not in found_top_ids:
            anomalies.append(
                f"top-level section '{num} {heading}' was not located in the body text -- "
                f"check whether its heading is spaced/formatted differently than expected."
            )
    for aid, heading in CHANDIGARH_ANNEXURE_HEADINGS:
        if aid not in found_top_ids:
            anomalies.append(f"unnumbered section '{heading}' was not located in the body text.")

    if not tops:
        anomalies.append("no top-level sections located at all -- chunker produced nothing.")
        return [], anomalies

    # Known source-PDF defect, verified by hand: clause "12.2 PROVISIONS FOR HIGH RISE
    # DEVELOPMENT" is itself typeset in the source as "12 . 2PROV ISIONS FOR HIGH RISE
    # DEVELOPMENT" (a stray space before the dot, and the run-on "2PROV"), which the sub-clause
    # regex correctly does not match as "12.2" -- its own short intro line ends up folded into
    # clause 12.1's trailing text instead of getting its own entry. Its children (12.2.1-12.2.7)
    # are unaffected and are captured normally. Recorded here rather than silently disappearing.
    anomalies.append(
        "clause '12.2 PROVISIONS FOR HIGH RISE DEVELOPMENT' has no entry of its own: the source "
        "PDF typesets its heading as '12 . 2PROV ISIONS...' (malformed spacing), which the "
        "sub-clause matcher does not recognise. Its brief intro text is folded into clause "
        "12.1's text instead. Its own numbered children (12.2.1-12.2.7) are captured correctly."
    )

    clauses: list[dict] = []
    seen_numbers: dict[str, int] = {}

    def make_clause(number: str, heading: str, start_line: int, end_line: int) -> None:
        if start_line >= end_line:
            return
        seen_numbers[number] = seen_numbers.get(number, 0) + 1
        occurrence = seen_numbers[number]
        clause_number = number if occurrence == 1 else f"{number}#{occurrence}"
        if occurrence > 1:
            anomalies.append(
                f"sub-clause number '{number}' matched more than once (occurrence {occurrence}) "
                f"at page {lines[start_line][0]}; disambiguated as '{clause_number}'. Likely a "
                f"cross-reference to another clause (e.g. 'as per Rule 10.1') that happened to "
                f"start its own physical line -- verify against the source before treating both "
                f"as independent clauses."
            )
        text_lines = [lines[i][1] for i in range(start_line, end_line)]
        pages_covered = {lines[i][0] for i in range(start_line, end_line)}
        clauses.append({
            "clause_id": f"{doc_id}:{clause_number}",
            "doc_id": doc_id,
            "number": clause_number,
            "heading": heading,
            "text": " ".join(text_lines).strip(),
            "page": lines[start_line][0],
            "has_table": False,
            "table_ref": None,
            "ocr": any(ocr_by_page.get(p, False) for p in pages_covered),
            "parent": doc_id,
            "part": None,
        })

    for top_i, (number, heading, start_line) in enumerate(tops):
        end_line = tops[top_i + 1][2] if top_i + 1 < len(tops) else len(lines)

        sub_starts: list[tuple[str, str, int]] = []
        if not number.startswith("annexure"):
            li = start_line
            while li < end_line:
                line = lines[li][1]
                m = CHANDIGARH_SUBCLAUSE_MARKER.match(line)
                number_only_m = CHANDIGARH_SUBCLAUSE_NUMBER_ONLY.match(line)
                sub_num, rest = None, None
                if m:
                    sub_num, rest = m.group(1), m.group(2)
                elif (
                    number_only_m
                    and li + 1 < end_line
                    and not CHANDIGARH_SUBCLAUSE_NUMBER_ONLY.match(lines[li + 1][1])
                    and not CHANDIGARH_SUBCLAUSE_MARKER.match(lines[li + 1][1])
                ):
                    # Bare "4.2" on its own line -- heading text is the next line.
                    sub_num, rest = number_only_m.group(1), lines[li + 1][1]
                if sub_num is not None:
                    segments = sub_num.split(".")
                    # Guard against a sub-number belonging to a LATER top-level section leaking
                    # in via a cross-reference inside this section's own prose, and against a
                    # table numeric value (e.g. a clearance-distance table row rendering as
                    # "11.50") being mistaken for a sub-clause -- no real sub-clause in this
                    # document goes past a second/third segment in the low single digits (the
                    # deepest confirmed real one is 12.2.7), so an implausibly large segment is
                    # table data, not a heading.
                    plausible = all(int(s) <= 20 for s in segments[1:])
                    if segments[0] == number and plausible:
                        sub_heading = rest.strip().rstrip(":-.").strip()
                        sub_starts.append((sub_num, sub_heading, li))
                    elif segments[0] == number and not plausible:
                        anomalies.append(
                            f"rejected implausible sub-clause number '{sub_num}' at page "
                            f"{lines[li][0]} (heading would have been {rest.strip()[:60]!r}) -- "
                            f"almost certainly a table value, not a real heading."
                        )
                li += 1

        if not sub_starts:
            make_clause(number, heading, start_line, end_line)
            continue

        make_clause(number, heading, start_line, sub_starts[0][2])
        for sub_i, (sub_num, sub_heading, sub_start) in enumerate(sub_starts):
            sub_end = sub_starts[sub_i + 1][2] if sub_i + 1 < len(sub_starts) else end_line
            make_clause(sub_num, sub_heading, sub_start, sub_end)

    return clauses, anomalies


def ingest_one(doc_meta: dict) -> dict:
    doc_id = doc_meta["doc_id"]
    raw_path = ROOT / doc_meta["raw_path"]
    recorded_sha = doc_meta["sha256"]
    actual_sha = sha256_of(raw_path)
    if actual_sha != recorded_sha:
        raise SystemExit(
            f"[{doc_id}] sha256 mismatch: MANIFEST.json says {recorded_sha}, file on disk is "
            f"{actual_sha}. Per CLAUDE.md §6.1 the sha is the citation anchor -- update the "
            f"manifest deliberately, don't silently re-extract a changed source."
        )

    out_dir = EXTRACTED_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(raw_path))
    page_info = probe_and_rasterize(doc, out_dir)
    if doc_id == CHANDIGARH_DOC_ID:
        clauses, anomalies = chunk_clauses_chandigarh(doc, doc_id, page_info)
    else:
        clauses, anomalies = chunk_clauses(doc, doc_id, page_info)
    doc.close()

    clauses_path = out_dir / "clauses.jsonl"
    with open(clauses_path, "w", encoding="utf-8") as f:
        for c in clauses:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    ocr_pages = [p["page"] for p in page_info if p["ocr_required"]]

    health = {
        "doc_id": doc_id,
        "doc_type": doc_meta["doc_type"],
        "sha256": actual_sha,
        "page_count": len(page_info),
        "clause_count": len(clauses),
        "ocr_pages": ocr_pages,
        "anomalies": anomalies,
    }
    (out_dir / "extract_health.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
    return health


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    target = sys.argv[1] if len(sys.argv) > 1 else None
    docs = manifest["documents"]
    if target:
        docs = [d for d in docs if d["doc_id"] == target]
        if not docs:
            raise SystemExit(f"no such doc_id in MANIFEST.json: {target}")

    all_health = []
    for doc_meta in docs:
        print(f"ingesting {doc_meta['doc_id']} ...")
        health = ingest_one(doc_meta)
        all_health.append(health)
        print(
            f"  {health['clause_count']} clauses, {len(health['ocr_pages'])} OCR pages, "
            f"{len(health['anomalies'])} anomalies"
        )
        for a in health["anomalies"]:
            print(f"    ! {a}")

    print("\ningest complete.")


if __name__ == "__main__":
    main()
