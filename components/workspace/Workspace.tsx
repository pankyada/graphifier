"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { PanelLeft } from "lucide-react";
import { useWorkspaceState, type Workspace as WorkspaceState } from "./useWorkspace";
import { WorkspaceProvider, useWorkspace } from "./WorkspaceContext";
import { TopBar } from "@/components/shell/TopBar";
import { LeftRail } from "@/components/shell/LeftRail";
import { Inspector } from "@/components/shell/Inspector";
import { InspectorTab } from "@/components/shell/InspectorTab";
import { ResizeHandle } from "@/components/shell/ResizeHandle";
import { Toasts } from "@/components/shell/Toasts";
import { StatusBanners } from "@/components/shell/StatusBanners";
import { SettingsDialog } from "@/components/shell/SettingsDialog";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { ShortcutsDialog } from "@/components/shell/ShortcutsDialog";
import { CodeSearchDialog } from "@/components/evidence/CodeSearchDialog";
import { MainPane } from "@/components/graph/MainPane";
import { CoverageDialog } from "@/components/graph/CoverageDialog";
import { FolderBrowserDialog } from "@/components/repos/FolderBrowserDialog";
import { RunAnalysisDialog } from "@/components/jobs/RunAnalysisDialog";

const SHEET_MARGIN = 12;

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

  const railWidth = ws.railPinned ? ws.railWidth : 0;
  // The inspector floats over the canvas, so these tell floating controls how far to stay clear of it.
  const sheetOpen = !ws.inspectorHidden;
  const gridVars = {
    "--rail-w": `${railWidth}px`,
    "--inspector-w": `${ws.inspectorWidth}px`,
    "--sheet-space": sheetOpen ? `${ws.inspectorWidth + SHEET_MARGIN * 2}px` : "0px",
    "--tab-right": sheetOpen ? `${ws.inspectorWidth + SHEET_MARGIN}px` : "0px",
    "--rail-handle": ws.railPinned ? "6px" : "0px",
  } as unknown as CSSProperties;

  const drawerOpen = ws.railDrawerOpen || ws.inspectorDrawerOpen;
  const closeDrawers = () => {
    ws.setRailDrawerOpen(false);
    ws.setInspectorDrawerOpen(false);
  };

  return (
    <div className="app">
      <TopBar />

      <div
        className={`workspace${ws.railPinned ? "" : " rail-unpinned"}${ws.inspectorHidden ? " inspector-hidden" : ""}`}
        style={gridVars}
      >
        <LeftRail />
        <ResizeHandle target="rail" />

        <main className="main">
          <div className="main-body">
            <StatusBanners />
            <MainPane />
            <button
              type="button"
              className="panel-fab panel-fab-left"
              aria-label="Show sidebar"
              title="Show sidebar ([)"
              onClick={ws.toggleRail}
            >
              <PanelLeft className="icon" aria-hidden="true" />
            </button>
          </div>
        </main>

        <ResizeHandle target="inspector" />
        <Inspector />
        <InspectorTab />
      </div>

      {drawerOpen ? (
        <button type="button" className="scrim" aria-label="Close open panel" onClick={closeDrawers} />
      ) : null}

      <Toasts />
      <SettingsDialog />
      <FolderBrowserDialog />
      <RunAnalysisDialog />
      <CoverageDialog />
      <CodeSearchDialog />
      <CommandPalette />
      <ShortcutsDialog />
    </div>
  );
}
