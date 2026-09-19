import { useState } from "react";
import "./App.css";
import UploadScreen from "./components/UploadScreen";
import ConfirmScreen from "./components/ConfirmScreen";
import FindingsScreen from "./components/FindingsScreen";

/** mohali-check web app (Track D, CLAUDE.md §11 Stage 1).
 *
 * Three-step flow proving the API contract end-to-end from a browser:
 *   upload/select a BuildingModel -> confirm low-confidence rooms -> findings + overlay + report.
 * No component library, no state manager — plain fetch() calls (see src/api.js) against
 * packages/api/main.py.
 */
export default function App() {
  const [step, setStep] = useState("upload"); // "upload" | "confirm" | "findings"
  const [model, setModel] = useState(null);
  const [caseLabel, setCaseLabel] = useState("");

  function handleModelLoaded(loadedModel, label) {
    setModel(loadedModel);
    setCaseLabel(label);
    setStep("confirm");
  }

  function handleConfirmed(confirmedModel) {
    setModel(confirmedModel);
    setStep("findings");
  }

  function restart() {
    setModel(null);
    setCaseLabel("");
    setStep("upload");
  }

  return (
    <div className="app-shell">
      <header>
        <h1>mohali-check</h1>
        <p className="hint">
          Pre-submission compliance checker for Greater Mohali building drawings. Not a GMADA/PUDA
          approval or sanction — see the report footer.
        </p>
        <nav className="steps">
          <span className={step === "upload" ? "step active" : "step"}>1. Upload</span>
          <span className={step === "confirm" ? "step active" : "step"}>2. Confirm</span>
          <span className={step === "findings" ? "step active" : "step"}>3. Findings</span>
        </nav>
      </header>

      <main>
        {step === "upload" && <UploadScreen onModelLoaded={handleModelLoaded} />}
        {step === "confirm" && model && (
          <ConfirmScreen model={model} onConfirmed={handleConfirmed} />
        )}
        {step === "findings" && model && (
          <FindingsScreen model={model} caseLabel={caseLabel} onRestart={restart} />
        )}
      </main>
    </div>
  );
}
