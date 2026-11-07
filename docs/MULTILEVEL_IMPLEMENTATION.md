# Multilevel graph implementation

Delivered 7 November 2026. This document distinguishes the implemented feature from the broader roadmap in `MULTILEVEL_GRAPH_PLAN.md`.

## Delivered

- Architecture, Components and Full detail; two-level recommendations when intermediate grouping adds no structure, three levels for meaningful larger scopes.
- Deterministic manifest/directory boundaries and file components in large scopes. Stable group IDs, ownership membership, source evidence, observed summaries and typed direct-edge rollups.
- Bounded input/output/dependency samples and exact counts, preserving full support separately. Structural ownership never becomes an architecture dependency. No aggregate reachability is used to infer detailed lineage.
- Test code hidden by default using directory/filename conventions, explicit context and recognised Python unittest/pytest definitions. Mixed code and shared production resources stay visible. Test-only relationships are filtered even when endpoints also occur in production.
- Python lexical class/function/method/async extraction with shadow-aware local calls; conservative JS/TS classes, methods, named functions and named arrows. Local static JS/TS/Python imports connect captured source programs. Unsupported calls/import forms stay unresolved.
- Indexed SQLite generations, memberships, rollups and support. Fingerprints include snapshot vector, applied resolutions, grouping version, graph implementation and test visibility.
- Recoverable raw/hierarchy construction stages and atomic publication. Analysis prewarms the default repository view; projection failures do not invalidate successful source extraction.
- Bounded warm windows and pinned indexed detailed traces. Search reveals detailed matches from any level. Group exploration, breadcrumbs, context toggle, classification and support inspector are wired into the existing UI.
- Neo4j exports retain full detail including tests and add groups, memberships and rollups in the existing owned transactional projection.

## Validation

The backend suite passed 155 tests after the AI-assisted hierarchy integration. Backend regressions cover source ownership, test filtering, shared canonical resources, false aggregate paths, bounded boundaries, support pagination, snapshot pinning, failed-publication recovery and warm reads/traces that forbid a full rebuild. Production build and TypeScript checks are run during integration. Browser checks use the existing base repository to verify Architecture, group inspection, drill-down and hidden-test counts.

Synthetic local measurements (Python 3.14 on this workspace host; direct functions, not HTTP):

| Fixture | Hierarchy construction | SQLite publication | Warm overview read | Overview payload |
|---|---:|---:|---:|---:|
| 10k nodes, sparse chain | 0.111 s | 0.157 s | max 1.01 ms over 10 reads | 8.7 KB |
| 100k nodes, sparse chain | 1.221 s | 1.572 s | max 1.75 ms over 10 reads | 83.6 KB |
| 100,001 nodes, 100k hub calls | 1.409 s | 1.692 s | 0.82 ms | 3.1 KB |

These fixtures validate bounded overview behaviour, not end-to-end extraction speed, dense-graph performance, HTTP p95 or million-node capacity. Peak process RSS was approximately 344 MB for the cumulative sparse run and 301 MB for the hub run. Measurements preceded the final exclusion of structural rollups and do not include source discovery or AI analysis.

## Explicit limits and follow-on work

Cold graph construction and consolidation still use whole-graph memory. Stage checkpoints resume projection construction but do not yet partition it into independently incremental components. Source extraction reuses unchanged static files; a new snapshot rebuilds its hierarchy. There is no million-node or arbitrary dense-graph readiness claim.

Hierarchy offers deterministic source structure and optional saved AI-assisted component explanations and capability grouping. Durable human regrouping overrides and dependency-aware component invalidation remain follow-on work. AI requests use bounded source evidence and dependencies; separate architecture batches are not globally consolidated, and this limitation appears as a partial-coverage warning. Logical boundaries do not prove deployment architecture. Symbol coverage is strongest in Python and conservative in JS/TS; other existing language adapters keep their prior coverage.

Stored generations currently have no automatic retention policy. Large repeated analyses can grow SQLite; do not remove generations while readers rely on pinned IDs. Neo4j still uses whole-scope transactional replacement. Scoped detail includes bounded external detail endpoints, rather than fully mixed collapsed/expanded component representation.

Restart the API and worker after upgrading. Existing snapshots get hierarchy views immediately; run a new analysis to extract the new code symbols. Legacy snapshots derive local-import links from captured source during cold projection construction; live checkout changes do not affect that evidence. Old interrupted extraction checkpoints reject changed parser fingerprints explicitly rather than mixing implementations.


## AI-assisted hierarchy validation

The configured Responses/Chat Completions transport is reused. Unit and integration tests mock provider responses; no live model run was submitted during implementation. Tests cover valid grouping and summaries, source snippets and prompt budgets, malicious/foreign references, unchanged detailed evidence, hidden tests, per-repository scope, saved-response recovery, cancellation, generation pinning, partial fallbacks, and credential exclusion. Neo4j uses the same saved proposals when exporting semantic groups.
