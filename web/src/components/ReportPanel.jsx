import { useState } from "react";
import { marked } from "marked";
import { downloadReportPdf, reportHtmlUrl } from "../api";

/** Report preview + download. Renders the exact Markdown text the backend returned (never
 * regenerated or altered client-side) and offers a real download of that same text. */
export default function ReportPanel({ markdown, model, findings }) {
  const [busyHtml, setBusyHtml] = useState(false);
  const [busyPdf, setBusyPdf] = useState(false);
  const [secondaryError, setSecondaryError] = useState(null);

  function downloadMarkdown() {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "buildwise-report.md";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function openHtml() {
    setBusyHtml(true);
    setSecondaryError(null);
    try {
      const url = await reportHtmlUrl(model, findings);
      window.open(url, "_blank", "noreferrer");
    } catch (err) {
      setSecondaryError(String(err.message || err));
    } finally {
      setBusyHtml(false);
    }
  }

  async function downloadPdf() {
    setBusyPdf(true);
    setSecondaryError(null);
    try {
      await downloadReportPdf(model, findings);
    } catch (err) {
      setSecondaryError(String(err.message || err));
    } finally {
      setBusyPdf(false);
    }
  }

  const html = marked.parse(markdown, { headerIds: false, mangle: false });

  return (
    <div className="report-panel">
      <div className="report-panel__actions">
        <button type="button" className="button button--primary" onClick={downloadMarkdown}>
          Download .md
        </button>
        <button type="button" className="button button--ghost" onClick={openHtml} disabled={busyHtml}>
          {busyHtml ? "Opening…" : "Preview HTML"}
        </button>
        <button type="button" className="button button--ghost" onClick={downloadPdf} disabled={busyPdf}>
          {busyPdf ? "Preparing…" : "Download PDF"}
        </button>
      </div>
      {secondaryError && <p className="error">{secondaryError}</p>}
      <div className="report-preview" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
