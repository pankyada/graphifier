"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  Crosshair,
  Database,
  FolderPlus,
  Keyboard,
  Layers,
  LayoutPanelLeft,
  Maximize,
  PanelRight,
  Play,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  X,
  type LucideIcon,
} from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { displayName, kindColor, kindIcon, kindName } from "@/components/graph/kinds";

const MAX_NODES = 12;

interface Item {
  id: string;
  group: "Nodes" | "Repositories" | "Actions";
  icon: LucideIcon;
  color?: string;
  title: string;
  meta?: string;
  run: () => void;
  /** Shift+Enter or the row's trace button. Nodes only. */
  trace?: () => void;
}

function highlighted(text: string, needle: string): ReactNode {
  const at = needle ? text.toLowerCase().indexOf(needle) : -1;
  if (at < 0) return text;
  return (
    <>
      {text.slice(0, at)}
      <mark>{text.slice(at, at + needle.length)}</mark>
      {text.slice(at + needle.length)}
    </>
  );
}

/** Cmd+K or /: one entry point for finding a node, switching repository and running any action. */
export function CommandPalette() {
  const ws = useWorkspace();
  const open = ws.dialog === "palette";
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="dialog palette"
      aria-label="Search nodes and actions"
      onClose={ws.closeDialog}
      onClick={(event) => {
        if (event.target === ref.current) ws.closeDialog();
      }}
    >
      {open ? <PaletteBody /> : null}
    </dialog>
  );
}

