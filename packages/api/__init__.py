"""Track D — Surface. FastAPI app + thin adapters to the other tracks' packages.

Owned by Track D (CLAUDE.md §4). This package must import cleanly even when
packages/parser, packages/rules, packages/solver and packages/ambiguity don't exist yet or are
mid-build — every adapter here tries the real import first and falls back to a fixture, per
CLAUDE.md's own Stage 1 design ("tracks B/C/D never need the parser").
"""
