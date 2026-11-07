"use client";

import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { ArrowLeft, ArrowRight, Check, ChevronRight, CircleDashed, Command, Copy, Crosshair } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { EvidenceList } from "@/components/evidence/EvidenceList";
import { CodeViewer } from "@/components/evidence/CodeViewer";
import { MappingPanel } from "@/components/mapping/MappingPanel";
import { displayName, kindColor, kindIcon, kindName } from "@/components/graph/kinds";
import { NodeActions } from "@/components/graph/NodeCard";
import { setHighlight } from "@/lib/highlight";
import { evidenceTarget, summarizeEvidence, type ViewerTarget } from "@/lib/evidence";
import { explainEdge, explainNode, isSymbolicExpression } from "@/lib/explain";
import { relativeTime, sha8, truncateText } from "@/lib/format";
import { api } from "@/lib/api";
import { useCountUp } from "@/lib/useCountUp";
import type { GraphEdge, GraphNode } from "@/lib/types";
import type { ReactNode } from "react";
import type { InspectorTab } from "@/components/workspace/useWorkspace";

const TABS: { value: InspectorTab; label: string }[] = [
  { value: "evidence", label: "Evidence" },
  { value: "links", label: "Links" },
  { value: "details", label: "Details" },
  { value: "mapping", label: "Mapping" },
];

