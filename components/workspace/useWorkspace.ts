"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, messageOf } from "@/lib/api";
import { PREF_KEYS, readList, readNumberPref, readPref, writeList, writePref } from "@/lib/prefs";
import { isActive } from "@/lib/jobs";
import { useResource } from "@/lib/useResource";
import type {
  Graph,
  GraphEdge,
  GraphNode,
  Health,
  Job,
  Neo4jSyncResult,
  Repository,
  Resolution,
  Settings,
  SymbolsResponse,
  Trace,
  TraceDirection,
} from "@/lib/types";

export const DEFAULT_ENVIRONMENT = "default";
export const ACTOR = "human";
export const LARGE_GRAPH_THRESHOLD = 150;

const RAIL_MIN = 240;
const RAIL_MAX = 420;
const INSPECTOR_MIN = 300;
const INSPECTOR_MAX = 520;
const RECENT_LIMIT = 6;
const ENV_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/;

export type Scope = "repo" | "all";
export type InspectorTab = "evidence" | "details" | "mapping";
export type ToastTone = "ok" | "bad" | "info";
export type DialogName = "settings" | "browse" | "run" | "coverage";

export interface Selection {
  kind: "node" | "edge";
  id: string;
}

export interface Focus {
  id: string;
  direction: TraceDirection;
}

export interface Toast {
  id: number;
  tone: ToastTone;
  text: string;
}

