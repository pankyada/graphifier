"use client";

import { ArrowRight, CircleAlert } from "lucide-react";
import { shortId, relativeTime } from "@/lib/format";
import type { BindingPreview, Resolution } from "@/lib/types";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { evidenceTarget, type ViewerTarget } from "@/lib/evidence";

interface PreviewPanelProps {
  preview: BindingPreview;
  onOpenEvidence: (target: ViewerTarget) => void;
}

/**
 * Renders the preview_binding output as returned by the API:
 * counts, affected_references (with before/after RESOLVES_TO targets and evidence).
 */
export function PreviewPanel({ preview, onOpenEvidence }: PreviewPanelProps) {
  const ws = useWorkspace();
  const repoId = preview.repo_id;
  const counts = preview.counts;
  const affected = preview.affected_references ?? [];

  const stats: { label: string; value: number }[] = [
    { label: "nodes added", value: counts.nodes_added },
    { label: "nodes removed", value: counts.nodes_removed },
    { label: "edges added", value: counts.edges_added },
    { label: "edges removed", value: counts.edges_removed },
  ];

  return (
    <div className="stack" aria-label="Preview of graph changes">
      <div className="label">Preview of graph changes</div>
      <div className="preview-counts">
        {stats.map((stat) => (
          <div key={stat.label} className="stat">
            <span className="stat-value">{stat.value}</span>
            <span className="stat-label">{stat.label}</span>
          </div>
        ))}
      </div>

      <div className="label" style={{ marginTop: 4 }}>
        Affected references · {affected.length}
      </div>
      {affected.length === 0 ? (
        <p className="hint" style={{ margin: 0 }}>
          No reference changes its canonical target. Applying would not change lineage in the current snapshot.
        </p>
      ) : (
        affected.map((ref) => {
          const first = ref.evidence?.[0];
          return (
            <div key={ref.reference_id} className="affected">
              <div className="row-inline" style={{ justifyContent: "space-between" }}>
                <span className="mono truncate" title={ref.name ?? ref.reference_id}>
                  {ref.name ?? shortId(ref.reference_id)}
                </span>
                {first ? (
                  <button
                    type="button"
                    className="btn ghost small"
                    onClick={() =>
                      onOpenEvidence(
                        evidenceTarget(first, {
                          fallbackRepoId: repoId,
                          environment: preview.environment,
                          graphSnapshots: ws.graph.data?.snapshots,
                        }),
                      )
                    }
                  >
                    Open source
                  </button>
                ) : null}
              </div>
              {ref.expression ? (
                <span className="mono muted truncate" title={ref.expression} style={{ fontSize: 11 }}>
                  {ref.expression}
                </span>
              ) : null}
              <div className="arrow-pair">
                <span>{describeTargets(ref.before)}</span>
                <ArrowRight className="icon" aria-hidden="true" />
                <span>{describeTargets(ref.after)}</span>
              </div>
            </div>
          );
        })
      )}

      <p className="note-line" style={{ margin: 0 }}>
        Graph version {shortId(preview.graph_version_before, 8)} → {shortId(preview.graph_version_after, 8)}
      </p>
    </div>
  );
}

function describeTargets(targets: string[]): string {
  if (!targets || targets.length === 0) return "unresolved";
  if (targets.length === 1) return shortTarget(targets[0]);
  return `${shortTarget(targets[0])} +${targets.length - 1}`;
}

function shortTarget(id: string): string {
  return id.length > 26 ? `${id.slice(0, 26)}…` : id;
}

interface ConflictListProps {
  conflicts: Resolution[];
}

/** Live bindings on the same repo/environment/symbol. Any entry blocks apply. */
export function ConflictList({ conflicts }: ConflictListProps) {
  if (conflicts.length === 0) return null;
  return (
    <div className="conflict-box" role="alert">
      <div className="conflict-title">
        <CircleAlert className="icon" aria-hidden="true" style={{ display: "inline", verticalAlign: "-2px" }} /> Conflict:
        a live binding already exists for this symbol in this environment. Apply is disabled.
      </div>
      {conflicts.map((item) => (
        <div key={item.id} className="conflict-item">
          <span className="mono truncate" title={item.expression}>
            {item.expression}
          </span>
          <span className="note-line">
            {item.status} · v{item.version}
            {item.actor ? ` · ${item.actor}` : ""} · {relativeTime(item.updated_at)}
          </span>
        </div>
      ))}
    </div>
  );
}
