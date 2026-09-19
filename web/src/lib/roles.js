// Sheet-role vocabulary for the multi-file drawing upload (POST /cases/assemble).
//
// The upload UI no longer asks the user to declare a role per file — every file goes in under
// the repeated "files" field and the backend infers the role itself from the file's own content
// (packages/api/role_inference.py reads the PDF title block; DXF falls back to filename, lower
// trust). This module now only carries the label vocabulary needed to translate the raw role
// string the backend returns (e.g. "ground", "elevation_front") into something a person reads
// comfortably (e.g. "Ground floor plan"), plus the shared accepted-extension check used both to
// filter the file picker and to reject drops client-side before they ever reach the network.

export const ROLE_LABELS = {
  basement: "Basement plan",
  stilt: "Stilt plan",
  ground: "Ground floor plan",
  first: "First floor plan",
  second: "Second floor plan",
  third: "Third floor plan",
  fourth: "Fourth floor plan",
  site: "Site plan",
  zoning: "Zoning plan",
  section: "Section",
  elevation: "Elevation",
  elevation_front: "Front elevation",
  elevation_rear: "Rear elevation",
  elevation_side: "Side elevation",
};

/** Translates a raw role key returned by /cases/assemble into a friendly label. Elevation roles
 * can arrive auto-numbered on collision (e.g. "elevation_2", CLAUDE.md-adjacent
 * packages/api/role_inference.py's assign_roles) — those fall back to a humanized version of the
 * key rather than an unlabeled raw string. */
export function roleLabel(role) {
  if (ROLE_LABELS[role]) return ROLE_LABELS[role];
  const base = role.replace(/_\d+$/, "");
  const suffix = role.match(/_(\d+)$/);
  const baseLabel = ROLE_LABELS[base];
  if (baseLabel && suffix) return `${baseLabel} (${suffix[1]})`;
  return role
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export const ACCEPTED_EXTENSIONS = [".pdf", ".dxf"];

export function hasAcceptedExtension(filename) {
  const lower = filename.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}
