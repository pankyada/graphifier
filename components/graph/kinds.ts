import { Box, Code, Columns3, Cpu, Database, FileText, Sparkles, Table2, Workflow, type LucideIcon } from "lucide-react";
import { kindLabel } from "@/lib/explain";

// Kind -> icon. Unknown kinds fall back to a generic box so new extractor
// kinds still render. Kinds themselves come from the data, never hard-coded lists.
const KIND_ICONS: Record<string, LucideIcon> = {
  dataset: Table2,
  column: Columns3,
  program: Code,
  transformation: Workflow,
  model: Sparkles,
  file: FileText,
  job: Cpu,
};

export function kindIcon(kind: string): LucideIcon {
  return KIND_ICONS[kind] ?? Box;
}

export function kindName(kind: string): string {
  return kindLabel(kind);
}

// Hues stay clear of the semantic tokens: amber unresolved, red failed, teal/indigo lineage direction.
const KIND_COLORS: Record<string, string> = {
  dataset: "#2563eb",
  column: "#64748b",
  program: "#7c3aed",
  transformation: "#0891b2",
  model: "#db2777",
  file: "#78716c",
  job: "#4d7c0f",
};

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? "#7a8394";
}

/**
 * Short label for cramped surfaces: file paths reduce to their basename and dotted
 * dataset names split into table and schema. The full name stays in tooltips and details.
 */
export function displayName(node: { kind: string; name: string }): { primary: string; prefix: string | null } {
  const { name, kind } = node;
  if (name.includes("/") && !name.includes("$")) {
    const parts = name.split("/").filter(Boolean);
    return { primary: parts[parts.length - 1] ?? name, prefix: parts.length > 1 ? parts[parts.length - 2] : null };
  }
  if (kind === "dataset" && /^[\w-]+(\.[\w-]+)+$/.test(name)) {
    const cut = name.lastIndexOf(".");
    return { primary: name.slice(cut + 1), prefix: name.slice(0, cut) };
  }
  return { primary: name, prefix: null };
}

/** Icon for a canonical physical identity node. */
export const CANONICAL_ICON = Database;
