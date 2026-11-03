"use client";

import { useMemo, useState } from "react";
import { Copy, FileText, X } from "lucide-react";
import { api } from "@/lib/api";
import { sha8 } from "@/lib/format";
import { useResource } from "@/lib/useResource";
import type { EvidenceResponse } from "@/lib/types";
import type { ViewerTarget } from "@/lib/evidence";

const WINDOW_LINES = 2000;
const CONTEXT_LINES = 400;

interface CodeViewerProps {
  target: ViewerTarget;
  onClose: () => void;
}

/**
 * Shows the indexed source snapshot for an evidence span. Content comes from
 * the snapshot that produced the selected item in the active environment, not
 * the working tree, so the footer says so. Very large files render a window
 * around the evidence rather than every line.
 */
export function CodeViewer({ target, onClose }: CodeViewerProps) {
  const { repoId, snapshotId, environment, file } = target;
  const key = repoId && snapshotId ? `${repoId}|${snapshotId}|${environment}|${file}` : null;
  const source = useResource<EvidenceResponse>(key, (signal) =>
    api.evidence({ repoId, snapshotId, environment, file }, signal),
  );

  const lines = useMemo(() => (source.data?.content ?? "").split("\n"), [source.data]);
  const total = lines.length;
  const windowed = total > WINDOW_LINES;
  const from = windowed ? Math.max(1, target.startLine - CONTEXT_LINES) : 1;
  const to = windowed ? Math.min(total, target.endLine + CONTEXT_LINES) : total;

  return (
    <section className="code-viewer" aria-label={`Source ${target.file}`}>
      <div className="code-head">
        <FileText className="icon" aria-hidden="true" />
        <span className="mono truncate grow" title={target.file}>
          {target.file}
        </span>
        <span className="muted" style={{ whiteSpace: "nowrap" }}>
          L{target.startLine}
          {target.endLine !== target.startLine ? `–${target.endLine}` : ""}
        </span>
        <button type="button" className="icon-btn" aria-label="Close source viewer" onClick={onClose}>
          <X className="icon" aria-hidden="true" />
        </button>
      </div>

      {!snapshotId ? (
        <div className="empty-row" role="status">
          No indexed snapshot for this item in environment {environment}. Run analysis in this environment to view its source.
        </div>
      ) : null}
      {snapshotId && source.loading && !source.data ? <div className="empty-row">Loading indexed source…</div> : null}
      {source.error ? (
        <div className="empty-row" role="alert" style={{ color: "var(--red-700)" }}>
          {source.status === 404
            ? `Snapshot not found for this repository in environment ${environment}.`
            : source.error}
        </div>
      ) : null}
      {source.data && source.data.content === null ? (
        <div className="empty-row">Snapshot file unavailable. The indexed snapshot has no content for this file.</div>
      ) : null}

      {source.data && source.data.content !== null ? (
        <div className="code-scroll" role="region" aria-label="Source lines" tabIndex={0}>
          {windowed && from > 1 ? <div className="note-line" style={{ padding: "2px 10px" }}>… {from - 1} earlier lines hidden</div> : null}
          {lines.slice(from - 1, to).map((text, index) => {
            const number = from + index;
            const inRange = number >= target.startLine && number <= target.endLine;
            return (
              <div key={number} className={`code-line${inRange ? " in-range" : ""}`} id={`L${number}`}>
                <span className="ln">{number}</span>
                <span className="src">{text || " "}</span>
              </div>
            );
          })}
          {windowed && to < total ? <div className="note-line" style={{ padding: "2px 10px" }}>… {total - to} more lines</div> : null}
        </div>
      ) : (
        <div />
      )}

      <div className="code-foot">
        {source.data?.sha256 ? (
          <>
            <span className="mono">sha256 {sha8(source.data.sha256)}</span>
            <button
              type="button"
              className="icon-btn"
              aria-label="Copy full sha256"
              onClick={() => void navigator.clipboard?.writeText(source.data?.sha256 ?? "")}
            >
              <Copy className="icon" aria-hidden="true" />
            </button>
          </>
        ) : null}
        <span className="grow">Indexed snapshot in {environment}, not working tree.</span>
        {total > 0 ? <span>{total} lines</span> : null}
      </div>
    </section>
  );
}
