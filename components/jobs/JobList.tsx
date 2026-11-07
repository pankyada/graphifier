"use client";

import { useRef, useState } from "react";
import { ChevronDown, Play, X } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { StatusLine } from "@/components/shell/StatusLine";
import { StatusChip } from "./StatusChip";
import { activeAnalysisJob, analysisModeOf, canResumeJob, isActive, JOB_MODE_LABEL } from "@/lib/jobs";
import { relativeTime, shortId } from "@/lib/format";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";

const RECENT_JOBS = 3;

/** Jobs section: run analysis, list jobs, poll progress, cancel with inline confirm. */
export function JobList() {
  const ws = useWorkspace();
  const resumePending = useRef(new Set<string>());
  const [resuming, setResuming] = useState<Set<string>>(() => new Set());
  const resume = async (job: Job) => {
    if (resumePending.current.has(job.id)) return;
    resumePending.current.add(job.id);
    setResuming(new Set(resumePending.current));
    try {
      const resumed = await api.resumeJob(job.id);
      ws.toast("info", `Resume ${resumed.status} for ${ws.repoNames.get(job.repo_id) ?? job.repo_id} (${job.environment}). Saved source and analysis settings will be reused.`);
    } catch (error) {
      ws.fail("Could not resume analysis", error);
    } finally {
      ws.jobs.reload();
      resumePending.current.delete(job.id);
      setResuming(new Set(resumePending.current));
    }
  };
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [showAll, setShowAll] = useState(false);
  // Active work always stays in view; finished jobs collapse so Mappings stays reachable.
  const shownJobs = showAll ? ws.jobList : ws.jobList.filter((job, index) => index < RECENT_JOBS || isActive(job));
  const hiddenJobs = ws.jobList.length - shownJobs.length;

  const runDisabled = ws.repos.data === null || ws.repoList.length === 0 || !ws.repoId || ws.scope === "all";
  const runTitle =
    ws.scope === "all"
      ? "Select a single repository to run analysis. Analysis is per repository."
      : !ws.repoId
        ? "Select a repository first."
        : "Run static or AI harness analysis for this repository";

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="section-body">
      <div className="section-actions">
        <button
          type="button"
          className="btn primary small"
          disabled={runDisabled}
          title={runTitle}
          onClick={() => ws.openDialog("run")}
        >
          <Play className="icon" aria-hidden="true" />
          Run analysis
        </button>
      </div>
      {ws.scope === "all" ? (
        <div className="hint" style={{ padding: "0 2px 6px" }}>
          Showing jobs for all repositories. Pick one repository to run analysis.
        </div>
      ) : null}

      {ws.jobs.loading && !ws.jobs.data ? <StatusLine text="Loading jobs…" /> : null}
      {ws.jobs.error && !ws.jobs.data ? <StatusLine tone="bad" text={`Jobs unavailable: ${ws.jobs.error}`} /> : null}
      {ws.jobs.data && ws.jobList.length === 0 ? (
        <div className="empty-row">
          {ws.scope === "repo" && ws.repo
            ? `No jobs for ${ws.repo.name} yet. Run analysis to index it.`
            : "No jobs yet."}
        </div>
      ) : null}

      {shownJobs.map((job) => (
        <JobRow
          key={job.id}
          job={job}
          repoName={ws.repoNames.get(job.repo_id)}
          showRepo={ws.scope === "all"}
          resuming={resuming.has(job.id)}
          resumeBlocked={!!activeAnalysisJob(ws.jobList, job.repo_id, job.environment)}
          onResume={() => { void resume(job); }}
          cancelling={ws.cancelling.has(job.id) && isActive(job)}
          confirming={confirmId === job.id}
          expanded={expanded.has(job.id)}
          onAskCancel={() => setConfirmId(job.id)}
          onKeep={() => setConfirmId(null)}
          onConfirmCancel={() => {
            setConfirmId(null);
            void ws.requestCancel(job);
          }}
          onToggleExpanded={() => toggleExpanded(job.id)}
        />
      ))}
      {hiddenJobs > 0 ? (
        <button type="button" className="btn ghost small block" onClick={() => setShowAll(true)}>
          <ChevronDown className="icon" aria-hidden="true" />
          Show {hiddenJobs} older
        </button>
      ) : null}
    </div>
  );
}

interface JobRowProps {
  job: Job;
  repoName: string | undefined;
  showRepo: boolean;
  resuming: boolean;
  resumeBlocked: boolean;
  onResume: () => void;
  cancelling: boolean;
  confirming: boolean;
  expanded: boolean;
  onAskCancel: () => void;
  onKeep: () => void;
  onConfirmCancel: () => void;
  onToggleExpanded: () => void;
}

