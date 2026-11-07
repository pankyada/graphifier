# Current implementation update

AI fallback receives structured static gaps and can inspect static findings, declared schemas, and related indexed source. Mocked provider acceptance exercises a complex CTE with ambiguous ownership, schema lookup by source read, a recovered source-column → calculation → output-column path with exact citations, unresolved warnings, static-only zero model calls, and durable replay of gap/tool context after local files change. Recovery remains model-inferred and static coverage warnings are retained.

Lineage validation now includes full API/worker scenarios for cross-repository SQL source-column → calculation → shared output-column → downstream calculation, SAS DATA-step assignments, Python CSV/dataframe calculations, and snapshot evidence retrieval. Ambiguous SQL join columns warn without attaching unsupported ownership. AI parent IDs are remapped to stored graph identities, and canonical columns follow their canonical dataset parent.

Model transport and embedding failures now leave jobs failed and resumable. Their staged results remain invisible until publication completes. Resume keeps the original endpoint/model/settings and accepts current credentials only for that endpoint. A changed analysis implementation requires a new analysis. A provider request interrupted before its response is persisted may be repeated on resume.

Durable analysis checkpoints preserve captured sources, completed extraction, AI conversations, consolidation output, and publication state. Resume requeues failed/cancelled jobs atomically and rejects active scope conflicts. Crash/cancellation regressions cover continuing with captured source and avoiding duplicate published snapshots.

Cross-file AI evidence now validates against the indexed source corpus. Failed per-file enrichment preserves static findings with explicit warnings. A deterministic consolidation pass merges duplicate findings while retaining evidence spans. Graph and trace support Overview, Interfaces, and Detail independently of layout, and the evidence API includes all consolidated source spans.

The repository now includes manifest-based monorepo discovery, additional language adapters, configurable scan budgets, an OpenAI-compatible investigation harness, flow/constellation projections, and optional snapshot-scoped embeddings. See README.md and backend/API.md for current configuration and contracts. The older release record below describes the original implementation and is retained as historical validation.

Remote repository import and editable AI settings were added in the same update. GitHub/Bitbucket HTTPS or SSH imports are queued for the worker, cloned shallowly into staging, and registered only after checkout succeeds. Cancel/retry, duplicate import reuse, host allowlisting, root containment, and credential-safe errors are included. A local bare Git fixture verified a real clone, remote metadata, and suppressed post-checkout hooks. No live GitHub/Bitbucket or private enterprise credential flow was exercised. Imports do not fetch submodules or Git LFS content, and an existing completed import is reused without pulling newer commits.

AI Settings now persist endpoint/model/API mode and an optional write-only key in SQLite. Test connection lists models through `/models`; extraction/tool compatibility still depends on the selected provider.

Current checks completed on 7 November 2026 (Sydney):

- 86 backend tests passed, including harness tool calls/cancellation/budgets, graph projection evidence and bounded search, embeddings isolation/failure cleanup, API layer validation, persistent AI configuration, and remote clone lifecycle/cleanup/URL handling.
- TypeScript and the optimized Next.js production build passed.
- A synthetic monorepo with 1,500 SQL files and three package manifests indexed all 1,503 sources in 3.675 seconds. It produced 28,515 findings and a full graph of 14,259 nodes. Flow and constellation requests returned bounded 800-node windows in approximately 0.3 seconds. Constellation reduced the graph to 5,256 projected nodes, hiding 9,003 detailed nodes. Search located the final file's output beyond the initial window.
- Browser acceptance was attempted, but the browser tool did not complete. The new UI has build/type verification, without completed interactive browser verification in this update.

These synthetic measurements establish coverage beyond the former 1,200-file limit. They do not establish accuracy on enterprise repositories or performance at the configured 100,000-file ceiling. Source staging and static extraction caching reduce repeated work, while findings and full graph assembly still scale with graph size in memory. Jobs now checkpoint captured sources, per-file findings, AI conversations, consolidation, and publication phases. Failed/cancelled jobs with checkpoints can be resumed. Jobs interrupted before capture completes and older jobs require a new analysis. Embeddings use an exact SQLite vector scan, with no approximate-nearest-neighbor index. AI remains bounded per file with repository context tools, and broader semantic language coverage remains adapter work. No live external model or embedding calls were made for this update's verification.

