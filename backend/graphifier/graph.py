"""Repository-aware lineage graph construction and bounded traversal."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict, deque
from typing import Any

from .db import connect
from .graph_views import project_graph


_SYMBOL_PATTERNS = (
    lambda s: (re.compile(r"&" + re.escape(s) + r"(?![A-Za-z0-9_])\.?", re.I),),
    lambda s: (re.compile(r"(?<!\$)\{\s*" + re.escape(s) + r"\s*\}"),),
    lambda s: (re.compile(r"\$\{" + re.escape(s) + r"\}"), re.compile(r"\$" + re.escape(s) + r"\b")),
)


def _stable(prefix: str, *parts: Any) -> str:
    raw = "\0".join(str(p) for p in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _json(value: str | None, fallback=None):
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _symbol_forms(symbol: str) -> list[re.Pattern]:
    """Recognize the concrete syntaxes supported by static extraction."""
    forms: list[re.Pattern] = []
    for factory in _SYMBOL_PATTERNS:
        forms.extend(factory(symbol))
    return forms


def _replace_binding(text: str, symbol: str, replacement: str) -> str:
    out = text
    for pattern in _symbol_forms(symbol):
        out = pattern.sub(lambda _m: replacement, out)
    return out


def _resolved_name(entity: dict, bindings: list[dict]) -> tuple[str | None, list[dict]]:
    expr = entity.get("expression")
    name = str(entity.get("name", ""))
    # Only substitute a symbol when its syntax is present in the actual data
    # reference. default_value is deliberately never consulted here.
    candidates = [str(expr or ""), name]
    matches: list[dict] = []
    for binding in bindings:
        symbol = str(binding.get("symbol", ""))
        if not symbol:
            continue
        forms = _symbol_forms(symbol)
        if any(p.search(text) for text in candidates for p in forms):
            matches.append(binding)
    if not matches:
        return None, []
    result = _replace_binding(str(expr or name), str(matches[0]["symbol"]), str(matches[0]["expression"]))
    # Apply other bindings to the progressively expanded reference.
    for binding in matches[1:]:
        result = _replace_binding(result, str(binding["symbol"]), str(binding["expression"]))
    # A source expression may just be the interpolation token while its name
    # contains additional suffix/prefix text. Prefer the fully substituted name
    # when it carries more of the original reference.
    replaced_name = name
    for binding in matches:
        replaced_name = _replace_binding(replaced_name, str(binding["symbol"]), str(binding["expression"]))
    result = replaced_name if replaced_name != name else result
    result = result.strip().strip("`\"'")
    return (result if result and result != (expr or name) else None), matches


def _is_fully_qualified(name: str) -> bool:
    parts = name.split(".")
    if len(parts) < 2 or any(not p.strip() for p in parts):
        return False
    if re.search(r"[&${}]", name) or "<dynamic>" in name.lower():
        return False
    # WORK datasets are session-local and cannot be stitched between repos.
    if parts[0].strip().upper() == "WORK":
        return False
    # Qualification is lexical: a two-part SAS lib/member name is treated as
    # physical only inside the explicitly configured GRAPHIFIER_SYSTEM and
    # environment namespace. The graph does not infer real storage semantics.
    return bool(re.fullmatch(r"[\w$-]+(?:\.[\w$-]+)+", name, re.UNICODE))


def _scope_bindings(c, repo_id: str, environment: str) -> tuple[list[dict], list[dict]]:
    rows = c.execute(
        "SELECT * FROM resolutions WHERE repo_id=? AND environment=? AND status='applied' ORDER BY symbol,version,created_at",
        (repo_id, environment),
    ).fetchall()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["symbol"]].append(dict(row))
    conflicts = [items for items in grouped.values() if len(items) > 1]
    return ([items[0] for items in grouped.values() if len(items) == 1], conflicts)


def _load(c, repo_id: str | None, environment: str | None):
    where = ["j.status='completed'"]
    args: list[Any] = []
    if repo_id is not None:
        where.append("s.repo_id=?")
        args.append(repo_id)
    if environment is not None:
        where.append("j.environment=?")
        args.append(environment)
    rows = c.execute(
        "SELECT * FROM (SELECT s.*,j.environment,j.status AS job_status,j.updated_at AS job_updated_at, "
        "ROW_NUMBER() OVER (PARTITION BY s.repo_id ORDER BY s.created_at DESC,s.id DESC) AS snapshot_rank "
        "FROM snapshots s JOIN jobs j ON j.id=s.job_id WHERE " + " AND ".join(where) +
        ") WHERE snapshot_rank=1 ORDER BY repo_id", args,
    ).fetchall()
    latest: dict[str, dict] = {}
    for row in rows:
        item = dict(row)
        latest.setdefault(item["repo_id"], item)
    return latest


def _build(c, repo_id: str | None = None, environment: str | None = None,
           namespace: str | None = None, override_binding: dict | None = None,
           snapshot_id: str | None = None) -> dict:
    system = namespace or os.environ.get("GRAPHIFIER_SYSTEM", "local-workspace")
    snapshots = _load(c, repo_id, environment)
    if snapshot_id is not None:
        # Internal worker-only access to its staged snapshot. Public requests
        # continue to select completed jobs exclusively.
        row = c.execute("SELECT s.*,j.environment FROM snapshots s JOIN jobs j ON j.id=s.job_id WHERE s.id=? AND s.repo_id=? AND j.environment=?", (snapshot_id,repo_id,environment)).fetchone()
        if row is None:
            raise ValueError("Staged snapshot does not belong to this analysis scope")
        snapshots = {repo_id: dict(row)}
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    warnings: list[dict] = []
    snapshot_versions: list[dict] = []
    canonical_for_ref: dict[str, str] = {}
    bindings_used: list[dict] = []

    def add_node(item: dict):
        old = nodes.get(item["id"])
        if old is None:
            nodes[item["id"]] = item
        else:
            for field in ("evidence", "repositories", "snapshots"):
                old[field] = _merge_records(old.get(field, []), item.get(field, []))
            attrs = old.setdefault("attributes", {})
            for key, value in item.get("attributes", {}).items():
                if isinstance(value, list):
                    attrs[key] = _merge_records(attrs.get(key, []), value)
                else:
                    attrs[key] = value

    def add_edge(source: str, target: str, kind: str, attrs: dict | None = None,
                 evidence: list | None = None, key_scope: str = ""):
        semantic = {k: v for k, v in (attrs or {}).items() if k not in {"method", "source_methods"}}
        eid = _stable("edge", key_scope, source, target, kind, json.dumps(semantic, sort_keys=True))
        item = edges.get(eid)
        if item is None:
            item = {"id": eid, "source": source, "target": target, "kind": kind,
                    "attributes": attrs or {}, "evidence": [], "repositories": [], "snapshots": []}
            edges[eid] = item
        elif attrs:
            item["attributes"].update(attrs)
        if evidence:
            item["evidence"] = _merge_records(item["evidence"], evidence)
        if key_scope:
            item["repositories"] = _merge_records(item["repositories"], [key_scope])
        return item

    for rid, snap in snapshots.items():
        sid = snap["id"]
        env = snap["environment"]
        meta = {"repo_id": rid, "snapshot_id": sid, "job_id": snap["job_id"],
                "environment": env, "commit_hash": snap["commit_hash"],
                "content_hash": snap["content_hash"], "created_at": snap["created_at"]}
        snapshot_versions.append(meta)
        applied, binding_conflicts = _scope_bindings(c, rid, env)
        if override_binding and override_binding.get("repo_id") == rid and override_binding.get("environment") == env:
            applied = [b for b in applied if b.get("symbol") != override_binding.get("symbol")]
            binding_conflicts = [group for group in binding_conflicts
                                 if group[0].get("symbol") != override_binding.get("symbol")]
            if override_binding.get("status") in ("applied", "proposed"):
                applied.append(override_binding)
        for group in binding_conflicts:
            warnings.append({"repo_id": rid, "snapshot_id": sid,
                             "warning": {"kind": "binding_conflict", "symbol": group[0]["symbol"],
                                         "resolution_ids": [b["id"] for b in group],
                                         "message": "Multiple applied bindings exist for this symbol; reference left unresolved"}})
        bindings_used.extend(applied)

        findings = c.execute("SELECT category,data FROM findings WHERE repo_id=? AND snapshot_id=? ORDER BY category,item_key", (rid, sid))
        source_entities: dict[str, dict] = {}
        rels: list[dict] = []
        for f in findings:
            data = _json(f["data"], {}) or {}
            if f["category"] == "entity":
                source_entities[str(data.get("id", ""))] = data
            elif f["category"] == "relationship":
                rels.append(data)
            elif f["category"] == "warning":
                warnings.append({"repo_id": rid, "snapshot_id": sid, "warning": data})
        # Older snapshots have import reference nodes but no resolved local
        # program links. Derive those links from the captured source, never the
        # changing live checkout. The generation cache pays this cost once.
        if not any(r.get("attributes", {}).get("resolution") == "local-source" for r in rels):
            from collections.abc import Mapping
            from .code_links import link_code_findings

            class CapturedSources(Mapping):
                def __init__(self):
                    self.paths = {r[0] for r in c.execute("SELECT file FROM source_files WHERE repo_id=? AND snapshot_id=?", (rid, sid))}

                def __iter__(self):
                    return iter(self.paths)

                def __len__(self):
                    return len(self.paths)

                def __contains__(self, key):
                    return key in self.paths

                def __getitem__(self, key):
                    row = c.execute("SELECT content FROM source_files WHERE repo_id=? AND snapshot_id=? AND file=?", (rid, sid, key)).fetchone()
                    if row is None:
                        raise KeyError(key)
                    return row[0]

            linked = link_code_findings(source_entities.values(), rels, CapturedSources())
            rels.extend(linked["relationships"])
            warnings.extend({"repo_id": rid, "snapshot_id": sid, "warning": item} for item in linked["warnings"])
        symrows = c.execute("SELECT * FROM symbols WHERE repo_id=? AND snapshot_id=? ORDER BY name,expression", (rid, sid)).fetchall()
        symbol_metadata: dict[str, list] = defaultdict(list)
        for row in symrows:
            sym = dict(row)
            symbol_metadata[sym["name"]].append({"expression": sym["expression"], "default_value": sym["default_value"],
                                                  "evidence": _json(sym["evidence"], {}), "method": sym.get("method", "static")})
        for entity_id, source in source_entities.items():
            kind = source.get("kind", "unknown")
            source_evidence = source.get("evidence")
            ev = [{**span, "repo_id": rid} for span in source.get("evidence_spans", [source_evidence]) if isinstance(span, dict)]
            attrs = dict(source.get("attributes") or {})
            # Attaching every repository symbol to every node produces a
            # quadratic JSON response on macro-heavy repositories.
            symbol_names = set(re.findall(r"[A-Za-z_]\w*", str(source.get("expression") or "") + " " + str(source.get("name") or "")))
            attrs.update({"source_id": entity_id, "source_expression": source.get("expression"),
                          "symbol_metadata": {name: symbol_metadata[name] for name in symbol_names if name in symbol_metadata}})
            node = {"id": entity_id, "kind": kind, "name": source.get("name", entity_id),
                    "expression": source.get("expression"), "attributes": attrs, "evidence": ev,
                    "repositories": [rid], "snapshots": [meta]}
            add_node(node)
            if kind != "dataset":
                continue
            resolved, used = _resolved_name(source, applied)
            if not resolved:
                raw_name = str(source.get("name", ""))
                raw_expr = str(source.get("expression") or "")
                if re.search(r"&\w+|\{[^}]+\}|\$\{?\w+", raw_expr or raw_name):
                    continue
                # Statically observed physical names can stitch without a
                # resolution. Symbolic references require an applied binding.
                resolved = raw_name
            if not _is_fully_qualified(resolved):
                continue
            cid = _stable("physical-dataset", system, env, resolved.casefold())
            canonical_for_ref[entity_id] = cid
            binding_refs = [{"repo_id": b["repo_id"], "environment": b["environment"], "symbol": b["symbol"],
                             "resolution_id": b["id"], "version": b["version"]} for b in used]
            canonical = {"id": cid, "kind": "dataset", "name": resolved,
                         "attributes": {"canonical": True, "system": system, "environment": env,
                                        "fully_qualified": True, "source_references": [entity_id],
                                        "bindings": binding_refs},
                         "evidence": ev, "repositories": [rid], "snapshots": [meta]}
            add_node(canonical)
            nodes[cid]["attributes"]["source_references"] = _merge_records(nodes[cid]["attributes"].get("source_references", []), [entity_id])
            add_edge(entity_id, cid, "RESOLVES_TO", {"resolved_name": resolved, "system": system,
                                                       "environment": env, "bindings": binding_refs}, ev, rid)

        # A column can stitch only through one unambiguous physical parent.
        # Local/work datasets deliberately have no canonical identity.
        column_parents = defaultdict(set)
        for rel in rels:
            if rel.get("kind") == "HAS_COLUMN":
                column_parents[str(rel.get("target"))].add(str(rel.get("source")))
        for entity_id, source in source_entities.items():
            if source.get("kind") != "column":
                continue
            parent = (source.get("attributes") or {}).get("parent_dataset_id")
            if parent:
                parent = str(parent)
                if parent not in source_entities and f"{rid}:{parent}" in source_entities:
                    parent = f"{rid}:{parent}"
                if parent in source_entities:
                    column_parents[entity_id].add(parent)
            parents = column_parents[entity_id]
            canonical_parents = {canonical_for_ref.get(parent) for parent in parents}
            if len(canonical_parents) != 1 or None in canonical_parents:
                continue
            canonical_parent = next(iter(canonical_parents))
            name = str(source.get("name", ""))
            if not re.fullmatch(r"[A-Za-z_][\w$]*", name):
                continue
            cid = _stable("physical-column", canonical_parent, name.casefold())
            canonical_for_ref[entity_id] = cid
            ev = nodes[entity_id]["evidence"]
            add_node({"id": cid, "kind": "column", "name": name,
                      "attributes": {"canonical": True, "parent_dataset_id": canonical_parent,
                                     "source_references": [entity_id], "system": system, "environment": env},
                      "evidence": ev, "repositories": [rid], "snapshots": [meta]})
            add_edge(entity_id, cid, "RESOLVES_TO", {"parent_dataset_id": canonical_parent}, ev, rid)
            add_edge(canonical_parent, cid, "HAS_COLUMN", {}, ev, rid)

        for rel in rels:
            src, dst = str(rel.get("source", "")), str(rel.get("target", ""))
            if src not in nodes or dst not in nodes:
                continue
            ev0 = rel.get("evidence")
            ev = [{**span, "repo_id": rid} for span in rel.get("evidence_spans", [ev0]) if isinstance(span, dict)]
            attrs = dict(rel.get("attributes") or {})
            add_edge(src, dst, str(rel.get("kind", "RELATED")), attrs, ev, rid)
            # Project lineage through resolved physical references. This makes
            # cross-repository traversal possible while keeping source IDs/evidence.
            canonical_src, canonical_dst = canonical_for_ref.get(src, src), canonical_for_ref.get(dst, dst)
            if canonical_src != src or canonical_dst != dst:
                add_edge(canonical_src, canonical_dst, str(rel.get("kind", "RELATED")),
                         {**attrs, "via_reference": [src, dst]}, ev, rid)


    versions = sorted((b.get("id"), b.get("version"), b.get("status")) for b in bindings_used)
    return {"nodes": sorted(nodes.values(), key=lambda n: n["id"]),
            "edges": sorted(edges.values(), key=lambda e: e["id"]),
            "warnings": _merge_records([], warnings), "snapshots": snapshot_versions,
            "version": _stable("graph-version", json.dumps(snapshot_versions, sort_keys=True),
                                json.dumps(versions, sort_keys=True), system),
            "system": system, "environment": environment,
            "repo_id": repo_id}


def _merge_records(left: list, right: list) -> list:
    out = list(left or [])
    seen = {json.dumps(x, sort_keys=True, default=str) for x in out}
    for value in right or []:
        key = json.dumps(value, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def build_graph(repo_id: str | None = None, environment: str | None = None,
                namespace: str | None = None, view: str = "all",
                max_nodes: int | None = None, focus_id: str | None = None, query: str | None = None,
                granularity: str | None = None, scope_id: str | None = None,
                generation: str | None = None, include_tests: bool = False, offset: int = 0, hierarchy_mode: str = "ai") -> dict:
    from .graph_store import ensure_generation, read_window
    # Existing raw callers retain their full detailed graph; explicit hierarchy
    # requests use immutable indexed generations and bounded database windows.
    if granularity is None and scope_id is None and generation is None:
        from .hierarchy import filter_graph_context
        with connect() as c:
            result = filter_graph_context(_build(c, repo_id, environment, namespace), include_tests)
        return project_graph(result, view=view, max_nodes=max_nodes, focus_id=focus_id, query=query)
    gid = ensure_generation(repo_id,environment,namespace,include_tests,generation,hierarchy_mode)
    return read_window(gid,granularity or 'overview',scope_id,max_nodes or 800,query,focus_id,view,offset)


def preview_binding(proposal: dict) -> dict:
    with connect() as c:
        before = _build(c, repo_id=None, environment=proposal.get("environment"),
                        namespace=proposal.get("namespace"))
        after = _build(c, repo_id=None, environment=proposal.get("environment"),
                       namespace=proposal.get("namespace"), override_binding=proposal)
        conflicts = [dict(r) for r in c.execute(
            "SELECT * FROM resolutions WHERE repo_id=? AND environment=? AND symbol=? AND status='applied'",
            (proposal.get("repo_id"), proposal.get("environment"), proposal.get("symbol")),
        ).fetchall()]
    before_nodes = {n["id"]: n for n in before["nodes"]}
    after_nodes = {n["id"]: n for n in after["nodes"]}
    before_edges = {e["id"]: e for e in before["edges"]}
    after_edges = {e["id"]: e for e in after["edges"]}
    affected = []
    # Source references carry resolution edges after substitution. Include the
    # before/after canonical target and the exact evidence for user review.
    before_targets: dict[str, list] = defaultdict(list)
    after_targets: dict[str, list] = defaultdict(list)
    for edge in before["edges"]:
        if edge["kind"] == "RESOLVES_TO": before_targets[edge["source"]].append(edge["target"])
    for edge in after["edges"]:
        if edge["kind"] == "RESOLVES_TO": after_targets[edge["source"]].append(edge["target"])
    for ref in sorted(set(before_targets) | set(after_targets)):
        node = after_nodes.get(ref) or before_nodes.get(ref)
        if not node or proposal.get("repo_id") not in node.get("repositories", []):
            continue
        if before_targets.get(ref) != after_targets.get(ref):
            affected.append({"reference_id": ref, "name": node.get("name"),
                             "expression": node.get("expression"), "evidence": node.get("evidence", []),
                             "before": before_targets.get(ref, []), "after": after_targets.get(ref, [])})
    return {"repo_id": proposal.get("repo_id"), "environment": proposal.get("environment"),
            "symbol": proposal.get("symbol"), "expression": proposal.get("expression"),
            "conflict": conflicts[0] if conflicts else proposal.get("conflict"),
            "conflicts": conflicts, "affected_references": affected,
            "counts": {"nodes_added": len(set(after_nodes) - set(before_nodes)),
                       "nodes_removed": len(set(before_nodes) - set(after_nodes)),
                       "edges_added": len(set(after_edges) - set(before_edges)),
                       "edges_removed": len(set(before_edges) - set(after_edges))},
            "graph_version_before": before["version"], "graph_version_after": after["version"]}


def trace_graph(entity_id: str, direction: str = "both", repo_id: str | None = None,
                environment: str | None = None, namespace: str | None = None,
                max_depth: int = 20, view: str = "all", max_nodes: int | None = None, granularity: str | None = None, include_tests: bool = False, generation: str | None = None, hierarchy_mode: str = "ai") -> dict:
    if max_nodes is not None and not 1 <= max_nodes <= 5000:
        raise ValueError("max_nodes must be between 1 and 5000")
    if generation:
        from .graph_store import ensure_generation, trace_generation
        gid=ensure_generation(repo_id,environment,namespace,include_tests,generation,hierarchy_mode)
        return trace_generation(gid,entity_id,direction,max_depth,max_nodes or 800,view)
    from .hierarchy import filter_graph_context, build_hierarchy
    with connect() as c:
        graph = filter_graph_context(_build(c, repo_id, environment, namespace), include_tests)
    # Trace detailed dependencies before any presentation-level grouping.
    graph['edges'] = [e for e in graph['edges'] if e['kind'] not in {'CONTAINS','HAS_COLUMN','DEFINES'}]
    seeds = [entity_id]
    if entity_id.startswith('group:'):
        hierarchy = build_hierarchy(graph)
        seeds = [nid for nid, chain in hierarchy['ancestors'].items() if entity_id in chain]
    nodes = {n["id"]: n for n in graph["nodes"]}
    if not any(seed in nodes for seed in seeds):
        return {"entity_id": entity_id, "nodes": [], "edges": [], "unresolved_gaps": [],
                "truncated": False, "max_depth": max_depth, "graph_version": graph["version"],
                "view": view, "warnings": graph["warnings"]}
    max_depth = max(0, int(max_depth))
    direction = {"upstream": "in", "downstream": "out"}.get(direction, direction)
    if direction not in {"both", "in", "out"}:
        raise ValueError("direction must be both, in, out, upstream, or downstream")
    outgoing: dict[str, list] = defaultdict(list)
    incoming: dict[str, list] = defaultdict(list)
    edges = {e["id"]: e for e in graph["edges"]}
    for e in graph["edges"]:
        if e["kind"] == "RESOLVES_TO":
            outgoing[e["source"]].append((e, e["target"], "alias"))
            incoming[e["target"]].append((e, e["source"], "alias"))
        else:
            source, target = e["source"], e["target"]
            # READS records consumer -> resource. Dependency traversal follows
            # the data in the reverse direction without rewriting the fact.
            if e["kind"] == "READS" and nodes[source]["kind"] in {"program", "transformation"} and nodes[target]["kind"] in {"dataset", "column", "file"}:
                source, target = target, source
            outgoing[source].append((e, target, "out"))
            incoming[target].append((e, source, "in"))
    seed_truncated = max_nodes is not None and len(seeds) > max_nodes
    seeds = seeds[:max_nodes] if max_nodes is not None else seeds
    q = deque((seed, 0) for seed in seeds if seed in nodes)
    seen_depth = {seed: 0 for seed in seeds if seed in nodes}
    included_edges: set[str] = set()
    truncated = graph.get("truncated", False) or seed_truncated
    while q:
        current, depth = q.popleft()
        candidates = []
        if direction in ("out", "both"):
            candidates.extend(outgoing[current])
        if direction in ("in", "both"):
            candidates.extend(incoming[current])
        if direction != "both":
            # RESOLVES_TO is a canonical identity boundary. Cross it in either
            # direction, then keep lineage edges themselves directional.
            candidates.extend(outgoing[current] if direction == "in" else incoming[current])
            candidates = [entry for entry in candidates if entry[2] == "alias" or
                          (entry[2] == "in" and direction == "in") or
                          (entry[2] == "out" and direction == "out")]
        for edge, other, _orientation in candidates:
            included_edges.add(edge["id"])
            if other in seen_depth:
                continue
            if depth >= max_depth or (max_nodes is not None and len(seen_depth) >= max_nodes):
                truncated = True
                continue
            seen_depth[other] = depth + 1
            q.append((other, depth + 1))
    selected_nodes = [nodes[nid] for nid in seen_depth]
    selected_edges = [edges[eid] for eid in included_edges
                      if edges[eid]["source"] in seen_depth and edges[eid]["target"] in seen_depth]
    if max_nodes is not None and len(selected_edges) > max_nodes * 8:
        selected_edges = selected_edges[:max_nodes * 8]
        truncated = True
    gaps = []
    resolved_refs = {e["source"] for e in graph["edges"] if e["kind"] == "RESOLVES_TO"}
    for node in selected_nodes:
        if node.get("kind") == "dataset" and node.get("expression"):
            if (node["id"] not in resolved_refs and
                    re.search(r"&\w+|\{[^}]+\}|\$\{?\w+", str(node["expression"]))):
                gaps.append({"entity_id": node["id"], "name": node.get("name"),
                             "expression": node["expression"], "reason": "unresolved symbolic dataset reference",
                             "evidence": node.get("evidence", [])})
    return {"entity_id": entity_id, "direction": direction, "nodes": selected_nodes,
            "edges": selected_edges, "unresolved_gaps": gaps, "truncated": truncated,
            "max_depth": max_depth, "graph_version": graph["version"], "warnings": graph["warnings"], "view": view, "granularity": "detail", "hidden_test_nodes": graph.get("hidden_test_nodes",0)}