function JobRow(props: JobRowProps) {
  const { job, repoName, showRepo, cancelling, confirming, expanded } = props;
  const active = isActive(job);
  const mode = analysisModeOf(job);
  const total = job.total_files || 0;
  const percent = total > 0 ? Math.min(100, Math.round((job.processed_files / total) * 100)) : Math.round((job.progress ?? 0) * 100);
  const progressClass = job.status === "completed" ? "progress done" : job.status === "failed" ? "progress failed" : "progress";
  const error = job.error ?? "";
  const longError = error.length > 140;

  return (
    <div className="row" style={{ cursor: "default", gap: 6, padding: "7px 8px 8px 10px" }}>
      <div className="row-title" style={{ justifyContent: "space-between" }}>
        <StatusChip status={job.status} cancelling={cancelling} />
        <span className="row-meta" style={{ gap: 4, flexWrap: "wrap", justifyContent: "flex-end", minWidth: 0 }}>
          <span
            className="chip tag"
            title={
              mode === "agent"
                ? "AI harness: bounded source excerpts sent to the configured model endpoint"
                : "Static: parsed locally"
            }
          >
            {JOB_MODE_LABEL[mode]}
          </span>
          {job.use_ai_hierarchy ? <span className="chip tag" title="Model-assisted architecture grouping and component summaries">AI grouping</span> : null}
          <span className="chip tag" title="Environment">
            {job.environment}
          </span>
        </span>
      </div>

      {showRepo && repoName ? <div className="row-meta">{repoName}</div> : null}

      <div className="row-meta">
        <span className="mono">{shortId(job.id)}</span>
        <span>·</span>
        <span>
          {total > 0 ? `${job.processed_files}/${total} files` : active ? "Waiting for worker" : "No file count"}
        </span>
        <span style={{ marginLeft: "auto", whiteSpace: "nowrap" }} title={job.updated_at}>
          {relativeTime(job.updated_at)}
        </span>
      </div>

      {job.status !== "completed" ? (
        <div
          className={progressClass}
          role="progressbar"
          aria-label={`Analysis progress ${percent}%`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <span style={{ width: `${percent}%` }} />
        </div>
      ) : null}

      {job.checkpoint ? <div className="hint" style={{ overflowWrap: "anywhere" }}>
        Saved checkpoint: {job.checkpoint.phase === "ai_hierarchy" ? "Generating AI architecture" : job.checkpoint.phase} · {job.checkpoint.completed_files}/{job.checkpoint.total_files} files
        {job.checkpoint.current_file ? ` · ${job.checkpoint.current_file}` : ""}
      </div> : null}

      {canResumeJob(job) ? <div>
        <button type="button" className="btn small" disabled={props.resuming || props.resumeBlocked} onClick={props.onResume}
          title={props.resumeBlocked ? "An analysis is already active for this repository and environment." : "Continue from saved source and analysis settings. Re-analyse starts a fresh run."}>
          <Play className="icon" aria-hidden="true" />{props.resuming ? "Resuming…" : "Resume"}
        </button>
        <div className="hint">Resume reuses saved source and settings; Re-analyse starts fresh.</div>
        {props.resumeBlocked ? <div className="hint">Wait for the active run in this repository and environment.</div> : null}
      </div> : ["failed", "cancelled", "interrupted"].includes(job.status) ? <div className="hint">No resumable checkpoint available. Start a new analysis.</div> : null}

      {error ? (
        <div className="row-meta" style={{ color: "var(--red-700)", whiteSpace: "normal", alignItems: "flex-start" }}>
          <span className={expanded ? "" : "truncate"} style={expanded ? undefined : { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", whiteSpace: "normal" }}>
            {error}
          </span>
          {longError ? (
            <button type="button" className="btn ghost small" aria-expanded={expanded} onClick={props.onToggleExpanded}>
              {expanded ? "Less" : "More"}
            </button>
          ) : null}
        </div>
      ) : null}

      {active ? (
        confirming ? (
          <div className="row-inline" role="group" aria-label="Confirm cancel">
            <span className="muted" style={{ fontSize: 11.5 }}>Cancel this job?</span>
            <button type="button" className="btn danger small" onClick={props.onConfirmCancel}>
              Cancel job
            </button>
            <button type="button" className="btn small" onClick={props.onKeep}>
              Keep
            </button>
          </div>
        ) : (
          <div>
            <button
              type="button"
              className="btn ghost small"
              aria-label={`Cancel job ${shortId(job.id)}`}
              disabled={cancelling}
              onClick={props.onAskCancel}
            >
              <X className="icon" aria-hidden="true" />
              {cancelling ? "Cancelling…" : "Cancel"}
            </button>
          </div>
        )
      ) : null}
    </div>
  );
}
