"use client";

import { RefreshCw } from "lucide-react";

interface ApiDownProps {
  message: string;
  status: number;
  onRetry: () => void;
}

/** Actionable state for an unreachable or failing local API. */
export function ApiDown({ message, status, onRetry }: ApiDownProps) {
  const unreachable = status === 0 || status === 503;
  return (
    <div className="center-state">
      <section className="card" role="alert" aria-labelledby="api-down-title">
        <h2 id="api-down-title" className="card-title">
          {unreachable ? "Local API unavailable" : "API request failed"}
        </h2>
        <p className="error-text" style={{ color: "var(--ink-2)" }}>
          {message}
        </p>
        {unreachable ? (
          <>
            <p className="card-text">Start both processes, then retry:</p>
            <pre className="raw-block" aria-label="Start commands">
              {"npm run api   # Python API on 127.0.0.1:8787\nnpm run dev   # this web app"}
            </pre>
          </>
        ) : (
          <p className="card-text">The API responded with an error. The detail above came from the server.</p>
        )}
        <div className="row-inline">
          <button type="button" className="btn primary" onClick={onRetry}>
            <RefreshCw className="icon" aria-hidden="true" />
            Retry
          </button>
        </div>
      </section>
    </div>
  );
}
