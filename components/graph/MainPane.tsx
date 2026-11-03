"use client";

import { useMemo, type ReactNode } from "react";
import { Crosshair, Maximize, Play, RefreshCw, X } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { LARGE_GRAPH_THRESHOLD } from "@/components/workspace/useWorkspace";
import { Onboarding } from "@/components/repos/Onboarding";
import { isSymbolicExpression } from "@/lib/explain";
import { traceSides } from "@/lib/layout";
import type { TraceDirection } from "@/lib/types";
import { LineageCanvas } from "./LineageCanvas";
import { FocusList } from "./FocusList";
import { kindIcon, kindName } from "./kinds";
import type { LineageRole } from "./NodeCard";
import { ApiDown } from "@/components/shell/ApiDown";
import { StatusLine } from "@/components/shell/StatusLine";
import { ResourceNotice } from "@/components/shell/ResourceNotice";

const DIRECTIONS: { value: TraceDirection; label: string }[] = [
  { value: "in", label: "Upstream" },
  { value: "both", label: "Both" },
  { value: "out", label: "Downstream" },
];

/** Routes the main area between onboarding, API errors, loading and the graph. */
export function MainPane() {
  const ws = useWorkspace();

  if (ws.repos.error && !ws.repos.data) {
    return <ApiDown message={ws.repos.error} status={ws.repos.status} onRetry={ws.repos.reload} />;
  }
  if (!ws.repos.data) {
    return (
      <div className="center-state">
        <div className="skeleton-list" aria-busy="true" aria-label="Loading workspace">
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      </div>
    );
  }
  if (ws.repoList.length === 0) return <Onboarding />;
  if (ws.scope === "repo" && !ws.repo) {
    return (
      <div className="center-state">
        <div className="card">
          <p className="card-title">Select a repository</p>
          <p className="card-text">Pick a repository in the left rail, or switch to All repos for the aggregate graph.</p>
        </div>
      </div>
    );
  }
  return <GraphPane />;
}

