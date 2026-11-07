# Multilevel repository understanding — proposed implementation

Status: design proposal, 7 November 2026. See `MULTILEVEL_IMPLEMENTATION.md` for the delivered implementation, validation and remaining roadmap items.

## Outcome

Provide Architecture, Components and Detail as semantic levels. Small repositories default to Architecture and Detail; large repositories and solutions expose all three. Always retain the detailed evidence. Level selection changes the representation, not extraction completeness.

| Level | Question | Typical content |
|---|---|---|
| Architecture | What does this system do? | Services, capabilities, pipeline stages, external systems, major data stores and inputs/outputs |
| Components | How is it organised? | Modules, job families, packages, interfaces, tables and significant transformations |
| Detail | How is this implemented? | Files, classes, functions, methods, calls, tables, columns and individual calculations |

Level is independent of scope (solution/repository/component), lens (architecture/code/data lineage), and layout (Flow/Constellation). A small repository may still have meaningful components. Offer a manual level override. Very large solutions use nested scopes within these same three levels.

## Current implementation and gaps

- `graph_views.py` offers overview/interfaces/detail via visibility filtering and bounded paths through hidden nodes. It does not establish semantic aggregate membership.
- `consolidation.py` conservatively deduplicates findings with matching source evidence and semantics; retain this identity work separately from grouping.
- `discovery.py` discovers manifest/module boundaries; expand this as an anchor for component identification.
- `graph.py:build_graph` constructs the full graph before projecting/windowing it. Moving this work out of each request is a scaling prerequisite.
- `db.py` stores source snapshots and JSON findings in SQLite. Neo4j is a rebuildable optional projection. Preserve that ownership model.
- `worker.py` and `checkpoints.py` provide durable extraction/consolidation state. Add partition-level checkpoints for hierarchy and projection construction.
- Function/method coverage needs a language-by-language assessment and scope-aware extraction; existing broad language coverage must not be treated as full symbol resolution.

## Extraction and semantic consolidation

1. Inventory manifests, packages, deployment/configuration declarations, entrypoints, scheduler definitions, imports, APIs and physical data references. Files remain read-only inputs.
2. Extract detailed observations with lexical owner, qualified name/signature, source span, scope, visibility and provenance. Distinguish definition, invocation and physical resource identities. Preserve temporary/session data scope and unresolved calls.
3. Resolve cross-file references using symbol tables, module/import rules and known physical resource identity. Keep ambiguous candidates explicit. Name similarity does not prove identity.
4. Identify component boundaries using explicit configuration and manifests first, dependency structure second, directory boundaries as a labelled fallback. Shared libraries and shared datasets remain shared dependencies rather than duplicated ownership.
5. Build architecture groups from component responsibilities, declared deployment units, interfaces and observed data flows. A logical capability is not evidence of a deployed service. Record group category and basis.
6. With AI enabled, send bounded component evidence to propose labels, responsibilities and uncertain groupings. Require references to existing members and evidence. Validate membership, references and hierarchy cycles. Static-only mode still produces usable groups. Keep inferred labels and source-backed facts distinguishable.
7. Summarise bottom-up: detailed findings to components, components to architecture. Store structured inputs, outputs, behaviour, dependencies and unknowns alongside prose. Do not use generated prose as the sole evidence for parent summaries.

Use canonical ownership for navigation and separate many-to-many capability memberships. Code belongs to an owning scope; datasets have their own resource identity and are related by reads/writes. Low-confidence cases go into explicitly unclassified groups. Later manual split/merge/rename/move decisions are durable overlays with provenance; they must survive re-analysis or be flagged for reconciliation.

## Aggregate-edge correctness

Create a direct aggregate edge only when a detailed relationship crosses the corresponding boundary. Preserve direction, semantic kind, dependency role, conditions and inference status. Keep calls/imports separate from data reads/writes and value lineage separate from join/filter/control dependencies.

