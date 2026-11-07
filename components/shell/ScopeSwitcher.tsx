"use client";

import { useEffect, useState } from "react";
import { Check, ChevronsUpDown, Folder, FolderPlus, GitBranch, Layers } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { DEFAULT_ENVIRONMENT } from "@/components/workspace/useWorkspace";
import { isImportActive } from "@/lib/jobs";
import { Popover } from "./Popover";

/** The one place that answers "what am I looking at": repository, all repositories, environment. */
export function ScopeSwitcher() {
  const ws = useWorkspace();
  const name = ws.scope === "all" ? "All repositories" : (ws.repo?.name ?? "No repository");
  const cloning = ws.importList.filter(isImportActive).length;

  return (
    <Popover
      label={`Scope: ${name}, environment ${ws.environment}`}
      triggerClassName="scope-trigger"
      trigger={
        <>
          <span className="scope-name truncate">{name}</span>
          <span className="scope-env mono truncate">{ws.environment}</span>
          <ChevronsUpDown className="icon" aria-hidden="true" />
        </>
      }
    >
      {(close) => (
        <div className="menu">
          <div className="menu-label">Repository</div>
          <div className="menu-scroll">
            {ws.repoList.map((item) => {
              const active = ws.scope === "repo" && item.id === ws.repoId;
              const Icon = item.remote_url ? GitBranch : Folder;
              return (
                <button
                  key={item.id}
                  type="button"
                  className="menu-item"
                  aria-current={active ? "true" : undefined}
                  title={item.path}
                  onClick={() => {
                    ws.selectRepo(item.id);
                    close();
                  }}
                >
                  <Icon className="icon" aria-hidden="true" />
                  <span className="menu-item-text">
                    <span className="truncate">{item.name}</span>
                    <span className="menu-item-meta mono truncate">{item.path}</span>
                  </span>
                  {active ? <Check className="icon menu-check" aria-hidden="true" /> : null}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="menu-item"
            aria-current={ws.scope === "all" ? "true" : undefined}
            onClick={() => {
              ws.setScope("all");
              close();
            }}
          >
            <Layers className="icon" aria-hidden="true" />
            <span className="menu-item-text">All repositories</span>
            {ws.scope === "all" ? <Check className="icon menu-check" aria-hidden="true" /> : null}
          </button>
          <button
            type="button"
            className="menu-item"
            onClick={() => {
              ws.openDialog("browse");
              close();
            }}
          >
            <FolderPlus className="icon" aria-hidden="true" />
            <span className="menu-item-text">
              Add repository
              {cloning > 0 ? <span className="menu-item-meta">{cloning} clone{cloning === 1 ? "" : "s"} in progress</span> : null}
            </span>
          </button>
          <div className="menu-sep" />
          <EnvironmentField />
        </div>
      )}
    </Popover>
  );
}

function EnvironmentField() {
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
    <label className="menu-field">
      <span className="menu-label">Environment</span>
      <input
        className="input mono"
        list={listId}
        value={draft}
        spellCheck={false}
        autoComplete="off"
        title="Scopes graph, symbols, mappings and jobs. Press Enter to apply."
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
    </label>
  );
}
