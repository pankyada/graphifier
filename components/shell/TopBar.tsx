"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { CircleAlert, Crosshair, Database, PanelLeft, PanelRight, RefreshCw, Search, Settings, Waypoints } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { kindIcon, kindName } from "@/components/graph/kinds";
import { DEFAULT_ENVIRONMENT } from "@/components/workspace/useWorkspace";
import type { GraphNode } from "@/lib/types";

export function TopBar() {
  const ws = useWorkspace();
  const settings = ws.settings.data;
  const healthOk = !!ws.health.data && !ws.health.error;
  const neo4jReady = settings ? settings.neo4j.enabled : false;

  return (
    <header className="topbar">
      <button
        type="button"
        className="icon-btn drawer-toggle"
        aria-label="Toggle repositories and jobs panel"
        aria-expanded={ws.railDrawerOpen}
        onClick={() => ws.setRailDrawerOpen(!ws.railDrawerOpen)}
      >
        <PanelLeft className="icon" aria-hidden="true" />
      </button>

      <div className="brand">
        <span className="brand-glyph" aria-hidden="true">
          <Waypoints className="icon" />
        </span>
        Graphifier
      </div>

      <div className="topbar-group">
        <label className="label" htmlFor="environment-input">
          Env
        </label>
        <EnvironmentInput />
      </div>

      <span className="topbar-sep" aria-hidden="true" />

      <div className="topbar-group">
        <div className="segmented" role="group" aria-label="Analysis scope">
          <button
            type="button"
            aria-pressed={ws.scope === "repo"}
            disabled={!ws.repoId}
            onClick={() => ws.setScope("repo")}
          >
            Repo
          </button>
          <button type="button" aria-pressed={ws.scope === "all"} onClick={() => ws.setScope("all")}>
            All repos
          </button>
        </div>
        <label className="sr-only" htmlFor="repo-select">
          Repository
        </label>
        <select
          id="repo-select"
          className="select topbar-desktop-only"
          style={{ maxWidth: 180 }}
          value={ws.repoId ?? ""}
          disabled={ws.repoList.length === 0}
          onChange={(event) => ws.selectRepo(event.target.value)}
        >
          {ws.repoList.length === 0 ? <option value="">No repositories</option> : null}
          {ws.repoList.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>

      <SearchBox />

      <span className="topbar-spacer" />

      <div className="topbar-group">
        <button
          type="button"
          className="btn small topbar-desktop-only"
          disabled={!neo4jReady || ws.syncing}
          title={neo4jReady ? "Rebuild the Neo4j projection for the current scope and environment" : "Neo4j is not configured on this server"}
          onClick={() => void ws.syncNeo4j()}
        >
          <Database className={`icon${ws.syncing ? " spin" : ""}`} aria-hidden="true" />
          Sync Neo4j
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-label="Refresh graph, jobs and mappings"
          title="Refresh"
          onClick={() => {
            ws.repos.reload();
            ws.jobs.reload();
            ws.reloadGraph();
            ws.reloadMappings();
          }}
        >
          <RefreshCw className={`icon${ws.graph.loading ? " spin" : ""}`} aria-hidden="true" />
        </button>
        <span className="status-pill" role="status" aria-label={healthOk ? "API healthy" : "API unreachable"}>
          <span className={`health-dot${healthOk ? " ok" : ws.health.error ? " bad" : ""}`} aria-hidden="true" />
          <span className="muted topbar-desktop-only" style={{ fontSize: 11 }}>
            {healthOk ? `API ${ws.health.data?.version ?? ""}` : ws.health.error ? "API unreachable" : "Checking API"}
          </span>
        </span>
        <button
          type="button"
          className="icon-btn"
          aria-label="Open settings"
          title="Settings (sanitized)"
          onClick={() => ws.openDialog("settings")}
        >
          <Settings className="icon" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="icon-btn drawer-toggle"
          aria-label="Toggle inspector panel"
          aria-expanded={ws.inspectorDrawerOpen}
          onClick={() => ws.setInspectorDrawerOpen(!ws.inspectorDrawerOpen)}
        >
          <PanelRight className="icon" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}

function EnvironmentInput() {
  const ws = useWorkspace();
  const [draft, setDraft] = useState(ws.environment);
  const listId = "recent-environments";

  useEffect(() => {
    setDraft(ws.environment);
  }, [ws.environment]);

  const commit = () => {
    const value = draft.trim() || DEFAULT_ENVIRONMENT;
    // Blur fires on every tab-away; only a real change should reset the view.
    if (value === ws.environment) {
      setDraft(ws.environment);
      return;
    }
    if (ws.commitEnvironment(value)) setDraft(value);
    else setDraft(ws.environment);
  };

  return (
    <>
      <input
        id="environment-input"
        className="input mono"
        style={{ width: 120 }}
        list={listId}
        value={draft}
        spellCheck={false}
        autoComplete="off"
        aria-describedby="environment-hint"
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
      />
      <datalist id={listId}>
        {ws.recentEnvironments.map((value) => (
          <option key={value} value={value} />
        ))}
      </datalist>
      <span id="environment-hint" className="sr-only">
        Environment scopes graph, symbols, mappings and jobs. Press Enter to apply.
      </span>
    </>
  );
}

function SearchBox() {
  const ws = useWorkspace();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  const nodes = ws.graph.data?.nodes ?? [];
  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return [];
    const matches: GraphNode[] = [];
    for (const node of nodes) {
      const haystack = `${node.name} ${node.expression ?? ""} ${node.kind}`.toLowerCase();
      if (haystack.includes(needle)) matches.push(node);
      if (matches.length >= 12) break;
    }
    return matches;
  }, [nodes, query]);

  useEffect(() => {
    const onPointer = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, []);

  const choose = (node: GraphNode, refocus: boolean) => {
    if (refocus) ws.setFocus(node.id, "both");
    else ws.selectNode(node.id);
    ws.centerOn(node.id);
    setOpen(false);
    setQuery("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(index + 1, Math.max(0, results.length - 1)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(0, index - 1));
    } else if (event.key === "Enter" && results[active]) {
      event.preventDefault();
      choose(results[active], event.shiftKey);
    } else if (event.key === "Escape") {
      setOpen(false);
      event.currentTarget.blur();
    }
  };

  const showResults = open && query.trim().length > 0;

  return (
    <div className="search-wrap" ref={boxRef}>
      <Search className="icon search-icon" aria-hidden="true" />
      <input
        id="global-search"
        className="input"
        type="search"
        role="combobox"
        aria-expanded={showResults}
        aria-controls="global-search-results"
        aria-autocomplete="list"
        aria-label="Search loaded graph nodes"
        placeholder={ws.graph.data ? `Search ${nodes.length} nodes` : "Search nodes"}
        value={query}
        disabled={!ws.graph.data}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      <span className="kbd topbar-desktop-only" style={{ position: "absolute", right: 6, top: 6 }} aria-hidden="true">
        /
      </span>
      {showResults ? (
        <div id="global-search-results" className="search-results" role="listbox" aria-label="Matching nodes">
          {results.length === 0 ? (
            <div className="empty-row">No loaded node matches “{query.trim()}”.</div>
          ) : (
            results.map((node, index) => {
              const Icon = kindIcon(node.kind);
              return (
                <div
                  key={node.id}
                  role="option"
                  aria-selected={index === active}
                  className="search-result"
                  tabIndex={-1}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(node, false)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") choose(node, event.shiftKey);
                  }}
                >
                  <Icon className="icon" aria-hidden="true" />
                  <span className="truncate">
                    <span style={{ fontWeight: 500 }}>{node.name}</span>{" "}
                    <span className="muted">{kindName(node.kind)}</span>
                  </span>
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={`Focus lineage of ${node.name}`}
                    title="Focus lineage (Shift+Enter)"
                    onClick={(event) => {
                      event.stopPropagation();
                      choose(node, true);
                    }}
                  >
                    <Crosshair className="icon" aria-hidden="true" />
                  </button>
                </div>
              );
            })
          )}
        </div>
      ) : null}
      {ws.graph.error ? (
        <span className="sr-only">
          <CircleAlert aria-hidden="true" /> Search unavailable until the graph loads.
        </span>
      ) : null}
    </div>
  );
}
