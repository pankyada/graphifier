# Extending Graphifier

Read `DESIGN.md` first. The architectural rule is simple: extend extraction and resolution through the durable local model, then rebuild projections. Do not patch Neo4j directly or silently replace raw source evidence.

## Repository map

| Location | Responsibility |
|---|---|
| `app/`, `components/`, `lib/` | Next.js workspace and browser interaction |
| `app/api/[...path]/route.ts` | Server-side proxy to local API; secrets never enter the browser |
| `backend/graphifier/api.py` | FastAPI resource endpoints and boundary checks |
| `backend/graphifier/db.py` | SQLite connection and schema |
| `backend/graphifier/paths.py` | Scan allowlist, traversal and file limits |
| `backend/graphifier/worker.py` | Durable job processing and atomic snapshots |
| `backend/graphifier/extraction.py` | Conservative language extraction and common findings format |
| `backend/graphifier/agent.py` | Optional bounded OpenAI analysis and validation |
| `backend/graphifier/resolution.py` | Proposal lifecycle and optimistic concurrency |
| `backend/graphifier/graph.py` | Symbol substitution, physical identity, graph and trace |
| `backend/graphifier/neo4j_adapter.py` | Rebuildable Neo4j projection |
| `examples/` | Inspectable SAS/SQL/Python/Shell handoff examples |

## Add or improve a language adapter

The current entry point is `extract_file(path: str, content: str) -> dict`. It must return four lists: `entities`, `relationships`, `symbols`, and `warnings`.

```python
{
    "entities": [{
        "id": "source-local-stable-id",
        "kind": "dataset",
        "name": "${SCHEMA}.orders",
        "expression": "${SCHEMA}.orders",
        "attributes": {"method": "static"},
        "evidence": {"file": "jobs/orders.sql", "start_line": 3, "end_line": 7}
    }],
    "relationships": [],
    "symbols": [{
        "name": "SCHEMA", "expression": "${SCHEMA}",
        "evidence": {"file": "jobs/orders.sql", "start_line": 3, "end_line": 3}
    }],
    "warnings": ["Dynamic invocation context was not resolved."]
}
```

1. Add the file suffix to the supported scan list only after an adapter handles it.
2. Parse without executing source. For Python use AST rather than importing modules. For SQL dialect support, add a dedicated parser behind the same result contract rather than indefinitely expanding regular expressions.
3. Produce stable source-local IDs. The worker adds repository scope. Column identity includes its owning dataset; a column named `id` is not globally unique.
4. Emit transformations as nodes with expression and explanation. Prefer accurate coarse lineage over fabricated fine-grained lineage.
5. Relationships must reference emitted entity IDs. Use upstream-to-downstream data-flow direction. The current `DERIVES_FROM` name uses that flow convention; consumers must not reverse it based on English wording.
6. Preserve unresolved symbols and report unsupported constructs in warnings.
7. Add representative fixtures and one targeted check for the new semantics. Check evidence ranges and traversal direction, not just counts.

As adapter size grows, split `extraction.py` into `extractors/{sas,sql,python,shell}.py` with an explicit registry. Keep the public worker contract stable. Track adapter versions in snapshots before implementing cache reuse.

## Add a resolution action

The first release supports symbol-value bindings scoped by repository and environment. To add namespace aliases, exact reference-to-asset links, or external dependencies:

1. Define an explicit action type and a validated payload. Do not overload `expression` to contain executable expressions or a hidden mini-language.
2. Define scope and precedence. Exact source-reference scope and program invocation scope are useful next steps. Ambiguity must be returned as conflict data.
3. Persist the proposal and attribution in SQLite. Add a schema migration rather than dropping user history.
4. Extend the pure projection layer to apply the action without mutating source findings.
5. Extend preview to report affected references, merges/splits, and graph changes.
6. Apply with expected-version concurrency checks; enforce conflict checks inside the same transaction.
7. Support retraction and append an audit event.
8. Expose the same operation to the UI and external API clients.

For deterministic expression resolution, add a structured expression tree and bounded fixed-point evaluation. Detect cycles such as `A -> B -> A`. Runtime evaluation, shell expansion, and Python `eval` are not acceptable resolution mechanisms.

## Build an external agent integration

