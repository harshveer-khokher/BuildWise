"""Track A — Parser (CLAUDE.md §4).

dxf_ingest.py   -- DXF -> raw layer/entity geometry (no schema dependency)
pdf_ingest.py   -- vector-PDF sheet -> raw geometry + title-block text (no schema dependency)
semantics.py    -- multi-sheet assembly (CLAUDE.md §10.1): raw per-sheet geometry -> one
                   packages.schema.BuildingModel

Deliberately layered: dxf_ingest/pdf_ingest never import packages.schema, so they can be unit
tested and reused without pulling in the frozen contract. semantics.py is the only module in
this package that constructs BuildingModel/Floor/Room objects.
"""
