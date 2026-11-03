"use client";

import { Folder, FolderPlus } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { StatusLine } from "@/components/shell/StatusLine";

/** Repositories section of the left rail. Selecting a row sets the repo scope. */
export function RepoList() {
  const ws = useWorkspace();
  const repos = ws.repoList;

  return (
    <div className="section-body">
      <div className="section-actions">
        <button type="button" className="btn small" onClick={() => ws.openDialog("browse")}>
          <FolderPlus className="icon" aria-hidden="true" />
          Add repository
        </button>
      </div>

      {ws.repos.loading && !ws.repos.data ? <StatusLine text="Loading repositories…" /> : null}
      {ws.repos.error && !ws.repos.data ? <StatusLine tone="bad" text={ws.repos.error} /> : null}

      {!ws.repos.loading && repos.length === 0 && !ws.repos.error ? (
        <div className="empty-row">None yet. Add a folder from the allowed root to start.</div>
      ) : null}

      {repos.map((item) => {
        const active = item.id === ws.repoId && ws.scope === "repo";
        return (
          <button
            key={item.id}
            type="button"
            className="row"
            aria-pressed={active}
            onClick={() => ws.selectRepo(item.id)}
            title={item.path}
          >
            <span className="row-title">
              <Folder className="icon" aria-hidden="true" />
              <span className="truncate">{item.name}</span>
            </span>
            <span className="row-meta">
              <span className="middle-ellipsis mono">
                <span>{item.path}</span>
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
