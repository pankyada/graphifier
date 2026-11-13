# Graphifier

A local Next.js workspace for evidence-backed repository flow, data lineage, interface graphs, and optional semantic code search across multi-language repositories. Index source, inspect calculations and statistical models, trace potential downstream impact, and resolve variable-based table names through a shared human/agent API.

SQLite stores source snapshots, findings, jobs, and mapping decisions. Neo4j is an optional, rebuildable connected-graph projection. AI enrichment uses a configurable OpenAI-compatible endpoint only when selected for a job. Embeddings are separately optional.

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

Open [Graphifier](http://127.0.0.1:3011). The API runs at [127.0.0.1:8787](http://127.0.0.1:8787/api/health); its generated contract is at [API docs](http://127.0.0.1:8787/docs).

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

You can also import a GitHub or Bitbucket repository by URL from the repository panel. The worker clones it into the configured repository root, then registers the completed checkout for analysis. Imports run asynchronously with progress, cancellation, and retry. An optional branch selects a branch or tag accepted by Git. Private repositories use the worker host's configured Git credential helper or SSH agent/key. Interactive credential prompts are disabled, and credentials must not be embedded in the URL. GitHub and Bitbucket Cloud are allowed by default; add enterprise Git hosts with `GRAPHIFIER_GIT_HOSTS`. Import performs a clone of source files; submodules and Git LFS objects require separate host preparation.

For your own code, set `GRAPHIFIER_REPO_ROOT` to an absolute parent directory containing the repositories. Registration and scanning stay inside that root. The folder browser selects directories on the machine running the API, not on a remote browser's device.

## Optional integrations

**AI harness:** open Settings to enter the endpoint base URL, model, API mode, and optional API key. Test connection lists the endpoint’s advertised models, then Save persists the configuration for the API and worker. Choose Responses or Chat Completions to match your provider. Saved configuration overrides `OPENAI_BASE_URL`, `GRAPHIFIER_AGENT_MODEL`, `GRAPHIFIER_AGENT_API`, and `OPENAI_API_KEY` defaults. The key is write-only in the UI/API. Leaving it blank preserves the existing value only for the same endpoint. Changing the endpoint (including its path) clears the previous key unless a new key is supplied; Remove key explicitly clears it. Provider redirects are rejected: configure the final API URL directly. Settings are stored in the local SQLite database, including any saved key. Restart the API and worker after upgrading this code; later settings changes apply to new analyses. Both workflow profiles are captured at source snapshot time and preserved when resuming. Explicitly select AI analysis when submitting a job. The model investigates indexed repository context through paginated file listing, bounded source reads, and literal search, with configurable file and step budgets. Source excerpts leave the device for the selected endpoint. The harness prioritizes likely entrypoints and context-heavy files, validates line evidence and relationship endpoints, and records model provenance. It cannot execute repository code.

**Workflow model selection:** Settings has independent model and reasoning controls for **AI harness** and **AI architecture grouping**, sharing the endpoint and credentials. Fresh OpenAI settings default to `gpt-6-luna` with **Low** reasoning for the harness and **High** for grouping; the harness also has a **Luna Medium** preset. Existing saved harness choices are preserved. Custom endpoints inherit the harness model and effort for grouping until overridden. Test connection lists advertised model IDs for both selectors; it does not guarantee support for a reasoning effort. Environment defaults: `GRAPHIFIER_AGENT_REASONING_EFFORT`, `GRAPHIFIER_HIERARCHY_MODEL`, and `GRAPHIFIER_HIERARCHY_REASONING_EFFORT`.

**AI grouping and summaries:** enable **AI architecture grouping** in Run analysis. This is independent of source AI extraction: static extraction plus AI grouping is supported. The selected model receives bounded component facts, dependencies and captured code excerpts, then proposes component explanations and architecture groups. Every accepted membership and citation refers to an existing entity; detailed facts and lineage are unchanged. Graph views offer **AI grouping** and **Source structure**, with inferred rationale, model, confidence (a model assessment, not a measured probability) and source citations in the inspector. Partial/invalid output leaves source groups in place and shows coverage warnings. Model transport failures leave the job resumable; completed responses are checkpointed. Browsing never makes model calls. `GRAPHIFIER_AI_HIERARCHY_MAX_BATCHES=0` means no total call cap; a positive value caps model calls across component and architecture passes, and the captured budget is preserved on resume. Each request remains bounded; architecture grouping across separate batches is explicitly reported as incomplete.

**Optional embeddings:** set `GRAPHIFIER_EMBEDDING_MODEL`, then enable embeddings for a job. `GRAPHIFIER_EMBEDDING_BASE_URL` and `GRAPHIFIER_EMBEDDING_API_KEY` override the OpenAI environment settings (not saved UI settings). A different embedding endpoint requires its own explicit key; it never inherits the previous provider’s key. Code chunks and vectors are stored with source hashes and exact line ranges in SQLite. Search uses exact cosine similarity over the selected latest snapshots. This portable local vector store scans the matching vectors for each query, so very large vector indexes will need an approximate-nearest-neighbor backend. Failed or incomplete indexes are excluded from search.

**Neo4j:** set `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`. Use Sync Neo4j to publish a projection. Aggregate synchronization connects repositories within the selected environment. Local browsing and resolution work without Neo4j. The adapter replaces only its own projection scope and keeps other scopes intact.

**External agents:** use the same HTTP API as the UI. Set `GRAPHIFIER_API_TOKEN` for authenticated direct API access and send a bearer token. The Next.js proxy adds this server-side token; do not put it in a `NEXT_PUBLIC_*` variable. Agent attribution does not replace authorization. See [API contract](backend/API.md) and [extension guide](docs/EXTENDING.md).

## Documentation

- [Detailed architecture and domain model](docs/DESIGN.md)
- [Delivered scope, limitations, and validation](docs/IMPLEMENTATION.md)
- [Multilevel graph implementation and validation](docs/MULTILEVEL_IMPLEMENTATION.md)
- [How to extend parsers, resolution actions, agents, models, and graph storage](docs/EXTENDING.md)
- [HTTP API contract](backend/API.md)
- [UI design direction](docs/UI_DESIGN.md)
- [Sample repositories](examples/README.md)

## Data and operations

Default SQLite location: `backend/data/graphifier.sqlite3`. Override with `GRAPHIFIER_DB`. Indexed source content is stored there to preserve evidence after files change. Treat the database as source-code-bearing data. Back up SQLite with its backup API or while services are stopped; do not copy only the database file while ignoring active WAL files.

Run one worker per database. Queued jobs persist across restarts. Interrupted running work is marked failed at restart. Jobs with a durable checkpoint can be resumed from the job list using their captured source and settings. Starting a new analysis captures current files. Older jobs or jobs interrupted before source capture completes require a new analysis. Unchanged static extraction is reused by source hash, path, and parser version. Source snapshots are staged on disk. AI enrichment runs again when selected. Findings and graph assembly still use memory proportional to graph size.

The extraction is conservative and bounded. Dynamic macros, arbitrary Python execution, SQL dialect details, runtime paths, and deployed statistical-model versions may remain unresolved. A graph shows potential static lineage, not proof of production execution. Bindings currently apply at repository/environment/symbol scope, not invocation scope.

## Views and repository scale

- **Flow** shows programs, modules, entrypoints, and dependencies with source evidence.
- **Constellation** emphasizes interfaces, shared datasets, models, and high-level transformations. Internal work data and column details are hidden, with bounded derived connections retaining evidence through hidden intermediates.
- **Code search** uses the optional embeddings index and links each match to its indexed source.

Choose **Architecture**, **Components**, or **Full detail** independently of the Flow/Constellation layout. Architecture groups describe observed responsibilities, inputs, outputs and dependencies. Components expose module/directory boundaries, with file components in larger scopes. Full detail includes implementation entities and lineage. Small repositories can drill directly from Architecture to Detail when an intermediate level adds no useful structure. All three levels remain selectable.

Select a group and choose **Explore contents**. Breadcrumbs return to its containing scope. Search finds detailed entities across levels and reveals their containing component. Summary connections expose paginated supporting relationships and indexed source evidence. Ownership relationships remain in Detail rather than masquerading as architecture dependencies.

**Canvas limits:** choose 40, 100, 250 or All loaded. Architecture and Components default to All loaded; Full detail defaults to 100. The caption distinguishes nodes shown, nodes loaded, scope totals and server truncation. All loaded displays the current bounded server window, not the entire repository. Narrow the scope or search to locate entities beyond that window. Focused lineage traces retain all returned path nodes and are not trimmed by the canvas limit.

**Include tests** is off by default. Test directory/filename conventions and recognised Python unittest/pytest declarations classify test entities; mixed/shared production resources stay visible. Hidden-test counts and classification metadata remain inspectable. Filtering changes the view, never the stored evidence. Neo4j exports retain tests and include hierarchy groups, membership and rollups.

Hierarchy views use durable indexed SQLite generations keyed by source snapshots, bindings and grouping implementation. Navigation and traces pin a generation; Refresh adopts the latest. Warm views and pinned traces read bounded windows/adjacency instead of rebuilding the full graph. Raw/hierarchy build stages survive failed publication. Cold construction still assembles the complete graph in memory. Re-analysis is needed to obtain newly supported function/method declarations. Existing snapshots gain hierarchy views immediately, with local-import links derived from their captured source.

The browser requests a bounded graph window and searches across the full projected graph before applying that window. Hidden counts and truncation remain visible. The full graph is retained for detailed inspection and Neo4j projection.

Manifest discovery identifies package/module boundaries and monorepos. SAS, SQL, Python, and Shell retain specialized extraction. Additional languages include JavaScript/TypeScript, Java, Kotlin, Scala, Go, Rust, C#, Ruby, R, C/C++, and PHP, with conservative structural/interface heuristics and explicit coverage warnings. Supported imports, manifest entrypoints, and module membership provide flow context. These adapters do not provide complete language semantics.

Default scan budgets are 100,000 files, 1 GB total source, and 5 MB per file. Exceeding a scan budget fails explicitly and preserves the previous completed snapshot. Configure `GRAPHIFIER_MAX_FILES`, `GRAPHIFIER_MAX_SOURCE_BYTES`, and `GRAPHIFIER_MAX_FILE_BYTES` for your estate. AI file and investigation-step budgets are unlimited by default. Set `GRAPHIFIER_AGENT_MAX_FILES` or `GRAPHIFIER_AGENT_MAX_STEPS` to a positive number to impose a cap; `0` means unlimited. Cancellation and per-request timeouts remain available. Model context and output limits still apply. Files outside an explicitly configured file budget retain static findings with coverage warnings.

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
- **AI job fails:** inspect its error; verify credentials, model access, endpoint, and network. TLS uses verified certificates; use `SSL_CERT_FILE` for an approved enterprise CA bundle, never disable verification.
- **Neo4j unavailable:** check URI/authentication and database availability. Local findings remain usable.
- **Binding has no affected references:** inspect the exact symbol and source expression. A config variable may require further interpretation or a future adapter before it affects a dataset identity.

## Column lineage coverage

Supported SQL projections connect source columns through explicit calculation nodes to output columns. Table aliases, simple joins, explicit INSERT target columns, and filter/join/grouping dependencies are recorded with their roles. Ambiguous unqualified join columns and nested/compound query scopes produce coverage warnings. SAS single-source DATA-step assignments and literal Python dataframe column assignments provide calculation paths to written outputs. Dataset and column identities can connect across indexed files and repositories when their physical parent identity is known.

AI extraction follows the same parent-dataset and transformation-expression contract. Calculation expressions must match their cited source, and model-local references are remapped before graph assembly. These checks establish structural evidence consistency; they do not establish complete SQL dialect, SAS macro, or arbitrary Python execution semantics.

When AI analysis is enabled, unresolved static cases become explicit investigation tasks. The harness can inspect static findings, look up declared table/column schemas from the captured repository, and read related code before proposing missing lineage. Complex SQL and ambiguous joins are prioritized for investigation. Recovered relationships retain model provenance and source citations. Static coverage warnings remain visible, and a model proposal does not prove that an unsupported SQL construct was fully resolved. Static-only analysis makes no model requests.
