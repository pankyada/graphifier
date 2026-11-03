import type { Evidence, SnapshotMeta } from "./types";

/**
 * A source span to open. `snapshotId` is the indexed snapshot that produced the
 * selected graph item for this repository and environment, or null when none
 * exists. Null is shown to the user; it is never replaced by "latest".
 */
export interface ViewerTarget {
  repoId: string;
  environment: string;
  snapshotId: string | null;
  file: string;
  startLine: number;
  endLine: number;
}

/**
 * First source (item metadata, then graph metadata) that holds a snapshot for
 * this repository AND environment. Snapshots from other environments never match.
 */
export function pickSnapshotId(
  repoId: string,
  environment: string,
  ...sources: (SnapshotMeta[] | undefined)[]
): string | null {
  if (!repoId) return null;
  for (const source of sources) {
    const matches = (source ?? []).filter((item) => item.repo_id === repoId && item.environment === environment);
    if (matches.length === 0) continue;
    matches.sort((a, b) => b.created_at.localeCompare(a.created_at));
    return matches[0].snapshot_id;
  }
  return null;
}

export interface TargetContext {
  /** Repository to use when the evidence entry does not carry repo_id. */
  fallbackRepoId: string | null;
  environment: string;
  /** Snapshot metadata carried by the selected node or edge. */
  ownerSnapshots?: SnapshotMeta[];
  /** Snapshot metadata of the loaded graph (fallback). */
  graphSnapshots?: SnapshotMeta[];
}

export function evidenceTarget(entry: Evidence, context: TargetContext): ViewerTarget {
  const repoId = entry.repo_id ?? context.fallbackRepoId ?? "";
  return {
    repoId,
    environment: context.environment,
    snapshotId: pickSnapshotId(repoId, context.environment, context.ownerSnapshots, context.graphSnapshots),
    file: entry.file,
    startLine: entry.start_line,
    endLine: entry.end_line,
  };
}
