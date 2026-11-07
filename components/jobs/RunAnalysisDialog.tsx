"use client";

import { useState, type FormEvent } from "react";
import { Cloud, Cpu } from "lucide-react";
import { Dialog } from "@/components/shell/Dialog";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { api, messageOf } from "@/lib/api";
import { activeAnalysisJob, analysisSubmissionMessage, type AnalysisMode } from "@/lib/jobs";

/** Explicit opt-in for source sent to configured model endpoints. */
export function RunAnalysisDialog() {
  const ws = useWorkspace();
  const open = ws.dialog === "run";
  return (
    <Dialog open={open} onClose={ws.closeDialog} title="Run analysis" size="default">
      {open ? <RunForm key={`${ws.repoId}|${ws.environment}|${ws.runAnalysisMode}`} /> : null}
    </Dialog>
  );
}

function RunForm() {
  const ws = useWorkspace();
  const [mode, setMode] = useState<AnalysisMode>(ws.runAnalysisMode);
  const [useAiHierarchy, setUseAiHierarchy] = useState(ws.runAnalysisMode === "agent");
  const [useEmbeddings, setUseEmbeddings] = useState(false);
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const repo = ws.repo;
  const agentBlocked = (mode === "agent" || useEmbeddings || useAiHierarchy) && !consent;
  const activeJob = activeAnalysisJob(ws.jobList, repo?.id ?? null, ws.environment);
  const disabled = ws.scope !== "repo" || !repo || submitting || agentBlocked || !!activeJob;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!repo || disabled) return;
    setSubmitting(true);
    setError(null);
    try {
      const existing = new Set(ws.jobList.map((job) => job.id));
      const job = await api.createJob(repo.id, ws.environment, mode === "agent", useEmbeddings, useAiHierarchy);
      ws.toast("info", analysisSubmissionMessage(job, repo.name, mode, useEmbeddings, existing.has(job.id)));
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
            <span className="radio-text">Parses source locally using language adapters.</span>
          </span>
        </label>

        <label className="radio-card">
          <input
            type="radio"
            name="analysis-mode"
            value="agent"
            checked={mode === "agent"}
            onChange={() => { setMode("agent"); setUseAiHierarchy(true); }}
          />
          <span>
            <span className="radio-title">
              <Cloud className="icon" aria-hidden="true" /> AI harness
            </span>
            <span className="radio-text">
              Explores repository context and follows dependencies using the configured model and analysis budget.
            </span>
          </span>
        </label>
      </fieldset>

      <label className="radio-card">
        <input type="checkbox" checked={useEmbeddings} onChange={(event) => setUseEmbeddings(event.target.checked)} />
        <span>
          <span className="radio-title">Optional code embeddings</span>
          <span className="radio-text">Index source chunks for semantic search using the configured embedding endpoint.</span>
        </span>
      </label>

      <label className="radio-card"><input type="checkbox" checked={useAiHierarchy} onChange={(event) => setUseAiHierarchy(event.target.checked)} /><span><span className="radio-title">AI architecture grouping</span><span className="radio-text">Use the configured model to explain responsibilities and group components. Available with either extraction mode; source structure remains available.</span></span></label>

      {mode === "agent" || useEmbeddings || useAiHierarchy ? (
        <div className="consent" role="note">
          <strong>Source disclosure.</strong>
          <span>
            Source excerpts, code chunks, component summaries and selected code snippets from this repository are sent to the configured OpenAI-compatible endpoints while the job runs.
          </span>
          <label className="check-consent">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            <span>I agree to send source to the configured model endpoints.</span>
          </label>
        </div>
      ) : null}

      {ws.settings.data?.agent && (mode === "agent" || useAiHierarchy) ? <div className="note-line" aria-label="Selected workflow models">{mode === "agent" ? <p>Extraction: {ws.settings.data.agent.model} · {ws.settings.data.agent.reasoning_effort ?? "provider default"}</p> : null}{useAiHierarchy ? <p>Architecture: {ws.settings.data.agent.hierarchy_model ?? ws.settings.data.agent.model} · {ws.settings.data.agent.hierarchy_reasoning_effort ?? "provider default"}</p> : null}</div> : null}
      {activeJob ? <p className="note-line" role="status">{activeJob.use_agent ? "AI" : "Static"} analysis is already {activeJob.status} for this repository and environment.</p> : null}
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
          {submitting ? "Queuing…" : mode === "agent" ? "Run AI harness analysis" : useAiHierarchy ? "Run static + AI grouping" : "Run static analysis"}
        </button>
      </div>
    </form>
  );
}
