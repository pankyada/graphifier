"use client";

import { useMemo } from "react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { setHighlight } from "@/lib/highlight";
import { kindColor, kindIcon, kindName } from "./kinds";

/** Legend that is also the filter: hover previews a kind on the canvas, click hides or shows it. */
export function KindLegend({ nodes }: { nodes: { kind: string }[] }) {
  const ws = useWorkspace();
  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of nodes) counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [nodes]);

  if (kinds.length === 0) return null;

  return (
    <div className="kind-legend" role="group" aria-label="Show or hide node kinds">
      {kinds.map(([kind, count]) => {
        const Icon = kindIcon(kind);
        const shown = !ws.hiddenKinds.has(kind);
        return (
          <button
            key={kind}
            type="button"
            className="kind-chip"
            aria-pressed={shown}
            title={`${shown ? "Hide" : "Show"} ${kindName(kind).toLowerCase()} nodes`}
            onClick={() => {
              setHighlight(null);
              ws.toggleKind(kind);
            }}
            onMouseEnter={() => shown && setHighlight({ type: "kind", kind })}
            onMouseLeave={() => setHighlight(null)}
          >
            <Icon className="icon" aria-hidden="true" style={shown ? { color: kindColor(kind) } : undefined} />
            {kindName(kind)}
            <span className="kind-chip-count">{count}</span>
          </button>
        );
      })}
      {ws.hiddenKinds.size > 0 ? (
        <button type="button" className="kind-chip kind-chip-reset" onClick={() => ws.setHiddenKinds(new Set())}>
          Show all
        </button>
      ) : null}
    </div>
  );
}
