"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Eye, EyeOff, Search } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { isNarrowViewport } from "@/components/workspace/useWorkspace";
import { StatusLine } from "@/components/shell/StatusLine";
import { isSymbolicExpression } from "@/lib/explain";
import { setHighlight } from "@/lib/highlight";
import type { GraphNode } from "@/lib/types";
import { nodeDegrees, NOISE_KIND } from "./hubs";
import { displayName, kindColor, kindIcon, kindName } from "./kinds";

const PAGE = 50;

/** Every entity in scope, grouped by kind. Doubles as the legend and the kind filter. */
export function ExplorePanel() {
  const ws = useWorkspace();
  const graph = ws.graph.data;
  const [text, setText] = useState(ws.graphQuery);
  const [openOverrides, setOpenOverrides] = useState<Map<string, boolean>>(() => new Map());
  const [limits, setLimits] = useState<Map<string, number>>(() => new Map());

  // The API query pulls matches outside a bounded graph into the result; the list then narrows to them.
  useEffect(() => {
    const timer = window.setTimeout(() => ws.setGraphQuery(text.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [text, ws.setGraphQuery]);
  useEffect(() => {
    setText((current) => (current.trim() === ws.graphQuery ? current : ws.graphQuery));
  }, [ws.graphQuery]);

  const groups = useMemo(() => {
    const all = graph?.nodes ?? [];
    const degrees = nodeDegrees(graph?.edges ?? []);
    const needle = text.trim().toLowerCase();
    const nodes = needle
      ? all.filter((node) => `${node.name} ${node.expression ?? ""} ${node.kind}`.toLowerCase().includes(needle))
      : all;
    const byKind = new Map<string, GraphNode[]>();
    for (const node of nodes) {
      const list = byKind.get(node.kind) ?? [];
      list.push(node);
      byKind.set(node.kind, list);
    }
    for (const list of byKind.values()) {
      list.sort((a, b) => (degrees.get(b.id) ?? 0) - (degrees.get(a.id) ?? 0) || a.name.localeCompare(b.name));
    }
    const entries = [...byKind.entries()].sort(
      ([kindA, a], [kindB, b]) => Number(kindA === NOISE_KIND) - Number(kindB === NOISE_KIND) || b.length - a.length,
    );
    return { entries, degrees, total: all.length, matches: nodes.length };
  }, [graph, text]);

  const selectedId = ws.selection?.kind === "node" ? ws.selection.id : null;
  const query = text.trim();

  return (
    <div className="explore">
      <div className="explore-filter">
        <Search className="icon" aria-hidden="true" />
        <input
          type="search"
          aria-label="Filter entities"
          placeholder={groups.total > 0 ? `Filter ${groups.total} entities` : "Filter entities"}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            ws.setFocus(null);
            ws.clearSelection();
          }}
        />
      </div>

      {ws.hiddenKinds.size > 0 ? (
        <button type="button" className="explore-reset" onClick={() => ws.setHiddenKinds(new Set())}>
          {ws.hiddenKinds.size} kind{ws.hiddenKinds.size === 1 ? "" : "s"} hidden · Show all
        </button>
      ) : null}

      <div className="explore-groups">
        {!graph && ws.graph.loading ? <StatusLine text="Loading entities…" /> : null}
        {graph && groups.matches === 0 ? (
          <div className="empty-row">{query ? `Nothing matches “${query}”.` : "No entities yet. Run an analysis to populate this list."}</div>
        ) : null}

        {groups.entries.map(([kind, items]) => {
          const Icon = kindIcon(kind);
          const open = openOverrides.get(kind) ?? (query !== "" || kind !== NOISE_KIND);
          const shown = !ws.hiddenKinds.has(kind);
          const limit = limits.get(kind) ?? PAGE;
          return (
            <section key={kind} className="explore-group" aria-label={`${kindName(kind)} entities`}>
              <div className={`explore-head${shown ? "" : " is-hidden"}`}>
                <button
                  type="button"
                  className="explore-toggle"
                  aria-expanded={open}
                  onClick={() => setOpenOverrides((current) => new Map(current).set(kind, !open))}
                  onMouseEnter={() => shown && setHighlight({ type: "kind", kind })}
                  onMouseLeave={() => setHighlight(null)}
                >
                  {open ? <ChevronDown className="icon" aria-hidden="true" /> : <ChevronRight className="icon" aria-hidden="true" />}
                  <Icon className="icon" aria-hidden="true" style={shown ? { color: kindColor(kind) } : undefined} />
                  <span className="truncate">{kindName(kind)}</span>
                  <span className="explore-count">{items.length}</span>
                </button>
                <button
                  type="button"
                  className="explore-eye"
                  aria-pressed={!shown}
                  aria-label={`${shown ? "Hide" : "Show"} ${kindName(kind).toLowerCase()} on canvas`}
                  title={`${shown ? "Hide" : "Show"} on canvas`}
                  onClick={() => {
                    setHighlight(null);
                    ws.toggleKind(kind);
                  }}
                >
                  {shown ? <Eye className="icon" aria-hidden="true" /> : <EyeOff className="icon" aria-hidden="true" />}
                </button>
              </div>

              {open
                ? items.slice(0, limit).map((node) => {
                    const degree = groups.degrees.get(node.id) ?? 0;
                    const unresolved = isSymbolicExpression(node.expression) && !ws.resolvedSources.has(node.id);
                    return (
                      <button
                        key={node.id}
                        type="button"
                        className="explore-row"
                        aria-current={selectedId === node.id ? "true" : undefined}
                        title={node.expression ?? node.name}
                        onClick={() => {
                          ws.setFocus(node.id, ws.focus?.direction ?? "both");
                          if (isNarrowViewport()) ws.setRailDrawerOpen(false);
                        }}
                        onMouseEnter={() => setHighlight({ type: "node", id: node.id })}
                        onMouseLeave={() => setHighlight(null)}
                      >
                        <span className="truncate">{displayName(node).primary}</span>
                        {unresolved ? <span className="explore-unresolved" title="Unresolved reference" /> : null}
                        {degree > 0 ? <span className="explore-degree" title={`${degree} connections`}>{degree}</span> : null}
                      </button>
                    );
                  })
                : null}
              {open && items.length > limit ? (
                <button
                  type="button"
                  className="explore-more"
                  onClick={() => setLimits((current) => new Map(current).set(kind, limit + PAGE * 2))}
                >
                  Show more ({items.length - limit} left)
                </button>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
