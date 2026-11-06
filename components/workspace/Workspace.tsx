"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { useWorkspaceState, type Workspace as WorkspaceState } from "./useWorkspace";
import { WorkspaceProvider, useWorkspace } from "./WorkspaceContext";
import { TopBar } from "@/components/shell/TopBar";
import { LeftRail } from "@/components/shell/LeftRail";
import { Inspector } from "@/components/shell/Inspector";
import { ResizeHandle } from "@/components/shell/ResizeHandle";
import { Toasts } from "@/components/shell/Toasts";
import { StatusBanners } from "@/components/shell/StatusBanners";
import { SettingsDialog } from "@/components/shell/SettingsDialog";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { ShortcutsDialog } from "@/components/shell/ShortcutsDialog";
import { MainPane } from "@/components/graph/MainPane";
import { CoverageDialog } from "@/components/graph/CoverageDialog";
import { FolderBrowserDialog } from "@/components/repos/FolderBrowserDialog";
import { RunAnalysisDialog } from "@/components/jobs/RunAnalysisDialog";

/** Root client shell. Owns global state and renders the grid, dialogs and toasts. */
export function Workspace() {
  const state = useWorkspaceState();
  return (
    <WorkspaceProvider value={state}>
      <WorkspaceShell />
    </WorkspaceProvider>
  );
}

function WorkspaceShell() {
  const ws = useWorkspace();
  const wsRef = useRef<WorkspaceState>(ws);

  useEffect(() => {
    wsRef.current = ws;
  });

  // Keyboard: Cmd+K or / palette, [ ] panels, f fit, u/d/b trace, Backspace back, ? help, Esc clear.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (wsRef.current.dialog === "palette") wsRef.current.closeDialog();
        else if (!document.querySelector("dialog[open]")) wsRef.current.openDialog("palette");
        return;
      }
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (document.querySelector("dialog[open]")) return;
      const target = event.target as HTMLElement | null;
      const typing = !!target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
      const current = wsRef.current;

      if (event.key === "Escape") {
        if (current.focus) current.setFocus(null);
        else if (current.selection) current.clearSelection();
        return;
      }
      if (typing) return;
      switch (event.key) {
        case "/": {
          event.preventDefault();
          current.openDialog("palette");
          break;
        }
        case "?":
          current.openDialog("shortcuts");
          break;
        case "[":
          current.toggleRail();
          break;
        case "]":
          current.toggleInspector();
          break;
        case "f":
          current.fitGraph();
          break;
        case "u":
        case "d":
        case "b":
          if (current.selection?.kind === "node") {
            current.setFocus(current.selection.id, event.key === "u" ? "in" : event.key === "d" ? "out" : "both");
          }
          break;
        case "Backspace":
          current.focusBack();
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const railWidth = ws.railHidden ? 0 : ws.railWidth;
  const inspectorWidth = ws.inspectorHidden ? 0 : ws.inspectorWidth;
  // CSS custom properties drive the grid tracks; hidden panels collapse to 0px.
  const gridVars = {
    "--rail-w": `${railWidth}px`,
    "--inspector-w": `${inspectorWidth}px`,
    "--rail-handle": ws.railHidden ? "0px" : "6px",
    "--inspector-handle": ws.inspectorHidden ? "0px" : "6px",
  } as unknown as CSSProperties;

  const drawerOpen = ws.railDrawerOpen || ws.inspectorDrawerOpen;
  const closeDrawers = () => {
    ws.setRailDrawerOpen(false);
    ws.setInspectorDrawerOpen(false);
  };

  const visibleNodes = ws.graph.data?.nodes.length ?? 0;
  const visibleEdges = ws.graph.data?.edges.length ?? 0;
  const healthOk = !!ws.health.data && !ws.health.error;

  return (
    <div className="app">
      <TopBar />

      <div
        className={`workspace${ws.railHidden ? " rail-hidden" : ""}${ws.inspectorHidden ? " inspector-hidden" : ""}`}
        style={gridVars}
      >
        <LeftRail />
        <ResizeHandle target="rail" />

        <main className="main">
          <div className="main-body">
            <StatusBanners />
            <MainPane />
          </div>
        </main>

        <ResizeHandle target="inspector" />
        <Inspector />
      </div>

      {drawerOpen ? (
        <button type="button" className="scrim" aria-label="Close open panel" onClick={closeDrawers} />
      ) : null}

      <footer className="statusbar" aria-label="Status">
        <span className="status-pill">
          <span className={`health-dot${healthOk ? " ok" : ws.health.error ? " bad" : ""}`} aria-hidden="true" />
          {healthOk ? <span className="ok">API ok</span> : ws.health.error ? <span className="bad">API unreachable</span> : "Checking API"}
        </span>
        <span className="hide-small">
          Scope: {ws.scope === "all" ? "all repositories" : (ws.repo?.name ?? "no repository")} · env{" "}
          <span className="mono">{ws.environment}</span>
        </span>
        <span className="hide-small">
          Snapshot graph: {visibleNodes} nodes · {visibleEdges} edges
        </span>
        <span className="topbar-spacer" style={{ flex: 1 }} />
        <button type="button" className="statusbar-link hide-small" onClick={() => ws.openDialog("shortcuts")}>
          Keyboard shortcuts <span className="kbd">?</span>
        </button>
      </footer>

      <Toasts />
      <SettingsDialog />
      <FolderBrowserDialog />
      <RunAnalysisDialog />
      <CoverageDialog />
      <CommandPalette />
      <ShortcutsDialog />
    </div>
  );
}