export function isNarrowViewport(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(max-width: 1100px)").matches;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * Single source of truth for the workspace: repositories, active scope and
 * environment, graph/trace/mapping data, job polling, selection and panels.
 * Components read it through WorkspaceProvider so props are not drilled.
 */
export function useWorkspaceState() {
  const [hydrated, setHydrated] = useState(false);
  const [repoId, setRepoId] = useState<string | null>(null);
  const [scope, setScopeState] = useState<Scope>("repo");
  const [environment, setEnvironmentState] = useState(DEFAULT_ENVIRONMENT);
  const [recentEnvironments, setRecentEnvironments] = useState<string[]>([DEFAULT_ENVIRONMENT]);
  const [railWidth, setRailWidthState] = useState(288);
  const [inspectorWidth, setInspectorWidthState] = useState(360);
  const [railHidden, setRailHidden] = useState(false);
  const [inspectorHidden, setInspectorHidden] = useState(false);
  const [railDrawerOpen, setRailDrawerOpen] = useState(false);
  const [inspectorDrawerOpen, setInspectorDrawerOpen] = useState(false);
  const [staticNoticeDismissed, setStaticNoticeDismissed] = useState(false);
  const [focus, setFocusState] = useState<Focus | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("evidence");
  const [mappingSymbol, setMappingSymbol] = useState<string | null>(null);
  const [mappingResolutionId, setMappingResolutionId] = useState<string | null>(null);
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(() => new Set());
  const [centerRequest, setCenterRequest] = useState<{ id: string; nonce: number } | null>(null);
  const [fitNonce, setFitNonce] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [authIssue, setAuthIssue] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<Set<string>>(() => new Set());
  const [lastSync, setLastSync] = useState<Neo4jSyncResult | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [dialog, setDialog] = useState<DialogName | null>(null);

  const toastSeq = useRef(0);
  const nonce = useRef(0);
  const seenJobs = useRef(new Map<string, string>());

  // ---------- toasts & errors ----------

  const toast = useCallback((tone: ToastTone, text: string) => {
    toastSeq.current += 1;
    const id = toastSeq.current;
    setToasts((prev) => [...prev.slice(-3), { id, tone, text }]);
    window.setTimeout(
      () => setToasts((prev) => prev.filter((item) => item.id !== id)),
      tone === "bad" ? 9000 : 4000,
    );
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const fail = useCallback(
    (context: string, error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        setAuthIssue(error.message);
        toast("bad", `${context}: API token rejected.`);
        return;
      }
      toast("bad", `${context}: ${messageOf(error)}`);
    },
    [toast],
  );

  // ---------- hydrate non-secret preferences after mount (no SSR mismatch) ----------

  useEffect(() => {
    const env = readPref(PREF_KEYS.environment, DEFAULT_ENVIRONMENT);
    setEnvironmentState(ENV_PATTERN.test(env) ? env : DEFAULT_ENVIRONMENT);
    const recents = readList(PREF_KEYS.recentEnvironments).filter((v) => ENV_PATTERN.test(v));
    setRecentEnvironments(recents.length ? recents : [DEFAULT_ENVIRONMENT]);
    setScopeState(readPref(PREF_KEYS.scope, "repo") === "all" ? "all" : "repo");
    const storedRepo = readPref(PREF_KEYS.repoId, "");
    setRepoId(storedRepo || null);
    setRailWidthState(clamp(readNumberPref(PREF_KEYS.railWidth, 288), RAIL_MIN, RAIL_MAX));
    setInspectorWidthState(clamp(readNumberPref(PREF_KEYS.inspectorWidth, 360), INSPECTOR_MIN, INSPECTOR_MAX));
    setRailHidden(readPref(PREF_KEYS.railHidden, "") === "1");
    setInspectorHidden(readPref(PREF_KEYS.inspectorHidden, "") === "1");
    setStaticNoticeDismissed(readPref(PREF_KEYS.staticNoticeDismissed, "") === "1");
    setHydrated(true);
  }, []);

  // ---------- resources ----------

  const health = useResource<Health>("health", (signal) => api.health(signal));
  const settings = useResource<Settings>("settings", (signal) => api.settings(signal));
  const repos = useResource<{ repositories: Repository[] }>("repos", (signal) => api.repositories(signal));

  const repoList = useMemo(() => repos.data?.repositories ?? [], [repos.data]);
  const repo = useMemo(() => repoList.find((item) => item.id === repoId) ?? null, [repoList, repoId]);
  const repoNames = useMemo(() => new Map(repoList.map((item) => [item.id, item.name])), [repoList]);

  // Keep the selected repo valid whenever the repository list changes.
  useEffect(() => {
    if (!repos.data) return;
    const ids = new Set(repos.data.repositories.map((item) => item.id));
    setRepoId((prev) => (prev && ids.has(prev) ? prev : repos.data?.repositories[0]?.id ?? null));
  }, [repos.data]);

  const scopeRepoId = scope === "repo" ? repoId : undefined;

  const jobsKey = !repos.data ? null : scope === "all" ? "all" : repoId ? `repo:${repoId}` : null;
  const jobs = useResource<{ jobs: Job[] }>(jobsKey, (signal) => api.jobs(scopeRepoId ?? undefined, signal));
  const jobList = useMemo(() => jobs.data?.jobs ?? [], [jobs.data]);

  const graphKey =
    repoList.length > 0 && (scope === "all" || repoId) ? `${scope === "all" ? "*" : repoId}|${environment}` : null;
  const graph = useResource<Graph>(graphKey, (signal) =>
    api.graph({ repoId: scopeRepoId ?? undefined, environment }, signal),
  );

  const mappingKey = scope === "repo" && repoId && repoList.length > 0 ? `${repoId}|${environment}` : null;
  const symbols = useResource<SymbolsResponse>(mappingKey, (signal) => api.symbols(repoId ?? "", environment, signal));
  const resolutions = useResource<{ resolutions: Resolution[] }>(mappingKey, (signal) =>
    api.resolutions(repoId ?? "", environment, signal),
  );

  const traceKey = focus ? `${focus.id}|${focus.direction}|${scope === "all" ? "*" : repoId}|${environment}` : null;
  const trace = useResource<Trace>(traceKey, (signal) =>
    api.trace(
      {
        entityId: focus?.id ?? "",
        direction: focus?.direction ?? "both",
        repoId: scopeRepoId ?? undefined,
        environment,
      },
      signal,
    ),
  );

  // Health polls every 15s, paused while the tab is hidden.
  const reloadHealth = health.reload;
  useEffect(() => {
    const id = window.setInterval(() => {
      if (!document.hidden) reloadHealth();
    }, 15000);
    return () => window.clearInterval(id);
  }, [reloadHealth]);

  // ---------- job polling and completion side effects ----------

  const anyActive = jobList.some((job) => isActive(job));
  const reloadJobs = jobs.reload;
  const jobsError = jobs.error;

  useEffect(() => {
    if (!anyActive) return;
    const timer = window.setTimeout(() => {
      if (!document.hidden) reloadJobs();
    }, jobsError ? 5000 : 1500);
    return () => window.clearTimeout(timer);
  }, [anyActive, jobs.data, jobsError, reloadJobs]);

  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden) reloadJobs();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [reloadJobs]);

  const reloadGraph = graph.reload;
  const reloadSymbols = symbols.reload;
  const reloadResolutions = resolutions.reload;

  useEffect(() => {
    if (!jobs.data) return;
    const seen = seenJobs.current;
    let completed = 0;
    const failed: Job[] = [];
    for (const job of jobs.data.jobs) {
      const previous = seen.get(job.id);
      if (previous && isActive({ status: previous }) && job.status !== previous) {
        if (job.status === "completed") completed += 1;
        if (job.status === "failed") failed.push(job);
      }
      seen.set(job.id, job.status);
    }
    if (completed > 0) {
      reloadGraph();
      reloadSymbols();
      reloadResolutions();
      toast("ok", `Analysis completed. Graph reloaded${completed > 1 ? ` (${completed} jobs)` : ""}.`);
    }
    for (const job of failed) {
      toast("bad", `Analysis failed: ${job.error || "no error text returned by the API."}`);
    }
  }, [jobs.data, reloadGraph, reloadSymbols, reloadResolutions, toast]);

  useEffect(() => {
    if (!jobs.data) return;
    const activeIds = new Set(jobs.data.jobs.filter((job) => isActive(job)).map((job) => job.id));
    setCancelling((prev) => {
      const next = new Set([...prev].filter((id) => activeIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [jobs.data]);

  // ---------- derived graph data ----------

  const nodeIndex = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const node of graph.data?.nodes ?? []) map.set(node.id, node);
    return map;
  }, [graph.data]);

  const edgeIndex = useMemo(() => {
    const map = new Map<string, GraphEdge>();
    for (const edge of graph.data?.edges ?? []) map.set(edge.id, edge);
    return map;
  }, [graph.data]);

  const resolvedSources = useMemo(() => {
    const set = new Set<string>();
    for (const edge of graph.data?.edges ?? []) if (edge.kind === "RESOLVES_TO") set.add(edge.source);
    return set;
  }, [graph.data]);

  const latestJob = jobList[0] ?? null;

  // ---------- actions: scope, repo, environment ----------

  const resetView = useCallback(() => {
    setFocusState(null);
    setSelection(null);
    setCenterRequest(null);
  }, []);

  const selectRepo = useCallback(
    (id: string) => {
      setRepoId(id);
      writePref(PREF_KEYS.repoId, id);
      setScopeState("repo");
      writePref(PREF_KEYS.scope, "repo");
      resetView();
    },
    [resetView],
  );

  const setScope = useCallback(
    (next: Scope) => {
      setScopeState(next);
      writePref(PREF_KEYS.scope, next);
      resetView();
    },
    [resetView],
  );

  const commitEnvironment = useCallback(
    (raw: string) => {
      const value = raw.trim() || DEFAULT_ENVIRONMENT;
      if (!ENV_PATTERN.test(value)) {
        toast("bad", "Environment names use letters, numbers, dot, dash or underscore (max 64).");
        return false;
      }
      setEnvironmentState(value);
      writePref(PREF_KEYS.environment, value);
      setRecentEnvironments((prev) => {
        const next = [value, ...prev.filter((item) => item !== value)].slice(0, RECENT_LIMIT);
        writeList(PREF_KEYS.recentEnvironments, next);
        return next;
      });
      resetView();
      return true;
    },
    [resetView, toast],
  );

  // ---------- actions: panels ----------

  const setRailWidth = useCallback((width: number) => {
    const next = clamp(Math.round(width), RAIL_MIN, RAIL_MAX);
    setRailWidthState(next);
    writePref(PREF_KEYS.railWidth, next);
  }, []);

  const setInspectorWidth = useCallback((width: number) => {
    const next = clamp(Math.round(width), INSPECTOR_MIN, INSPECTOR_MAX);
    setInspectorWidthState(next);
    writePref(PREF_KEYS.inspectorWidth, next);
  }, []);

  const toggleRail = useCallback(() => {
    if (isNarrowViewport()) {
      setRailDrawerOpen((open) => !open);
      return;
    }
    const next = !railHidden;
    setRailHidden(next);
    writePref(PREF_KEYS.railHidden, next ? "1" : "");
  }, [railHidden]);

  const toggleInspector = useCallback(() => {
    if (isNarrowViewport()) {
      setInspectorDrawerOpen((open) => !open);
      return;
    }
    const next = !inspectorHidden;
    setInspectorHidden(next);
    writePref(PREF_KEYS.inspectorHidden, next ? "1" : "");
  }, [inspectorHidden]);

  const showInspector = useCallback(() => {
    if (isNarrowViewport()) setInspectorDrawerOpen(true);
    else {
      setInspectorHidden(false);
      writePref(PREF_KEYS.inspectorHidden, "");
    }
  }, []);

  const dismissStaticNotice = useCallback(() => {
    setStaticNoticeDismissed(true);
    writePref(PREF_KEYS.staticNoticeDismissed, "1");
  }, []);

  // ---------- actions: graph selection, focus and lineage ----------

  const selectNode = useCallback(
    (id: string) => {
      setSelection({ kind: "node", id });
      showInspector();
      setInspectorTab("evidence");
    },
    [showInspector],
  );

  const selectEdge = useCallback(
    (id: string) => {
      setSelection({ kind: "edge", id });
      showInspector();
      setInspectorTab("evidence");
    },
    [showInspector],
  );

  const clearSelection = useCallback(() => setSelection(null), []);

  const setFocus = useCallback(
    (id: string | null, direction: TraceDirection = "both") => {
      if (!id) {
        setFocusState(null);
        return;
      }
      setFocusState({ id, direction });
      setSelection({ kind: "node", id });
    },
    [],
  );

  const setDirection = useCallback((direction: TraceDirection) => {
    setFocusState((prev) => (prev ? { ...prev, direction } : prev));
  }, []);

  const centerOn = useCallback((id: string) => {
    nonce.current += 1;
    setCenterRequest({ id, nonce: nonce.current });
  }, []);

  const fitGraph = useCallback(() => setFitNonce((value) => value + 1), []);

  const toggleKind = useCallback((kind: string) => {
    setHiddenKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }, []);

  // ---------- actions: mappings ----------

  const openMapping = useCallback(
    (symbol: string | null, resolutionId: string | null = null) => {
      setMappingSymbol(symbol);
      setMappingResolutionId(resolutionId);
      setInspectorTab("mapping");
      showInspector();
    },
    [showInspector],
  );

  const reloadMappings = useCallback(() => {
    reloadSymbols();
    reloadResolutions();
  }, [reloadSymbols, reloadResolutions]);

  const reloadTrace = trace.reload;
  const reloadAfterBinding = useCallback(() => {
    reloadGraph();
    reloadSymbols();
    reloadResolutions();
    if (focus) reloadTrace();
  }, [reloadGraph, reloadSymbols, reloadResolutions, reloadTrace, focus]);

  // ---------- actions: jobs ----------

  const requestCancel = useCallback(
    async (job: Job) => {
      setCancelling((prev) => new Set(prev).add(job.id));
      try {
        await api.cancelJob(job.id);
        toast("info", "Cancel requested. The status updates when the worker acknowledges it.");
        reloadJobs();
      } catch (error) {
        setCancelling((prev) => {
          const next = new Set(prev);
          next.delete(job.id);
          return next;
        });
        fail("Cancel failed", error);
      }
    },
    [fail, reloadJobs, toast],
  );

  // ---------- actions: Neo4j ----------

  const syncNeo4j = useCallback(async () => {
    setSyncing(true);
    try {
      const result = await api.neo4jSync(
        scope === "repo" && repoId ? { repoId, environment } : { environment },
      );
      setLastSync(result);
      if (result.status === "error" || result.error) {
        toast("bad", `Neo4j sync failed: ${result.error ?? result.status}. Local graph unaffected.`);
      } else {
        toast("ok", `Neo4j projection synced: ${result.nodes} nodes, ${result.edges} edges.`);
      }
    } catch (error) {
      fail("Neo4j sync", error);
    } finally {
      setSyncing(false);
    }
  }, [environment, fail, repoId, scope, toast]);

  // ---------- panels: dialogs ----------

  const openDialog = useCallback((name: DialogName) => setDialog(name), []);
  const closeDialog = useCallback(() => setDialog(null), []);

  const afterRegister = useCallback(
    (created: Repository) => {
      setRepoId(created.id);
      writePref(PREF_KEYS.repoId, created.id);
      setScopeState("repo");
      writePref(PREF_KEYS.scope, "repo");
      resetView();
      repos.reload();
      toast("ok", `Registered ${created.name}. Run analysis to index it.`);
    },
    [repos, resetView, toast],
  );

  return {
    hydrated,
    // connection
    health,
    settings,
    authIssue,
    clearAuthIssue: () => setAuthIssue(null),
    // repositories and scope
    repos,
    repoList,
    repo,
    repoId,
    repoNames,
    scope,
    setScope,
    selectRepo,
    afterRegister,
    environment,
    recentEnvironments,
    commitEnvironment,
    // jobs
    jobs,
    jobList,
    latestJob,
    cancelling,
    requestCancel,
    // graph
    graph,
    nodeIndex,
    edgeIndex,
    resolvedSources,
    hiddenKinds,
    toggleKind,
    setHiddenKinds,
    focus,
    setFocus,
    setDirection,
    trace,
    selection,
    selectNode,
    selectEdge,
    clearSelection,
    centerRequest,
    centerOn,
    fitNonce,
    fitGraph,
    reloadGraph,
    // mappings
    symbols,
    resolutions,
    mappingSymbol,
    mappingResolutionId,
    openMapping,
    reloadMappings,
    reloadAfterBinding,
    inspectorTab,
    setInspectorTab,
    // panels
    railWidth,
    setRailWidth,
    inspectorWidth,
    setInspectorWidth,
    railHidden,
    railDrawerOpen,
    setRailDrawerOpen,
    toggleRail,
    inspectorHidden,
    inspectorDrawerOpen,
    setInspectorDrawerOpen,
    toggleInspector,
    showInspector,
    staticNoticeDismissed,
    dismissStaticNotice,
    dialog,
    openDialog,
    closeDialog,
    // neo4j
    lastSync,
    syncing,
    syncNeo4j,
    // feedback
    toasts,
    toast,
    dismissToast,
    fail,
    scopeRepoId,
  };
}

export type Workspace = ReturnType<typeof useWorkspaceState>;
