"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Search } from "lucide-react";
import { Dialog } from "@/components/shell/Dialog";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { api, isAbortError, messageOf } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { EmbeddingMatch, EmbeddingStatus } from "@/lib/types";

export function CodeSearchDialog() {
  const ws = useWorkspace();
  const open = ws.dialog === "embeddings";
  return (
    <Dialog open={open} onClose={ws.closeDialog} title="Semantic code search" size="wide">
      {open ? <CodeSearch key={`${ws.scopeRepoId ?? "all"}|${ws.environment}`} /> : null}
    </Dialog>
  );
}

function CodeSearch() {
  const ws = useWorkspace();
  const repoId = ws.scopeRepoId ?? undefined;
  const status = useResource<EmbeddingStatus>(
    `${repoId ?? "all"}|${ws.environment}`,
    (signal) => api.embeddingStatus({ repoId, environment: ws.environment }, signal),
  );
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<EmbeddingMatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setSearching(true);
    setError(null);
    setMatches(null);
    try {
      const result = await api.searchEmbeddings(
        { query: query.trim(), repoId, environment: ws.environment },
        controller.signal,
      );
      if (!controller.signal.aborted) setMatches(result.matches);
    } catch (failure) {
      if (!isAbortError(failure)) setError(messageOf(failure));
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  }

  return (
    <div className="stack">
      <p className="card-text" style={{ margin: 0 }}>
        Find code by meaning across {ws.scope === "all" ? "all repositories" : ws.repo?.name}.
        Results retain the indexed file, snapshot and source lines.
      </p>
      {status.error ? <p className="error-text" role="alert">{status.error}</p> : null}
      {status.data ? (
        <p className="hint" style={{ margin: 0 }}>
          {status.data.indexed_chunks} chunks across {status.data.indexed_snapshots} snapshots · {status.data.model || "No embedding model configured"}
        </p>
      ) : null}
      {status.data && !status.data.enabled ? (
        <p className="note-line">Configure an embedding model and endpoint on the server, then enable code embeddings when running analysis.</p>
      ) : null}
      {status.data?.enabled && status.data.indexed_chunks === 0 ? (
        <p className="note-line">Run analysis with optional code embeddings enabled to index this scope.</p>
      ) : null}
      <form onSubmit={search} className="row-inline">
        <input
          className="input"
          type="search"
          aria-label="Describe code to find"
          placeholder="Where are risk scores calculated?"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          style={{ flex: 1 }}
        />
        <button
          className="btn primary"
          type="submit"
          disabled={!query.trim() || searching || !status.data?.enabled || status.data.indexed_chunks === 0}
        >
          <Search className="icon" aria-hidden="true" />
          {searching ? "Searching…" : "Search"}
        </button>
      </form>
      <p className="hint" style={{ margin: 0 }}>
        Your query is sent to the configured embedding endpoint. Similarity scores rank related code.
      </p>
      {error ? <p className="error-text" role="alert">{error}</p> : null}
      {matches?.length === 0 ? <p className="muted">No matching chunks in this scope.</p> : null}
      <div className="embedding-results" aria-live="polite">
        {matches?.map((match, index) => (
          <article className="embedding-result" key={`${match.repo_id}|${match.snapshot_id}|${match.file}|${match.start_line}|${index}`}>
            <div className="embedding-result-head">
              <strong className="mono">{match.file}</strong>
              <span className="chip">Lines {match.start_line}–{match.end_line}</span>
              <span className="hint">Similarity {match.score.toFixed(3)}</span>
            </div>
            <div className="hint">
              {ws.repoNames.get(match.repo_id) ?? match.repo_id} · snapshot {match.snapshot_id.slice(0, 8)}
            </div>
            <pre><code>{match.content}</code></pre>
          </article>
        ))}
      </div>
    </div>
  );
}
