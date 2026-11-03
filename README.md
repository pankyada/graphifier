# Graphifier

A local Next.js workspace for evidence-backed data lineage across SAS, SQL, Python, and Shell repositories. Index source, inspect calculations and statistical models, trace potential downstream impact, and resolve variable-based table names through a shared human/agent API.

SQLite stores source snapshots, findings, jobs, and mapping decisions. Neo4j is an optional, rebuildable connected-graph projection. Luna enrichment uses the OpenAI API only when explicitly selected for a job.

## Run locally

Requires Node.js 20.9+ and Python 3.11+ on macOS/Linux. This build was exercised with Node 25 and Python 3.14 on macOS. The setup command uses pinned runtime versions in `backend/requirements.lock.txt`; `backend/requirements.txt` describes the direct dependency ranges for future updates.

```bash
npm install
npm run setup:backend
cp .env.example .env.local
```

Start each process in its own terminal from this directory:

```bash
npm run api
```

```bash
npm run worker
```

```bash
npm run dev
```

Open [Graphifier](http://127.0.0.1:3000). The API runs at [127.0.0.1:8787](http://127.0.0.1:8787/api/health); its generated contract is at [API docs](http://127.0.0.1:8787/docs).

Next.js, the API, and the worker read root `.env.local`; existing exported variables take precedence. Restart processes after changing configuration. Do not commit `.env.local`.

For a production-mode local UI: `npm run build`, then `npm start`. Keep the API and worker running separately. These commands bind to loopback. This is a local single-user application, not a hosted multi-user service.

## First walkthrough

1. Add a repository using the folder browser. The default allowed root contains `examples/sas-risk` and `examples/reporting`.
2. Register both folders and run **static analysis** in environment `default`.
3. Inspect the SAS logistic-model lineage and the reporting SQL transformation.
4. In each repository, propose a binding for `RISK_SCORE_TABLE` with replacement value `risk.risk_scored` in environment `default`.
5. Preview the affected references, then apply each proposal.
6. Switch to all repositories. Both references resolve to the same physical dataset. Explore downstream to `reporting.risk_summary`.
7. Retract a binding to restore the unresolved reference. The source expression and indexed evidence remain intact.

For your own code, set `GRAPHIFIER_REPO_ROOT` to an absolute parent directory containing the repositories. Registration and scanning stay inside that root. The folder browser selects directories on the machine running the API, not on a remote browser's device.

## Optional integrations

**Luna:** set `OPENAI_API_KEY` in the server environment or `.env.local`. The default model is `gpt-6-luna`; override it with `GRAPHIFIER_AGENT_MODEL`. Explicitly select agent mode when submitting a job. Bounded source excerpts leave the device. The agent may perform bounded literal lookups over the scanned source; it cannot execute repository code. API keys are never returned to the browser.

**Neo4j:** set `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`. Use Sync Neo4j to publish a projection. Aggregate synchronization connects repositories within the selected environment. Local browsing and resolution work without Neo4j. The adapter replaces only its own projection scope and keeps other scopes intact.

**External agents:** use the same HTTP API as the UI. Set `GRAPHIFIER_API_TOKEN` for authenticated direct API access and send a bearer token. The Next.js proxy adds this server-side token; do not put it in a `NEXT_PUBLIC_*` variable. Agent attribution does not replace authorization. See [API contract](backend/API.md) and [extension guide](docs/EXTENDING.md).

## Documentation

- [Detailed architecture and domain model](docs/DESIGN.md)
- [Delivered scope, limitations, and validation](docs/IMPLEMENTATION.md)
- [How to extend parsers, resolution actions, agents, models, and graph storage](docs/EXTENDING.md)
- [HTTP API contract](backend/API.md)
- [UI design direction](docs/UI_DESIGN.md)
- [Sample repositories](examples/README.md)

## Data and operations

Default SQLite location: `backend/data/graphifier.sqlite3`. Override with `GRAPHIFIER_DB`. Indexed source content is stored there to preserve evidence after files change. Treat the database as source-code-bearing data. Back up SQLite with its backup API or while services are stopped; do not copy only the database file while ignoring active WAL files.

Run one worker per database. Queued jobs persist across restarts. Interrupted running work is marked failed at restart; it never replaces a completed snapshot. Resubmit a job to retry. This release rescans supported files; incremental dependency-aware caching is a documented extension.

The extraction is conservative and bounded. Dynamic macros, arbitrary Python execution, SQL dialect details, runtime paths, and deployed statistical-model versions may remain unresolved. A graph shows potential static lineage, not proof of production execution. Bindings currently apply at repository/environment/symbol scope, not invocation scope.

## Checks

```bash
npm run typecheck
npm run build
.venv/bin/python -m pip install -r backend/requirements-dev.txt
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v
```

Tests target path containment, resolution conflicts/retraction, graph stitching and traversal, job atomicity, snapshot evidence, worker ownership, and integration boundaries. Live integration evidence and remaining gaps are recorded in `docs/IMPLEMENTATION.md`.

## Troubleshooting

- **API unavailable:** run `npm run api`; verify the configured API URL and port.
- **Queued job does not move:** start `npm run worker` using the same database/configuration as the API.
- **Folder rejected:** choose a directory under `GRAPHIFIER_REPO_ROOT`; symlink escapes are rejected.
- **No graph for an environment:** submit analysis in that environment or switch back to the indexed environment.
- **Luna job fails:** inspect its error; verify credentials, model access, endpoint, and network. TLS uses verified certificates; use `SSL_CERT_FILE` for an approved enterprise CA bundle, never disable verification.
- **Neo4j unavailable:** check URI/authentication and database availability. Local findings remain usable.
- **Binding has no affected references:** inspect the exact symbol and source expression. A config variable may require further interpretation or a future adapter before it affects a dataset identity.