function GraphPane() {
  const ws = useWorkspace();
  const graph = ws.graph.data;
  const focusTrace = ws.focus ? ws.trace.data : null;
  const allNodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const allEdges = useMemo(() => graph?.edges ?? [], [graph]);

  const unresolvedIds = useMemo(() => {
    const set = new Set<string>();
    for (const node of allNodes) {
      if (isSymbolicExpression(node.expression) && !ws.resolvedSources.has(node.id)) set.add(node.id);
    }
    return set;
  }, [allNodes, ws.resolvedSources]);

  const { visibleNodes, visibleEdges } = useMemo(() => {
    const baseNodes = focusTrace ? focusTrace.nodes : allNodes;
    const baseEdges = focusTrace ? focusTrace.edges : allEdges;
    const nodes = baseNodes.filter((node) => !ws.hiddenKinds.has(node.kind));
    const ids = new Set(nodes.map((node) => node.id));
    const edges = baseEdges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
    return { visibleNodes: nodes, visibleEdges: edges };
  }, [focusTrace, allNodes, allEdges, ws.hiddenKinds]);

  const roles = useMemo(() => {
    const map = new Map<string, Exclude<LineageRole, null>>();
    if (!ws.focus || !focusTrace) return map;
    const sides = traceSides(ws.focus.id, focusTrace.edges);
    for (const id of sides.upstream) map.set(id, "upstream");
    for (const id of sides.downstream) map.set(id, "downstream");
    map.set(ws.focus.id, "focus");
    return map;
  }, [ws.focus, focusTrace]);

  const scopeRepos = ws.scope === "all" ? ws.repoList : ws.repo ? [ws.repo] : [];
  const indexedRepoIds = new Set((graph?.snapshots ?? []).map((snapshot) => snapshot.repo_id));
  const indexedCount = scopeRepos.filter((item) => indexedRepoIds.has(item.id)).length;
  const warningCount = graph?.warnings.length ?? 0;
  const latestFailed = ws.latestJob && (ws.latestJob.status === "failed" || ws.latestJob.status === "cancelled");
  const showFocusList = !ws.focus && allNodes.length > LARGE_GRAPH_THRESHOLD;

  if (ws.graph.error && !graph) {
    const offline = ws.graph.status === 0 || ws.graph.status === 503;
    return offline ? (
      <ApiDown message={ws.graph.error} status={ws.graph.status} onRetry={ws.graph.reload} />
    ) : (
      <div className="center-state">
        <div className="card">
          <p className="card-title">Graph unavailable</p>
          <p className="error-text" role="alert">
            {ws.graph.error}
          </p>
          <div className="row-inline">
            <button type="button" className="btn" onClick={ws.graph.reload}>
              <RefreshCw className="icon" aria-hidden="true" />
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!graph && ws.graph.loading) {
    return (
      <div className="center-state">
        <div className="skeleton-list" aria-busy="true" aria-label="Loading graph">
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      </div>
    );
  }

  const toolbar = (
    <div className="graph-toolbar" role="toolbar" aria-label="Lineage toolbar">
      {ws.focus ? (
        <span className="focus-chip">
          <Crosshair className="icon" aria-hidden="true" />
          <span className="truncate">
            Focus: {allNodes.find((node) => node.id === ws.focus?.id)?.name ?? ws.focus.id}
          </span>
          <button type="button" className="icon-btn" aria-label="Clear focus" onClick={() => ws.setFocus(null)}>
            <X className="icon" aria-hidden="true" />
          </button>
        </span>
      ) : (
        <span className="muted" style={{ fontSize: 12 }}>
          {allNodes.length > 0 ? "No focus. Choose a node to trace lineage." : "Lineage"}
        </span>
      )}

      <div className="segmented" role="group" aria-label="Trace direction">
        {DIRECTIONS.map((item) => (
          <button
            key={item.value}
            type="button"
            aria-pressed={ws.focus?.direction === item.value}
            disabled={!ws.focus}
            onClick={() => ws.setDirection(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <KindFilter nodes={allNodes} />

      <button type="button" className="icon-btn" aria-label="Fit graph to view" title="Fit (F)" onClick={ws.fitGraph}>
        <Maximize className="icon" aria-hidden="true" />
      </button>

      <span className="toolbar-spacer" />

      <span className="toolbar-counts" aria-live="polite">
        {visibleNodes.length} nodes · {visibleEdges.length} edges
        {ws.hiddenKinds.size > 0 || focusTrace ? ` (of ${allNodes.length} / ${allEdges.length})` : ""}
      </span>

      <button
        type="button"
        className={`btn small${indexedCount < scopeRepos.length || warningCount > 0 ? "" : " ghost"}`}
        onClick={() => ws.openDialog("coverage")}
        title="Coverage and warnings"
      >
        Coverage {indexedCount}/{scopeRepos.length}
        {warningCount > 0 ? ` · ${warningCount} warning${warningCount === 1 ? "" : "s"}` : ""}
      </button>
    </div>
  );

  const notices = (
    <div className="notice-row">
      {ws.graph.error ? <ResourceNotice tone="bad" title="Graph refresh failed" text={ws.graph.error} /> : null}
      {latestFailed && graph && graph.snapshots.length > 0 ? (
        <ResourceNotice
          tone="warn"
          title={`Latest job ${ws.latestJob?.status}`}
          text={`${ws.latestJob?.error ? `${ws.latestJob.error}. ` : ""}Showing the last completed snapshot.`}
        />
      ) : null}
      {ws.focus && ws.trace.error ? (
        <ResourceNotice tone="bad" title="Trace failed" text={ws.trace.error} />
      ) : null}
      {focusTrace?.truncated ? (
        <ResourceNotice
          tone="warn"
          title="Trace truncated"
          text={`Lineage stops at depth ${focusTrace.max_depth}. Narrow the focus to see the rest.`}
        />
      ) : null}
      {focusTrace && focusTrace.unresolved_gaps.length > 0 ? (
        <ResourceNotice
          tone="warn"
          title={`${focusTrace.unresolved_gaps.length} unresolved symbolic reference${focusTrace.unresolved_gaps.length === 1 ? "" : "s"}`}
          text="Bind them in Mappings to stitch these references to physical datasets."
        />
      ) : null}
      {graph && !ws.staticNoticeDismissed && allNodes.length > 0 ? (
        <ResourceNotice
          tone="info"
          title="Static analysis"
          text="Shows possible, not proven, runtime lineage."
          onDismiss={ws.dismissStaticNotice}
        />
      ) : null}
    </div>
  );

  let body: ReactNode;
  if (graph && allNodes.length === 0) {
    body = (
      <div className="center-state">
        <div className="card">
          <p className="card-title">{graph.snapshots.length === 0 ? "No completed analysis yet" : "No lineage entities found"}</p>
          <p className="card-text">
            {graph.snapshots.length === 0
              ? `Nothing has completed for ${ws.scope === "all" ? "any repository" : ws.repo?.name ?? "this repository"} in environment ${ws.environment}. Analysis reads files, so a completed job is required before the graph shows anything.`
              : "No lineage entities found in indexed files. The analysis completed, but no datasets, programs or transformations were extracted."}
          </p>
          {graph.snapshots.length === 0 ? (
            <div className="row-inline">
              <button
                type="button"
                className="btn primary"
                disabled={ws.scope === "all" || !ws.repo}
                title={ws.scope === "all" ? "Select a repository to run analysis" : undefined}
                onClick={() => ws.openDialog("run")}
              >
                <Play className="icon" aria-hidden="true" />
                Run analysis
              </button>
              {ws.scope === "all" ? <span className="hint">Pick one repository first.</span> : null}
            </div>
          ) : null}
        </div>
      </div>
    );
  } else if (focusTrace && focusTrace.nodes.length === 0) {
    body = (
      <div className="center-state">
        <div className="card">
          <p className="card-title">Focus is not in this graph</p>
          <p className="card-text">The focused node is missing from the current scope or environment.</p>
          <div className="row-inline">
            <button type="button" className="btn" onClick={() => ws.setFocus(null)}>
              Clear focus
            </button>
          </div>
        </div>
      </div>
    );
  } else if (showFocusList) {
    body = <FocusList nodes={allNodes} unresolvedIds={unresolvedIds} />;
  } else {
    body = (
      <div className="canvas-wrap">
        {ws.focus && ws.trace.loading ? (
          <div className="canvas-loading" role="status">
            <span className="spinner-dot" aria-hidden="true" /> Tracing lineage…
          </div>
        ) : null}
        {visibleNodes.length === 0 ? (
          <div className="center-state">
            <StatusLine text="Every node is hidden by the kind filter. Re-enable a kind to see the graph." />
          </div>
        ) : (
          <LineageCanvas
            nodes={visibleNodes}
            edges={visibleEdges}
            roles={roles}
            unresolvedIds={unresolvedIds}
            selection={ws.selection}
            centerRequest={ws.centerRequest}
            fitNonce={ws.fitNonce}
            onSelectNode={ws.selectNode}
            onFocusNode={(id) => ws.setFocus(id, ws.focus?.direction ?? "both")}
            onSelectEdge={ws.selectEdge}
            onClearSelection={ws.clearSelection}
          />
        )}
      </div>
    );
  }

  return (
    <div className="main-content" style={{ display: "flex", flexDirection: "column", flex: "1 1 auto", minHeight: 0 }}>
      {toolbar}
      {notices}
      {body}
    </div>
  );
}

function KindFilter({ nodes }: { nodes: { kind: string }[] }) {
  const ws = useWorkspace();
  const counts = new Map<string, number>();
  for (const node of nodes) counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1);
  const kinds = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  if (kinds.length === 0) return null;
  const shown = kinds.length - kinds.filter(([kind]) => ws.hiddenKinds.has(kind)).length;
  return (
    <details className="details-menu">
      <summary aria-label={`Filter kinds, ${shown} of ${kinds.length} shown`}>
        Kinds <span className="count">{shown}/{kinds.length}</span>
      </summary>
      <div className="menu-panel" role="group" aria-label="Visible kinds">
        {kinds.map(([kind, count]) => {
          const Icon = kindIcon(kind);
          return (
            <label key={kind} className="check-row">
              <input
                type="checkbox"
                checked={!ws.hiddenKinds.has(kind)}
                onChange={() => ws.toggleKind(kind)}
              />
              <Icon className="icon" aria-hidden="true" />
              <span>{kindName(kind)}</span>
              <span className="count">{count}</span>
            </label>
          );
        })}
      </div>
    </details>
  );
}