Every aggregate edge has support links to detailed relationships, exact or explicitly bounded counts, and paginated evidence. A composed path has an explicit witness path and is labelled derived. Do not infer A-to-C lineage solely because A-to-B and B-to-C involve different members of group B. Run impact/path queries on the detailed graph and lift their results into the chosen view. Do not use aggregate graph reachability as proof of a detailed path.

Internal edges stay available on expansion. Preserve disconnected/orphan findings in navigable groups. Many-to-many memberships must not multiply support counts; count distinct supporting edge IDs.

## Storage and publication

Keep source observations immutable and add indexed, rebuildable graph read models in SQLite:

| Logical table | Purpose |
|---|---|
| graph_generations | Snapshot-set, environment, resolution revision, grouping revision, parser/model/prompt versions and build status |
| graph_nodes / graph_edges | Detailed identities and indexed adjacency within a generation |
| graph_groups | Stable group identity, level/category, label, summary and provenance |
| graph_memberships | Ownership or semantic membership with rationale and provenance |
| graph_rollup_edges | Typed cross-group relationships and counts |
| graph_rollup_support | Paged links from summary edges to detailed edges or witness paths |
| graph_build_units | Durable partition status, input fingerprint and dependency fingerprints |
| graph_group_decisions | Human overrides and reconciliation status |

Index by generation, level, scope/parent, node kind, and edge source/target. Keep large evidence out of overview payloads. Store canonical definition identity separately from its snapshot occurrence; reconcile renamed/moved definitions conservatively. Group IDs should not depend on generated labels.

Build a staged generation in bounded batches, validate it, then atomically switch the active pointer. Readers pin one generation for pagination, expansion and evidence. Preserve the last complete generation on failure. Return explicit rebuild/stale status after resolution or grouping changes; never silently mix generations.

For a multi-repository solution, pin the complete snapshot vector and environment/namespace context. Explain that these indexed revisions need not represent one coordinated production release. Track shared-asset dependencies so a changed repository invalidates affected solution rollups.

Export detailed and aggregate projections plus membership/support into Neo4j with generation ownership. SQLite remains authoritative. Embeddings, when enabled, can include component summaries linked to their generation and evidence; they support discovery, not identity merging.

## Incremental processing and recovery

Checkpoint discovery, per-file extraction, cross-file resolution partitions, component groups, architecture summaries and rollup partitions. A unit fingerprint includes source/dependency hashes and the relevant extraction/grouping/model configuration. Reuse unchanged units and invalidate affected callers/consumers, groups and parent summaries. Deletions remove obsolete memberships and support during the next generation build.

Process bounded batches and partition symbol/edge joins; do not assemble all findings in Python lists for million-node runs. Recompute a partition where incremental repair is ambiguous. Restart from persisted completed units; publish only validated generations. Existing checkpoint formats need version handling and an explicit restart message when migration is impossible.

## API and visualisation

Proposed contract (not existing routes):

- Graph window: generation, scope, level, lens, focus, filters, node/edge budget and cursor.
- Group children/members: cursor pagination, counts and ancestry.
- Edge support: supporting detailed edges or composed witness paths with paginated evidence.
- Entity location: ancestor groups so detailed search results can reveal the correct scope.
- Trace: detailed traversal with budget/completeness status, then level-specific presentation.
- Generation status: coverage, group/build readiness, active revision and recommended levels.

Keep existing granularity values through a documented compatibility mapping during migration. New responses distinguish abstraction-hidden, filtered, outside-window and unresolved counts. Server queries fetch only required scopes/adjacency; avoid full graph assembly on overview requests.

Architecture cards show responsibility, inputs/outputs, child counts and coverage. Component expansion preserves external boundary nodes. Detail loads one component, function neighbourhood or table/column scope. A table card can expand columns inline. Support mixed expansion with deterministic representative selection so an entity is not rendered both independently and inside a collapsed parent.

