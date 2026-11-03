import type {
  BrowseResponse,
  EvidenceResponse,
  Graph,
  Health,
  Job,
  Neo4jSyncResult,
  Repository,
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

  repositories: (signal?: AbortSignal) =>
    request<{ repositories: Repository[] }>("GET", "/repositories", { signal }),

  registerRepository: (path: string, name?: string) =>
    request<Repository>("POST", "/repositories", { body: { path, name: name || undefined } }),

  browse: (path?: string, signal?: AbortSignal) => request<BrowseResponse>("GET", "/browse", { query: { path }, signal }),

  jobs: (repoId?: string, signal?: AbortSignal) =>
    request<{ jobs: Job[] }>("GET", "/jobs", { query: { repo_id: repoId }, signal }),

  createJob: (repoId: string, environment: string, useAgent: boolean) =>
    request<Job>("POST", "/jobs", {
      body: { repo_id: repoId, environment, use_agent: useAgent },
    }),

  cancelJob: (jobId: string) => request<Job>("POST", `/jobs/${enc(jobId)}/cancel`),

  graph: (args: { repoId?: string; environment: string }, signal?: AbortSignal) =>
    request<Graph>("GET", "/graph", { query: { repo_id: args.repoId, environment: args.environment }, signal }),

  trace: (
    args: { entityId: string; direction: TraceDirection; repoId?: string; environment: string },
    signal?: AbortSignal,
  ) =>
    request<Trace>("GET", "/trace", {
      query: {
        entity_id: args.entityId,
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
