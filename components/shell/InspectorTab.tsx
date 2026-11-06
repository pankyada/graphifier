"use client";

import { ChevronLeft, Telescope, Waypoints } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { displayName, kindColor, kindIcon, kindName } from "@/components/graph/kinds";

/**
 * Pull-tab on the edge of the inspector sheet. It previews the sheet's content while
 * closed: what is selected and how much evidence backs it, or what needs attention.
 */
export function InspectorTab() {
  const ws = useWorkspace();
  const selection = ws.selection;
  const node = selection?.kind === "node" ? ws.nodeIndex.get(selection.id) : undefined;
  const edge = selection?.kind === "edge" ? ws.edgeIndex.get(selection.id) : undefined;
  const unresolved = ws.symbols.data?.symbols.filter((item) => !item.resolved).length ?? 0;

  const Icon = node ? kindIcon(node.kind) : edge ? Waypoints : Telescope;
  const color = node ? kindColor(node.kind) : undefined;
  const label = node ? displayName(node).primary : edge ? edge.kind.replace(/_/g, " ").toLowerCase() : "Overview";
  const evidence = (node ?? edge)?.evidence?.length;
  const count = evidence ?? (unresolved > 0 ? unresolved : undefined);
  const amber = evidence === undefined;
  const countText = evidence !== undefined ? `${evidence} evidence entries` : `${unresolved} unresolved`;

  return (
    <button
      type="button"
      className="inspector-tab"
      aria-label={`Toggle inspector: ${node ? `${kindName(node.kind)} ` : ""}${label}${count ? `, ${countText}` : ""}`}
      title="Toggle inspector (])"
      onClick={ws.toggleInspector}
    >
      <ChevronLeft className="inspector-tab-chevron" aria-hidden="true" />
      {/* Keyed so that a new selection replays the pop, even while the sheet is closed. */}
      <span className="inspector-tab-body" key={selection ? `${selection.kind}|${selection.id}` : "overview"}>
        <span
          className="inspector-tab-icon"
          aria-hidden="true"
          style={color ? { background: color } : undefined}
        >
          <Icon />
        </span>
        <span className="inspector-tab-label">{label}</span>
        {count ? <span className={`inspector-tab-count${amber ? " amber" : ""}`}>{count}</span> : null}
      </span>
    </button>
  );
}
