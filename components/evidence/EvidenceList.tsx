"use client";

import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { evidenceTarget, uniqueEvidence, type ViewerTarget } from "@/lib/evidence";
import type { Evidence, SnapshotMeta } from "@/lib/types";

export type { ViewerTarget } from "@/lib/evidence";

interface EvidenceListProps {
  items: Evidence[];
  /** Repository used when an entry does not carry repo_id (symbol evidence). */
  fallbackRepoId: string | null;
  /** Snapshot metadata carried by the selected node or edge, if any. */
  ownerSnapshots?: SnapshotMeta[];
  active: ViewerTarget | null;
  onOpen: (target: ViewerTarget) => void;
}

/** Evidence rows: each one is a file span in the indexed snapshot for the active environment. */
export function EvidenceList({ items, fallbackRepoId, ownerSnapshots, active, onOpen }: EvidenceListProps) {
  const ws = useWorkspace();
  const unique = uniqueEvidence(items, fallbackRepoId);
  const graphSnapshots = ws.focus ? ws.trace.data?.snapshots ?? ws.graph.data?.snapshots : ws.graph.data?.snapshots;

  if (unique.length === 0) {
    return <div className="empty-row">No indexed evidence recorded for this item.</div>;
  }

  return (
    <ul className="evidence-list" aria-label="Evidence entries">
      {unique.map((entry) => {
        const repoId = entry.repo_id ?? fallbackRepoId ?? "";
        const target = evidenceTarget(entry, {
          fallbackRepoId,
          environment: ws.environment,
          ownerSnapshots,
          graphSnapshots,
        });
        const current =
          !!active &&
          active.repoId === target.repoId &&
          active.environment === target.environment &&
          active.file === target.file &&
          active.startLine === target.startLine &&
          active.endLine === target.endLine &&
          active.snapshotId === target.snapshotId;
        const repoName = entry.repo_id ? ws.repoNames.get(entry.repo_id) : undefined;
        return (
          <li key={`${repoId}|${entry.snapshot_id ?? ""}|${entry.file}|${entry.start_line}|${entry.end_line}`}>
            <button
              type="button"
              className="evidence-item"
              aria-current={current ? "true" : undefined}
              onClick={() => onOpen(target)}
              disabled={!repoId}
              title={entry.file}
            >
              <span style={{ minWidth: 0 }}>
                <span className="evidence-file" style={{ display: "block" }}>
                  {entry.file}
                </span>
                {repoName ? (
                  <span className="muted" style={{ fontSize: 11 }}>
                    {repoName}
                  </span>
                ) : null}
              </span>
              <span className="evidence-lines">
                L{entry.start_line}
                {entry.end_line !== entry.start_line ? `–${entry.end_line}` : ""}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
