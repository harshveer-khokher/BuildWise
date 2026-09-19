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