---

# Implementation status and validation

Recorded 3 November 2026. This is a runnable local first release, with conservative extraction coverage. The architectural extension ideas in `DESIGN.md` and `EXTENDING.md` are deliberately broader than the shipped feature set.

## Delivered backend

- FastAPI local API, SQLite persistence, queued jobs, cancellation, atomic completed snapshots, and a separate single-owner worker.
- Allowlisted directory browsing/registration, real-path containment, supported suffixes, dependency/secret filename exclusions, and scan limits.
- SAS, SQL, Python AST, and Shell extraction into entities, relationships, transformation expressions, evidence spans, symbols, and coverage warnings.
- SAS logistic/statistical-model definitions and training/scoring references for supported procedure syntax.
- Snapshot source content and hashes, with optional Git revision. Evidence can be retrieved by snapshot/environment.
- OpenAI Responses enrichment with `gpt-6-luna` default, structured output, bounded literal lookups, verified TLS, per-file evidence validation, and explicit model-inferred provenance.
- Repository/environment/symbol proposals, graph previews, optimistic apply/retract, conflict checks, and audit events.
- Aggregate materialized graph with canonical qualified dataset identities scoped by system/environment, preserved source references, and bounded directional tracing.
- Parameterized, transactional Neo4j projection with composite uniqueness and scope ownership. Aggregate sync retains shared physical nodes across repositories.
- HTTP API for external agents. No separate MCP server is included.

## Coverage boundaries

| Area | Current boundary |
|---|---|
| SAS | Common DATA/SET/MERGE assignments, PROC SQL, supported statistical procedure/model/score patterns; macros/includes/runtime library expansion are incomplete |
| SQL | Common SELECT/FROM/JOIN and table writes; basic projection/calculation extraction; no full dialect AST or complete nested-query semantics |
| Python | AST-based recognition of common SQL/data I/O and interpolated strings; no execution, import resolution, or general dataframe semantic analysis |
| Shell | Common file/transfer references and variables; no shell execution, full expansion, or scheduler interpretation |
| Columns | Parent-dataset-scoped columns and bounded supported calculations; not complete column lineage for every SQL/SAS construct |
| Statistical models | Source definitions and supported training/scoring references; not proof of trained artifact version or deployment |
| Resolution | Repository + environment + symbol only; no invocation scope, structured expression interpreter, automatic alias/catalog resolver, or approval roles |
| Physical identity | Qualified lexical names within a configured system/environment; users must use distinct system scopes for unrelated databases |
| Files | File references may remain symbolic; dated-file families are not fully modeled as logical partitions |
| Impact | Static graph reachability, with depth limits and gaps; not a runtime or semantic equivalence proof |
| Re-indexing | Full supported-file scan; no dependency-aware incremental cache |
| Jobs | One worker per database, restart marks interrupted work failed; no distributed leases or multi-host execution |
| Agent budgets | Bounded file/character coverage; over-budget files retain static results with explicit coverage warnings |
| Neo4j | Full scope replacement in one transaction; no outbox or generation-based incremental publication |
| Access | Local Host/Origin restrictions and optional bearer token; actor attribution is not role-based authorization |

The scanner excludes common sensitive filenames but is not a comprehensive secret scanner. Do not index repositories containing source that must not be persisted locally, and do not enable remote analysis for source that must not be sent to the configured endpoint.

## Evidence from this build

All 13 backend targeted tests pass in the project virtual environment. They cover resolution scope/conflict/version/retraction and concurrent apply, path and symlink containment, failed-job atomicity, snapshot evidence, token/host controls, single-worker ownership, SQLite connection cleanup, bounded agent enrichment, Neo4j projection isolation, and symbol replacement/traversal regressions.

Live acceptance performed against the shipped sample repositories:

