"""Sheet reference encoding.

meta.json's `sheets` dict maps role -> plain filename in the common case (one uploaded file is
one sheet). But a single DWG/DXF file commonly holds a whole sheet set as separate named
paperspace layout tabs (see dxf_ingest.list_layout_names) -- "GROUND FLOOR PLAN",
"ELEVATION FRONT", etc. -- rather than as separate uploaded files. To let one physical file back
several roles without changing every existing meta.json / test fixture's `sheets` value from a
bare string to a nested object, a layout reference is encoded as "filename#layout=NAME" here.

A plain filename with no marker decodes to (filename, None) -- "use this file's modelspace",
identical to today's behaviour.
"""

from __future__ import annotations

_LAYOUT_MARKER = "#layout="


def encode(filename: str, layout: str | None) -> str:
    if layout is None:
        return filename
    return f"{filename}{_LAYOUT_MARKER}{layout}"


def decode(ref: str) -> tuple[str, str | None]:
    if _LAYOUT_MARKER in ref:
        filename, layout = ref.split(_LAYOUT_MARKER, 1)
        return filename, layout
    return ref, None
