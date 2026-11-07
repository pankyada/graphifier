"use client";

import { useState, type FormEvent } from "react";
import { GitBranch, RefreshCw } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { api, messageOf } from "@/lib/api";
import { isImportActive } from "@/lib/jobs";
import { StatusChip } from "@/components/jobs/StatusChip";
import type { RepositoryImport } from "@/lib/types";

export function RemoteRepositoryForm() {
  const ws = useWorkspace();
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [pendingActions, setPendingActions] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!url.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createRepositoryImport({
        url: url.trim(),
        branch: branch.trim() || undefined,
        name: name.trim() || undefined,
      });
      ws.afterImportQueued(job);
      setUrl("");
      setBranch("");
      setName("");
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setSubmitting(false);
    }
  }

  async function changeImport(job: RepositoryImport, action: "cancel" | "retry") {
    setPendingActions((current) => new Set(current).add(job.id));
    setError(null);
    try {
      if (action === "retry") {
        const retried = await api.retryRepositoryImport(job.id);
        ws.afterImportQueued(retried);
      } else {
        await api.cancelRepositoryImport(job.id);
        ws.repositoryImports.reload();
      }
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setPendingActions((current) => {
        const next = new Set(current);
        next.delete(job.id);
        return next;
      });
    }
  }

  function openRepository(repoId: string, analyze: boolean) {
    ws.selectRepo(repoId);
    if (analyze) ws.openDialog("run");
    else ws.closeDialog();
  }

  const visibleImports = [
    ...ws.importList.filter(isImportActive),
    ...ws.importList.filter((job) => !isImportActive(job)).slice(0, 20),
  ];

  return (
    <div className="stack">
      <form onSubmit={submit} className="stack" aria-label="Clone remote repository">
        <p className="card-text" style={{ margin: 0 }}>
          Clone a GitHub or Bitbucket repository to this server, then run analysis on the local copy.
        </p>
        <fieldset disabled={submitting} className="stack" style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
          <label className="field">
            <span className="label">Repository URL</span>
            <input
              className="input"
              type="text"
              required
              maxLength={2048}
              autoComplete="off"
              spellCheck={false}
              placeholder="https://github.com/owner/repository.git"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
          </label>
          <div className="row-inline">
            <label className="field" style={{ flex: "1 1 180px" }}>
              <span className="label">Branch (optional)</span>
              <input className="input" maxLength={255} placeholder="Default branch" value={branch} onChange={(event) => setBranch(event.target.value)} />
            </label>
            <label className="field" style={{ flex: "1 1 180px" }}>
              <span className="label">Name (optional)</span>
              <input className="input" maxLength={120} placeholder="Use repository name" value={name} onChange={(event) => setName(event.target.value)} />
            </label>
          </div>
          <p className="hint" style={{ margin: 0 }}>
            HTTPS and SSH URLs are supported. Private repositories use this server’s existing Git or SSH credentials.
          </p>
          <div className="row-inline" style={{ justifyContent: "flex-end" }}>
            <button type="submit" className="btn primary" disabled={!url.trim()}>
              <GitBranch className="icon" aria-hidden="true" />
              {submitting ? "Queuing clone…" : "Clone repository"}
            </button>
          </div>
        </fieldset>
      </form>

      {error ? <p className="error-text" role="alert">{error}</p> : null}
      <div className="row-inline" style={{ justifyContent: "space-between" }}>
        <span className="label">Repository imports</span>
        <button type="button" className="btn small ghost" onClick={ws.repositoryImports.reload}>
          <RefreshCw className="icon" aria-hidden="true" /> Refresh
        </button>
      </div>
      {ws.repositoryImports.error ? <p className="error-text" role="alert">{ws.repositoryImports.error}</p> : null}
      {ws.repositoryImports.loading && !ws.repositoryImports.data ? <p className="hint">Loading imports…</p> : null}
      {ws.repositoryImports.data && visibleImports.length === 0 ? <p className="hint">No remote repositories imported yet.</p> : null}
      <div className="stack" style={{ maxHeight: "22rem", overflow: "auto" }} aria-live="polite">
        {visibleImports.map((job) => {
          const active = isImportActive(job);
          const pending = pendingActions.has(job.id);
          const registered = !!job.repo_id && ws.repoList.some((repo) => repo.id === job.repo_id);
          return (
            <article className="embedding-result stack" key={job.id} aria-label={`Import ${job.name || job.url}`}>
              <div className="row-inline" style={{ justifyContent: "space-between" }}>
                <strong>{job.name || "Remote repository"}</strong>
                <StatusChip status={job.status} cancelling={active && job.cancel_requested} />
              </div>
              <div className="mono" style={{ fontSize: 11, overflowWrap: "anywhere" }}>{job.url}</div>
              <div className="hint">{job.branch || "Default branch"}{job.status === "completed" ? " · local clone ready" : ""}</div>
              {active ? (
                <>
                  <progress max={1} value={Math.max(0, Math.min(1, job.progress))} aria-label="Repository clone progress" style={{ width: "100%" }} />
                  <p className="hint" style={{ margin: 0 }}>
                    {job.status === "queued" ? "Waiting for the worker to start cloning." : "Cloning repository files. You can close this dialog while it runs."}
                  </p>
                </>
              ) : null}
              {job.error ? <p className="error-text" style={{ margin: 0 }}>{job.error}</p> : null}
              <div className="row-inline" style={{ justifyContent: "flex-end" }}>
                {active ? (
                  <button type="button" className="btn small" disabled={pending || job.cancel_requested} onClick={() => void changeImport(job, "cancel")}>
                    {pending || job.cancel_requested ? "Cancelling…" : "Cancel clone"}
                  </button>
                ) : null}
                {job.status === "failed" || job.status === "cancelled" ? (
                  <button type="button" className="btn small" disabled={pending} onClick={() => void changeImport(job, "retry")}>
                    {pending ? "Retrying…" : "Retry clone"}
                  </button>
                ) : null}
                {job.status === "completed" && job.repo_id ? (
                  <>
                    <button type="button" className="btn small" disabled={!registered} onClick={() => openRepository(job.repo_id!, false)}>Open repository</button>
                    <button type="button" className="btn primary small" disabled={!registered} onClick={() => openRepository(job.repo_id!, true)}>Run analysis</button>
                  </>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
      {ws.importList.length > visibleImports.length ? <p className="hint">Showing active clones and the 20 most recent finished imports.</p> : null}
    </div>
  );
}
