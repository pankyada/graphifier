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

/** Icon for a canonical physical identity node. */
export const CANONICAL_ICON = Database;
