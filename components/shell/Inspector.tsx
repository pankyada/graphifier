"use client";

import { Fragment, useEffect, useState } from "react";
import { ArrowRight, Copy, PanelRight, X } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { EvidenceList } from "@/components/evidence/EvidenceList";
import { CodeViewer } from "@/components/evidence/CodeViewer";
import { MappingPanel } from "@/components/mapping/MappingPanel";
import { kindIcon, kindName } from "@/components/graph/kinds";
import { evidenceTarget, type ViewerTarget } from "@/lib/evidence";
import { explainEdge, explainNode, isSymbolicExpression } from "@/lib/explain";
import { relativeTime, sha8, truncateText } from "@/lib/format";
import type { GraphEdge, GraphNode } from "@/lib/types";
import type { InspectorTab } from "@/components/workspace/useWorkspace";

const TABS: { value: InspectorTab; label: string }[] = [
  { value: "evidence", label: "Evidence" },
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
  const graphSnapshots = ws.graph.data?.snapshots;

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
  const title = node ? node.name : edge ? edge.kind.replace(/_/g, " ").toLowerCase() : "Inspector";
  const Icon = node ? kindIcon(node.kind) : null;

  return (
    <aside className={`inspector${drawerOpen ? " is-open" : ""}`} aria-label="Inspector">
      <div className="drawer-head">
        <span className="label">Inspector</span>
        <button type="button" className="icon-btn" aria-label="Close inspector" onClick={() => ws.setInspectorDrawerOpen(false)}>
          <X className="icon" aria-hidden="true" />
        </button>
      </div>

      <div className="inspector-head">
        <div className="inspector-title-row">
          {node && Icon ? (
            <span className="chip">
              <Icon className="icon" aria-hidden="true" />
              {kindName(node.kind)}
            </span>
          ) : edge ? (
            <span className="chip">{edge.kind.replace(/_/g, " ").toLowerCase()}</span>
          ) : null}
          <h2 className="inspector-title" title={title}>
            {title}
          </h2>
          <span className="grow" />
          <button
            type="button"
            className="icon-btn topbar-desktop-only"
            aria-label="Hide inspector"
            title="Hide inspector (])"
            onClick={ws.toggleInspector}
          >
            <PanelRight className="icon" aria-hidden="true" />
          </button>
        </div>
        {node || edge ? (
          <div className="inspector-sub">
            <span className="mono truncate" title={selection?.id}>
              {selection?.id}
            </span>
            <CopyButton value={selection?.id ?? ""} label="Copy id" />
          </div>
        ) : null}
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
          </button>
        ))}
      </div>

      <div className="tabpanel" role="tabpanel" id="inspector-panel" aria-labelledby={`tab-${ws.inspectorTab}`}>
        {ws.inspectorTab === "evidence" ? (
          !node && !edge ? (
            <p className="muted" style={{ margin: 0 }}>
              Select a node or edge to see indexed evidence.
            </p>
          ) : (
            <>
              {edge && node === null ? (
                <EdgeHeader edge={edge} />
              ) : null}
              <section aria-label="Evidence">
                <div className="label" style={{ marginBottom: 6 }}>
                  Evidence · {evidence.length}
                </div>
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

        {ws.inspectorTab === "details" ? (
          node ? (
            <NodeDetails node={node} />
          ) : edge ? (
            <EdgeDetails edge={edge} />
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              Select a node or edge to see its details.
            </p>
          )
        ) : null}

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
  const edges = ws.graph.data?.edges ?? [];
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

  return (
    <>
      <KeyValue
        rows={[
          ["Kind", kindName(node.kind)],
          ["Name", node.name],
          ["Repositories", repoNames.join(", ") || "—"],
          ["Canonical", node.attributes?.canonical === true ? "yes" : "no"],
          ["Evidence", String(node.evidence?.length ?? 0)],
        ]}
      />

      {expression ? (
        <section aria-label="Raw expression">
          <div className="label" style={{ marginBottom: 6 }}>
            Raw expression (never executed)
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
  return (
    <button
      type="button"
      className="icon-btn"
      aria-label={label}
      title={label}
      disabled={!value}
      onClick={() => void navigator.clipboard?.writeText(value)}
    >
      <Copy className="icon" aria-hidden="true" />
    </button>
  );
}
