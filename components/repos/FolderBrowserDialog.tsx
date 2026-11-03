"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ArrowUp, ChevronRight, Folder, FolderOpen } from "lucide-react";
import { Dialog } from "@/components/shell/Dialog";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { api, messageOf } from "@/lib/api";
import { basename, parentPath } from "@/lib/format";
import { useResource } from "@/lib/useResource";
import type { BrowseResponse } from "@/lib/types";

export function FolderBrowserDialog() {
  const ws = useWorkspace();
  const open = ws.dialog === "browse";
  return (
    <Dialog open={open} onClose={ws.closeDialog} title="Add repository" size="wide">
      {open ? <Browser /> : null}
    </Dialog>
  );
}

/**
 * Lists allowlisted directories only. The API returns directories and never
 * exposes files here. Registering uses the highlighted folder, or the folder
 * currently open when nothing is highlighted.
 */
function Browser() {
  const ws = useWorkspace();
  const [path, setPath] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [rootPath, setRootPath] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const listing = useResource<BrowseResponse>(`browse:${path ?? ""}`, (signal) => api.browse(path ?? undefined, signal));
  const current = listing.data?.path ?? null;
  const target = selected ?? current;

  useEffect(() => {
    if (path === null && listing.data && rootPath === null) setRootPath(listing.data.path);
  }, [listing.data, path, rootPath]);

  useEffect(() => {
    if (!nameTouched && target) setName(basename(target));
  }, [target, nameTouched]);

  const open = (next: string | null) => {
    setError(null);
    setSelected(null);
    setPath(next);
  };

  const canGoUp = !!current && current !== rootPath && parentPath(current) !== null;

  const register = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!target) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.registerRepository(target, name.trim() || undefined);
      ws.afterRegister(created);
      ws.closeDialog();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={register} className="stack" aria-label="Folder browser">
      <p className="card-text" style={{ margin: 0 }}>
        Pick a local folder. Graphifier reads files, never runs them. Browsing stays inside the allowed root
        {ws.settings.data ? (
          <>
            {" "}
            <span className="mono">{ws.settings.data.repo_root}</span>
          </>
        ) : null}
        .
      </p>

      <div className="row-inline" style={{ flexWrap: "nowrap" }}>
        <button type="button" className="btn small" disabled={!canGoUp} onClick={() => open(parentPath(current ?? "") )} aria-label="Up one folder">
          <ArrowUp className="icon" aria-hidden="true" />
          Up
        </button>
        <nav aria-label="Current folder" className="crumbs grow">
          <span className="truncate" title={current ?? ""}>
            {current ?? (listing.loading ? "Loading…" : "—")}
          </span>
        </nav>
      </div>

      {listing.error ? (
        <p className="error-text" role="alert">
          {listing.error}
        </p>
      ) : null}

      <div className="browser-list" role="listbox" aria-label="Folders" aria-busy={listing.loading}>
        {listing.loading && !listing.data ? <div className="empty-row">Loading folders…</div> : null}
        {listing.data && listing.data.entries.length === 0 ? (
          <div className="empty-row">No subfolders here. You can still register this folder.</div>
        ) : null}
        {listing.data?.entries.map((entry) => {
          const isSelected = entry.path === target;
          return (
            <div key={entry.path} className="browser-row" role="option" aria-selected={isSelected}>
              <Folder className="icon" aria-hidden="true" />
              <button
                type="button"
                className="browser-name"
                title="Select. Double-click to open."
                onClick={() => setSelected(entry.path)}
                onDoubleClick={() => open(entry.path)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") open(entry.path);
                }}
              >
                {entry.name}
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Open ${entry.name}`}
                onClick={() => open(entry.path)}
              >
                <ChevronRight className="icon" aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>

      <div className="row-inline" style={{ alignItems: "flex-end" }}>
        <div className="field" style={{ flex: "1 1 180px" }}>
          <label className="label" htmlFor="repo-name">
            Name
          </label>
          <input
            id="repo-name"
            className="input"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setNameTouched(true);
            }}
            maxLength={120}
            placeholder={target ? basename(target) : "Repository name"}
          />
        </div>
        <div className="field" style={{ flex: "2 1 240px", minWidth: 0 }}>
          <span className="label">Selected folder</span>
          <span className="mono truncate" title={target ?? ""} style={{ height: 28, display: "flex", alignItems: "center" }}>
            <FolderOpen className="icon" aria-hidden="true" style={{ marginRight: 6 }} />
            {target ?? "Nothing selected"}
          </span>
        </div>
      </div>

      {error ? (
        <p className="error-text" role="alert">
          {error}
        </p>
      ) : null}

      <div className="row-inline" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn" onClick={ws.closeDialog}>
          Cancel
        </button>
        <button type="submit" className="btn primary" disabled={!target || submitting}>
          {submitting ? "Registering…" : "Register folder"}
        </button>
      </div>
    </form>
  );
}
