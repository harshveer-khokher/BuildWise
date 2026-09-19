"""Track C — Ambiguity engine. CLAUDE.md §8: "this is the USP."

Ambiguity is a classified outcome, not "low confidence." classifier.py assigns one of the
seven fixed classes from CLAUDE.md §8 using legible, deterministic trigger logic (never an
LLM guess, per CLAUDE.md §1 rule 1). dossier.py turns a classified trigger into a
submission-ready dossier: both readings, which is safer, the exact document to carry as
proof, and a justification paragraph.
"""

from .classifier import AmbiguityTrigger, classify_all
from .dossier import Dossier, build_dossier

__all__ = [
    "AmbiguityTrigger",
    "classify_all",
    "Dossier",
    "build_dossier",
]
