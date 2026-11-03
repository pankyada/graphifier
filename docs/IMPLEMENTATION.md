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