1. Registered `examples/sas-risk` and `examples/reporting` through HTTP.
2. Submitted jobs through HTTP and processed them using the separate worker. Both static jobs completed.
3. Proposed and applied `RISK_SCORE_TABLE = risk.risk_scored` for both repositories in environment `default`.
4. Confirmed exactly one resolved physical dataset shared by two repositories. Downstream tracing reached the reporting summary; the checked trace contained 13 nodes and 26 edges.
5. Retrieved indexed SAS source and its SHA-256 through the evidence endpoint.
6. Completed an actual Luna API job on the sample SAS repository in the separate `agent-validation` environment. The initial host certificate failure was fixed with a verified certifi trust store, then the retry completed.
7. Synchronized the resolved aggregate to a temporary local Neo4j 5.26.32 instance: 48 nodes and 79 edges. A direct Cypher query confirmed the scored dataset carried both repository references.

The temporary Neo4j instance is validation infrastructure, not a configured production deployment. The sample database is ignored by version control. No real business repositories were scanned. Live sample success does not establish extraction accuracy across a larger SAS/SQL/Python/Shell estate.

Frontend validation: TypeScript and optimized Next.js production build pass. Browser acceptance at 1440×960 exercised folder browsing/registration, static job submission and completion through the separate worker, dataset selection with indexed code, mapping retraction, proposal preview and reapplication, all-repository search, and downstream trace (13 nodes / 26 edges). Network inspection confirmed evidence requests include both `snapshot_id` and `environment`. A 900px viewport had no page-width overflow; after the sidebar fix the desktop sidebar also had no horizontal overflow.

The final production-mode app was started at `http://127.0.0.1:3001` (port 3000 was already occupied). The API and worker remained running locally. Final production browser checks reported zero console errors or warnings. Screenshot: `output/playwright/lineage-final.png` (local validation artifact, ignored by Git).

## Delivered UI

The light workspace includes repository/job/mapping panels, a React Flow lineage canvas, graph search and upstream/downstream focus, source and detail inspectors, folder registration, static/Luna job submission, progress/cancellation controls, resolution previews/apply/retract, coverage warnings, sanitized settings, and optional Neo4j sync. Graph opening uses a readable camera position; Fit offers a whole-graph overview. Large graphs use a focus chooser. Narrow layouts use slide-over panels.

Canvas interaction: hovering a node lights its full lineage (green upstream, rust downstream) and labels its direct edges; the selected node keeps this highlight and shows inline trace actions. Nodes are draggable, with Reset layout until the node set changes. The kind legend on the canvas is also the filter. A trace keeps a clickable focus trail and a client-side hop stepper over the loaded trace. Cmd+K or `/` opens one palette for nodes, repositories and actions, replacing the top-bar search and kind menu. Arrow keys walk the graph; `?` lists all shortcuts. The inspector adds a Links tab and, with nothing selected, an overview of loaded graph counts and the most connected nodes. The left sidebar is an icon strip showing one section at a time: its panel opens over the canvas on hover or click and collapses on its own, and the pin at the bottom of the strip or `[` keeps it open. The inspector is a sheet floating over the canvas, opened with `]` or a pull-tab on its edge. The tab shows the current selection and evidence count even while the sheet is closed, and a live tether connects it to the selected node. Selecting a node no longer opens a closed sheet. Below 1100px the strip is hidden and a matching floating button opens the sidebar. Toolbar, notices and kind legend float over a full-bleed canvas. Node position changes animate over 240ms, longer than the 120ms general limit in `UI_DESIGN.md`, so a re-layout stays followable; reduced-motion disables it.

Job mode and environment come from persisted API data. Evidence selection resolves an exact indexed snapshot in the active environment. Source views do not silently fall back to another environment's latest snapshot. The browser is not given API or Neo4j credentials.

Still outside this release: custom graph editing, an explicit manual layout editor, graph comparison between revisions, invocation-scoped mapping controls, and multi-user authorization. User visual preference and accuracy on real business repositories remain acceptance work beyond the sample validation above.

## Next extensions in useful order

1. Evaluate coverage on representative repositories and prioritize actual unsupported syntax.
2. Replace SQL regex handling with a dialect-aware AST adapter; deepen SAS macro and LIBNAME resolution.
3. Add invocation-scoped bindings and explicit physical connection identities.
4. Add agent proposal-only permissions and richer evidence/rationale for resolutions.
5. Add scheduler manifests, file transfer contracts, and API producer/consumer evidence.
6. Add model artifact manifests and observed execution lineage.
7. Add incremental dependency invalidation, projection generations, and multi-worker leases when scale requires them.
