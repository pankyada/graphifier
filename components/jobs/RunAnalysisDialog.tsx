"use client";

import { useState, type FormEvent } from "react";
import { Cloud, Cpu } from "lucide-react";
import { Dialog } from "@/components/shell/Dialog";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { api, messageOf } from "@/lib/api";
import type { AnalysisMode } from "@/lib/jobs";

/**
 * Explicit source disclosure before any job is queued. The Luna agent sends
 * bounded source excerpts off-device, so Run stays disabled until the user
 * ticks the consent box. Force re-index is intentionally absent: the backend
 * currently has no cache to bypass.
 */
export function RunAnalysisDialog() {
  const ws = useWorkspace();
  const open = ws.dialog === "run";
  return (
    <Dialog open={open} onClose={ws.closeDialog} title="Run analysis" size="default">
      {open ? <RunForm /> : null}
    </Dialog>
  );
}

function RunForm() {
  const ws = useWorkspace();
  const [mode, setMode] = useState<AnalysisMode>("static");
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const repo = ws.repo;
  const agentBlocked = mode === "agent" && !consent;
  const disabled = !repo || submitting || agentBlocked;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!repo || agentBlocked) return;
    setSubmitting(true);
    setError(null);
    try {
      const existing = new Set(ws.jobList.map((job) => job.id));
      const job = await api.createJob(repo.id, ws.environment, mode === "agent");
      if (existing.has(job.id)) {
        ws.toast("info", "A job is already queued or running for this repository and environment. Showing it instead.");
      } else {
        ws.toast("info", `Queued ${mode === "agent" ? "Luna agent" : "static"} analysis for ${repo.name}.`);
      }
      ws.jobs.reload();
      ws.closeDialog();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} aria-label="Run analysis form" className="stack">
      <p className="card-text" style={{ margin: 0 }}>
        Analysis of <strong>{repo?.name ?? "no repository"}</strong> in environment{" "}
        <span className="mono">{ws.environment}</span>. Files are read, never executed.
      </p>

      <fieldset className="radio-group">
        <legend className="label">Analysis mode</legend>

        <label className="radio-card">
          <input
            type="radio"
            name="analysis-mode"
            value="static"
            checked={mode === "static"}
            onChange={() => setMode("static")}
          />
          <span>
            <span className="radio-title">
              <Cpu className="icon" aria-hidden="true" /> Static analysis
              <span className="chip tag">default</span>
            </span>
            <span className="radio-text">Parses locally. No data leaves this device.</span>
          </span>
        </label>

        <label className="radio-card">
          <input
            type="radio"
            name="analysis-mode"
            value="agent"
            checked={mode === "agent"}
            onChange={() => setMode("agent")}
          />
          <span>
            <span className="radio-title">
              <Cloud className="icon" aria-hidden="true" /> Luna agent
            </span>
            <span className="radio-text">
              Adds agent-assisted extraction using the configured model. Local storage does not mean local inference.
            </span>
          </span>
        </label>
      </fieldset>

      {mode === "agent" ? (
        <div className="consent" role="note">
          <strong>Source disclosure.</strong>
          <span>
            Bounded source excerpts from this repository are sent to the configured OpenAI endpoint while the job
            runs. Nothing is sent for static analysis.
          </span>
          <label className="check-consent">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            <span>I understand source excerpts leave this device.</span>
          </label>
        </div>
      ) : null}

      <p className="hint" style={{ margin: 0 }}>
        If a job is already queued or running for this repository and environment, Graphifier returns that job rather
        than starting another.
      </p>

      {error ? (
        <p className="error-text" role="alert">
          {error}
        </p>
      ) : null}

      <div className="row-inline" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn" onClick={ws.closeDialog}>
          Cancel
        </button>
        <button type="submit" className="btn primary" disabled={disabled}>
          {submitting ? "Queuing…" : mode === "agent" ? "Run Luna agent analysis" : "Run static analysis"}
        </button>
      </div>
    </form>
  );
}
