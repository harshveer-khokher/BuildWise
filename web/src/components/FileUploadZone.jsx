import { useId, useRef, useState } from "react";
import { hasAcceptedExtension } from "../lib/roles";

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Generic multi-file drawing upload: one drop zone / browse button, no per-role slots. Every
 * file goes to POST /cases/assemble under the repeated "files" field — the backend infers each
 * file's role from its own content, so the user never has to know which sheet is which
 * (see api.js's assembleCase). Pre-submission there is no role to show yet, so this is just a
 * plain staged file list with a remove control; the role each file was resolved to (or why it
 * wasn't) only exists after the API responds, and is rendered by the caller once that happens. */
export default function FileUploadZone({ files, onChange, disabled }) {
  const inputId = useId();
  const inputRef = useRef(null);
  const [dragActive, setDragActive] = useState(false);
  const [rejections, setRejections] = useState([]);

  function addFiles(fileList) {
    const incoming = Array.from(fileList || []);
    if (incoming.length === 0) return;

    const accepted = [];
    const rejected = [];
    for (const file of incoming) {
      if (!hasAcceptedExtension(file.name)) {
        rejected.push(`"${file.name}" is not a .pdf or .dxf file — not added.`);
        continue;
      }
      const isDuplicate = files.some(
        (f) => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified,
      );
      if (isDuplicate) continue;
      accepted.push(file);
    }
    setRejections(rejected);
    if (accepted.length > 0) onChange([...files, ...accepted]);
  }

  function handleRemove(index) {
    onChange(files.filter((_, i) => i !== index));
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragActive(false);
    if (disabled) return;
    addFiles(e.dataTransfer.files);
  }

  return (
    <div className="file-upload">
      <div
        className={`file-dropzone${dragActive ? " file-dropzone--active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
      >
        <span className="file-dropzone__icon" aria-hidden="true">
          ⇪
        </span>
        <p className="file-dropzone__text">Drag drawing files here, or</p>
        <label
          htmlFor={inputId}
          className={`button button--secondary${disabled ? " button--disabled" : ""}`}
        >
          Browse files
        </label>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          multiple
          accept=".pdf,.dxf"
          disabled={disabled}
          className="file-dropzone__input"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <p className="hint">Any number of files — ground/upper floor plans, section, elevations, site plan. Accepted formats: .pdf, .dxf.</p>
      </div>

      {rejections.length > 0 && (
        <ul className="validation-list">
          {rejections.map((r) => (
            <li key={r} className="error">
              {r}
            </li>
          ))}
        </ul>
      )}

      {files.length > 0 && (
        <ul className="file-list">
          {files.map((file, index) => (
            <li className="file-list__item" key={`${file.name}-${file.size}-${file.lastModified}`}>
              <span className="file-list__name">{file.name}</span>
              <span className="file-list__size">{formatFileSize(file.size)}</span>
              <button
                type="button"
                className="file-list__remove"
                onClick={() => handleRemove(index)}
                disabled={disabled}
                aria-label={`Remove ${file.name}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