export function Inspector() {
  const ws = useWorkspace();
  const selection = ws.selection;
  const node = selection?.kind === "node" ? (ws.nodeIndex.get(selection.id) ?? null) : null;
  const edge = selection?.kind === "edge" ? (ws.edgeIndex.get(selection.id) ?? null) : null;
  const fallbackRepoId = ws.scope === "repo" ? ws.repoId : null;
  const evidence = node?.evidence ?? edge?.evidence ?? [];

  const ownerSnapshots = node?.snapshots ?? edge?.snapshots;
  const graphSnapshots = (ws.focus ? ws.trace.data?.snapshots : undefined) ?? ws.graph.data?.snapshots;
  const provenance = summarizeEvidence(evidence, fallbackRepoId);
  const relatedWarnings = (ws.graph.data?.warnings ?? []).filter((entry) => provenance.repositoryIds.has(entry.repo_id));
  const visibleEdges = (ws.focus ? ws.trace.data?.edges : undefined) ?? ws.graph.data?.edges;

  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const selectionKey = selection ? `${selection.kind}|${selection.id}` : "";

  // Open the first evidence span of each new selection so the source is visible at once.
  useEffect(() => {
    const first = evidence[0];
    if (!first) {
      setViewer(null);
      return;
    }
    setViewer(
      evidenceTarget(first, {
        fallbackRepoId,
        environment: ws.environment,
        ownerSnapshots,
        graphSnapshots,
      }),
    );
    // Only the selection drives this; evidence identity changes with it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionKey]);

  const drawerOpen = ws.inspectorDrawerOpen;
  const title = node ? displayName(node).primary : edge ? edge.kind.replace(/_/g, " ").toLowerCase() : "Overview";
  const linkCount = useMemo(() => {
    if (edge) return 2;
    if (!node) return 0;
    return neighbors(node.id, visibleEdges ?? []).reduce((sum, group) => sum + group.size, 0);
  }, [node, edge, visibleEdges]);
  const tabCount = (tab: InspectorTab) =>
    !node && !edge ? 0 : tab === "evidence" ? provenance.spans : tab === "links" ? linkCount : 0;
  const Icon = node ? kindIcon(node.kind) : null;

  return (
    <aside
      className={`inspector${drawerOpen ? " is-open" : ""}`}
      aria-label="Inspector"
      style={{ "--sheet-tint": node ? kindColor(node.kind) : "var(--accent-600)" } as CSSProperties}
    >
      <div className="inspector-head" key={selectionKey}>
        <div className="inspector-title-row">
          {node && Icon ? (
            <span className="chip">
              <Icon className="icon" aria-hidden="true" />
              {kindName(node.kind)}
            </span>
          ) : edge ? (
            <span className="chip">{edge.kind.replace(/_/g, " ").toLowerCase()}</span>
          ) : null}
          <h2 className="inspector-title" title={node?.name ?? title}>
            {title}
          </h2>
        </div>
        {node || edge ? (
          <div className="inspector-sub">
            <span className="mono truncate" title={selection?.id}>
              {selection?.id}
            </span>
            <CopyButton value={selection?.id ?? ""} label="Copy id" />
          </div>
        ) : null}
        {node && (node.kind === "architecture" || node.kind === "component") ? <div className="hierarchy-summary"><p>{String(node.attributes.summary ?? "")}</p><p className="hint">{String(node.attributes.member_count ?? 0)} members · {String(node.attributes.basis ?? "Repository structure")}</p><button className="btn primary" onClick={() => ws.openGroup(node.id, node.kind === "component" || ws.graph.data?.recommended_levels?.length === 2 ? "detail" : "interfaces")}>Explore contents</button></div> : node ? <NodeActions id={node.id} /> : null}
        {edge && ws.graph.data?.generation && edge.attributes.support_count ? <EdgeSupport key={`${ws.graph.data.generation}:${edge.id}`} generation={ws.graph.data.generation} edgeId={edge.id} onOpen={setViewer} /> : null}
        {node?.attributes.ai_summary || node?.attributes.ai_name ? <div className="hierarchy-summary"><span className="chip">AI assisted · {String(node.attributes.model ?? node.attributes.ai_model ?? "configured model")}</span><p>{String(node.attributes.ai_summary ?? "")}</p>{node.attributes.rationale ? <p className="hint">{String(node.attributes.rationale)}</p> : null}{node.attributes.confidence !== undefined ? <p className="hint">Model-assessed confidence: {String(node.attributes.confidence)} (not a measured probability)</p> : null}</div> : null}
        {node && Array.isArray(node.attributes.cited_node_ids) && ws.graph.data?.generation ? <GroupingCitations key={`${ws.graph.data.generation}:${node.id}`} ids={node.attributes.cited_node_ids.filter((id): id is string => typeof id === "string")} generation={ws.graph.data.generation} /> : null}
        {node?.attributes.context ? <p className="hint">Context: {String(node.attributes.context)} · {String(node.attributes.context_reason ?? node.attributes.context_basis ?? "Source classification")}</p> : null}
        {node?.attributes.is_test === true ? <span className="chip">Testing component</span> : null}
      </div>

      <div className="tabs" role="tablist" aria-label="Inspector sections">
        {TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            id={`tab-${tab.value}`}
            aria-selected={ws.inspectorTab === tab.value}
            aria-controls="inspector-panel"
            className="tab"
            disabled={tab.value === "mapping" && ws.scope === "all"}
            onClick={() => ws.setInspectorTab(tab.value)}
          >
            {tab.label}
            {tabCount(tab.value) > 0 ? <span className="count">{tabCount(tab.value)}</span> : null}
          </button>
        ))}
      </div>

      <div className="tabpanel" role="tabpanel" id="inspector-panel" aria-labelledby={`tab-${ws.inspectorTab}`}>
        {ws.inspectorTab !== "mapping" && !node && !edge ? <Overview /> : null}

        {ws.inspectorTab === "links" && (node || edge) ? <Links nodeId={node?.id ?? null} edge={edge} /> : null}

        {ws.inspectorTab === "evidence" && (node || edge) ? (
          (
            <>
              {edge && node === null ? (
                <EdgeHeader edge={edge} />
              ) : null}
              <section aria-label="Evidence">
                <div className="label" style={{ marginBottom: 6 }}>
                  Evidence · {provenance.spans} spans
                </div>
                <p className="hint" style={{ margin: "0 0 8px" }}>
                  {provenance.files} source files · {provenance.repositories} repositories. Each reference opens its indexed source.
                </p>
                {relatedWarnings.length > 0 ? <button type="button" className="btn" onClick={() => ws.openDialog("coverage")} style={{ marginBottom: 8 }}>
                  {relatedWarnings.length} coverage warnings in contributing repositories
                </button> : null}
                <EvidenceList
                  items={evidence}
                  fallbackRepoId={fallbackRepoId}
                  ownerSnapshots={ownerSnapshots}
                  active={viewer}
                  onOpen={setViewer}
                />
              </section>
              {viewer && viewer.repoId ? <CodeViewer target={viewer} onClose={() => setViewer(null)} /> : null}
            </>
          )
        ) : null}

        {ws.inspectorTab === "details" && node ? <NodeDetails node={node} /> : null}
        {ws.inspectorTab === "details" && edge ? <EdgeDetails edge={edge} /> : null}

        {ws.inspectorTab === "mapping" ? (
          <>
            <MappingPanel onOpenEvidence={setViewer} selectedExpression={node?.expression ?? null} />
            {viewer && viewer.repoId ? <CodeViewer target={viewer} onClose={() => setViewer(null)} /> : null}
          </>
        ) : null}
      </div>
    </aside>
  );
}

