// Sheet-role vocabulary for the multi-file drawing upload (POST /cases/assemble).
//
// Field NAME = role, matching packages/parser/semantics.py's _PLAN_LEVELS / _SITE_ROLES /
// _SECTION_ROLE exactly (verified against that file, not guessed). Grouped for the upload UI
// per CLAUDE.md §10.1: a case is a sheet set, not one file — plan sheets carry footprints/rooms,
// the section carries height (available nowhere else), site/zoning carries the plot + buildable
// envelope, elevations are a storey-count cross-check only.

export const SHEET_GROUPS = [
  {
    id: "plans",
    label: "Floor plans",
    hint: "One slot per level. Each optional — supply whichever levels this building has.",
    roles: [
      { role: "basement", label: "Basement" },
      { role: "stilt", label: "Stilt" },
      { role: "ground", label: "Ground floor" },
      { role: "first", label: "First floor" },
      { role: "second", label: "Second floor" },
      { role: "third", label: "Third floor" },
      { role: "fourth", label: "Fourth floor" },
    ],
  },
  {
    id: "site",
    label: "Site / zoning plan",
    hint: "Plot boundary and, where traced, the zoned (buildable) area — needed for containment, coverage and FAR.",
    roles: [
      { role: "site", label: "Site plan" },
      { role: "zoning", label: "Zoning plan" },
    ],
  },
  {
    id: "section",
    label: "Section",
    hint: "The only sheet floor heights, total height and basement depth can be read from.",
    roles: [{ role: "section", label: "Section" }],
  },
  {
    id: "elevation",
    label: "Elevations",
    hint: "Cross-check only, for total height and storey count — never the primary height source.",
    roles: [
      { role: "elevation_front", label: "Front elevation" },
      { role: "elevation_rear", label: "Rear elevation" },
      { role: "elevation_side", label: "Side elevation" },
      { role: "elevation", label: "Elevation (single sheet)" },
    ],
  },
];

export const ACCEPTED_EXTENSIONS = [".pdf", ".dxf"];

export function hasAcceptedExtension(filename) {
  const lower = filename.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}
