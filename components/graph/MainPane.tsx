"use client";

import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowLeftRight, ArrowRight, ChevronRight, Crosshair, Minus, Play, Plus, RefreshCw, X } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { isNarrowViewport } from "@/components/workspace/useWorkspace";
import { Onboarding } from "@/components/repos/Onboarding";
import { isSymbolicExpression } from "@/lib/explain";
import { traceDepths, traceSides } from "@/lib/layout";
import type { GraphGranularity, TraceDirection } from "@/lib/types";
import { LineageCanvas } from "./LineageCanvas";
import { pickHubs } from "./hubs";
import { displayName } from "./kinds";
import { GuidedHint } from "./GuidedHint";
import type { LineageRole } from "./NodeCard";
import { ApiDown } from "@/components/shell/ApiDown";
import { StatusLine } from "@/components/shell/StatusLine";
import { ResourceNotice } from "@/components/shell/ResourceNotice";

const DIRECTIONS: { value: TraceDirection; label: string; icon: typeof ArrowLeft }[] = [
  { value: "in", label: "Upstream", icon: ArrowLeft },
  { value: "both", label: "Both", icon: ArrowLeftRight },
  { value: "out", label: "Downstream", icon: ArrowRight },
];

const DETAIL_HINTS: Record<GraphGranularity, string> = {
  overview: "Architecture groups, observed responsibilities and consolidated dependencies. Open a group to explore its contents.",
  interfaces: "Modules and implementation components within the selected scope, with their external connections.",
  detail: "Detailed implementation and lineage within this scope. Test visibility and display limits still apply.",
};

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
          <p className="card-text">Pick a repository in the scope switcher, or choose All repositories for the aggregate graph.</p>
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

  // Depth narrows an already-loaded trace on the client. null shows every hop the API returned.
  const [depth, setDepth] = useState<number | null>(null);
  const focusId = ws.focus?.id ?? null;
  useEffect(() => setDepth(null), [focusId, ws.focus?.direction]);

  const depths = useMemo(
    () => (focusId && focusTrace ? traceDepths(focusId, focusTrace.edges) : null),
    [focusId, focusTrace],
  );
  const maxDepth = depths ? Math.max(0, ...depths.values()) : 0;

  const selectedNodeId = ws.selection?.kind === "node" ? ws.selection.id : null;

  const [canvasLimit, setCanvasLimit] = useState<number | "all">(ws.graphGranularity === "detail" ? 100 : "all");
  useEffect(() => { setCanvasLimit(ws.graphGranularity === "detail" ? 100 : "all"); }, [ws.graphGranularity, ws.hierarchyScope, ws.repoId]);

  const { visibleNodes, visibleEdges, hubsOnly } = useMemo(() => {
    const baseEdges = focusTrace ? focusTrace.edges : allEdges;
    let baseNodes = focusTrace ? focusTrace.nodes : allNodes;
    if (focusTrace && focusId) {
      // A "both" trace can arrive with side branches reached through shared parents. Lineage is only
      // what flows into or out of the focus, so keep the directed reach.
      const sides = traceSides(focusId, focusTrace.edges);
      baseNodes = baseNodes.filter((node) => node.id === focusId || sides.upstream.has(node.id) || sides.downstream.has(node.id));
    }
    const filtered = baseNodes.filter(
      (node) =>
        !ws.hiddenKinds.has(node.kind) && (depth === null || !depths || (depths.get(node.id) ?? 0) <= depth),
    );
    // Too many nodes to read at once: open on the most-connected ones.
    const capped = !focusTrace && canvasLimit !== "all" && filtered.length > canvasLimit;
    const nodes = capped ? pickHubs(filtered, baseEdges, selectedNodeId ?? focusId, canvasLimit) : filtered;
    const ids = new Set(nodes.map((node) => node.id));
    const edges = baseEdges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
    return { visibleNodes: nodes, visibleEdges: edges, hubsOnly: capped };
  }, [focusTrace, focusId, allNodes, allEdges, ws.hiddenKinds, depth, depths, selectedNodeId, canvasLimit]);

  const roles = useMemo(() => {
    const map = new Map<string, Exclude<LineageRole, null>>();
    if (!ws.focus || !focusTrace) return map;
    const sides = traceSides(ws.focus.id, focusTrace.edges);
    for (const id of sides.upstream) map.set(id, "upstream");
    for (const id of sides.downstream) map.set(id, "downstream");
    map.set(ws.focus.id, "focus");
    return map;
  }, [ws.focus, focusTrace]);

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

  // Long trails keep the start and the most recent hops.
  const trail =
    ws.focusTrail.length > 4
      ? [ws.focusTrail[0], ...ws.focusTrail.slice(-3)]
      : ws.focusTrail;

  const showTrace = !!ws.focus || !!selectedNodeId;

  const toolbar = (
    <div className={`graph-toolbar${ws.focus ? " has-focus" : ""}`} role="toolbar" aria-label="Lineage toolbar">
      <div className="toolbar-cluster">
        <div className="segmented" role="group" aria-label="Graph view">
          <button type="button" aria-pressed={ws.graphView === "flow"} onClick={() => ws.setGraphView("flow")}>Flow</button>
          <button type="button" aria-pressed={ws.graphView === "constellation"} onClick={() => ws.setGraphView("constellation")}>Constellation</button>
        </div>
        {graph?.ai_hierarchy && graph.ai_hierarchy.status !== "not_requested" ? <div className="segmented" role="group" aria-label="Grouping basis"><button type="button" aria-pressed={ws.hierarchyMode === "ai"} onClick={() => ws.setHierarchyMode("ai")}>AI grouping</button><button type="button" aria-pressed={ws.hierarchyMode === "deterministic"} onClick={() => ws.setHierarchyMode("deterministic")}>Source structure</button></div> : null}
        <label className="graph-detail-level" title={DETAIL_HINTS[ws.graphGranularity]}>
          <span className="sr-only">Graph detail level</span>
          <select className="select" value={ws.graphGranularity} onChange={(event) => ws.setGraphGranularity(event.target.value as GraphGranularity)}>
            <option value="overview">Architecture</option>
            <option value="interfaces">Components</option>
            <option value="detail">Full detail</option>
          </select>
        </label>
      </div>

      <label className="toolbar-cluster" title={focusTrace ? "Loaded trace paths are shown without a canvas cap to preserve intermediate steps." : "Canvas limit only: ranks loaded nodes by connectivity and keeps the selected node visible. All loaded does not fetch the entire repository."}><span>Canvas</span><select className="select" aria-label="Canvas display limit" disabled={!!focusTrace} value={focusTrace ? "all" : canvasLimit} onChange={(event) => setCanvasLimit(event.target.value === "all" ? "all" : Number(event.target.value))}><option value="40">40 nodes</option><option value="100">100 nodes</option><option value="250">250 nodes</option><option value="all">All loaded</option></select></label>
      <nav className="toolbar-cluster" aria-label="Architecture location">
        <button className="btn small" onClick={() => ws.openGroup(null)}>All components</button>
        {(graph?.breadcrumbs ?? []).map((crumb) => <button key={crumb.id} className="btn small" onClick={() => ws.openGroup(crumb.id, crumb.level === "overview" ? "interfaces" : "detail")}>{crumb.name}</button>)}
      </nav>
      <label className="toolbar-cluster"><input type="checkbox" checked={ws.includeTests} onChange={(event) => { ws.setIncludeTests(event.target.checked); ws.setFocus(null); }} />Include tests{!ws.includeTests && graph?.counts?.hidden_test_nodes ? ` (${graph.counts.hidden_test_nodes} hidden)` : ""}</label>
      {ws.focus ? (
        <nav className="toolbar-cluster focus-trail" aria-label="Focus trail">
          <Crosshair className="icon" aria-hidden="true" />
          {trail.map((id, index) => {
            const node = ws.nodeIndex.get(id);
            const name = node ? displayName(node).primary : id;
            const current = index === trail.length - 1;
            return (
              <Fragment key={id}>
                {index > 0 ? <ChevronRight className="focus-trail-sep" aria-hidden="true" /> : null}
                <button
                  type="button"
                  className="focus-crumb truncate"
                  aria-current={current ? "step" : undefined}
                  title={node?.name ?? id}
                  onClick={() => (current ? ws.centerOn(id) : ws.setFocus(id, ws.focus?.direction ?? "both"))}
                >
                  {name}
                </button>
              </Fragment>
            );
          })}
          <button type="button" className="icon-btn" aria-label="Clear focus" title="Clear focus (Esc)" onClick={() => ws.setFocus(null)}>
            <X className="icon" aria-hidden="true" />
          </button>
        </nav>
      ) : null}

      {showTrace ? (
        <div className="toolbar-cluster toolbar-end">
          <div className="segmented" role="group" aria-label="Trace direction">
            {DIRECTIONS.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.value}
                  type="button"
                  aria-label={item.label}
                  aria-pressed={ws.focus?.direction === item.value}
                  title={item.label}
                  onClick={() => {
                    if (ws.focus) ws.setDirection(item.value);
                    else if (selectedNodeId) ws.setFocus(selectedNodeId, item.value);
                  }}
                >
                  <Icon className="icon" aria-hidden="true" />
                  <span className="seg-label">{item.label}</span>
                </button>
              );
            })}
          </div>
          {ws.focus && maxDepth > 1 ? (
            <div className="stepper" role="group" aria-label="Trace depth">
              <button
                type="button"
                aria-label="Show fewer hops"
                disabled={(depth ?? maxDepth) <= 1}
                onClick={() => setDepth(Math.max(1, (depth ?? maxDepth) - 1))}
              >
                <Minus className="icon" aria-hidden="true" />
              </button>
              <span aria-live="polite">
                {depth === null || depth >= maxDepth ? `${maxDepth} hops` : `${depth}/${maxDepth} hops`}
              </span>
              <button
                type="button"
                aria-label="Show more hops"
                disabled={depth === null || depth >= maxDepth}
                onClick={() => setDepth(depth === null || depth + 1 >= maxDepth ? null : depth + 1)}
              >
                <Plus className="icon" aria-hidden="true" />
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  // Only live failures interrupt the canvas. Everything else lives in the attention menu.
  const errors = (
    <>
      {ws.graph.error ? <ResourceNotice tone="bad" title="Graph refresh failed" text={ws.graph.error} /> : null}
      {ws.focus && ws.trace.error ? <ResourceNotice tone="bad" title="Trace failed" text={ws.trace.error} /> : null}
    </>
  );

  const loadedCount = focusTrace ? focusTrace.nodes.length : allNodes.length;
  const scopeTotal = !focusTrace ? graph?.counts?.scope_nodes : undefined;
  const caption = `${visibleNodes.length} shown / ${loadedCount} loaded${scopeTotal !== undefined ? ` · ${scopeTotal} in scope` : ""} · ${visibleEdges.length} visible edges${hubsOnly ? " · canvas limit: most-connected nodes" : ""}${(focusTrace?.truncated ?? graph?.truncated) ? " · server window limited; narrow scope or search to find more" : ""}`;

  let body: ReactNode;
  if (!graph && ws.graph.loading) {
    body = <div className="center-state" role="status">Loading graph…</div>;
  } else if (graph && allNodes.length === 0 && ws.graphQuery) {
    body = <div className="center-state"><p>No entities match “{ws.graphQuery}”. Try another name or clear the search.</p></div>;
  } else if (graph && allNodes.length === 0) {
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
  } else {
    body = (
      <div className="canvas-wrap">
        {ws.focus && ws.trace.loading ? (
          <div className="canvas-loading" role="status">
            <span className="spinner-dot" aria-hidden="true" /> Tracing lineage…
          </div>
        ) : null}
        {visibleNodes.length > 0 ? <GuidedHint /> : null}
        {visibleNodes.length === 0 ? (
          <div className="center-state">
            <StatusLine text="Every node is hidden by the kind filter. Re-enable a kind to see the graph." />
          </div>
        ) : (
          <LineageCanvas
            view={ws.graphView}
            nodes={visibleNodes}
            edges={visibleEdges}
            roles={roles}
            unresolvedIds={unresolvedIds}
            selection={ws.selection}
            centerRequest={ws.centerRequest}
            focusId={focusId}
            sheetWidth={ws.inspectorHidden || isNarrowViewport() ? 0 : ws.inspectorWidth}
            fitNonce={ws.fitNonce}
            onSelectNode={ws.selectNode}
            onNavigateNode={(id) => {
              ws.selectNode(id);
              ws.centerOn(id);
            }}
            onFocusNode={(id) => ws.setFocus(id, ws.focus?.direction ?? "both")}
            onSelectEdge={ws.selectEdge}
            onClearSelection={ws.clearSelection}
          />
        )}
        {visibleNodes.length > 0 ? (
          <span className="canvas-caption" aria-live="polite">
            {ws.graph.loading ? "Loading… " : ""}
            {caption}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div className="main-content">
      <div className="hud">
        {toolbar}
        {errors}
        {graph?.ai_hierarchy?.status === "partial" ? <div className="note-line" role="status"><strong>AI grouping is incomplete.</strong> Components without validated AI grouping retain their source structure.{graph.ai_hierarchy.warnings?.length ? <details><summary>Grouping coverage ({graph.ai_hierarchy.warnings.length})</summary><ul>{graph.ai_hierarchy.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details> : null}</div> : null}
        {ws.graphQuery && graph?.search_matches?.length ? <div className="hierarchy-search" aria-label="Detailed search results">{graph.search_matches.map((match) => <button key={match.node.id} className="btn small" onClick={() => { ws.openGroup(match.ancestors.at(-1) ?? null, "detail", match.node.id); ws.selectNode(match.node.id); ws.centerOn(match.node.id); }}><strong>{match.node.name}</strong><span className="hint">{match.node.kind} · {match.groups.map((group) => group.name).join(" / ")}</span></button>)}</div> : null}
      </div>
      {body}
    </div>
  );
}
