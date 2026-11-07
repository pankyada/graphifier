import { Box, Code, Columns3, Cpu, Database, FileText, Sparkles, Table2, Workflow, type LucideIcon } from "lucide-react";
import { kindLabel } from "@/lib/explain";

// Kind -> icon. Unknown kinds fall back to a generic box so new extractor
// kinds still render. Kinds themselves come from the data, never hard-coded lists.
const KIND_ICONS: Record<string, LucideIcon> = {
  architecture: Workflow,
  component: Box,
  method: Code,
  dataset: Table2,
  column: Columns3,
  program: Code,
  transformation: Workflow,
  model: Sparkles,
  file: FileText,
  job: Cpu,
  module: Box,
  endpoint: Workflow,
  function: Code,
  class: Box,
};

export function kindIcon(kind: string): LucideIcon {
  return KIND_ICONS[kind] ?? Box;
}

export function kindName(kind: string): string {
  return kindLabel(kind);
}

// Hues stay clear of the semantic tokens: amber unresolved, red failed, green upstream, rust downstream.
const KIND_COLORS: Record<string, string> = {
  architecture: "#245b75",
  component: "#995f26",
  method: "#6d4c9f",
  dataset: "#2f6690",
  column: "#7a756b",
  program: "#6d4c9f",
  transformation: "#2b7a9b",
  model: "#a8437a",
  file: "#8a7f70",
  job: "#5f7a1f",
  module: "#995f26",
  endpoint: "#245b75",
  function: "#6d4c9f",
  class: "#715a9e",
};

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? "#8a8578";
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
