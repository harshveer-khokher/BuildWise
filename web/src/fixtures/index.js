// Local copies of packages/cases/stubs/*.model.json (Track A/Stage-0 fixtures) so the upload
// screen has something to select without requiring a real drawing yet (CLAUDE.md §10.2).
// These are copies, not a dependency on packages/cases/ at build time — Track D does not import
// across the package boundary (CLAUDE.md §4).
import s01 from "./s01_clean_250.model.json";
import s02 from "./s02_setback_rear.model.json";
import s03 from "./s03_far_over.model.json";
import s04 from "./s04_stilt4_500.model.json";
import s05 from "./s05_no_zoning.model.json";
import s06 from "./s06_low_conf.model.json";

export const FIXTURES = [
  { id: "s01_clean_250", label: "s01 — clean baseline (250 sq yd)", model: s01 },
  { id: "s02_setback_rear", label: "s02 — rear setback violation", model: s02 },
  { id: "s03_far_over", label: "s03 — FAR exceeded", model: s03 },
  { id: "s04_stilt4_500", label: "s04 — stilt+4 FAR ambiguity", model: s04 },
  { id: "s05_no_zoning", label: "s05 — missing zoning plan (containment = unknown)", model: s05 },
  { id: "s06_low_conf", label: "s06 — low-confidence room labels", model: s06 },
];
