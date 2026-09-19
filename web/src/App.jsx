import { useEffect, useState } from "react";
import "./App.css";
import IntakeScreen from "./components/IntakeScreen";
import ConfirmScreen from "./components/ConfirmScreen";
import LoadingScreen from "./components/LoadingScreen";
import ResultsScreen from "./components/ResultsScreen";
import { runChecks, fetchOverlay, fetchReportMarkdown } from "./api";

const STEPS = ["Upload", "Confirm", "Results"];

function needsConfirmation(model) {
  return model.floors.some((floor) => floor.rooms.some((room) => room.confidence !== "high"));
}

function currentStepIndex(step) {
  if (step === "intake") return 0;
  if (step === "confirm") return 1;
  return 2; // loading, results, error all read as "on the way to / at" Results
}

export default function App() {
  const [step, setStep] = useState("intake"); // intake | confirm | loading | results | error
  const [model, setModel] = useState(null);
  const [caseLabel, setCaseLabel] = useState("");
  const [checksResult, setChecksResult] = useState(null);
  const [reportMarkdown, setReportMarkdown] = useState(null);
  const [overlay, setOverlay] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const [retryToken, setRetryToken] = useState(0);

  function handleModelReady(loadedModel, label) {
    setModel(loadedModel);
    setCaseLabel(label);
    setStep(needsConfirmation(loadedModel) ? "confirm" : "loading");
  }

  function handleConfirmed(confirmedModel) {
    setModel(confirmedModel);
    setStep("loading");
  }

  function restart() {
    setModel(null);
    setCaseLabel("");
    setChecksResult(null);
    setReportMarkdown(null);
    setOverlay(null);
    setErrorMessage(null);
    setStep("intake");
  }

  useEffect(() => {
    if (step !== "loading" || !model) return;
    let cancelled = false;

    async function run() {
      try {
        const result = await runChecks(model);
        if (cancelled) return;
        setChecksResult(result);

        // Both are best-effort extras: a report fetch failure is fatal to this screen's core
        // purpose (the report is a required deliverable), but the overlay is a nice-to-have —
        // its failure should not block the findings the user actually asked for.
        const markdown = await fetchReportMarkdown(model, result.findings);
        if (cancelled) return;
        setReportMarkdown(markdown);

        try {
          const overlayResult = await fetchOverlay(model, result.findings);
          if (!cancelled) setOverlay(overlayResult);
        } catch {
          if (!cancelled) setOverlay(null);
        }

        if (!cancelled) setStep("results");
      } catch (err) {
        if (!cancelled) {
          setErrorMessage(String(err.message || err));
          setStep("error");
        }
      }
    }

    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, model, retryToken]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ▦
          </span>
          <span className="brand-name">BuildWise</span>
        </div>
        <p className="brand-tagline">Build with confidence.</p>
        {step !== "results" && (
          <nav className="steps" aria-label="Progress">
            {STEPS.map((label, i) => (
              <span key={label} className={i === currentStepIndex(step) ? "step step--active" : "step"}>
                {i + 1}. {label}
              </span>
            ))}
          </nav>
        )}
      </header>

      <main className="app-main">
        {step === "intake" && <IntakeScreen onModelReady={handleModelReady} />}
        {step === "confirm" && model && (
          <ConfirmScreen model={model} onConfirmed={handleConfirmed} onCancel={restart} />
        )}
        {step === "loading" && <LoadingScreen />}
        {step === "error" && (
          <section className="screen">
            <div className="screen-header">
              <p className="eyebrow">Something went wrong</p>
              <h2>The check could not be completed</h2>
            </div>
            <p className="error">{errorMessage}</p>
            <div className="actions">
              <button
                type="button"
                className="button button--primary"
                onClick={() => {
                  setErrorMessage(null);
                  setStep("loading");
                  setRetryToken((t) => t + 1);
                }}
              >
                Try again
              </button>
              <button type="button" className="button button--ghost" onClick={restart}>
                Start over
              </button>
            </div>
          </section>
        )}
        {step === "results" && model && checksResult && (
          <ResultsScreen
            model={model}
            caseLabel={caseLabel}
            checksResult={checksResult}
            reportMarkdown={reportMarkdown}
            overlay={overlay}
            onRestart={restart}
          />
        )}
      </main>

      <footer className="app-footer">
        <p>
          BuildWise performs a pre-submission check only. It is not an approval, not a sanction,
          and not a certificate of compliance by GMADA, PUDA, or any authority.
        </p>
      </footer>
    </div>
  );
}
