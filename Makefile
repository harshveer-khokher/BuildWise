.PHONY: corpus stubs cases eval demo dev check

# PDF -> clauses.jsonl -> tables -> rule YAML -> verify -> REPORT.md (CLAUDE.md §6, §12).
# Idempotent and keyed on sha256: rerun freely, a changed source PDF is caught by extract.py's
# manifest hash check rather than silently re-extracted.
corpus:
	python tools/extract.py
	python tools/coverage.py

# Writes packages/cases/stubs/*.model.json. Run this first -- unblocks tracks B/C/D without
# needing any drawing at all (CLAUDE.md §10.2).
stubs:
	python packages/cases/gen_stub.py

# Regenerate mutations + truth files from packages/cases/real/ (CLAUDE.md §10.5). Owned by
# Track A; not implemented until Stage 1.
cases:
	python packages/cases/mutate.py

# Findings vs. truth, precision/recall, segmented by provenance (CLAUDE.md §10.3, §10.6).
eval:
	python -m pytest tests/test_eval.py -v

# End-to-end on the hero drawing (CLAUDE.md §14). Not wired until Stage 2/3.
demo:
	python -m packages.api.main --demo

# api + web
dev:
	python -m packages.api.main &
	cd web && npm run dev

# Every agent runs this before declaring done (CLAUDE.md §12).
check: eval
