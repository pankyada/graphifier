"use client";

import { Database, Ellipsis, FileSearch, Keyboard, RefreshCw, Search, Settings, Waypoints } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { ReanalyseMenu } from "@/components/jobs/ReanalyseMenu";
import { AttentionMenu } from "./AttentionMenu";
import { Popover } from "./Popover";
import { ScopeSwitcher } from "./ScopeSwitcher";

export function TopBar() {
  return (
    <header className="topbar">
      <div className="brand" title="Graphifier">
        <span className="brand-glyph" aria-hidden="true">
          <Waypoints className="icon" />
        </span>
        <span className="sr-only">Graphifier</span>
      </div>
      <ScopeSwitcher />
      <SearchBox />
      <AttentionMenu />
      <ReanalyseMenu />
      <MoreMenu />
    </header>
  );
}

function SearchBox() {
  const ws = useWorkspace();
  return (
    <button
      type="button"
      id="global-search"
      className="search-trigger"
      aria-label="Search entities and actions"
      aria-haspopup="dialog"
      onClick={() => ws.openDialog("palette")}
    >
      <Search className="icon" aria-hidden="true" />
      <span className="truncate">Search entities and actions</span>
      <span className="search-trigger-keys topbar-desktop-only" aria-hidden="true">
        <span className="kbd">⌘</span>
        <span className="kbd">K</span>
      </span>
    </button>
  );
}

function MoreMenu() {
  const ws = useWorkspace();
  const healthOk = !!ws.health.data && !ws.health.error;
  const neo4jReady = ws.settings.data?.neo4j.enabled ?? false;

  return (
    <Popover
      label="More actions"
      triggerClassName="icon-btn more-trigger"
      align="right"
      width={240}
      trigger={
        <>
          <Ellipsis className={`icon${ws.graph.loading || ws.syncing ? " spin" : ""}`} aria-hidden="true" />
          {ws.health.error ? <span className="more-alert" aria-hidden="true" /> : null}
        </>
      }
    >
      {(close) => (
        <div className="menu">
          <button
            type="button"
            className="menu-item"
            onClick={() => {
              ws.openDialog("embeddings");
              close();
            }}
          >
            <FileSearch className="icon" aria-hidden="true" />
            <span className="menu-item-text">Code search</span>
          </button>
          <button
            type="button"
            className="menu-item"
            onClick={() => {
              ws.repos.reload();
              ws.jobs.reload();
              ws.reloadGraph();
              ws.reloadMappings();
              close();
            }}
          >
            <RefreshCw className="icon" aria-hidden="true" />
            <span className="menu-item-text">Refresh</span>
          </button>
          <button
            type="button"
            className="menu-item"
            disabled={!neo4jReady || ws.syncing}
            title={neo4jReady ? "Rebuild the Neo4j projection for the current scope and environment" : "Neo4j is not configured on this server"}
            onClick={() => {
              void ws.syncNeo4j();
              close();
            }}
          >
            <Database className="icon" aria-hidden="true" />
            <span className="menu-item-text">Sync Neo4j</span>
          </button>
          <div className="menu-sep" />
          <button
            type="button"
            className="menu-item"
            onClick={() => {
              ws.openDialog("shortcuts");
              close();
            }}
          >
            <Keyboard className="icon" aria-hidden="true" />
            <span className="menu-item-text">Keyboard shortcuts</span>
            <span className="kbd">?</span>
          </button>
          <button
            type="button"
            className="menu-item"
            onClick={() => {
              ws.openDialog("settings");
              close();
            }}
          >
            <Settings className="icon" aria-hidden="true" />
            <span className="menu-item-text">Settings</span>
          </button>
          <div className="menu-sep" />
          <div className="menu-status" role="status">
            <span className={`health-dot${healthOk ? " ok" : ws.health.error ? " bad" : ""}`} aria-hidden="true" />
            {healthOk ? `API ${ws.health.data?.version ?? ""}` : ws.health.error ? "API unreachable" : "Checking API"}
          </div>
        </div>
      )}
    </Popover>
  );
}
