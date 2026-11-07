# Graphifier local API contract

Base URL: `http://127.0.0.1:8787`. JSON unless noted. Errors use `{ "detail": "..." }`.

## Repositories and jobs

- `GET /api/health` — `{status,version}`.
- `GET /api/repositories` — `{repositories:[{id,name,path,created_at}]}`.
- `POST /api/repositories` — `{name?,path}`; returns the repository object.
- `GET /api/browse?path=` — allowlisted directories and `{path,entries:[{name,path,is_dir}]}`.
- `GET /api/jobs?repo_id=` — `{jobs:[{id,repo_id,environment,use_agent,use_embeddings,status,progress,total_files,processed_files,error,commit_hash,snapshot_hash,created_at,updated_at}]}`.
- `POST /api/jobs` — `{repo_id,environment?:string,use_agent?:boolean,use_embeddings?:boolean,force?:boolean}`; queues and returns a job. Environment defaults to `default`. Without `force`, an already-active job in that repository/environment is returned; this is not an incremental cache.
- `GET /api/jobs/{id}` — job object, including its persisted `use_agent` and `use_embeddings` modes. `POST /api/jobs/{id}/cancel` requests cancellation.

Statuses: `queued`, `running`, `completed`, `failed`, `cancelled`.

## Remote repository imports

- `POST /api/repository-imports` accepts `{url,branch?,name?}` and returns an asynchronous import record.
- `GET /api/repository-imports` returns `{imports:[...]}`.
- `GET /api/repository-imports/{id}` returns the current import record.
- `POST /api/repository-imports/{id}/cancel` requests cancellation.
- `POST /api/repository-imports/{id}/retry` retries a failed or cancelled import.

Import fields include `id`, `url`, `branch`, `name`, `status`, `progress`, `error`, `repo_id`, `cancel_requested`, `commit_hash`, `created_at`, and `updated_at`. States are `queued`, `cloning`, `completed`, `failed`, and `cancelled`. Successful import registers a local checkout under the configured repository root. Submit a normal analysis job for its `repo_id` afterward. The worker must be running to process imports.

GitHub and Bitbucket Cloud are allowed by default. `GRAPHIFIER_GIT_HOSTS` adds comma-separated enterprise Git hosts. `GRAPHIFIER_CLONE_TIMEOUT` defaults to 1800 seconds. Private repository access uses host Git credentials or SSH configuration. URL-embedded secrets are rejected, prompts are disabled, and failure messages omit raw Git output.

## Graph and evidence

- `GET /api/graph?repo_id=&environment=&namespace=&view=all|flow|constellation&max_nodes=&focus_id=&query=` — omit `repo_id` for an aggregate across registered repositories. Returns `{repo_id,environment,context,nodes:[{id,kind,name,expression?,attributes,evidence:[{file,start_line,end_line}]}],edges:[{id,source,target,kind,attributes,evidence}],version}`. `context` aliases `environment`. `GRAPHIFIER_SYSTEM` is explicit system identity (default `local-workspace`); unresolved IDs stay repository scoped. Resolved fully qualified physical identity may stitch across repositories only within the same system and environment.
- `GET /api/symbols?repo_id=&environment=` — `{repo_id,environment,namespace,system,symbols:[{name,expression,default_value,method,evidence,resolved,resolution}]}`. `environment` selects the matching indexed snapshot and bindings.
- `GET /api/evidence?repo_id=&file=&snapshot_id=&environment=` — `{repo_id,file,snapshot_id,environment,content,sha256,evidence:[...]}`. Content is from the indexed snapshot, not the current working tree. A supplied `snapshot_id` must belong to that repository and environment.
- `GET /api/trace?entity_id=&direction=both|in|out&repo_id=&environment=&namespace=&view=all|flow|constellation` — `{entity_id,direction,nodes,edges}` including recursively connected trace results.

## Shared symbol bindings

- `GET /api/resolutions?repo_id=&environment=` — `{resolutions:[...]}`.
- `POST /api/resolutions/propose` — `{repo_id,environment,symbol,expression,default_value?,actor?}`. Environment is mandatory. Returns a proposed object with a preview and explicit conflict details; proposals do not change the graph.
- `GET /api/resolutions/{id}/preview` — current preview, including expected version.
- `POST /api/resolutions/{id}/apply` — `{expected_version,actor?}`; applies only if version still matches.
- `POST /api/resolutions/{id}/retract` — `{expected_version,actor?}`; retracts an applied binding.

Bindings are scoped by repository, environment, and symbol. Existing live bindings on that exact key conflict; names in other scopes never merge. The raw expression is retained and never executed. Each action is audited.

`expression` in a proposal is the replacement value (for example `risk.risk_scored`), not executable code. `default_value` is descriptive metadata, not an automatic resolution. A proposal response includes its `id`, `version`, `status`, and `preview`. Preview contains `affected_references`, graph-change `counts`, `conflicts`, and before/after graph versions. The preview GET wraps these as `{resolution,expected_version,preview}`. Apply/retract return the updated resolution; stale versions or active-binding conflicts return HTTP 409.

