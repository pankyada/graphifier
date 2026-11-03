"use client";

import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { ResourceNotice } from "./ResourceNotice";

/** Page-level banners: API health regressions and rejected tokens. */
export function StatusBanners() {
  const ws = useWorkspace();
  const healthDown = !!ws.health.error && !!ws.repos.data;
  const showAuth = !!ws.authIssue;

  if (!healthDown && !showAuth) return null;

  return (
    <div className="banner-stack">
      {healthDown ? (
        <div className="banner bad" role="alert">
          <div className="banner-body">
            <div className="banner-title">API unreachable</div>
            <div>
              {ws.health.error} Local data stays on screen. Changes will fail until the API is back. Start it with{" "}
              <span className="mono">npm run api</span>.
            </div>
          </div>
          <button type="button" className="btn small" onClick={ws.health.reload}>
            Retry
          </button>
        </div>
      ) : null}
      {showAuth ? (
        <ResourceNotice
          tone="warn"
          title="API token required"
          text="The Python API rejected the request. Set GRAPHIFIER_API_TOKEN in the Next.js server environment so the proxy can forward it. The browser never stores the token."
          onDismiss={ws.clearAuthIssue}
        />
      ) : null}
    </div>
  );
}
