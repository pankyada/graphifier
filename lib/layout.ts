import type { GraphEdge, GraphNode } from "./types";

// Node card footprint used both for layout spacing and for centering the camera.
export const NODE_WIDTH = 232;
export const NODE_HEIGHT = 64;

const COLUMN_GAP = 72;
const ROW_GAP = 20;

export interface Point {
  x: number;
  y: number;
}

/**
 * Left-to-right layered layout without an external dependency.
 *
 * Rank = longest path from sources. Cycles are broken deterministically by
 * promoting the unprocessed node with the fewest remaining predecessors. Within
 * a rank, nodes are ordered by name and then by one barycenter sweep so that
 * edges cross less. Output is stable for the same input.
 */
export function layeredLayout(nodes: GraphNode[], edges: GraphEdge[]): Map<string, Point> {
  const names = new Map<string, string>();
  for (const node of nodes) names.set(node.id, node.name ?? node.id);
  const ids = [...names.keys()].sort((a, b) => {
    const byName = (names.get(a) ?? "").localeCompare(names.get(b) ?? "");
    return byName !== 0 ? byName : a.localeCompare(b);
  });

  // Parallel edges (same source and target, different kinds) count once for placement.
  const successors = new Map<string, string[]>();
  const predecessors = new Map<string, string[]>();
  const indegree = new Map<string, number>();
  for (const id of ids) {
    successors.set(id, []);
    predecessors.set(id, []);
    indegree.set(id, 0);
  }
  const seenPairs = new Set<string>();
  for (const edge of edges) {
    if (!names.has(edge.source) || !names.has(edge.target) || edge.source === edge.target) continue;
    const pair = `${edge.source}\u0000${edge.target}`;
    if (seenPairs.has(pair)) continue;
    seenPairs.add(pair);
    successors.get(edge.source)?.push(edge.target);
    predecessors.get(edge.target)?.push(edge.source);
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
  }

  const rank = new Map<string, number>();
  const remaining = new Map(indegree);
  const done = new Set<string>();
  const queue: string[] = [];
  for (const id of ids) {
    if ((remaining.get(id) ?? 0) === 0) {
      queue.push(id);
      rank.set(id, 0);
    }
  }

  while (done.size < ids.length) {
    if (queue.length === 0) {
      let pick: string | undefined;
      let best = Number.POSITIVE_INFINITY;
      for (const id of ids) {
        if (done.has(id)) continue;
        const count = remaining.get(id) ?? 0;
        if (count < best) {
          best = count;
          pick = id;
        }
      }
      if (pick === undefined) break;
      remaining.set(pick, 0);
      if (!rank.has(pick)) rank.set(pick, 0);
      queue.push(pick);
    }
    const current = queue.shift() as string;
    if (done.has(current)) continue;
    done.add(current);
    const base = rank.get(current) ?? 0;
    for (const next of successors.get(current) ?? []) {
      // Back edges point at an already-placed node. Its rank is final, so skip it
      // rather than pushing it right and invalidating edges already laid out.
      if (done.has(next)) continue;
      rank.set(next, Math.max(rank.get(next) ?? 0, base + 1));
      const count = (remaining.get(next) ?? 0) - 1;
      remaining.set(next, count);
      if (count <= 0 && !queue.includes(next)) queue.push(next);
    }
  }

  const maxRank = Math.max(0, ...rank.values());
  const layers: string[][] = Array.from({ length: maxRank + 1 }, () => []);
  for (const id of ids) layers[rank.get(id) ?? 0].push(id);

  const position = new Map<string, number>();
  layers[0]?.forEach((id, index) => position.set(id, index));
  for (let r = 1; r < layers.length; r += 1) {
    const layer = layers[r];
    const barycenter = new Map<string, number>();
    layer.forEach((id, index) => {
      const sources = (predecessors.get(id) ?? []).map((p) => position.get(p)).filter((v): v is number => v !== undefined);
      barycenter.set(id, sources.length ? sources.reduce((sum, v) => sum + v, 0) / sources.length : index);
    });
    layer.sort((a, b) => (barycenter.get(a) ?? 0) - (barycenter.get(b) ?? 0));
    layer.forEach((id, index) => position.set(id, index));
  }

  const tallest = Math.max(1, ...layers.map((layer) => layer.length));
  const out = new Map<string, Point>();
  const stride = NODE_HEIGHT + ROW_GAP;
  layers.forEach((layer, r) => {
    const offset = ((tallest - layer.length) * stride) / 2;
    layer.forEach((id, index) => {
      out.set(id, { x: r * (NODE_WIDTH + COLUMN_GAP), y: offset + index * stride });
    });
  });
  return out;
}

/**
 * Split a trace around its focus node into upstream (feeds the focus) and
 * downstream (fed by the focus). Walks edges in each direction from the focus.
 */
export function traceSides(focusId: string, edges: GraphEdge[]): { upstream: Set<string>; downstream: Set<string> } {
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const edge of edges) {
    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    if (!incoming.has(edge.target)) incoming.set(edge.target, []);
    outgoing.get(edge.source)?.push(edge.target);
    incoming.get(edge.target)?.push(edge.source);
  }
  const walk = (start: string, adjacency: Map<string, string[]>) => {
    const seen = new Set<string>([start]);
    const stack = [start];
    while (stack.length) {
      const current = stack.pop() as string;
      for (const next of adjacency.get(current) ?? []) {
        if (seen.has(next)) continue;
        seen.add(next);
        stack.push(next);
      }
    }
    seen.delete(start);
    return seen;
  };
  const upstream = walk(focusId, incoming);
  const downstream = walk(focusId, outgoing);
  for (const id of upstream) if (downstream.has(id)) downstream.delete(id);
  return { upstream, downstream };
}

/** Edge ids on the lineage of a node, split by side, for lighting up its path. */
export function lineagePath(
  id: string,
  edges: GraphEdge[],
): { upstream: Set<string>; downstream: Set<string>; upstreamEdges: Set<string>; downstreamEdges: Set<string> } {
  const { upstream, downstream } = traceSides(id, edges);
  const upstreamEdges = new Set<string>();
  const downstreamEdges = new Set<string>();
  for (const edge of edges) {
    if (upstream.has(edge.source) && (edge.target === id || upstream.has(edge.target))) upstreamEdges.add(edge.id);
    if (downstream.has(edge.target) && (edge.source === id || downstream.has(edge.source))) downstreamEdges.add(edge.id);
  }
  return { upstream, downstream, upstreamEdges, downstreamEdges };
}

/** Hop distance of every node reachable from the focus, walking away from it in each direction. */
export function traceDepths(focusId: string, edges: GraphEdge[]): Map<string, number> {
  const depths = new Map<string, number>([[focusId, 0]]);
  const walk = (next: (edge: GraphEdge, current: string) => string | null) => {
    const seen = new Set([focusId]);
    let frontier = [focusId];
    let depth = 0;
    while (frontier.length > 0) {
      depth += 1;
      const following: string[] = [];
      for (const current of frontier) {
        for (const edge of edges) {
          const other = next(edge, current);
          if (other === null || seen.has(other)) continue;
          seen.add(other);
          following.push(other);
          depths.set(other, Math.min(depths.get(other) ?? depth, depth));
        }
      }
      frontier = following;
    }
  };
  walk((edge, current) => (edge.target === current ? edge.source : null));
  walk((edge, current) => (edge.source === current ? edge.target : null));
  return depths;
}
