"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Cloud, Cpu, RefreshCw } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { api } from "@/lib/api";
import { activeAnalysisJob, analysisSubmissionMessage } from "@/lib/jobs";

export function ReanalyseMenu() {
  const ws = useWorkspace();
  const container = useRef<HTMLDetailsElement>(null);
  const [submitting, setSubmitting] = useState(false);
  const activeJob = activeAnalysisJob(ws.jobList, ws.repoId, ws.environment);
  const unavailable = ws.scope !== "repo" || !ws.repo;
  const disabled = unavailable || submitting || !!activeJob;

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (container.current && !container.current.contains(event.target as Node)) container.current.open = false;
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);

  function close() {
    if (container.current) container.current.open = false;
  }

  async function runStatic() {
    if (!ws.repo || disabled) return;
    const repo = ws.repo;
    const environment = ws.environment;
    const knownJobs = new Set(ws.jobList.map((job) => job.id));
    setSubmitting(true);
    close();
    try {
      const job = await api.createJob(repo.id, environment, false);
      ws.toast("info", analysisSubmissionMessage(job, repo.name, "static", false, knownJobs.has(job.id)));
      ws.jobs.reload();
    } catch (error) {
      ws.fail("Analysis could not start", error);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <details
      ref={container}
      className="analysis-menu"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          close();
          container.current?.querySelector("summary")?.focus();
          event.stopPropagation();
        }
      }}
    >
      <summary className="btn primary small" aria-label="Re-analyse selected repository">
        <RefreshCw className={`icon${submitting ? " spin" : ""}`} aria-hidden="true" />
        {submitting ? "Queuing…" : "Re-analyse"}
        <ChevronDown className="icon" aria-hidden="true" />
      </summary>
      <div className="analysis-options stack" role="group" aria-label="Re-analysis options">
        <div>
          <strong>{unavailable ? "Select one repository" : ws.repo?.name}</strong>
          <div className="hint">Environment {ws.environment}</div>
        </div>
        {activeJob && !unavailable ? (
          <p className="hint" role="status" style={{ margin: 0 }}>
            {activeJob.use_agent ? "AI" : "Static"} analysis is {activeJob.status}. Wait for completion or cancel it in Jobs.
          </p>
        ) : null}
        <button type="button" className="btn" disabled={disabled} onClick={() => void runStatic()}>
          <Cpu className="icon" aria-hidden="true" /> Static analysis
        </button>
        <button type="button" className="btn" disabled={disabled} onClick={() => { close(); ws.openAnalysis("agent"); }}>
          <Cloud className="icon" aria-hidden="true" /> AI analysis…
        </button>
        <button type="button" className="btn ghost small" disabled={disabled} onClick={() => { close(); ws.openAnalysis("static"); }}>
          Analysis options and embeddings…
        </button>
      </div>
    </details>
  );
}