/** Direct neighbors of a node, in then out, each mapped to the edge kinds linking them. */
function neighbors(id: string, edges: GraphEdge[]): [Map<string, string[]>, Map<string, string[]>] {
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const edge of edges) {
    if (edge.target === id) incoming.set(edge.source, [...(incoming.get(edge.source) ?? []), edge.kind]);
    if (edge.source === id) outgoing.set(edge.target, [...(outgoing.get(edge.target) ?? []), edge.kind]);
  }
  return [incoming, outgoing];
}

function edgeKindText(kinds: string[]): string {
  return [...new Set(kinds)].map((kind) => kind.replace(/_/g, " ").toLowerCase()).join(", ");
}

/** Row that previews a node on the canvas on hover and walks to it on click. */
function NodeLink({ id, meta }: { id: string; meta?: string }) {
  const ws = useWorkspace();
  const node = ws.nodeIndex.get(id);
  // The row may unmount under the pointer once the selection changes.
  useEffect(() => () => setHighlight(null), []);
  if (!node) {
    return <div className="node-link mono truncate">{id}</div>;
  }
  const Icon = kindIcon(node.kind);
  return (
    <button
      type="button"
      className="node-link"
      title={node.name}
      onMouseEnter={() => setHighlight({ type: "node", id })}
      onMouseLeave={() => setHighlight(null)}
      onFocus={() => setHighlight({ type: "node", id })}
      onBlur={() => setHighlight(null)}
      onClick={() => {
        setHighlight(null);
        ws.selectNode(id);
        ws.centerOn(id);
      }}
    >
      <Icon className="icon" aria-hidden="true" style={{ color: kindColor(node.kind) }} />
      <span className="truncate node-link-name">{displayName(node).primary}</span>
      <span className="truncate node-link-meta">{meta ?? kindName(node.kind)}</span>
    </button>
  );
}

function Links({ nodeId, edge }: { nodeId: string | null; edge: GraphEdge | null }) {
  const ws = useWorkspace();
  const edges = (ws.focus ? ws.trace.data?.edges : undefined) ?? ws.graph.data?.edges;
  const [incoming, outgoing] = useMemo(() => neighbors(nodeId ?? "", edges ?? []), [nodeId, edges]);

  if (edge) {
    return (
      <>
        <LinkGroup icon={ArrowLeft} title="From">
          <NodeLink id={edge.source} />
        </LinkGroup>
        <LinkGroup icon={ArrowRight} title="To">
          <NodeLink id={edge.target} />
        </LinkGroup>
      </>
    );
  }
  return (
    <>
      <LinkGroup icon={ArrowLeft} title={`Feeds from · ${incoming.size}`}>
        {incoming.size === 0 ? <div className="empty-row">Nothing upstream in this graph.</div> : null}
        {[...incoming].map(([id, kinds]) => (
          <NodeLink key={id} id={id} meta={edgeKindText(kinds)} />
        ))}
      </LinkGroup>
      <LinkGroup icon={ArrowRight} title={`Feeds into · ${outgoing.size}`}>
        {outgoing.size === 0 ? <div className="empty-row">Nothing downstream in this graph.</div> : null}
        {[...outgoing].map(([id, kinds]) => (
          <NodeLink key={id} id={id} meta={edgeKindText(kinds)} />
        ))}
      </LinkGroup>
    </>
  );
}

function LinkGroup({ icon: Icon, title, children }: { icon: typeof ArrowLeft; title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="link-group">
      <div className="label link-group-head">
        <Icon className="icon" aria-hidden="true" />
        {title}
      </div>
      {children}
    </section>
  );
}

