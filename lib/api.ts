import type {
  AgentSettings,
  AgentSettingsInput,
  AgentConnectionTest,
  BrowseResponse,
  EvidenceResponse,
  Graph,
  GraphView,
  GraphGranularity,
  EmbeddingMatch,
  EmbeddingStatus,
  Health,
  Job,
  Neo4jSyncResult,
  Repository,
  RepositoryImport,
  Resolution,
  ResolutionPreviewResponse,
  Settings,
  SymbolsResponse,
  Trace,
  TraceDirection,
} from "./types";

/**
 * Typed client for the Graphifier API.
 *
 * Every request goes to a relative `/api/...` path, which the Next.js server
 * route (app/api/[...path]/route.ts) forwards to the Python API. The bearer
 * token is injected server-side only; nothing secret is read or stored here.
 */

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

export function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return `/api${path}${qs ? `?${qs}` : ""}`;
}

function detailOf(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : String(item),
      )
      .join("; ");
  }
  return null;
}

async function request<T>(method: "GET" | "POST", path: string, options: RequestOptions = {}): Promise<T> {
  const hasBody = options.body !== undefined;
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers: hasBody ? { Accept: "application/json", "Content-Type": "application/json" } : { Accept: "application/json" },
      body: hasBody ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, "Cannot reach the Graphifier web server. Run npm run dev, then npm run api.");
  }

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    if (response.status === 404 && path === "/repository-imports") {
      throw new ApiError(404, "The running API does not provide repository imports. Restart the Graphifier API from this project with npm run api, and restart npm run worker. Then refresh imports.");
    }
    throw new ApiError(
      response.status,
      detailOf(data) ?? (response.statusText || `Request failed with status ${response.status}`),
    );
  }
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  health: (signal?: AbortSignal) => request<Health>("GET", "/health", { signal }),

  settings: (signal?: AbortSignal) => request<Settings>("GET", "/settings", { signal }),

  saveAgentSettings: (body: AgentSettingsInput, signal?: AbortSignal) =>
    request<AgentSettings>("POST", "/settings/agent", { body, signal }),

  testAgentConnection: (body: AgentSettingsInput, signal?: AbortSignal) =>
    request<AgentConnectionTest>("POST", "/settings/agent/test", { body, signal }),

  repositories: (signal?: AbortSignal) =>
    request<{ repositories: Repository[] }>("GET", "/repositories", { signal }),

  repositoryImports: (signal?: AbortSignal) =>
    request<{ imports: RepositoryImport[] }>("GET", "/repository-imports", { signal }),

  createRepositoryImport: (body: { url: string; branch?: string; name?: string }) =>
    request<RepositoryImport>("POST", "/repository-imports", { body }),

  cancelRepositoryImport: (id: string) =>
    request<RepositoryImport>("POST", `/repository-imports/${enc(id)}/cancel`),

  retryRepositoryImport: (id: string) =>
    request<RepositoryImport>("POST", `/repository-imports/${enc(id)}/retry`),

  registerRepository: (path: string, name?: string) =>
    request<Repository>("POST", "/repositories", { body: { path, name: name || undefined } }),

  browse: (path?: string, signal?: AbortSignal) => request<BrowseResponse>("GET", "/browse", { query: { path }, signal }),

  jobs: (repoId?: string, signal?: AbortSignal) =>
    request<{ jobs: Job[] }>("GET", "/jobs", { query: { repo_id: repoId }, signal }),

  createJob: (repoId: string, environment: string, useAgent: boolean, useEmbeddings = false, useAiHierarchy = false) =>
    request<Job>("POST", "/jobs", {
      body: { repo_id: repoId, environment, use_agent: useAgent, use_embeddings: useEmbeddings, use_ai_hierarchy: useAiHierarchy },
    }),

  embeddingStatus: (args: { repoId?: string; environment: string }, signal?: AbortSignal) =>
    request<EmbeddingStatus>("GET", "/embeddings/status", { query: { repo_id: args.repoId, environment: args.environment }, signal }),

  searchEmbeddings: (args: { query: string; repoId?: string; environment: string }, signal?: AbortSignal) =>
    request<{ matches: EmbeddingMatch[]; model: string }>("POST", "/embeddings/search", {
      body: { query: args.query, repo_id: args.repoId, environment: args.environment, limit: 10 }, signal,
    }),

  resumeJob: (jobId: string) => request<Job>("POST", `/jobs/${enc(jobId)}/resume`),
  cancelJob: (jobId: string) => request<Job>("POST", `/jobs/${enc(jobId)}/cancel`),

  graph: (args: { repoId?: string; environment: string; view?: GraphView; granularity?: GraphGranularity; query?: string; focusId?: string; scopeId?: string; generation?: string; includeTests?: boolean; hierarchyMode?: "ai" | "deterministic" }, signal?: AbortSignal) =>
    request<Graph>("GET", "/graph", { query: { repo_id: args.repoId, environment: args.environment, view: args.view, granularity: args.granularity, max_nodes: 300, query: args.query, focus_id: args.focusId, scope_id: args.scopeId, generation: args.generation, hierarchy_mode: args.hierarchyMode ?? "ai", include_tests: args.includeTests ?? false }, signal }),

  graphLocation: (generation: string, nodeId: string) => request<{ ancestors: string[]; groups: import("./types").GraphNode[] }>("GET", "/graph/location", { query: { generation, node_id: nodeId } }),

  edgeSupport: (generation: string, edgeId: string, offset = 0, signal?: AbortSignal) => request<{ edges: import("./types").GraphEdge[]; total: number; has_more: boolean }>("GET", "/graph/edge-support", { query: { generation, edge_id: edgeId, offset, limit: 20 }, signal }),

  trace: (
    args: { entityId: string; direction: TraceDirection; repoId?: string; environment: string; view?: GraphView; granularity?: GraphGranularity; generation?: string; includeTests?: boolean; hierarchyMode?: "ai" | "deterministic" },
    signal?: AbortSignal,
  ) =>
    request<Trace>("GET", "/trace", {
      query: {
        entity_id: args.entityId,
        generation: args.generation,
        hierarchy_mode: args.hierarchyMode ?? "ai", include_tests: args.includeTests ?? false,
        view: args.view,
        granularity: args.granularity,
        max_nodes: 800,
        direction: args.direction,
        repo_id: args.repoId,
        environment: args.environment,
      },
      signal,
    }),

  symbols: (repoId: string, environment: string, signal?: AbortSignal) =>
    request<SymbolsResponse>("GET", "/symbols", { query: { repo_id: repoId, environment }, signal }),

  /**
   * Source for one indexed snapshot. The snapshot must belong to the repository and
   * environment; without it the API would pick the latest snapshot, so refuse here.
   */
  evidence: (
    args: { repoId: string; snapshotId: string | null; environment: string; file: string },
    signal?: AbortSignal,
  ) => {
    if (!args.snapshotId) {
      return Promise.reject(
        new ApiError(0, `No indexed snapshot for this repository in environment ${args.environment}.`),
      );
    }
    return request<EvidenceResponse>("GET", "/evidence", {
      query: {
        repo_id: args.repoId,
        file: args.file,
        snapshot_id: args.snapshotId,
        environment: args.environment,
      },
      signal,
    });
  },

  resolutions: (repoId: string, environment: string, signal?: AbortSignal) =>
    request<{ resolutions: Resolution[] }>("GET", "/resolutions", {
      query: { repo_id: repoId, environment },
      signal,
    }),

  proposeResolution: (args: {
    repoId: string;
    environment: string;
    symbol: string;
    expression: string;
    defaultValue?: string;
    actor: string;
  }) =>
    request<Resolution>("POST", "/resolutions/propose", {
      body: {
        repo_id: args.repoId,
        environment: args.environment,
        symbol: args.symbol,
        expression: args.expression,
        default_value: args.defaultValue || undefined,
        actor: args.actor,
      },
    }),

  resolutionPreview: (id: string, signal?: AbortSignal) =>
    request<ResolutionPreviewResponse>("GET", `/resolutions/${enc(id)}/preview`, { signal }),

  applyResolution: (id: string, expectedVersion: number, actor: string) =>
    request<Resolution>("POST", `/resolutions/${enc(id)}/apply`, {
      body: { expected_version: expectedVersion, actor },
    }),

  retractResolution: (id: string, expectedVersion: number, actor: string) =>
    request<Resolution>("POST", `/resolutions/${enc(id)}/retract`, {
      body: { expected_version: expectedVersion, actor },
    }),

  neo4jSync: (args: { repoId?: string; environment?: string }) =>
    request<Neo4jSyncResult>("POST", "/neo4j/sync", {
      body: { repo_id: args.repoId, environment: args.environment },
    }),
};