The machine-readable OpenAPI snapshot is `docs/openapi.json` from the repository root. The live `/openapi.json` is authoritative for the running version.

The worker uses a database-specific process lock, so a second worker cannot mark the first worker's active jobs failed. On restart, the lock owner marks abandoned `running` jobs as failed. Their durable checkpoints remain available through Resume, and completed snapshots commit atomically.

## Optional integrations

- `GET /api/settings` — sanitized runtime settings. `agent` includes `base_url`, `model`, `api_mode`, `key_configured`, and `saved`. Secret key values are omitted.
- `POST /api/settings/agent` — `{base_url,model,api_mode,api_key?,clear_api_key?}` saves persistent AI connection settings. API mode is `responses` or `chat_completions`. An omitted or blank key preserves the saved/inherited value. `clear_api_key:true` explicitly clears it, including an inherited environment key. Returns the sanitized agent configuration.
- `POST /api/settings/agent/test` — same body, tests the unsaved candidate by requesting its `/models` endpoint. Returns `{status,models,selected_model_available}`. It does not save the form or prove extraction/tool support. Connection failures return HTTP 503 without credential details.

Saved AI configuration takes precedence over environment defaults and is read by the worker at the beginning of each file analysis. The connection remains fixed through that file's tool loop. Configuration, including a saved key, is stored in local SQLite; API responses omit the key.
- `POST /api/neo4j/sync` — `{repo_id?:string,environment?:string}`. Omit both to rebuild the aggregate Graphifier projection; a supplied environment or repository filters that projection. It uses stable, composite `(projection_id,id)` node identity and transactionally replaces only the selected Graphifier projection, preserving other systems/environments/repository filters. Reports `{status,repo_id,environment,system,projection_id,nodes,edges,error?}`; failure messages never include connection credentials.

When `GRAPHIFIER_API_TOKEN` is configured, API requests require `Authorization: Bearer <token>` except `/api/health`. `X-Graphifier-Actor` may identify the person or agent in the audit log. API requests accept only literal local Host/Origin values; DNS names that resolve to loopback are not trusted.

AI analysis uses the selected OpenAI-compatible endpoint. `GRAPHIFIER_AGENT_API` selects `responses` or `chat_completions`. `OPENAI_BASE_URL` and `OPENAI_API_KEY` configure the endpoint and optional authorization. Certificate verification stays enabled and honors `SSL_CERT_FILE`. The harness can list indexed files, read source ranges, and search literals. `GRAPHIFIER_AGENT_MAX_FILES` defaults to 200 prioritized files, and `GRAPHIFIER_AGENT_MAX_STEPS` defaults to eight requests per file. Inferred findings carry `method: model-inferred`; static findings carry `method: static`.

Graph `view` defaults to `all` for existing API clients. `max_nodes` accepts 1–5000. `query` searches name/kind/expression before limiting the display, and `focus_id` starts the window around a selected node. Projection metadata includes counts and explicit truncation. The browser chooses a 300-node graph window. Traces traverse detailed dependencies; they never infer a path through unrelated aggregate members.

- `GET /api/embeddings/status?repo_id=&environment=` returns `{enabled,model,indexed_chunks,indexed_snapshots}` for completed indexes of the latest completed analysis snapshots.
- `POST /api/embeddings/search` accepts `{query,repo_id?,environment?,limit?}`. Query length is 1–8000 and limit is 1–100 (default 10). Returns `{model,matches:[{repo_id,snapshot_id,file,start_line,end_line,content,source_sha256,score}]}`. Scope is applied before cosine ranking. Empty/unconfigured indexes return no matches without a model request. Endpoint failures return HTTP 503.

Embeddings are disabled until `GRAPHIFIER_EMBEDDING_MODEL` is configured and a job sets `use_embeddings:true`. The optional provider overrides are `GRAPHIFIER_EMBEDDING_BASE_URL` and `GRAPHIFIER_EMBEDDING_API_KEY`; otherwise the shared OpenAI settings apply. Batch size defaults to 16. Vectors stay in SQLite with their snapshot, source hash, model, and provider identity. Search excludes incomplete indexes and does not substitute an older index for a newer analysis lacking embeddings.

AI connection settings use `model` and `reasoning_effort` for the harness, plus independent `hierarchy_model` and `hierarchy_reasoning_effort` for architecture grouping. Omitted fields preserve saved choices; `hierarchy_model:null` restores automatic model selection, while explicit null effort requests the provider default. Fresh official OpenAI profiles default to `gpt-6-luna` Low for the harness and `gpt-6-luna` High for grouping. Existing harness values are preserved; custom endpoints inherit the harness profile for grouping unless overridden. Public settings return effective profiles and hierarchy configured flags. Connection tests report `selected_model_available` and `hierarchy_model_available` from advertised model IDs. Responses requests send `reasoning.effort`, and Chat Completions requests send `reasoning_effort` only when configured. Both profiles are frozen in the source checkpoint for all stages and resumes; credentials are excluded from checkpoints.

## Graph detail levels

