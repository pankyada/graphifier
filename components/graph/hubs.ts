import type { GraphEdge, GraphNode } from "@/lib/types";

/** Most-connected nodes shown when a graph is too large to lay out in full. */
export const HUB_LIMIT = 40;

/** Import statements: numerous and rarely the point, so they rank last and start collapsed. */
export const NOISE_KIND = "dependency";

export function nodeDegrees(edges: GraphEdge[]): Map<string, number> {
  const degrees = new Map<string, number>();
  for (const edge of edges) {
    degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
  }
  return degrees;
}

/** Top nodes by connection count. `keepId` stays visible so a selection can always be centred. */
export function pickHubs(nodes: GraphNode[], edges: GraphEdge[], keepId: string | null, limit = HUB_LIMIT): GraphNode[] {
  const degrees = nodeDegrees(edges);
  const ranked = [...nodes].sort(
    (a, b) =>
      Number(a.kind === NOISE_KIND) - Number(b.kind === NOISE_KIND) ||
      (degrees.get(b.id) ?? 0) - (degrees.get(a.id) ?? 0) ||
      a.name.localeCompare(b.name),
  );
  const hubs = ranked.slice(0, limit);
  const kept = keepId ? ranked.find((node) => node.id === keepId) : undefined;
  if (kept && !hubs.includes(kept)) { hubs.pop(); hubs.push(kept); }
  return hubs;
}