const TOP_CONNECTED = 6;

/** Nothing selected: what is in this graph and where to start, from loaded data only. */
function Overview() {
  const ws = useWorkspace();
  const graph = ws.graph.data;
  const unresolved = ws.symbols.data?.symbols.filter((item) => !item.resolved).length;

  const connected = useMemo(() => {
    const degree = new Map<string, number>();
    for (const edge of graph?.edges ?? []) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
    return [...degree.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, TOP_CONNECTED);
  }, [graph]);

  const startNode = connected[0] ? ws.nodeIndex.get(connected[0][0]) : undefined;
  const startName = startNode ? displayName(startNode).primary : "";

  if (!graph) {
    return (
      <p className="muted" style={{ margin: 0 }}>
        Select a node or edge to see indexed evidence.
      </p>
    );
  }

  return (
    <>
      <div className="overview-stats">
        <Stat label="Nodes" value={graph.nodes.length} />
        <Stat label="Edges" value={graph.edges.length} />
        {unresolved !== undefined ? <Stat label="Unresolved" value={unresolved} amber={unresolved > 0} /> : null}
      </div>

      <section aria-label="Start here" className="start-here">
        <div className="label">Start here</div>
        {connected[0] ? (
          <StartCard
            icon={Crosshair}
            title={`Trace ${startName}`}
            text={`The busiest node, with ${connected[0][1]} edges.`}
            onClick={() => {
              ws.setFocus(connected[0][0], "both");
              ws.centerOn(connected[0][0]);
            }}
          />
        ) : null}
        {unresolved ? (
          <StartCard
            icon={CircleDashed}
            title={`Resolve ${unresolved} unknown ${unresolved === 1 ? "table" : "tables"}`}
            text="Bind variables to real datasets and stitch the lineage."
            onClick={() => ws.setInspectorTab("mapping")}
          />
        ) : null}
        <StartCard
          icon={Command}
          title="Search everything"
          text="Jump to any node, repository or action with ⌘K."
          onClick={() => ws.openDialog("palette")}
        />
      </section>

      {connected.length > 0 ? (
        <LinkGroup icon={ArrowRight} title="Most connected">
          {connected.map(([id, count]) => (
            <NodeLink key={id} id={id} meta={`${count} edges`} />
          ))}
        </LinkGroup>
      ) : null}
    </>
  );
}