Provide breadcrumbs, explicit expand/collapse, level selector, search across all levels and an inspector explaining group membership or edge support. Preserve positions on expansion. Semantic zoom can be optional later; explicit navigation comes first. Keep Flow and Constellation as layout choices rather than synonyms for abstraction.

Initial adjustable budgets: 10–30 architecture groups, 20–80 components per scope, 100–300 detailed canvas nodes. These are usability targets, not completeness caps. Split oversized scopes, paginate lists and offer focus rather than silently dropping evidence. Recommend two levels when a Components step adds little meaningful structure; use topology, boundary count and reduction ratio rather than lines of code alone. Never create arbitrary architectural groups merely to hit a number.

## Example: a SAS risk solution

- Architecture: source ingestion, customer preparation, risk scoring, reporting and their shared/external data resources.
- Components within scoring: feature job family, model invocation, score publication, input/output tables.
- Detail: SAS programs/macros, SQL statements, column calculations, model features, join/filter roles and output columns.

A reported output column can be found from Architecture, revealed inside its owning scope, and traced to source evidence without losing snapshot context. Business-friendly labels remain inferred unless supported by documentation or a recorded user decision.

## Delivery and subagent ownership

First freeze shared entity, membership, generation and API contracts. Then use subagents as requested:

1. Extraction agent: symbol/owner contracts and adapters, cross-file resolution, boundary signals and extraction fixtures.
2. Hierarchy agent: grouping, structured summaries, typed rollups, support paths and invariants.
3. Storage/API agent: migrations, indexed read models, checkpoint lifecycle, atomic publication, pagination and Neo4j projection.
4. UI agent: level/scope/lens controls, group cards, expansion, ancestry, support inspector and accessible navigation.
5. Verification agent after integration: independent semantic, recovery and performance checks.

Assign non-overlapping files or explicitly coordinate shared files. Preserve existing uncommitted work. UI and hierarchy work can start against agreed fixtures while storage is built. The parent agent owns integration and contract changes. Read installed Next.js guidance before UI implementation.

Deliver in gates: (A) deterministic hierarchy from existing findings with drill-down, (B) stronger detailed symbol extraction and optional AI naming/grouping, (C) incremental large-scale operation and overrides. Indexed read models and bounded queries are part of A; do not advertise very-large-repository support until C performance gates pass.

## Acceptance and measurement

- Every detailed node is reachable from an appropriate scope, including unclassified/orphan nodes; no identity merges caused by aggregation.
- Every aggregate edge resolves to real support; unrelated paths inside one group cannot create false column lineage.
- Small, monorepo, multi-repository, shared-library, cyclic-dependency and temporary-dataset fixtures preserve direction, scope and evidence across levels.
- Repeated unchanged builds retain IDs/memberships; label changes do not break bookmarks.
- Kill/resume tests at each phase reuse completed work; incomplete generations never become active.
- Binding apply/retract, deletion and human regrouping invalidate affected read models and retain coherent evidence.
- Overview query plans do not read every detailed node/edge. Test 10k, 100k and 1m nodes with sparse, hub-heavy and dense-cross-boundary graphs.
- Proposed targets to benchmark on a declared machine: warm overview API p95 below 500 ms, expansion below 1 second, overview payload below 250 KB excluding evidence. Record cold latency, build time, peak memory, disk growth and browser interaction latency separately. These are targets, not demonstrated results.
- Report extraction coverage by language/entity/relationship capability; unsupported dynamic resolution stays visible at every level.

## Recommended defaults and deferred work

Use three semantic levels internally; offer two or three in navigation according to meaningful structure. Prefer deterministic grouping, explicit user overrides and optional AI enrichment. Keep SQLite authoritative and Neo4j optional. Defer automatic zoom-driven level changes and advanced graph clustering until explicit drill-down is usable. Complete symbol extraction is a progressive language-support commitment, not a promise that arbitrary dynamic programs can be fully resolved.
