"use client";

import { useEffect, useState } from "react";
import { Database, PanelLeft, PanelRight, RefreshCw, Search, Settings, Waypoints } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { DEFAULT_ENVIRONMENT } from "@/components/workspace/useWorkspace";

export function TopBar() {
  const ws = useWorkspace();
  const settings = ws.settings.data;
  const healthOk = !!ws.health.data && !ws.health.error;
  const neo4jReady = settings ? settings.neo4j.enabled : false;

  return (
    <header className="topbar">
      <button
        type="button"
        className="icon-btn"
        aria-label="Toggle repositories and jobs panel"
        title="Toggle left panel ([)"
        onClick={ws.toggleRail}
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
          className="icon-btn"
          aria-label="Toggle inspector panel"
          title="Toggle inspector (])"
          onClick={ws.toggleInspector}
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
  const count = ws.graph.data?.nodes.length;
  return (
    <button
      type="button"
      id="global-search"
      className="search-trigger"
      aria-label="Search nodes and actions"
      aria-haspopup="dialog"
      onClick={() => ws.openDialog("palette")}
    >
      <Search className="icon" aria-hidden="true" />
      <span className="truncate">{count !== undefined ? `Search ${count} nodes and actions` : "Search actions"}</span>
      <span className="search-trigger-keys topbar-desktop-only" aria-hidden="true">
        <span className="kbd">⌘</span>
        <span className="kbd">K</span>
      </span>
    </button>
  );
}