function PaletteBody() {
  const ws = useWorkspace();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const needle = query.trim().toLowerCase();
  const nodes = ws.graph.data?.nodes;

  const items = useMemo<Item[]>(() => {
    const close = ws.closeDialog;
    const act = (fn: () => void) => () => {
      close();
      fn();
    };

    const nodeItems: Item[] = [];
    if (needle) {
      const matches = (nodes ?? [])
        .map((node) => {
          const name = node.name.toLowerCase();
          const rank = name.startsWith(needle)
            ? 0
            : displayName(node).primary.toLowerCase().startsWith(needle)
              ? 1
              : name.includes(needle)
                ? 2
                : `${node.expression ?? ""} ${node.kind}`.toLowerCase().includes(needle)
                  ? 3
                  : -1;
          return { node, rank };
        })
        .filter((entry) => entry.rank >= 0)
        .sort((a, b) => a.rank - b.rank || a.node.name.localeCompare(b.node.name))
        .slice(0, MAX_NODES);
      for (const { node } of matches) {
        const { primary, prefix } = displayName(node);
        nodeItems.push({
          id: `node:${node.id}`,
          group: "Nodes",
          icon: kindIcon(node.kind),
          color: kindColor(node.kind),
          title: primary,
          meta: [kindName(node.kind), prefix].filter(Boolean).join(" · "),
          run: act(() => {
            ws.selectNode(node.id);
            ws.centerOn(node.id);
          }),
          trace: act(() => {
            ws.setFocus(node.id, "both");
            ws.centerOn(node.id);
          }),
        });
      }
    }

    const repoItems: Item[] = ws.repoList
      .filter((repo) => repo.id !== ws.repoId || ws.scope !== "repo")
      .map((repo) => ({
        id: `repo:${repo.id}`,
        group: "Repositories" as const,
        icon: Layers,
        title: `Switch to ${repo.name}`,
        run: act(() => ws.selectRepo(repo.id)),
      }));

    const actions: Item[] = [
      {
        id: "run",
        group: "Actions",
        icon: Play,
        title: "Run analysis",
        meta: ws.repo?.name,
        run: act(() => ws.openDialog("run")),
      },
      {
        id: "add",
        group: "Actions",
        icon: FolderPlus,
        title: "Add repository",
        run: act(() => ws.openDialog("browse")),
      },
      {
        id: "scope",
        group: "Actions",
        icon: Layers,
        title: ws.scope === "all" ? "Show current repository only" : "Show all repositories",
        run: act(() => ws.setScope(ws.scope === "all" ? "repo" : "all")),
      },
      { id: "fit", group: "Actions", icon: Maximize, title: "Fit graph to view", run: act(ws.fitGraph) },
      {
        id: "refresh",
        group: "Actions",
        icon: RefreshCw,
        title: "Refresh graph and jobs",
        run: act(() => {
          ws.repos.reload();
          ws.jobs.reload();
          ws.reloadGraph();
          ws.reloadMappings();
        }),
      },
      { id: "coverage", group: "Actions", icon: ShieldCheck, title: "Open coverage and warnings", run: act(() => ws.openDialog("coverage")) },
      { id: "rail", group: "Actions", icon: LayoutPanelLeft, title: ws.railPinned ? "Hide sidebar" : "Show sidebar", run: act(ws.toggleRail) },
      { id: "inspector", group: "Actions", icon: PanelRight, title: "Toggle inspector", run: act(ws.toggleInspector) },
      { id: "settings", group: "Actions", icon: Settings, title: "Open settings", run: act(() => ws.openDialog("settings")) },
      { id: "keys", group: "Actions", icon: Keyboard, title: "Keyboard shortcuts", run: act(() => ws.openDialog("shortcuts")) },
    ];
    if (ws.settings.data?.neo4j.enabled) {
      actions.push({ id: "neo4j", group: "Actions", icon: Database, title: "Sync Neo4j", run: act(() => void ws.syncNeo4j()) });
    }
    if (ws.focus) {
      actions.unshift({ id: "clear", group: "Actions", icon: X, title: "Clear focus", run: act(() => ws.setFocus(null)) });
    }

    const matches = (item: Item) => !needle || `${item.title} ${item.meta ?? ""}`.toLowerCase().includes(needle);
    return [...nodeItems, ...repoItems.filter(matches), ...actions.filter(matches)];
    // ws is a new object on every workspace change; these are the values the list reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needle, nodes, ws.repoList, ws.repoId, ws.scope, ws.repo, ws.focus, ws.settings.data, ws.railPinned]);

  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [active, items]);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (items.length ? (index + 1) % items.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (items.length ? (index - 1 + items.length) % items.length : 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = items[active];
      if (!item) return;
      if (event.shiftKey && item.trace) item.trace();
      else item.run();
    }
  };

  let lastGroup: string | null = null;

  return (
    <div className="palette-body">
      <div className="palette-input">
        <Search className="icon" aria-hidden="true" />
        <input
          autoFocus
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-autocomplete="list"
          aria-label="Search nodes and actions"
          placeholder={nodes ? `Search ${nodes.length} nodes, repositories and actions` : "Search repositories and actions"}
          value={query}
          spellCheck={false}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
        <span className="kbd" aria-hidden="true">
          esc
        </span>
      </div>
      <div className="palette-list" id="palette-list" role="listbox" aria-label="Results" ref={listRef}>
        {items.length === 0 ? <div className="empty-row">Nothing matches “{query.trim()}”.</div> : null}
        {items.map((item, index) => {
          const heading = item.group !== lastGroup ? item.group : null;
          lastGroup = item.group;
          const Icon = item.icon;
          return (
            <div key={item.id} role="presentation">
              {heading ? <div className="palette-group">{heading}</div> : null}
              <div
                role="option"
                aria-selected={index === active}
                className="palette-item"
                onMouseMove={() => setActive(index)}
                onClick={item.run}
              >
                <Icon className="icon" aria-hidden="true" style={item.color ? { color: item.color } : undefined} />
                <span className="truncate palette-title">{highlighted(item.title, needle)}</span>
                {item.meta ? <span className="truncate palette-meta">{item.meta}</span> : null}
                {item.trace ? (
                  <button
                    type="button"
                    className="icon-btn"
                    tabIndex={-1}
                    aria-label={`Trace lineage of ${item.title}`}
                    title="Trace lineage (Shift+Enter)"
                    onClick={(event) => {
                      event.stopPropagation();
                      item.trace?.();
                    }}
                  >
                    <Crosshair className="icon" aria-hidden="true" />
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      <div className="palette-foot">
        <span>
          <span className="kbd">↑</span> <span className="kbd">↓</span> move
        </span>
        <span>
          <span className="kbd">↵</span> open
        </span>
        <span>
          <span className="kbd">⇧</span> <span className="kbd">↵</span> trace node
        </span>
      </div>
    </div>
  );
}
