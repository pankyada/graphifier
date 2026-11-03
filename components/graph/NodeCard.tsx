"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { CircleAlert, Database, FileSearch } from "lucide-react";
import type { GraphNode } from "@/lib/types";
import { kindIcon, kindName } from "./kinds";

export type LineageRole = "focus" | "upstream" | "downstream" | null;

export interface LineageNodeData extends Record<string, unknown> {
  node: GraphNode;
  role: LineageRole;
  unresolved: boolean;
  selected: boolean;
}

export type LineageFlowNode = Node<LineageNodeData, "lineage">;

/** Readable node card: kind icon, name, kind, canonical/unresolved state and evidence count. */
export function NodeCard({ data }: NodeProps<LineageFlowNode>) {
  const { node, role, unresolved, selected } = data;
  const canonical = node.attributes?.canonical === true;
  const Icon = unresolved ? CircleAlert : canonical ? Database : kindIcon(node.kind);
  const evidenceCount = node.evidence?.length ?? 0;

  const classes = [
    "node-card",
    role === "focus" ? "is-focus" : "",
    role === "upstream" ? "is-upstream" : "",
    role === "downstream" ? "is-downstream" : "",
    unresolved ? "is-unresolved" : "",
    canonical ? "is-canonical" : "",
    selected ? "is-selected" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} title={`${kindName(node.kind)}: ${node.name}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} style={{ opacity: 0 }} />
      <div className="node-kind-icon" aria-hidden="true">
        <Icon className="icon" />
      </div>
      <div className="node-body">
        <div className="node-name">{node.name}</div>
        <div className="node-sub">
          <span className="mono">{node.kind}</span>
          {canonical ? <span>· canonical</span> : null}
          {unresolved ? <span style={{ color: "var(--amber-700)" }}>· unresolved</span> : null}
          {role && role !== "focus" ? <span>· {role}</span> : null}
          <span className="node-evidence" title={`${evidenceCount} evidence entries`}>
            <FileSearch style={{ width: 12, height: 12 }} aria-hidden="true" />
            {evidenceCount}
          </span>
        </div>
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} style={{ opacity: 0 }} />
    </div>
  );
}
