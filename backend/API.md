# Graphifier local API contract

Base URL: `http://127.0.0.1:8787`. JSON unless noted. Errors use `{ "detail": "..." }`.

## Repositories and jobs

- `GET /api/health` — `{status,version}`.
- `GET /api/repositories` — `{repositories:[{id,name,path,created_at}]}`.
- `POST /api/repositories` — `{name?,path}`; returns the repository object.
- `GET /api/browse?path=` — allowlisted directories and `{path,entries:[{name,path,is_dir}]}`.
- `GET /api/jobs?repo_id=` — `{jobs:[{id,repo_id,environment,use_agent,status,progress,total_files,processed_files,error,commit_hash,snapshot_hash,created_at,updated_at}]}`.
- `POST /api/jobs` — `{repo_id,environment?:string,use_agent?:boolean,force?:boolean}`; queues and returns a job. Environment defaults to `default`. Without `force`, an already-active job in that repository/environment is returned; this is not an incremental cache.
- `GET /api/jobs/{id}` — job object, including its persisted `use_agent` mode. `POST /api/jobs/{id}/cancel` requests cancellation.

Statuses: `queued`, `running`, `completed`, `failed`, `cancelled`.

## Graph and evidence

- `GET /api/graph?repo_id=&environment=&namespace=` — omit `repo_id` for an aggregate across registered repositories. Returns `{repo_id,environment,context,nodes:[{id,kind,name,expression?,attributes,evidence:[{file,start_line,end_line}]}],edges:[{id,source,target,kind,attributes,evidence}],version}`. `context` aliases `environment`. `GRAPHIFIER_SYSTEM` is explicit system identity (default `local-workspace`); unresolved IDs stay repository scoped. Resolved fully qualified physical identity may stitch across repositories only within the same system and environment.
- `GET /api/symbols?repo_id=&environment=` — `{repo_id,environment,namespace,system,symbols:[{name,expression,default_value,method,evidence,resolved,resolution}]}`. `environment` selects the matching indexed snapshot and bindings.
- `GET /api/evidence?repo_id=&file=&snapshot_id=&environment=` — `{repo_id,file,snapshot_id,environment,content,sha256,evidence:[...]}`. Content is from the indexed snapshot, not the current working tree. A supplied `snapshot_id` must belong to that repository and environment.
- `GET /api/trace?entity_id=&direction=both|in|out&repo_id=&environment=&namespace=` — `{entity_id,direction,nodes,edges}` including recursively connected trace results.

## Shared symbol bindings

- `GET /api/resolutions?repo_id=&environment=` — `{resolutions:[...]}`.
- `POST /api/resolutions/propose` — `{repo_id,environment,symbol,expression,default_value?,actor?}`. Environment is mandatory. Returns a proposed object with a preview and explicit conflict details; proposals do not change the graph.
- `GET /api/resolutions/{id}/preview` — current preview, including expected version.
- `POST /api/resolutions/{id}/apply` — `{expected_version,actor?}`; applies only if version still matches.
- `POST /api/resolutions/{id}/retract` — `{expected_version,actor?}`; retracts an applied binding.

Bindings are scoped by repository, environment, and symbol. Existing live bindings on that exact key conflict; names in other scopes never merge. The raw expression is retained and never executed. Each action is audited.

`expression` in a proposal is the replacement value (for example `risk.risk_scored`), not executable code. `default_value` is descriptive metadata, not an automatic resolution. A proposal response includes its `id`, `version`, `status`, and `preview`. Preview contains `affected_references`, graph-change `counts`, `conflicts`, and before/after graph versions. The preview GET wraps these as `{resolution,expected_version,preview}`. Apply/retract return the updated resolution; stale versions or active-binding conflicts return HTTP 409.

The machine-readable OpenAPI snapshot is `docs/openapi.json` from the repository root. The live `/openapi.json` is authoritative for the running version.

The worker uses a database-specific process lock, so a second worker cannot mark the first worker's active jobs failed. On restart, the lock owner marks any abandoned `running` job as failed; completed snapshots commit atomically.

## Optional integrations

- `GET /api/settings` — sanitized runtime settings, never secrets.
- `POST /api/neo4j/sync` — `{repo_id?:string,environment?:string}`. Omit both to rebuild the aggregate Graphifier projection; a supplied environment or repository filters that projection. It uses stable, composite `(projection_id,id)` node identity and transactionally replaces only the selected Graphifier projection, preserving other systems/environments/repository filters. Reports `{status,repo_id,environment,system,projection_id,nodes,edges,error?}`; failure messages never include connection credentials.

When `GRAPHIFIER_API_TOKEN` is configured, API requests require `Authorization: Bearer <token>` except `/api/health`. `X-Graphifier-Actor` may identify the person or agent in the audit log. API requests accept only literal local Host/Origin values; DNS names that resolve to loopback are not trusted.

When an OpenAI key is configured, `use_agent:true` enables bounded Responses API investigation. It analyzes at most 20 files and at most 80,000 characters per file; skipped files retain static findings and a warning. `OPENAI_BASE_URL` may select a compatible API base; certificate verification stays enabled and honors `SSL_CERT_FILE`. Inferred findings carry `method: model-inferred`; static findings carry `method: static`.
