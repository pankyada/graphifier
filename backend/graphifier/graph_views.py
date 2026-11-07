"""Evidence-preserving graph projections and bounded exploration windows."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque

# Only dependency edges may be composed through an internal implementation node.
DEPENDENCIES = {"INPUT_TO", "PRODUCES", "WRITES", "DERIVES_FROM", "TRAINS", "SCORES", "CALLS", "IMPORTS", "DEPENDS_ON", "TRANSFERS"}
STRUCTURE = {"CONTAINS", "HAS_COLUMN", "DEFINES", "RESOLVES_TO"}


def _unique(records):
    seen = set()
    result = []
    for record in records:
        key = json.dumps(record, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            result.append(record)
    return result


def _roles(path):
    return tuple(sorted({str(edge.get("attributes", {}).get("role")) for edge in path if edge.get("attributes", {}).get("role")}))


def _enabled(value):
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _important(node, aliases):
    attrs = node.get("attributes") or {}
    kind = node.get("kind", "").lower()
    if node["id"] in aliases:
        return False
    if kind in {"column", "variable", "parameter", "local", "symbol"}:
        return False
    if attrs.get("visibility") == "interface" or any(_enabled(attrs.get(key)) for key in ("interface", "exported", "entrypoint")):
        return True
    if any(_enabled(attrs.get(key)) for key in ("transient", "temporary")) or attrs.get("scope") == "local" or attrs.get("visibility") == "internal":
        return False
    name = str(node.get("name", "")).lower()
    if kind == "dataset" and (name.startswith("work.") or name in {"_null_", "work"}):
        return False
    if kind == "transformation" and attrs.get("output_column_id"):
        return False
    # Source files are represented by program nodes. External file resources stay.
    if kind == "file" and attrs.get("language"):
        return False
    return True


def project_graph(graph, view="all", max_nodes=None, focus_id=None, query=None, granularity=None):
    """Project without modifying the full graph; report every display truncation."""
    if view not in {"all", "flow", "constellation"}:
        raise ValueError("view must be all, flow, or constellation")
    if max_nodes is not None and not 1 <= max_nodes <= 5000:
        raise ValueError("max_nodes must be between 1 and 5000")
    if granularity not in {None, "overview", "interfaces", "detail"}:
        raise ValueError("granularity must be overview, interfaces, or detail")
    original_nodes = {n["id"]: n for n in graph["nodes"]}
    original_edges = graph["edges"]
    aliases = {e["source"]: e["target"] for e in original_edges if e["kind"] == "RESOLVES_TO"}
    nodes = dict(original_nodes)
    edges = list(original_edges)
    bridge_truncated = False
    if granularity in {"overview", "interfaces"} or (granularity is None and view == "constellation"):
        nodes = {key: node for key, node in nodes.items() if _important(node, aliases)}
        if granularity == "overview":
            nodes = {key: node for key, node in nodes.items() if node.get("kind") != "transformation"}
        edges = [e for e in edges if e["source"] in nodes and e["target"] in nodes]
        outgoing = defaultdict(list)
        for edge in original_edges:
            if edge["kind"] in DEPENDENCIES:
                outgoing[edge["source"]].append(edge)
        # Each projected edge retains one concrete witness path. Do not merge
        # unrelated branches into a purported single execution path.
        derived = set()
        visits = 0
        for start in sorted(nodes):
            queue = deque((edge["target"], [edge], []) for edge in outgoing[start]
                          if edge["target"] not in nodes and edge["target"] not in aliases)
            visited = {(start, ())}
            scheduled = {(item[0], _roles(item[1])) for item in queue}
            while queue:
                current, path, internal = queue.popleft()
                state = (current, _roles(path))
                if state in visited:
                    continue
                visited.add(state)
                visits += 1
                if visits > 100_000:
                    bridge_truncated = True
                    break
                if current in nodes:
                    key = (start, current, _roles(path))
                    if key in derived:
                        continue
                    derived.add(key)
                    digest = hashlib.sha256(json.dumps(key).encode()).hexdigest()[:24]
                    methods = sorted({str(e.get("attributes", {}).get("method", "static")) for e in path})
                    edges.append({"id": f"projected:{digest}", "source": start, "target": current,
                                  "kind": "VIA_INTERNAL", "attributes": {"derived": True,
                                  "method": "graph-projection", "source_methods": methods,
                                  "via_nodes": internal, "via_edges": [e["id"] for e in path],
                                  "relationship_kinds": [e["kind"] for e in path],
                                  "dependency_roles": sorted({str(e.get("attributes", {}).get("role")) for e in path if e.get("attributes", {}).get("role")}),
                                  "path_attributes": [e.get("attributes", {}) for e in path]},
                                  "evidence": _unique([ev for e in path for ev in e.get("evidence", [])]),
                                  "repositories": _unique([r for e in path for r in e.get("repositories", [])])})
                    continue
                if len(path) >= 32:
                    if outgoing[current]:
                        bridge_truncated = True
                    continue
                for edge in outgoing[current]:
                    target = aliases.get(edge["target"], edge["target"])
                    next_state = (target, _roles(path + [edge]))
                    if next_state not in scheduled and next_state not in visited:
                        scheduled.add(next_state)
                        queue.append((target, path + [edge], internal + [current]))
            if visits > 100_000:
                break
    incoming_calls = {e["target"] for e in edges if e["kind"] in {"CALLS", "IMPORTS", "DEPENDS_ON", "INVOKES"}}
    entrypoints = [n["id"] for n in nodes.values() if _enabled(n.get("attributes", {}).get("entrypoint"))]
    candidates = [n["id"] for n in nodes.values() if n["kind"] == "program" and n["id"] not in incoming_calls]
    counts = {"total_nodes": len(original_nodes), "total_edges": len(original_edges),
              "projected_nodes": len(nodes), "projected_edges": len(edges),
              "hidden_nodes": len(original_nodes) - len(nodes)}
    truncated = bridge_truncated
    if query:
        max_nodes = max_nodes or 800
    if query or (max_nodes is not None and len(nodes) > max_nodes):
        adjacent = defaultdict(set)
        for edge in edges:
            adjacent[edge["source"]].add(edge["target"])
            adjacent[edge["target"]].add(edge["source"])
        focus = aliases.get(focus_id, focus_id) if view == "constellation" else focus_id
        entrypoint_set, candidate_set = set(entrypoints), set(candidates)
        ranked = sorted(nodes, key=lambda key: (key not in entrypoint_set, key not in candidate_set,
                                               -len(adjacent[key]), key))
        if query:
            needle = query.casefold()
            ranked = [key for key in ranked if needle in " ".join(str(nodes[key].get(field) or "") for field in ("name", "kind", "expression")).casefold()]
        seeds = ([focus] if focus in nodes else []) + ranked
        selected = set()
        for seed in seeds:
            queue = deque([seed])
            queued = {seed}
            while queue and len(selected) < max_nodes:
                current = queue.popleft()
                if current in selected:
                    continue
                selected.add(current)
                neighbors = adjacent[current] - selected - queued
                queued.update(neighbors)
                queue.extend(sorted(neighbors))
            if len(selected) >= max_nodes:
                break
        nodes = {key: nodes[key] for key in nodes if key in selected}
        edges = [e for e in edges if e["source"] in nodes and e["target"] in nodes]
        truncated = truncated or len(selected) < counts["projected_nodes"]
    if max_nodes is not None and len(edges) > max_nodes * 8:
        edges = edges[:max_nodes * 8]
        truncated = True
    counts.update({"visible_nodes": len(nodes), "visible_edges": len(edges)})
    return {**graph, "nodes": list(nodes.values()), "edges": edges, "view": view,
            "granularity": granularity or ("interfaces" if view == "constellation" else "detail"),
            "counts": counts, "truncated": truncated, "projection_truncated": bridge_truncated,
            "entrypoints": entrypoints, "entrypoint_candidates": candidates}