function Stat({ label, value, amber = false }: { label: string; value: number; amber?: boolean }) {
  const shown = useCountUp(value);
  return (
    <div className={`stat${amber ? " amber" : ""}`}>
      <span className="stat-value">{shown}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

function StartCard(props: { icon: typeof Command; title: string; text: string; onClick: () => void }) {
  const Icon = props.icon;
  return (
    <button type="button" className="start-card" onClick={props.onClick}>
      <span className="start-card-icon" aria-hidden="true">
        <Icon className="icon" />
      </span>
      <span className="start-card-body">
        <span className="start-card-title truncate">{props.title}</span>
        <span className="start-card-text">{props.text}</span>
      </span>
      <ChevronRight className="icon start-card-arrow" aria-hidden="true" />
    </button>
  );
}

function EdgeHeader({ edge }: { edge: GraphEdge }) {
  const ws = useWorkspace();
  const source = ws.nodeIndex.get(edge.source)?.name ?? edge.source;
  const target = ws.nodeIndex.get(edge.target)?.name ?? edge.target;
  return (
    <div className="arrow-pair" aria-label="Edge endpoints">
      <span className="truncate mono" title={source}>
        {source}
      </span>
      <ArrowRight className="icon" aria-hidden="true" />
      <span className="truncate mono" title={target}>
        {target}
      </span>
    </div>
  );
}

function NodeDetails({ node }: { node: GraphNode }) {
  const ws = useWorkspace();
  const edges = (ws.focus ? ws.trace.data?.edges : undefined) ?? ws.graph.data?.edges ?? [];
  const resolvesTo = edges.filter((edge) => edge.kind === "RESOLVES_TO" && edge.source === node.id);
  const bindingSymbols = Array.from(
    new Set(
      edges
        .filter((edge) => edge.kind === "RESOLVES_TO" && (edge.source === node.id || edge.target === node.id))
        .flatMap((edge) => (Array.isArray(edge.attributes?.bindings) ? edge.attributes.bindings : []))
        .map((binding) => (binding && typeof binding === "object" ? String((binding as { symbol?: unknown }).symbol ?? "") : ""))
        .filter(Boolean),
    ),
  );
  const expression = node.expression ?? (typeof node.attributes?.source_expression === "string" ? node.attributes.source_expression : null);
  const explanation = explainNode(node, {
    resolvesTo: resolvesTo.map((edge) => edge.target),
    boundSymbols: bindingSymbols,
  });
  const repoNames = (node.repositories ?? []).map((id) => ws.repoNames.get(id) ?? id);
  const snapshots = node.snapshots ?? [];
  const readers = edges.filter((edge) => edge.kind === "READS" && edge.target === node.id);
  const writers = edges.filter((edge) => edge.kind === "WRITES" && edge.target === node.id);
  const columns = new Set(edges.filter((edge) => edge.kind === "HAS_COLUMN" && edge.source === node.id).map((edge) => edge.target));
  const inputs = edges.filter((edge) => edge.kind === "DERIVES_FROM" && edge.target === node.id);
  const outputs = edges.filter((edge) => edge.kind === "DERIVES_FROM" && edge.source === node.id);

  return (
    <>
      <KeyValue
        rows={[
          ["Kind", kindName(node.kind)],
          ["Name", node.name],
          ["Repositories", repoNames.join(", ") || "—"],
          ["Observed data role", readers.length && writers.length ? "Read source and write target" : readers.length ? "Read source" : writers.length ? "Write target" : "Not established in loaded graph"],
          ["Loaded columns", String(columns.size)],
          ["Loaded column/data dependencies", `${inputs.length} inputs · ${outputs.length} outputs`],
          ["Canonical", node.attributes?.canonical === true ? "yes" : "no"],
          ["Evidence", String(node.evidence?.length ?? 0)],
        ]}
      />

      {expression ? (
        <section aria-label="Raw expression">
          <div className="label" style={{ marginBottom: 6 }}>
            {node.kind === "transformation" ? "Transformation expression (never executed)" : "Raw expression (never executed)"}
          </div>
          <pre className="raw-block">{expression}</pre>
          {isSymbolicExpression(expression) ? (
            <p className="hint" style={{ margin: "6px 0 0" }}>
              Contains symbolic references. Values come from applied bindings only.
            </p>
          ) : null}
        </section>
      ) : null}

      <section aria-label="Explanation">
        <div className="label" style={{ marginBottom: 6 }}>
          What this shows
        </div>
        <ul className="explain">
          {explanation.map((line, index) => (
            <li key={`${index}|${line}`}>{line}</li>
          ))}
        </ul>
      </section>

      {snapshots.length > 0 ? (
        <section aria-label="Snapshots">
          <div className="label" style={{ marginBottom: 6 }}>
            Indexed snapshots
          </div>
          <div className="table-list">
            {snapshots.map((snap) => (
              <div key={`${snap.repo_id}|${snap.snapshot_id}`} className="kv" style={{ gridTemplateColumns: "auto 1fr" }}>
                <div className="k">{ws.repoNames.get(snap.repo_id) ?? snap.repo_id}</div>
                <div className="v">
                  {sha8(snap.commit_hash) || "no commit"} · {relativeTime(snap.created_at)}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <AttributeTable attributes={node.attributes} />
    </>
  );
}

function EdgeDetails({ edge }: { edge: GraphEdge }) {
  const ws = useWorkspace();
  const source = ws.nodeIndex.get(edge.source);
  const target = ws.nodeIndex.get(edge.target);
  const explanation = explainEdge(edge, source?.name ?? edge.source, target?.name ?? edge.target);
  const via = typeof edge.attributes?.via === "string" ? edge.attributes.via : null;
  const transformation = via ? ws.nodeIndex.get(via) : undefined;
  const expression = transformation?.expression ?? (typeof edge.attributes?.expression === "string" ? edge.attributes.expression : null);
  return (
    <>
      <KeyValue
        rows={[
          ["Kind", edge.kind],
          ["Source", source ? `${source.name} (${source.kind})` : edge.source],
          ["Target", target ? `${target.name} (${target.kind})` : edge.target],
          ["Evidence", String(edge.evidence?.length ?? 0)],
        ]}
      />
      <section aria-label="Explanation">
        <div className="label" style={{ marginBottom: 6 }}>
          What this shows
        </div>
        <ul className="explain">
          {explanation.map((line, index) => (
            <li key={`${index}|${line}`}>{line}</li>
          ))}
        </ul>
      </section>
      {via ? <section aria-label="Transformation"><div className="label">Transformation</div>
        {transformation ? <NodeLink id={transformation.id} /> : <p className="hint">{via}</p>}
        {expression ? <pre className="raw-block">{expression}</pre> : null}
      </section> : null}
      <AttributeTable attributes={edge.attributes} />
    </>
  );
}

function KeyValue({ rows }: { rows: [string, string][] }) {
  return (
    <div className="kv" aria-label="Details">
      {rows.map(([key, value]) => (
        <Fragment key={key}>
          <div className="k">{key}</div>
          <div className="v">{value}</div>
        </Fragment>
      ))}
    </div>
  );
}

function AttributeTable({ attributes }: { attributes: Record<string, unknown> | undefined }) {
  const entries = Object.entries(attributes ?? {}).filter(([key]) => key !== "canonical");
  if (entries.length === 0) return null;
  return (
    <section aria-label="Attributes">
      <div className="label" style={{ marginBottom: 6 }}>
        Attributes
      </div>
      <table className="kv-table">
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key}>
              <th scope="row">{key}</th>
              <td>{truncateText(typeof value === "string" ? value : JSON.stringify(value), 320)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const Icon = copied ? Check : Copy;
  return (
    <button
      type="button"
      className="icon-btn"
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      disabled={!value}
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => {
          setCopied(true);
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => setCopied(false), 1200);
        });
      }}
    >
      <Icon className="icon" aria-hidden="true" style={copied ? { color: "var(--ok-600)" } : undefined} />
    </button>
  );
}

function EdgeSupport({ generation, edgeId, onOpen }: { generation: string; edgeId: string; onOpen: (target: ViewerTarget) => void }) {
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState<number | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (offset === null) return;
    const controller = new AbortController();
    setLoading(true); setError(null);
    api.edgeSupport(generation, edgeId, offset, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setEdges((old) => offset === 0 ? result.edges : [...old, ...result.edges]); setTotal(result.total);
    }).catch((error) => { if (!controller.signal.aborted) setError(String(error)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [generation, edgeId, offset, retry]);
  return <div className="hierarchy-summary"><button className="btn small" disabled={loading || (total !== null && edges.length >= total)} onClick={() => { setOffset(edges.length); setRetry((value) => value + 1); }}>{loading ? "Loading support…" : total === null ? "Show supporting relationships" : `Load more (${edges.length}/${total})`}</button>
    {error ? <p role="alert">{error}</p> : null}
    {edges.map((edge) => <div key={edge.id}><p className="hint">{edge.kind} · {edge.source} → {edge.target}</p><EvidenceList items={edge.evidence} fallbackRepoId={null} ownerSnapshots={edge.snapshots} active={null} onOpen={onOpen} /></div>)}
  </div>;
}

function GroupingCitations({ ids, generation }: { ids: string[]; generation: string }) {
  const ws = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return <details className="hierarchy-summary"><summary>AI source references ({ids.length})</summary>
    {ids.map((id) => <button key={id} className="btn small" disabled={busy} onClick={async () => {
      setBusy(true); setError(null);
      try {
        const location = await api.graphLocation(generation, id);
        ws.openGroup(location.ancestors.at(-1) ?? null, "detail", id); ws.selectNode(id); ws.centerOn(id);
      } catch (error) { setError(error instanceof Error ? error.message : "Could not reveal source reference"); }
      finally { setBusy(false); }
    }}>{ws.nodeIndex.get(id)?.name ?? id}</button>)}
    {error ? <p role="alert">{error}</p> : null}
  </details>;
}
