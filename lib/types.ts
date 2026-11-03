// Shapes mirror backend/graphifier/api.py, graph.py and resolution.py.
// Keep optional fields optional: the backend omits some keys on some paths.

export interface Health {
  status: string;
  version: string;
}

export interface Settings {
  repo_root: string;
  system: string;
  agent: { enabled: boolean; model: string; api_key_configured: boolean };
  neo4j: { enabled: boolean; uri_configured: boolean };
  api_token_required: boolean;
}

export interface Repository {
  id: string;
  name: string;
  path: string;
  created_at: string;
}

export interface BrowseEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

export interface BrowseResponse {
  path: string;
  entries: BrowseEntry[];
}

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | (string & {});

export interface Job {
  id: string;
  repo_id: string;
  environment: string;
  /** True when the job ran the bounded Luna agent pass; false for static analysis. */
  use_agent: boolean;
  status: JobStatus;
  progress: number;
  total_files: number;
  processed_files: number;
  error: string | null;
  commit_hash: string | null;
  snapshot_hash: string | null;
  created_at: string;
  updated_at: string;
}

export interface Evidence {
  file: string;
  start_line: number;
  end_line: number;
  repo_id?: string;
}

export interface SnapshotMeta {
  repo_id: string;
  snapshot_id: string;
  job_id: string;
  environment: string;
  commit_hash: string | null;
  content_hash: string;
  created_at: string;
}

export interface GraphNode {
  id: string;
  kind: string;
  name: string;
  expression?: string | null;
  attributes: Record<string, unknown> & { canonical?: boolean };
  evidence: Evidence[];
  repositories?: string[];
  snapshots?: SnapshotMeta[];
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  attributes: Record<string, unknown>;
  evidence: Evidence[];
  repositories?: string[];
  snapshots?: SnapshotMeta[];
}

/** Warnings are strings ("file: message") from the worker, or binding_conflict objects. */
export interface WarningEntry {
  repo_id: string;
  snapshot_id: string;
  warning: unknown;
}

export interface Graph {
  repo_id: string | null;
  environment: string | null;
  context?: string | null;
  system: string;
  version: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  warnings: WarningEntry[];
  snapshots: SnapshotMeta[];
}

export interface UnresolvedGap {
  entity_id: string;
  name: string;
  expression: string;
  reason: string;
  evidence: Evidence[];
}

export type TraceDirection = "in" | "out" | "both";

export interface Trace {
  entity_id: string;
  direction: TraceDirection;
  nodes: GraphNode[];
  edges: GraphEdge[];
  unresolved_gaps: UnresolvedGap[];
  truncated: boolean;
  max_depth: number;
  graph_version: string;
  warnings: WarningEntry[];
}

export interface SymbolEntry {
  name: string;
  expression: string;
  default_value: string | null;
  evidence: Evidence;
  resolved: boolean;
  resolution?: Resolution | null;
}

export interface SymbolsResponse {
  repo_id: string;
  environment: string | null;
  namespace: string;
  system: string;
  symbols: SymbolEntry[];
}

export type ResolutionStatus = "proposed" | "applied" | "retracted" | (string & {});

export interface PreviewAffected {
  reference_id: string;
  name: string | null;
  expression: string | null;
  evidence: Evidence[];
  before: string[];
  after: string[];
}

export interface PreviewCounts {
  nodes_added: number;
  nodes_removed: number;
  edges_added: number;
  edges_removed: number;
}

export interface BindingPreview {
  repo_id: string;
  environment: string;
  symbol: string;
  expression: string;
  conflict: Resolution | null;
  conflicts: Resolution[];
  affected_references: PreviewAffected[];
  counts: PreviewCounts;
  graph_version_before: string;
  graph_version_after: string;
}

export interface Resolution {
  id: string;
  repo_id: string;
  environment: string;
  symbol: string;
  expression: string;
  default_value: string | null;
  status: ResolutionStatus;
  version: number;
  actor: string | null;
  created_at: string;
  updated_at: string;
  /** Present on propose responses only. */
  conflict?: Resolution | null;
  /** Present on propose responses only (preview_binding output). */
  preview?: BindingPreview;
}

export interface ResolutionPreviewResponse {
  resolution: Resolution;
  expected_version: number;
  preview: BindingPreview;
}

export interface EvidenceItem {
  category: string;
  item: Record<string, unknown>;
  evidence: Record<string, unknown>;
}

export interface EvidenceResponse {
  repo_id: string;
  file: string;
  snapshot_id: string | null;
  environment: string | null;
  content: string | null;
  sha256: string | null;
  evidence: EvidenceItem[];
}

export interface Neo4jSyncResult {
  status: string;
  repo_id: string | null;
  environment: string | null;
  system: string;
  projection_id: string;
  nodes: number;
  edges: number;
  error?: string | null;
}
