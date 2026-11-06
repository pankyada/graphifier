"use client";

import { Handle, NodeToolbar, Position, type Node, type NodeProps } from "@xyflow/react";
import { ArrowLeft, ArrowRight, CircleAlert, Crosshair, Database, FileSearch } from "lucide-react";
import { useMemo } from "react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import type { GraphNode, TraceDirection } from "@/lib/types";
import { displayName, kindColor, kindIcon, kindName } from "./kinds";

export type LineageRole = "focus" | "upstream" | "downstream" | null;
export type PathRole = "self" | "upstream" | "downstream" | "dim" | null;

export interface LineageNodeData extends Record<string, unknown> {
  node: GraphNode;
  role: LineageRole;
  path: PathRole;
  unresolved: boolean;
  selected: boolean;
}

export type LineageFlowNode = Node<LineageNodeData, "lineage">;

/** Readable node card: kind icon, short name, kind and schema, state badge and evidence count. */
export function NodeCard({ data, id }: NodeProps<LineageFlowNode>) {
  const { node, role, path, unresolved, selected } = data;
  const canonical = node.attributes?.canonical === true;
  const Icon = unresolved ? CircleAlert : canonical ? Database : kindIcon(node.kind);
  const evidenceCount = node.evidence?.length ?? 0;
  const { primary, prefix } = displayName(node);
  const color = unresolved ? undefined : kindColor(node.kind);

  const classes = [
    "node-card",
    role === "focus" ? "is-focus" : "",
    role === "upstream" ? "is-upstream" : "",
    role === "downstream" ? "is-downstream" : "",
    unresolved ? "is-unresolved" : "",
    canonical ? "is-canonical" : "",
    selected ? "is-selected" : "",
    path === "dim" ? "is-dim" : "",
    path === "upstream" ? "lit-upstream" : "",
    path === "downstream" ? "lit-downstream" : "",
    path === "self" ? "lit-self" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const roleText = role && role !== "focus" ? ` (${role})` : "";

  return (
    <div className={classes} title={`${kindName(node.kind)}: ${node.name}${roleText}`}>
      <NodeToolbar isVisible={selected} position={Position.Top} offset={10}>
        <NodeActions id={id} />
      </NodeToolbar>
      <Handle type="target" position={Position.Left} isConnectable={false} style={{ opacity: 0 }} />
      <div
        className="node-kind-icon"
        aria-hidden="true"
        style={color ? { color, background: `${color}14` } : undefined}
      >
        <Icon className="icon" />
      </div>
      <div className="node-body">
        <div className="node-name">{primary}</div>
        <div className="node-sub">
          <span className="truncate">
            {node.kind}
            {prefix ? ` · ${prefix}` : ""}
          </span>
          <span className="node-evidence" title={`${evidenceCount} evidence entries`}>
            <FileSearch style={{ width: 12, height: 12 }} aria-hidden="true" />
            {evidenceCount}
          </span>
        </div>
      </div>
      {unresolved ? (
        <span className="node-badge amber">unresolved</span>
      ) : canonical ? (
        <span className="node-badge">canonical</span>
      ) : null}
      <Handle type="source" position={Position.Right} isConnectable={false} style={{ opacity: 0 }} />
    </div>
  );
}

const ACTIONS: { direction: TraceDirection; label: string; hint: string }[] = [
  { direction: "in", label: "Upstream", hint: "Trace what feeds this node (U)" },
  { direction: "both", label: "Trace", hint: "Trace both directions (B)" },
  { direction: "out", label: "Downstream", hint: "Trace what this node feeds (D)" },
];

/** Floats over the selected node and heads the inspector, so tracing is always one click away. */
export function NodeActions({ id }: { id: string }) {
  const ws = useWorkspace();
  const edges = ws.graph.data?.edges;
  const counts = useMemo(() => {
    const result = { in: 0, out: 0 };
    for (const edge of edges ?? []) {
      if (edge.target === id) result.in += 1;
      if (edge.source === id) result.out += 1;
    }
    return result;
  }, [edges, id]);

  return (
    <div className="node-actions nodrag nopan" role="group" aria-label="Trace lineage">
      {ACTIONS.map(({ direction, label, hint }) => {
        const Icon = direction === "in" ? ArrowLeft : direction === "out" ? ArrowRight : Crosshair;
        const active = ws.focus?.id === id && ws.focus.direction === direction;
        const count = direction === "in" ? counts.in : direction === "out" ? counts.out : null;
        return (
          <button
            key={direction}
            type="button"
            title={hint}
            aria-pressed={active}
            disabled={count === 0 || counts.in + counts.out === 0}
            onClick={(event) => {
              event.stopPropagation();
              ws.setFocus(id, direction);
            }}
          >
            <Icon className="icon" aria-hidden="true" />
            {label}
            {count !== null ? <span className="node-action-count">{count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
