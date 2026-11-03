"use client";

import { useState } from "react";
import { CircleDashed } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { StatusLine } from "@/components/shell/StatusLine";
import { truncateText } from "@/lib/format";

type Tab = "unresolved" | "mappings";

/** Mappings section: unresolved symbols for the selected repository, plus resolution records. */
export function MappingRail() {
  const ws = useWorkspace();
  const [tab, setTab] = useState<Tab>("unresolved");

  if (ws.scope === "all" || !ws.repoId) {
    return (
      <div className="section-body">
        <div className="empty-row">
          Mappings are per repository. Pick one repository in Repositories to list its unresolved symbols.
        </div>
      </div>
    );
  }

  const unresolved = (ws.symbols.data?.symbols ?? []).filter((item) => !item.resolved);
  const resolutions = ws.resolutions.data?.resolutions ?? [];
  const loading = (ws.symbols.loading && !ws.symbols.data) || (ws.resolutions.loading && !ws.resolutions.data);
  const error = ws.symbols.error ?? ws.resolutions.error;

  return (
    <div className="section-body">
      <div className="segmented" role="tablist" aria-label="Mapping lists" style={{ alignSelf: "start", margin: "0 0 6px" }}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "unresolved"}
          onClick={() => setTab("unresolved")}
        >
          Unresolved {unresolved.length > 0 ? `(${unresolved.length})` : ""}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "mappings"}
          onClick={() => setTab("mappings")}
        >
          Mappings {resolutions.length > 0 ? `(${resolutions.length})` : ""}
        </button>
      </div>

      {loading ? <StatusLine text="Loading symbols…" /> : null}
      {error && !loading ? <StatusLine tone="bad" text={`Mappings unavailable: ${error}`} /> : null}

      {tab === "unresolved" && !loading && !error ? (
        unresolved.length === 0 ? (
          <div className="empty-row">
            {ws.symbols.data && ws.symbols.data.symbols.length === 0
              ? "No symbols in the latest completed analysis. Run analysis if sources changed."
              : "Every symbol is resolved in this environment."}
          </div>
        ) : (
          unresolved.map((item) => {
            const active = ws.mappingSymbol === item.name && !ws.mappingResolutionId;
            return (
              <button
                key={`${item.name}|${item.expression}`}
                type="button"
                className="row"
                aria-pressed={active}
                onClick={() => ws.openMapping(item.name, null)}
              >
                <span className="row-title">
                  <CircleDashed className="icon" aria-hidden="true" style={{ color: "var(--amber-700)" }} />
                  <span className="mono truncate">{item.name}</span>
                  <span className="chip unresolved" style={{ marginLeft: "auto" }}>
                    unresolved
                  </span>
                </span>
                <span className="row-meta">
                  <span className="mono truncate" title={item.expression}>
                    {truncateText(item.expression, 60)}
                  </span>
                </span>
              </button>
            );
          })
        )
      ) : null}

      {tab === "mappings" && !loading && !error ? (
        resolutions.length === 0 ? (
          <div className="empty-row">No proposals yet. Pick an unresolved symbol and propose a value expression.</div>
        ) : (
          resolutions.map((item) => {
            const active = ws.mappingResolutionId === item.id;
            return (
              <button
                key={item.id}
                type="button"
                className="row"
                aria-pressed={active}
                onClick={() => ws.openMapping(item.symbol, item.id)}
              >
                <span className="row-title">
                  <span className="mono truncate">{item.symbol}</span>
                  <span className={`chip ${item.status}`} style={{ marginLeft: "auto" }}>
                    {item.status}
                  </span>
                </span>
                <span className="row-meta">
                  <span className="mono truncate" title={item.expression}>
                    {truncateText(item.expression, 60)}
                  </span>
                </span>
                <span className="row-meta">
                  <span className="chip tag">{item.environment}</span>
                  <span>v{item.version}</span>
                </span>
              </button>
            );
          })
        )
      ) : null}
    </div>
  );
}
