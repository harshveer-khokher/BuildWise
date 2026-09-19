import { useEffect, useMemo, useState } from "react";
import { assembleCase, listJurisdictions, uploadModel } from "../api";
import { mergeSynthesizedPlot } from "../lib/geometry";
import { FIXTURES } from "../fixtures";
import PlotSizeInput from "./PlotSizeInput";
import SheetUploadGrid from "./SheetUploadGrid";
import SampleDrawingPicker from "./SampleDrawingPicker";

const EMPTY_SHEETS = {};

/** The whole intake workflow in one compact view: Location -> Plot information -> Building plan
 * upload -> "Check my plan". A separate, clearly-labeled sample-drawing shortcut sits alongside
 * it for a full-result demo path (design brief scope #1-3). */
export default function IntakeScreen({ onModelReady }) {
  const [jurisdictions, setJurisdictions] = useState(null);
  const [jurisdictionsError, setJurisdictionsError] = useState(null);
  const [jurisdictionId, setJurisdictionId] = useState(null);

  const [width, setWidth] = useState("");
  const [length, setLength] = useState("");
  const [unit, setUnit] = useState("m");

  const [sheets, setSheets] = useState(EMPTY_SHEETS);
  const [fileErrors, setFileErrors] = useState({});

  const [fixtureId, setFixtureId] = useState(FIXTURES[0].id);

  const [busy, setBusy] = useState(false);
  const [sampleBusy, setSampleBusy] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listJurisdictions()
      .then((list) => {
        if (cancelled) return;
        setJurisdictions(list);
        if (list.length > 0) setJurisdictionId(list[0].id);
      })
      .catch((err) => {
        if (!cancelled) setJurisdictionsError(String(err.message || err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const jurisdiction = jurisdictions?.find((j) => j.id === jurisdictionId) || null;
  const hasAnySheet = useMemo(() => Object.values(sheets).some(Boolean), [sheets]);
  const widthNum = Number(width);
  const lengthNum = Number(length);
  const plotSizeValid = width !== "" && length !== "" && widthNum > 0 && lengthNum > 0;

  function setSheet(role, file, errorMessage) {
    setSheets((prev) => {
      const next = { ...prev };
      if (file) next[role] = file;
      else delete next[role];
      return next;
    });
    setFileErrors((prev) => ({ ...prev, [role]: errorMessage }));
  }

  const validationMessages = [];
  if (jurisdictionsError) {
    validationMessages.push("Could not load the list of locations — check that the API is running.");
  } else if (!jurisdictionId) {
    validationMessages.push("Please select a location.");
  }
  if (!plotSizeValid) {
    validationMessages.push("Enter the plot width and length.");
  }
  if (!hasAnySheet) {
    validationMessages.push("Upload a building plan to continue.");
  }
  const hasBlockingFileError = Object.values(fileErrors).some(Boolean);

  const canSubmit = validationMessages.length === 0 && !hasBlockingFileError && !busy;

  async function handleSubmit() {
    if (!canSubmit) return;
    setBusy(true);
    setSubmitError(null);
    try {
      const model = await assembleCase(sheets, jurisdiction.authority);
      const merged = mergeSynthesizedPlot(model, width, length, unit);
      onModelReady(merged, "Your uploaded drawing");
    } catch (err) {
      setSubmitError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function handleLoadSample() {
    setSampleBusy(true);
    setSubmitError(null);
    try {
      const fixture = FIXTURES.find((f) => f.id === fixtureId);
      const model = await uploadModel(fixture.model);
      onModelReady(model, `Sample drawing — ${fixture.label}`);
    } catch (err) {
      setSubmitError(String(err.message || err));
    } finally {
      setSampleBusy(false);
    }
  }

  return (
    <section className="screen intake">
      <div className="intake-header">
        <p className="eyebrow">Pre-submission check</p>
        <h2>Check a building plan</h2>
        <p className="lede">
          Upload a drawing to see violations, ambiguities and verified fixes before it enters the
          GMADA/PUDA approval loop. This tool never says "approved" or "compliant" — the result is
          always framed as issues found, for you to read and act on.
        </p>
      </div>

      <ol className="intake-steps">
        <li className="intake-card">
          <div className="intake-card__head">
            <span className="intake-card__index">1</span>
            <h3>Location</h3>
          </div>
          {jurisdictionsError ? (
            <p className="error">{jurisdictionsError}</p>
          ) : (
            <label className="field">
              <span className="field-label">Jurisdiction</span>
              <select
                value={jurisdictionId || ""}
                onChange={(e) => setJurisdictionId(e.target.value)}
                disabled={!jurisdictions}
              >
                {!jurisdictions && <option>Loading…</option>}
                {jurisdictions?.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {jurisdiction && <p className="hint">{jurisdiction.source_note}</p>}
        </li>

        <li className="intake-card">
          <div className="intake-card__head">
            <span className="intake-card__index">2</span>
            <h3>Plot information</h3>
          </div>
          <PlotSizeInput
            width={width}
            length={length}
            unit={unit}
            onChange={(patch) => {
              if ("width" in patch) setWidth(patch.width);
              if ("length" in patch) setLength(patch.length);
              if ("unit" in patch) setUnit(patch.unit);
            }}
          />
        </li>

        <li className="intake-card">
          <div className="intake-card__head">
            <span className="intake-card__index">3</span>
            <h3>Building plan</h3>
          </div>
          <p className="hint">Accepted formats: .pdf, .dxf.</p>
          <SheetUploadGrid sheets={sheets} onSetSheet={setSheet} fileErrors={fileErrors} />
        </li>
      </ol>

      <div className="intake-submit">
        {validationMessages.length > 0 && (
          <ul className="validation-list">
            {validationMessages.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
        {submitError && <p className="error">{submitError}</p>}
        <button
          type="button"
          className="button button--primary"
          onClick={handleSubmit}
          disabled={!canSubmit}
          title={validationMessages.length > 0 ? validationMessages.join(" ") : undefined}
        >
          {busy ? "Checking…" : "Check my plan →"}
        </button>
      </div>

      <div className="intake-divider" role="separator">
        <span>or</span>
      </div>

      <SampleDrawingPicker
        fixtureId={fixtureId}
        onFixtureIdChange={setFixtureId}
        onLoad={handleLoadSample}
        busy={sampleBusy}
      />
    </section>
  );
}
