import { SHEET_GROUPS, hasAcceptedExtension } from "../lib/roles";

/** Multi-file, role-tagged drawing upload — one slot per sheet role, matching POST
 * /cases/assemble's real field-name vocabulary exactly (CLAUDE.md §10.1: a building is a sheet
 * set, not one file). Every slot is individually optional; the intake screen requires at least
 * one filled slot overall. */
export default function SheetUploadGrid({ sheets, onSetSheet, fileErrors }) {
  function handleFile(role, fileList) {
    const file = fileList?.[0] || null;
    if (file && !hasAcceptedExtension(file.name)) {
      onSetSheet(role, null, `"${file.name}" is not a .pdf or .dxf file — not uploaded.`);
      return;
    }
    onSetSheet(role, file, null);
  }

  return (
    <div className="sheet-groups">
      {SHEET_GROUPS.map((group) => (
        <fieldset className="sheet-group" key={group.id}>
          <legend>{group.label}</legend>
          <p className="hint">{group.hint}</p>
          <div className="sheet-slots">
            {group.roles.map(({ role, label }) => {
              const file = sheets[role];
              const inputId = `sheet-${role}`;
              return (
                <div className={`sheet-slot${file ? " sheet-slot--filled" : ""}`} key={role}>
                  <label htmlFor={inputId} className="sheet-slot__label">
                    {label}
                  </label>
                  <div className="sheet-slot__control">
                    <input
                      id={inputId}
                      type="file"
                      accept=".pdf,.dxf"
                      onChange={(e) => handleFile(role, e.target.files)}
                    />
                    {file && (
                      <button
                        type="button"
                        className="sheet-slot__clear"
                        onClick={() => onSetSheet(role, null, null)}
                        aria-label={`Remove ${label}`}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  {file && <p className="sheet-slot__filename">{file.name}</p>}
                  {fileErrors[role] && <p className="error">{fileErrors[role]}</p>}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
