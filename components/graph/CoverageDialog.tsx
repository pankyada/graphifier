"use client";

import { CircleAlert, CircleCheckBig } from "lucide-react";
import { Dialog } from "@/components/shell/Dialog";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { relativeTime, sha8 } from "@/lib/format";
import type { Repository, WarningEntry } from "@/lib/types";

/** Describe a warning without assuming its shape: strings and binding_conflict objects both occur. */
export function describeWarning(warning: unknown): { title: string | null; message: string } {
  if (typeof warning === "string") return { title: null, message: warning };
  if (warning && typeof warning === "object") {
    const record = warning as { kind?: unknown; message?: unknown; symbol?: unknown };
    const title = typeof record.kind === "string" ? record.kind.replace(/_/g, " ") : null;
    const message = typeof record.message === "string" ? record.message : JSON.stringify(warning);
    const symbol = typeof record.symbol === "string" ? ` (symbol ${record.symbol})` : "";
    return { title, message: `${message}${symbol}` };
  }
  return { title: null, message: String(warning) };
}

export function CoverageDialog() {
  const ws = useWorkspace();
  const open = ws.dialog === "coverage";
  return (
    <Dialog open={open} onClose={ws.closeDialog} title="Coverage and warnings" size="wide">
      {open ? <CoverageBody /> : null}
    </Dialog>
  );
}

function CoverageBody() {
  const ws = useWorkspace();
  const graph = ws.graph.data;
  const scopeRepos: Repository[] = ws.scope === "all" ? ws.repoList : ws.repo ? [ws.repo] : [];
  const snapshots = graph?.snapshots ?? [];
  const warnings: WarningEntry[] = graph?.warnings ?? [];

  const warningsByRepo = new Map<string, number>();
  for (const entry of warnings) warningsByRepo.set(entry.repo_id, (warningsByRepo.get(entry.repo_id) ?? 0) + 1);
  const indexed = scopeRepos.filter((item) => snapshots.some((snap) => snap.repo_id === item.id));

  return (
    <div className="stack">
      <p className="card-text" style={{ margin: 0 }}>
        <strong>
          {indexed.length} of {scopeRepos.length}
        </strong>{" "}
        repositories have a completed snapshot in environment <span className="mono">{ws.environment}</span>.
        {warnings.length > 0 ? ` ${warnings.length} warning${warnings.length === 1 ? "" : "s"} recorded.` : " No warnings recorded."}
      </p>
      <p className="hint" style={{ margin: 0 }}>
        Warnings come from static extraction (files that could not be fully parsed) and binding conflicts. Any warning
        means coverage for that file may be partial.
      </p>

      <div className="settings-grid" role="table" aria-label="Repository coverage" style={{ gridTemplateColumns: "1fr" }}>
        {scopeRepos.length === 0 ? <div className="empty-row">No repository in scope.</div> : null}
        {scopeRepos.map((item) => {
          const snap = snapshots.find((entry) => entry.repo_id === item.id);
          const count = warningsByRepo.get(item.id) ?? 0;
          return (
            <div key={item.id} role="row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
              <span role="cell" style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                {snap ? (
                  <CircleCheckBig className="icon" aria-hidden="true" style={{ color: "var(--ok-700)" }} />
                ) : (
                  <CircleAlert className="icon" aria-hidden="true" style={{ color: "var(--amber-700)" }} />
                )}
                <span className="truncate" style={{ fontWeight: 500 }}>
                  {item.name}
                </span>
              </span>
              <span role="cell" className="v" style={{ textAlign: "right" }}>
                {snap
                  ? `indexed ${sha8(snap.commit_hash) || "no commit"} · ${relativeTime(snap.created_at)}`
                  : "not indexed in this environment"}
                {count > 0 ? ` · ${count} warning${count === 1 ? "" : "s"}` : ""}
              </span>
            </div>
          );
        })}
      </div>

      <div className="label">Warnings</div>
      {warnings.length === 0 ? (
        <div className="empty-row">None.</div>
      ) : (
        <ul className="table-list" style={{ listStyle: "none", padding: 0, margin: 0 }} aria-label="Warning details">
          {warnings.map((entry, index) => {
            const described = describeWarning(entry.warning);
            const repoName = ws.repoNames.get(entry.repo_id) ?? entry.repo_id;
            return (
              <li key={`${entry.snapshot_id}-${index}`} className="affected">
                <span className="note-line">
                  {repoName}
                  {described.title ? ` · ${described.title}` : ""}
                </span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, overflowWrap: "anywhere" }}>
                  {described.message}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
