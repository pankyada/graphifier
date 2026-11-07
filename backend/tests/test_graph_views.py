from __future__ import annotations

import unittest
from graphifier.graph_views import project_graph


def node(key, kind="dataset", **attributes):
    return {"id": key, "name": key, "kind": kind, "attributes": attributes, "evidence": []}


def edge(source, target, kind="INPUT_TO"):
    return {"id": source + ":" + target, "source": source, "target": target, "kind": kind,
            "attributes": {"method": "static"}, "evidence": [{"file": "job.sas", "start_line": 1, "end_line": 2}]}


class GraphViewTests(unittest.TestCase):
    def test_internal_path_preserves_direction_and_evidence(self):
        original = {"nodes": [node("input"), node("work.temp"), node("output"), node("other")],
                    "edges": [edge("input", "work.temp"), edge("work.temp", "output"), edge("other", "work.temp", "CONTAINS")]}
        projected = project_graph(original, "constellation")
        self.assertEqual({n["id"] for n in projected["nodes"]}, {"input", "output", "other"})
        self.assertEqual(len(projected["edges"]), 1)
        link = projected["edges"][0]
        self.assertEqual((link["source"], link["target"]), ("input", "output"))
        self.assertEqual(link["attributes"]["via_nodes"], ["work.temp"])
        self.assertEqual(len(link["evidence"]), 1)
        self.assertEqual(len(original["nodes"]), 4)

    def test_projection_keeps_explicit_interface_and_hides_column_calculation(self):
        original = {"nodes": [node("work.external", interface=True), node("column", "column"),
                              node("calc", "transformation", output_column_id="column"), node("score", "transformation")], "edges": []}
        result = project_graph(original, "constellation")
        self.assertEqual({n["id"] for n in result["nodes"]}, {"work.external", "score"})

    def test_cycle_and_bounded_search(self):
        original = {"nodes": [node("start", "program", entrypoint=True), node("work.a"), node("work.b"), node("end")],
                    "edges": [edge("start", "work.a"), edge("work.a", "work.b"), edge("work.b", "work.a"), edge("work.b", "end")]}
        result = project_graph(original, "constellation", max_nodes=1, query="end")
        self.assertEqual([n["id"] for n in result["nodes"]], ["end"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["counts"]["projected_nodes"], 2)
        self.assertEqual(result["entrypoints"], ["start"])

    def test_canonical_references_are_not_duplicated(self):
        original = {"nodes": [node("reference"), node("physical", canonical=True), node("transform", "transformation")],
                    "edges": [edge("reference", "physical", "RESOLVES_TO"), edge("reference", "transform"), edge("physical", "transform")]}
        result = project_graph(original, "constellation")
        self.assertEqual({n["id"] for n in result["nodes"]}, {"physical", "transform"})
        self.assertEqual(len(result["edges"]), 1)

    def test_model_string_attributes_do_not_promote_false_interfaces(self):
        original = {"nodes": [node("work.temp", interface="false"),
                              node("internal", visibility="internal"),
                              node("public", visibility="interface", transient="false")], "edges": []}
        result = project_graph(original, "constellation")
        self.assertEqual([n["id"] for n in result["nodes"]], ["public"])

    def test_internal_chain_budget_is_reported(self):
        keys = ["source"] + [f"work.{index}" for index in range(40)] + ["target"]
        result = project_graph({"nodes": [node(key) for key in keys],
                                "edges": [edge(a, b) for a, b in zip(keys, keys[1:])]}, "constellation")
        self.assertTrue(result["projection_truncated"])
        self.assertEqual(result["edges"], [])

    def test_projected_dependency_roles_remain_distinct(self):
        value = edge("input", "step")
        value["id"] = "value"
        value["attributes"]["role"] = "value"
        join = edge("input", "step")
        join["id"] = "join"
        join["attributes"]["role"] = "join"
        graph = {"nodes": [node("input"), node("step", "transformation"), node("output")],
                 "edges": [value, join, edge("step", "output", "PRODUCES")]}
        result = project_graph(graph, granularity="overview")
        self.assertEqual({tuple(e["attributes"]["dependency_roles"]) for e in result["edges"]}, {("join",), ("value",)})

    def test_missing_search_does_not_return_unrelated_nodes(self):
        result = project_graph({"nodes": [node("a")], "edges": []}, query="missing")
        self.assertEqual(result["nodes"], [])


if __name__ == "__main__":
    unittest.main()
