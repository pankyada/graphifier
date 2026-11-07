import type { GraphEdge, GraphNode } from "./types";

// Symbolic references that static extraction leaves for bindings to resolve.
const SYMBOLIC = /&\w+|\{[^}]+\}|\$\{?\w+/;

export function isSymbolicExpression(expression: string | null | undefined): boolean {
  return !!expression && SYMBOLIC.test(expression);
}

export function kindLabel(kind: string): string {
  const labels: Record<string, string> = {
    dataset: "Dataset reference",
    column: "Column",
    program: "Program",
    transformation: "Transformation",
    model: "Model",
    file: "Source file",
    module: "Module",
    endpoint: "Endpoint",
  };
  return labels[kind] ?? (kind ? kind.charAt(0).toUpperCase() + kind.slice(1) : "Entity");
}

export function edgeKindLabel(kind: string): string {
  return kind.replace(/_/g, " ").toLowerCase();
}

export interface NodeContext {
  /** Node ids that this node RESOLVES_TO (canonical targets). */
  resolvesTo: string[];
  /** Symbols currently bound in this scope that are referenced by this expression. */
  boundSymbols: string[];
}

/** Plain-language explanation built only from fields the API returned. */
export function explainNode(node: GraphNode, context: NodeContext): string[] {
  const lines: string[] = [];
  const first = node.evidence?.[0];
  const where = first ? ` at ${first.file}:${first.start_line}` : "";
  const method = node.attributes?.method === "model-inferred"
    ? node.attributes.also_static ? "static analysis and AI inference" : "AI inference"
    : node.attributes?.canonical ? "dataset resolution" : "static analysis";
  lines.push(`${kindLabel(node.kind)} "${node.name}" was found by ${method}${where}.`);
  if (node.attributes?.entrypoint === true || node.attributes?.entrypoint === "true") lines.push("Detected entrypoint for this application or job.");
  if (node.attributes?.module) lines.push(`Module: ${String(node.attributes.module)}.`);

  if (node.attributes?.canonical === true) {
    const refs = Array.isArray(node.attributes.source_references) ? node.attributes.source_references.length : 0;
    const system = String(node.attributes.system ?? "");
    const env = String(node.attributes.environment ?? "");
    lines.push(
      `Canonical physical identity in system ${system || "unknown"}, environment ${env || "unknown"}; ` +
        `${refs} source reference${refs === 1 ? "" : "s"} stitch to it.`,
    );
  }

  if (isSymbolicExpression(node.expression)) {
    if (context.resolvesTo.length > 0) {
      lines.push(
        `Symbolic expression resolves through applied bindings${context.boundSymbols.length ? ` (${context.boundSymbols.join(", ")})` : ""}.`,
      );
    } else {
      lines.push("Symbolic expression with no applied binding in this scope, so it stays unresolved here.");
    }
  }
  return lines;
}

export function explainEdge(edge: GraphEdge, sourceName: string, targetName: string): string[] {
  const lines: string[] = [];
  if (edge.kind === "RESOLVES_TO") {
    const resolved = typeof edge.attributes?.resolved_name === "string" ? edge.attributes.resolved_name : targetName;
    lines.push(`Alias: "${sourceName}" is recorded as the physical name "${resolved}".`);
    const bindings = Array.isArray(edge.attributes?.bindings) ? edge.attributes.bindings.length : 0;
    lines.push(`Applied bindings used: ${bindings}.`);
  } else {
    const sourceMethods = Array.isArray(edge.attributes?.source_methods) ? edge.attributes.source_methods : [];
    const method = edge.attributes?.method === "model-inferred" || sourceMethods.includes("model-inferred")
      ? "AI-assisted source analysis" : "source analysis";
    lines.push(`"${sourceName}" ${edgeKindLabel(edge.kind)} "${targetName}" according to ${method}.`);
    if (edge.attributes?.projected || edge.attributes?.derived) lines.push("This connection summarizes a path through hidden intermediate entities. Its evidence retains the underlying source references.");
    if (edge.kind === "READS") lines.push(`Read source: "${targetName}". Consumer: "${sourceName}".`);
    if (edge.kind === "WRITES") lines.push(`Write target: "${targetName}". Producer: "${sourceName}".`);
    if (edge.kind === "DERIVES_FROM") lines.push(`Data dependency flows from "${sourceName}" to "${targetName}".`);
    lines.push("Source-derived lineage, not proof of runtime execution.");
  }
  return lines;
}
