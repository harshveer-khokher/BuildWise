"""Track C — Solver. Brute-force geometric repair search + non-geometric remedies.

Owned by Track C (CLAUDE.md §4, §9). Consumes the frozen schema
(packages/schema/building_model.py, packages/schema/findings.py) and a pluggable
rule-evaluation function -- it never hardcodes an import of packages.rules.engine
(see repair.py's module docstring for why).
"""

from .repair import RepairCandidate, search_repairs, solve
from .remedies import non_geometric_remedies_for_finding

__all__ = [
    "RepairCandidate",
    "search_repairs",
    "solve",
    "non_geometric_remedies_for_finding",
]