Use the HTTP API documented in `../backend/API.md`; there is no separate MCP server in this release. An agent can register a repository, submit/poll a job, inspect symbols and evidence, propose a binding, preview it, apply with an expected version, and query the resulting trace.

Recommended agent loop:

```text
GET symbols for repo/environment
GET evidence for unresolved references
Find authoritative configuration or ask a human
POST resolution proposal with actor attribution
GET proposal preview
If permitted and conflict-free: POST apply with expected_version
GET trace and report evidence + unresolved boundaries
```

The proposal field `expression` is the replacement value, for example `risk.risk_scored`. It is never executed. `default_value` is descriptive metadata, not an authoritative binding. Actor text is attribution, not an authentication mechanism.

Set `GRAPHIFIER_API_TOKEN` for direct API clients and send it in `Authorization: Bearer ...`. Read the current API contract for which routes require it. Never embed the token into graph data or an agent prompt. A future MCP adapter should be thin wrappers around these endpoints and preserve HTTP version-conflict behaviour. Do not give a resolver agent database write credentials.

## Extend Luna investigation

The current agent uses the Responses API with structured output and a bounded literal source lookup over already scanned files. It does not execute code or provide an unrestricted terminal. Enrichment is opt-in per job.

Additional tools should be deterministic and read-only: `read_source_range`, `find_symbol_definition`, `read_connection_mapping`, or `lookup_dataset_catalog`. Validate repository containment and return bounded excerpts. Treat source content and tool results as untrusted data. Model output must still pass evidence and endpoint validation.

Keep extraction evidence separate from model confidence. A plausible explanation is not proof of a relationship. Add per-finding method/model/prompt-version metadata before benchmarking or caching model results. For budget scaling, partition work by dependency units, cap calls/tokens, cache unchanged units, and track measured usage rather than assuming cost from file count.

## Extend statistical model lineage

Start with procedure-aware SAS adapters. Add model definition, training target, feature roles, training operation, scoring operation, artifact URI, and observed artifact version. Separate a source model definition from an actual trained artifact. Then add runtime manifest/log ingestion to link a training run to its produced artifact and a scoring run to the artifact it used.

For feature impact, represent training and scoring dependencies separately. A changed training feature can require retraining without altering the currently deployed artifact. Potential impact and observed runtime impact are different queries.

## Add transfers, APIs, and orchestration

For file transfers, represent source and destination locations plus the transfer operation. Resolve storage roots and environment variables using the same decision mechanism. Distinguish a dated instance from a logical collection.

For APIs, represent service identity, endpoint template, request/response fields, and calls. Match deployment-resolved endpoints or an explicit contract ID; similarly named paths across environments do not prove identity.

For schedulers, represent invocation edges and parameter bindings. Invocation-scoped resolution is necessary when a reusable program runs with different table names. Do not flatten these into one global variable binding.

## Replace or extend the graph backend

`neo4j_adapter.sync_repo` consumes `build_graph` output. Implement another adapter with the same normalized nodes/edges contract. Keep projection ownership explicit, parameterize writes, and return success only after commit. Do not remove data outside the adapter's namespace.

The current Neo4j adapter transactionally replaces one scope. For large graphs, use an outbox plus generation-based publication. Write a new generation, validate counts and references, atomically switch the active pointer, then clean up retired generations. Make retry behaviour idempotent.

## Scale jobs and persistence

The local runtime uses one worker and SQLite. Before parallelizing workers, replace restart recovery with leases, heartbeats, claim ownership, and safe retry. A job result should publish atomically; failed work should not replace the last good snapshot.

For incremental indexing, key cached findings by content hash, extractor version, model/prompt version, and relevant context. Track dependency invalidation for includes, shared configuration, and symbol bindings. A changed config can invalidate unchanged source files.

For multi-user deployment, add authenticated principals, authorization by repository/environment/action, central source storage policy, and an application service that cannot browse arbitrary host folders. Do not expose the local app directly to a network and call it multi-user support.

## Focused validation expectations

Choose checks for the change: extraction fixtures for new syntax, binding isolation and retraction for resolution changes, bounded upstream/downstream traversal for graph changes, and live driver synchronization for projection changes. UI changes should demonstrate the affected user flow in a browser. Never claim that mocked API or driver tests validate an external OpenAI account or deployed Neo4j instance.
