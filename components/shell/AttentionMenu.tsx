"use client";

import { Check, CircleAlert, ShieldCheck, TriangleAlert } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { isPartialAiWarning } from "@/lib/coverage";
import { Popover } from "./Popover";

interface Notice {
  id: string;
  title: string;
  text: string;
}

/** Conditions worth knowing about but not worth covering the canvas for. */
function useNotices(): { notices: Notice[]; indexed: number; total: number } {
  const ws = useWorkspace();
  const graph = ws.graph.data;
  const trace = ws.focus ? ws.trace.data : null;
  const notices: Notice[] = [];

  const scopeRepos = ws.scope === "all" ? ws.repoList : ws.repo ? [ws.repo] : [];
  const indexedIds = new Set((graph?.snapshots ?? []).map((snapshot) => snapshot.repo_id));
  const indexed = scopeRepos.filter((item) => indexedIds.has(item.id)).length;

  const latest = ws.latestJob;
  if (latest && (latest.status === "failed" || latest.status === "cancelled") && graph && graph.snapshots.length > 0) {
    notices.push({
      id: "job",
      title: `Latest job ${latest.status}`,
      text: `${latest.error ? `${latest.error}. ` : ""}Showing the last completed snapshot.`,
    });
  }
  if (graph?.truncated) {
    notices.push({
      id: "bounded",
      title: "Showing a bounded graph",
      text: "Filter in Explore or trace an entity to reach the rest of this repository.",
    });
  }
  const warnings = graph?.warnings ?? [];
  if (warnings.length > 0) {
    const partialAi = warnings.filter((entry) => isPartialAiWarning(entry.warning)).length;
    notices.push({
      id: "coverage",
      title: `${warnings.length} coverage warning${warnings.length === 1 ? "" : "s"}`,
      text: partialAi > 0
        ? `${partialAi} from partial AI coverage. Static and validated AI findings remain available.`
        : "Some files could not be fully analysed.",
    });
  }
  if (trace?.truncated) {
    notices.push({
      id: "trace",
      title: "Trace truncated",
      text: `Lineage stops at depth ${trace.max_depth}. Narrow the focus to see the rest.`,
    });
  }
  if (trace && trace.unresolved_gaps.length > 0) {
    const count = trace.unresolved_gaps.length;
    notices.push({
      id: "gaps",
      title: `${count} unresolved symbolic reference${count === 1 ? "" : "s"}`,
      text: "Bind them in Mappings to stitch these references to physical datasets.",
    });
  }
  return { notices, indexed, total: scopeRepos.length };
}

/** Single top-bar chip that replaces the stack of page banners. */
export function AttentionMenu() {
  const ws = useWorkspace();
  const { notices, indexed, total } = useNotices();
  const count = notices.length;

  return (
    <Popover
      label={count > 0 ? `${count} items need attention` : "Coverage and analysis notes"}
      triggerClassName={`attention-trigger${count > 0 ? " warn" : ""}`}
      align="right"
      width={340}
      trigger={
        count > 0 ? (
          <>
            <TriangleAlert className="icon" aria-hidden="true" />
            <span className="topbar-label">{count} need attention</span>
            <span className="topbar-label-short">{count}</span>
          </>
        ) : (
          <>
            <Check className="icon" aria-hidden="true" />
            <span className="topbar-label">Coverage {indexed}/{total}</span>
          </>
        )
      }
    >
      {(close) => (
        <div className="menu">
          {notices.map((notice) => (
            <div key={notice.id} className="attention-row">
              <CircleAlert className="icon" aria-hidden="true" />
              <div>
                <div className="attention-title">{notice.title}</div>
                <div className="attention-text">{notice.text}</div>
              </div>
            </div>
          ))}
          <button
            type="button"
            className="menu-item"
            onClick={() => {
              ws.openDialog("coverage");
              close();
            }}
          >
            <ShieldCheck className="icon" aria-hidden="true" />
            <span className="menu-item-text">Open coverage report</span>
            <span className="menu-item-meta">{indexed}/{total} indexed</span>
          </button>
          <div className="menu-sep" />
          <p className="attention-note">
            Connections describe potential flow inferred from source. Inspect evidence and extraction method for each finding.
          </p>
        </div>
      )}
    </Popover>
  );
}