`GET /api/graph` accepts `granularity=overview|interfaces|detail`, independently of `view=flow|constellation`. These values map to Architecture, Components and Full detail. Explicit levels use indexed immutable generations. Omitting granularity preserves the legacy view projection; `include_tests=false` is the default for both paths.

Additional parameters: `scope_id`, `generation`, `include_tests`, and nonnegative `offset`. `max_nodes` is 1–5000, with an API default of 800. A pinned generation must match repository/environment/namespace/test visibility or the API returns 409. Responses include `generation`, `scope_id`, `breadcrumbs`, `recommended_levels`, counts, `truncated`, `boundary_truncated`, `has_more`, and `next_offset`. Counts distinguish test exclusions, scope size, displayed nodes and remaining window members. Scoped boundary endpoints are marked `attributes.boundary=true` and subject to the same window budget.

A `query` also returns up to 30 `search_matches` from the full generation's detail index, each containing `node`, `ancestors` and `groups` for reveal navigation. Search respects test visibility. Summary nodes carry bounded evidence and input/output/dependency samples, exact counts, classification and grouping basis. Summary edges retain their semantic kind and support count; detailed support is fetched separately.

- `GET /api/graph/edge-support?generation=&edge_id=&offset=&limit=` returns `{generation,edge_id,edges,total,offset,has_more}`. Limit is 1–200; default 50.
- `GET /api/graph/location?generation=&node_id=` returns `{generation,node_id,ancestors,groups}`.
- `GET /api/trace` accepts `generation` and `include_tests`. Pinned traces use indexed detailed adjacency with node, edge and depth limits. Their returned granularity is `detail`; summary membership is not traversed as a dependency. Unknown/mismatched generations return 409.

Raw and hierarchy construction stages are durable; publication is atomic. Completed analysis prewarms the default repository view. Failed prewarming records an event and leaves the evidence snapshot usable; a subsequent request resumes projection construction. Existing ready generations remain available for pinned readers.

AI findings may cite any file in the same indexed repository snapshot. Evidence requests use the cited file with the returned snapshot ID to retrieve the exact indexed source. Cross-file citations are validated against that indexed source before publication.

## Durable analysis resume

`GET /api/jobs` and `GET /api/jobs/{id}` include `resumable` and `checkpoint`. A checkpoint reports `phase`, `completed_files`, `total_files`, and `current_file`. `POST /api/jobs/{id}/resume` queues the original failed or cancelled job with its captured sources and analysis settings. It preserves the job ID and analysis modes. A new analysis is a separate job that captures current source.

Resume rejects jobs without a usable checkpoint, already active/completed jobs, and another queued/running job in the same repository/environment with HTTP 409. The state check and requeue occur in one transaction, so duplicate resume requests cannot schedule duplicate work. Older jobs and interruption during initial source capture have no resume option. Cancellation clears only when a valid resume is accepted.

Model transport and embedding failures leave the analysis failed and resumable. Staged results remain unpublished until completion. Resume preserves the selected model and endpoint; current credentials may be reused only when their endpoint matches. Changing the analysis implementation requires a new analysis. A request interrupted before its response is durably saved may be repeated, so remote billing is not exactly-once.


## AI-assisted hierarchy

`POST /api/jobs` accepts `use_ai_hierarchy:boolean` (default false), independent of `use_agent` and `use_embeddings`. Job responses include the captured flag. The worker stages a source snapshot, builds component explanations and architecture proposals using the configured model, then completes publication. Checkpoint phase `ai_hierarchy` identifies this work. A failed/cancelled job resumes via the existing job endpoint, reusing completed per-request responses. Invalid model output is checkpointed and reported as partial fallback rather than retried indefinitely.

Graph and trace requests accept `hierarchy_mode=ai|deterministic` (default ai). The selected mode forms part of generation scope; pinned requests must preserve it. No saved AI proposal means deterministic fallback with `ai_hierarchy.status=not_requested`. Completed/partial proposals expose `ai_hierarchy` metadata (`status`, `model`, `warnings`, group and component-summary counts). Proposal content and warning-only revisions invalidate latest generation caches; old pinned generations remain available.

AI group attributes include `ai_summary`, `observed_summary`, `model`, `prompt_version`, `confidence`, `rationale`, `cited_node_ids` and `provenance=model-inferred`. Evidence shown with the inference comes from its cited nodes. Confidence is a model assessment, not empirical accuracy. Detailed entities and edges are preserved; summary edges are recomputed from their real supporting relationships after regrouping.

Saved proposals are applied per repository; similarly named capabilities in different repositories do not merge. Test/production contexts cannot be combined by the model. Group validation rejects unknown/duplicate memberships, foreign evidence and invalid fields. Oversized, omitted or invalid results use deterministic fallback with warnings. `GRAPHIFIER_AI_HIERARCHY_MAX_BATCHES` is a nonnegative model-call cap, captured for the job; 0 is unlimited total calls. Individual prompts, outputs and batches remain bounded. Graph requests and Neo4j sync use saved proposals and never invoke the model.
