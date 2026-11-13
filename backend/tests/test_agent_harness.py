import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from graphifier.agent import analyze_file, _response, validate, AnalysisCancelled


EMPTY = {"entities": [], "relationships": [], "symbols": [], "warnings": []}


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.environment = patch.dict(os.environ, {"GRAPHIFIER_DB": str(Path(self.tmp.name) / "db.sqlite3")})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_tools_follow_context_and_return_valid_findings(self):
        responses = [
            {"output": [{"type": "function_call", "call_id": "read", "name": "read_source", "arguments": json.dumps({"path": "other.py", "start_line": 1})}]},
            {"output_text": json.dumps(EMPTY)},
        ]
        with patch("graphifier.agent._response", side_effect=responses) as call:
            self.assertEqual(analyze_file("main.py", "import other\n", {"main.py": "import other\n", "other.py": "value = 1\n"}), EMPTY)
            self.assertIn("value = 1", call.call_args[0][0]["input"][-1]["output"])

    def test_step_budget_is_explicit(self):
        response = {"output": [{"type": "function_call", "call_id": "list", "name": "list_files", "arguments": '{"query":"","offset":0}'}]}
        with patch.dict(os.environ, {"GRAPHIFIER_AGENT_MAX_STEPS": "1"}), patch("graphifier.agent._response", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                analyze_file("main.py", "x=1", {"main.py": "x=1"})

    def test_unlimited_steps_exceed_previous_cap(self):
        response = {"output": [{"type": "function_call", "call_id": "list", "name": "list_files", "arguments": '{"query":"","offset":0}'}]}
        responses = [response] * 105 + [{"output_text": json.dumps(EMPTY)}]
        with patch.dict(os.environ, {"GRAPHIFIER_AGENT_MAX_STEPS": "0"}), patch("graphifier.agent._response", side_effect=responses) as call:
            self.assertEqual(analyze_file("main.py", "x=1", {"main.py": "x=1"}), EMPTY)
            self.assertEqual(call.call_count, 106)

    def test_cancel_before_request(self):
        class Sources(dict):
            def cancelled(self):
                return True
        with patch("graphifier.agent._response") as call:
            with self.assertRaises(AnalysisCancelled):
                analyze_file("main.py", "x=1", Sources())
            call.assert_not_called()

    def test_duplicate_entity_ids_are_rejected(self):
        entity = {"id": "x", "kind": "dataset", "name": "x", "evidence": {"file": "x.py", "start_line": 1, "end_line": 1}}
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            validate({**EMPTY, "entities": [entity, entity]}, "x.py", "x=1")

    def test_chat_tool_calls_grouped_before_outputs(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({"choices": [{"message": {"content": json.dumps(EMPTY)}}]}).encode()
        payload = {"model": "local", "instructions": "Return JSON", "tools": [], "max_output_tokens": 10, "input": [
            {"role": "user", "content": "inspect"},
            {"type": "function_call", "call_id": "a", "name": "read_source", "arguments": "{}"},
            {"type": "function_call", "call_id": "b", "name": "list_files", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "a", "output": "{}"},
            {"type": "function_call_output", "call_id": "b", "output": "{}"},
        ]}
        with patch.dict(os.environ, {"GRAPHIFIER_AGENT_API": "chat_completions", "OPENAI_BASE_URL": "http://localhost:8080/v1"}), patch("graphifier.provider_http.urlopen", return_value=Response()) as call:
            _response(payload)
            request = call.call_args[0][0]
            body = json.loads(request.data)
            self.assertEqual(len(body["messages"][2]["tool_calls"]), 2)
            self.assertTrue(request.full_url.endswith("/chat/completions"))

    def test_cross_file_citations_are_validated_against_snapshot(self):
        item = {"id": "x", "kind": "dataset", "name": "table", "attributes": {}, "evidence": {"file": "other.py", "start_line": 2, "end_line": 2}}
        result = {**EMPTY, "entities": [item]}
        self.assertEqual(validate(result, "main.py", "import other", {"main.py": "import other", "other.py": "# first\nvalue=1"}), result)
        with self.assertRaisesRegex(RuntimeError, "Invalid evidence range"):
            validate(result, "main.py", "import other", {"other.py": "one line"})

    def test_invalid_citation_repair_and_salvage(self):
        item = {"id": "x", "kind": "dataset", "name": "table", "attributes": [], "evidence": {"file": "other.py", "start_line": 2, "end_line": 2}}
        valid = {**EMPTY, "entities": [item]}
        bad = json.loads(json.dumps(valid))
        bad["entities"][0]["evidence"]["start_line"] = 99
        responses = [{"output_text": json.dumps(bad)}, {"output_text": json.dumps(valid)}]
        with patch("graphifier.agent._response", side_effect=responses) as call:
            result = analyze_file("main.py", "import other", {"main.py": "import other", "other.py": "# comment\nx=1"})
            self.assertEqual(result["entities"][0]["evidence"]["file"], "other.py")
            self.assertEqual(call.call_count, 2)
        with patch("graphifier.agent._response", return_value={"output_text": json.dumps(bad)}):
            result = analyze_file("main.py", "import other", {"main.py": "import other", "other.py": "# comment\nx=1"})
            self.assertEqual(result["entities"], [])
            self.assertIn("discarded 1", result["warnings"][0])

    def test_data_lineage_contract_accepts_owned_columns_and_exact_calculation(self):
        source = "SELECT amount * 2 AS doubled FROM sales;"
        ev = {"file": "query.sql", "start_line": 1, "end_line": 1}
        dataset = {"id": "sales", "kind": "dataset", "name": "sales", "attributes": {}, "evidence": ev}
        column = {"id": "amount", "kind": "column", "name": "amount", "attributes": {"parent_dataset_id": "sales"}, "evidence": ev}
        transform = {"id": "double", "kind": "transformation", "name": "double", "expression": "amount * 2", "attributes": {}, "evidence": ev}
        result = {**EMPTY, "entities": [dataset, column, transform], "relationships": [{"source": "sales", "target": "amount", "kind": "HAS_COLUMN", "attributes": {}, "evidence": ev}, {"source": "amount", "target": "double", "kind": "INPUT_TO", "attributes": {"role": "value"}, "evidence": ev}]}
        with patch("graphifier.agent._response", return_value={"output_text": json.dumps(result)}) as model:
            extracted = analyze_file("query.sql", source, {"query.sql": source})
        self.assertEqual(extracted["entities"][2]["expression"], "amount * 2")
        prompt = model.call_args[0][0]["instructions"]
        self.assertIn("Never assign ambiguous", prompt)
        self.assertIn("role=value, filter, join, or grouping", prompt)
        invalid = json.loads(json.dumps(result))
        invalid["entities"][1]["attributes"]["parent_dataset_id"] = "guessed"
        with self.assertRaisesRegex(RuntimeError, "parent_dataset_id"):
            validate(invalid, "query.sql", source)
        invalid = json.loads(json.dumps(result))
        invalid["entities"][2]["expression"] = "amount * 3"
        with self.assertRaisesRegex(RuntimeError, "actual source expression"):
            validate(invalid, "query.sql", source)

    def test_targeted_gap_context_and_paginated_schema_tool(self):
        class Sources(dict):
            current_analysis = {"gaps": [{"id": "gap-1", "kind": "ambiguous_column", "expression": "amount", "evidence": {"file": "query.sql", "start_line": 1, "end_line": 1}}], "warnings": ["Unqualified amount is ambiguous"]}
            def find_schema(self, query, offset):
                self.query = (query, offset)
                return {"matches": [{"table": "sales", "column": "amount", "evidence": {"file": "schema.sql", "start_line": 1, "end_line": 1}}], "next_offset": None}
        sources = Sources({"query.sql": "SELECT amount FROM sales JOIN refunds ON sales.id=refunds.id", "schema.sql": "CREATE TABLE sales(amount DECIMAL);"})
        replies = [{"output": [{"type": "function_call", "call_id": "schema", "name": "find_schema", "arguments": '{"query":"amount","offset":0}'}]}, {"output_text": json.dumps(EMPTY)}]
        with patch("graphifier.agent._response", side_effect=replies) as model:
            analyze_file("query.sql", sources["query.sql"], sources)
        self.assertEqual(sources.query, ("amount", 0))
        payload = model.call_args[0][0]
        self.assertIn("gap-1", payload["input"][0]["content"])
        self.assertIn("ambiguous_column", payload["input"][0]["content"])
        self.assertIn("schema.sql", payload["input"][-1]["output"])

    def test_literal_lookup_pages_beyond_first_eight_matches(self):
        from graphifier.agent import _lookup
        sources = {"schema.sql": "\n".join(f"column value_{n}" for n in range(12)), "other.sql": "column other"}
        first = _lookup("column", sources, file_filter="schema")
        second = _lookup("column", sources, offset=first["next_offset"], file_filter="schema")
        self.assertEqual(len(first["matches"]), 8)
        self.assertEqual(len(second["matches"]), 4)
        self.assertEqual(second["matches"][0]["line"], 9)
