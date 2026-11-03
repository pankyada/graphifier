"use client";

import { useMemo, useState } from "react";
import { Crosshair, Search } from "lucide-react";
import { kindIcon, kindName } from "./kinds";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import type { GraphNode } from "@/lib/types";

const MAX_ROWS = 300;

interface FocusListProps {
  nodes: GraphNode[];
  unresolvedIds: Set<string>;
}

/**
 * List-first entry point for large graphs. Rendering every node of a big
 * estate is unreadable, so the canvas only appears after a focus is chosen.
 */
export function FocusList({ nodes, unresolvedIds }: FocusListProps) {
  const ws = useWorkspace();
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = nodes.filter((node) => {
      if (!needle) return true;
      return `${node.name} ${node.expression ?? ""} ${node.kind}`.toLowerCase().includes(needle);
    });
    const byKind = new Map<string, GraphNode[]>();
    for (const node of filtered.slice(0, MAX_ROWS)) {
      const list = byKind.get(node.kind) ?? [];
      list.push(node);
      byKind.set(node.kind, list);
    }
    return { total: filtered.length, byKind: [...byKind.entries()].sort((a, b) => b[1].length - a[1].length) };
  }, [nodes, query]);

  return (
    <div className="focus-list" aria-label="Choose a focus">
      <div>
        <h2 className="card-title" style={{ fontSize: 15, margin: 0 }}>
          Choose a focus
        </h2>
        <p className="card-text" style={{ margin: "4px 0 0" }}>
          This graph has {nodes.length} nodes. Pick a node to trace its upstream or downstream lineage. Double-click a
          node on the canvas to refocus it.
        </p>
      </div>

      <div className="search-wrap" style={{ flex: "none", width: "100%" }}>
        <Search className="icon search-icon" aria-hidden="true" />
        <input
          className="input"
          type="search"
          aria-label="Search nodes to focus"
          placeholder="Filter by name, expression or kind"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div className="focus-list-groups">
        {groups.total === 0 ? <div className="empty-row">No node matches “{query.trim()}”.</div> : null}
        {groups.byKind.map(([kind, items]) => {
          const Icon = kindIcon(kind);
          return (
            <section key={kind} className="focus-group" aria-label={`${kindName(kind)} nodes`}>
              <div className="focus-group-head">
                <Icon className="icon" aria-hidden="true" />
                <span>{kindName(kind)}</span>
                <span className="count" style={{ marginLeft: "auto" }}>
                  {items.length}
                </span>
              </div>
              {items.map((node) => (
                <button
                  key={node.id}
                  type="button"
                  className="focus-item"
                  onClick={() => ws.setFocus(node.id, "both")}
                  title={node.expression ?? node.name}
                >
                  <Crosshair className="icon" aria-hidden="true" />
                  <span style={{ minWidth: 0 }}>
                    <span className="node-name" style={{ display: "block" }}>
                      {node.name}
                    </span>
                    <span className="mono muted truncate" style={{ display: "block", fontSize: 11 }}>
                      {node.expression ?? node.kind}
                    </span>
                  </span>
                  <span className="row-inline" style={{ gap: 4 }}>
                    {unresolvedIds.has(node.id) ? <span className="chip unresolved">unresolved</span> : null}
                    <span className="muted" style={{ fontSize: 11 }}>
                      {node.evidence?.length ?? 0} ev.
                    </span>
                  </span>
                </button>
              ))}
            </section>
          );
        })}
        {groups.total > MAX_ROWS ? (
          <div className="note-line">
            Showing the first {MAX_ROWS} of {groups.total} matches. Refine the filter to narrow the list.
          </div>
        ) : null}
      </div>
    </div>
  );
}
