"use client";

import { RefreshCw } from "lucide-react";
import { Dialog } from "./Dialog";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";

/** Sanitized runtime config from GET /api/settings. Secrets are never returned or shown. */
export function SettingsDialog() {
  const ws = useWorkspace();
  const open = ws.dialog === "settings";
  return (
    <Dialog open={open} onClose={ws.closeDialog} title="Settings" size="default">
      {open ? <SettingsBody /> : null}
    </Dialog>
  );
}

function yesNo(value: boolean | undefined): string {
  if (value === undefined) return "—";
  return value ? "yes" : "no";
}

function SettingsBody() {
  const ws = useWorkspace();
  const settings = ws.settings.data;
  const sync = ws.lastSync;

  return (
    <div className="stack">
      {ws.settings.error ? (
        <p className="error-text" role="alert">
          Settings unavailable: {ws.settings.error}
        </p>
      ) : null}
      {ws.settings.loading && !settings ? <p className="muted" style={{ margin: 0 }}>Loading settings…</p> : null}

      {settings ? (
        <div className="settings-grid" aria-label="Sanitized runtime settings">
          <div>
            <span className="k">Repository root</span>
            <span className="v">{settings.repo_root}</span>
          </div>
          <div>
            <span className="k">System identity</span>
            <span className="v">{settings.system}</span>
          </div>
          <div>
            <span className="k">Environment (this view)</span>
            <span className="v">{ws.environment}</span>
          </div>
          <div>
            <span className="k">Luna agent</span>
            <span className="v">
              {yesNo(settings.agent.enabled)} · model {settings.agent.model}
            </span>
          </div>
          <div>
            <span className="k">Agent key on server</span>
            <span className="v">{yesNo(settings.agent.api_key_configured)}</span>
          </div>
          <div>
            <span className="k">Neo4j configured</span>
            <span className="v">{yesNo(settings.neo4j.enabled)}</span>
          </div>
          <div>
            <span className="k">API token required</span>
            <span className="v">{yesNo(settings.api_token_required)}</span>
          </div>
        </div>
      ) : null}

      <p className="hint" style={{ margin: 0 }}>
        Secrets and connection strings are never shown here. The bearer token lives only in the Next.js server
        environment and is forwarded by the local proxy. The browser never stores it.
      </p>

      <div className="label">Last Neo4j sync (this session)</div>
      {sync ? (
        <div className="settings-grid">
          <div>
            <span className="k">Status</span>
            <span className="v">{sync.status}</span>
          </div>
          <div>
            <span className="k">Projection</span>
            <span className="v">
              {sync.projection_id} · {sync.nodes} nodes · {sync.edges} edges
            </span>
          </div>
          {sync.error ? (
            <div>
              <span className="k">Error</span>
              <span className="v" style={{ color: "var(--red-700)" }}>
                {sync.error}
              </span>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          No sync run in this session. There is no sync-status endpoint, so nothing is shown as synced.
        </p>
      )}

      <div className="row-inline">
        <button type="button" className="btn small" onClick={ws.settings.reload}>
          <RefreshCw className="icon" aria-hidden="true" />
          Reload settings
        </button>
      </div>
    </div>
  );
}
