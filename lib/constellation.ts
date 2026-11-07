import type { GraphEdge, GraphNode } from "./types";
import type { Point } from "./layout";

/** Stable seeds make each graph start in the same arrangement. */
export function constellationSeeds(nodes: GraphNode[]): Map<string, Point> {
  const ordered = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  const radius = Math.max(200, Math.sqrt(ordered.length) * 105);
  return new Map(ordered.map((node, index) => {
    const angle = index * 2.399963229728653;
    const distance = radius * Math.sqrt((index + 1) / Math.max(1, ordered.length));
    return [node.id, { x: Math.cos(angle) * distance, y: Math.sin(angle) * distance }];
  }));
}

/**
 * Incremental force simulation. The caller owns animation scheduling and cleanup.
 * Spatial buckets and bounded neighbor sampling avoid quadratic repulsion when
 * many nodes overlap. Pins remain fixed until reset, including after cooling.
 */
export class ConstellationSimulation {
  private readonly ids: string[];
  private readonly index: Map<string, number>;
  private readonly seeds: Map<string, Point>;
  private readonly points: Point[];
  private readonly velocities: Point[];
  private readonly links: [number, number][];
  private readonly degrees: number[];
  private readonly pinned = new Map<number, Point>();
  private alpha = 1;
  private ticks = 0;

  constructor(nodes: GraphNode[], edges: GraphEdge[]) {
    this.seeds = constellationSeeds(nodes);
    this.ids = [...this.seeds.keys()];
    this.index = new Map(this.ids.map((id, index) => [id, index]));
    this.points = [...this.seeds.values()].map((point) => ({ ...point }));
    this.velocities = this.points.map(() => ({ x: 0, y: 0 }));
    this.degrees = this.points.map(() => 0);
    this.links = [];
    for (const edge of edges) {
      const source = this.index.get(edge.source);
      const target = this.index.get(edge.target);
      if (source === undefined || target === undefined || source === target) continue;
      this.links.push([source, target]);
      this.degrees[source] += 1;
      this.degrees[target] += 1;
    }
  }

  positions(): Map<string, Point> {
    return new Map(this.ids.map((id, index) => [id, { ...this.points[index] }]));
  }

  pin(id: string, position: Point): void {
    const index = this.index.get(id);
    if (index === undefined || !Number.isFinite(position.x) || !Number.isFinite(position.y)) return;
    this.pinned.set(index, { ...position });
    this.points[index] = { ...position };
    this.velocities[index] = { x: 0, y: 0 };
    this.alpha = Math.max(this.alpha, 0.55);
    this.ticks = 0;
  }

  reset(): void {
    this.pinned.clear();
    this.ids.forEach((id, index) => {
      this.points[index] = { ...this.seeds.get(id)! };
      this.velocities[index] = { x: 0, y: 0 };
    });
    this.alpha = 1;
    this.ticks = 0;
  }

  /** Advances one bounded tick and returns whether more movement is needed. */
  tick(): boolean {
    if (this.alpha < 0.004 || this.ticks >= 180 || this.points.length === 0) return false;
    const cell = 260;
    const buckets = new Map<string, number[]>();
    this.points.forEach((point, index) => {
      const key = `${Math.floor(point.x / cell)},${Math.floor(point.y / cell)}`;
      const members = buckets.get(key) ?? [];
      members.push(index);
      buckets.set(key, members);
    });
    const forces = this.points.map((point) => ({ x: -point.x * 0.005, y: -point.y * 0.005 }));
    this.points.forEach((point, index) => {
      const bucketX = Math.floor(point.x / cell);
      const bucketY = Math.floor(point.y / cell);
      for (let dx = -1; dx <= 1; dx += 1) {
        for (let dy = -1; dy <= 1; dy += 1) {
          const members = buckets.get(`${bucketX + dx},${bucketY + dy}`) ?? [];
          const stride = Math.max(1, Math.ceil(members.length / 64));
          for (let offset = index % stride; offset < members.length; offset += stride) {
            const other = members[offset];
            if (other === index) continue;
            let x = point.x - this.points[other].x;
            let y = point.y - this.points[other].y;
            if (x === 0 && y === 0) {
              x = index < other ? -1 : 1;
              y = 0.5;
            }
            const distance = Math.max(1, Math.hypot(x, y));
            const collision = Math.max(0, 175 - distance) * 0.15;
            const repulsion = Math.min(24, 16000 / (distance * distance)) + collision;
            forces[index].x += x / distance * repulsion;
            forces[index].y += y / distance * repulsion;
          }
        }
      }
    });
    for (const [source, target] of this.links) {
      const x = this.points[target].x - this.points[source].x;
      const y = this.points[target].y - this.points[source].y;
      const distance = Math.max(1, Math.hypot(x, y));
      const strength = 0.04 / Math.sqrt(Math.max(this.degrees[source], this.degrees[target]));
      const force = (distance - 235) * strength;
      forces[source].x += x / distance * force;
      forces[source].y += y / distance * force;
      forces[target].x -= x / distance * force;
      forces[target].y -= y / distance * force;
    }
    this.points.forEach((point, index) => {
      const pin = this.pinned.get(index);
      if (pin) {
        point.x = pin.x;
        point.y = pin.y;
        return;
      }
      const velocity = this.velocities[index];
      velocity.x = (velocity.x + forces[index].x * this.alpha) * 0.65;
      velocity.y = (velocity.y + forces[index].y * this.alpha) * 0.65;
      point.x += Math.max(-20, Math.min(20, velocity.x));
      point.y += Math.max(-20, Math.min(20, velocity.y));
    });
    this.alpha *= 0.96;
    this.ticks += 1;
    return this.alpha >= 0.004 && this.ticks < 180;
  }
}
