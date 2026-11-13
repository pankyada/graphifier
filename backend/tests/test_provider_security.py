import os
import io
import json
import tempfile
import unittest
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from graphifier.agent_config import candidate_agent_config, load_agent_config, save_agent_config
from graphifier.db import connect, init_db
from graphifier.embeddings import configuration
from graphifier import agent, agent_config, embeddings


class ProviderCredentialTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {
            "GRAPHIFIER_DB": str(Path(tmp.name) / "test.db"),
            "OPENAI_BASE_URL": "https://provider.example/v1",
            "OPENAI_API_KEY": "test-provider-key",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        init_db()

    def settings(self, url, **kwargs):
        return dict(base_url=url, model="test", api_mode="responses", **kwargs)

    def test_test_and_save_do_not_rebind_implicit_credentials(self):
        for url in ("https://other.example/v1", "http://provider.example/v1",
                    "https://provider.example:444/v1", "https://provider.example/other"):
            with self.subTest(url=url):
                save_agent_config(**self.settings("https://provider.example/v1", api_key="saved-key"))
                candidate = candidate_agent_config(**self.settings(url, api_key=" "))
                self.assertEqual(candidate["api_key"], "")
                save_agent_config(**self.settings(url))
                self.assertEqual(load_agent_config()["api_key"], "")
                with connect() as c:
                    self.assertEqual(c.execute("SELECT api_key FROM agent_configuration").fetchone()[0], "")

    def test_equivalent_endpoint_preserves_key_and_explicit_key_can_rebind(self):
        candidate = candidate_agent_config(**self.settings("https://PROVIDER.example:443/v1/"))
        self.assertEqual(candidate["api_key"], "test-provider-key")
        save_agent_config(**self.settings("https://other.example/v1", api_key="replacement-key"))
        self.assertEqual(load_agent_config()["api_key"], "replacement-key")
        save_agent_config(**self.settings("https://other.example/v1", api_key="ignored", clear_api_key=True))
        self.assertEqual(load_agent_config()["api_key"], "")

    def test_first_save_and_legacy_null_cannot_inherit_foreign_key(self):
        save_agent_config(**self.settings("http://localhost:8080/v1"))
        self.assertEqual(load_agent_config()["api_key"], "")
        with connect() as c:
            c.execute("UPDATE agent_configuration SET api_key=NULL")
        self.assertEqual(load_agent_config()["api_key"], "")
        with connect() as c:
            c.execute("UPDATE agent_configuration SET base_url='https://provider.example/v1'")
        self.assertEqual(load_agent_config()["api_key"], "test-provider-key")

    def test_embedding_override_requires_its_own_key(self):
        self.assertEqual(configuration()[2], "test-provider-key")
        with patch.dict(os.environ, {"GRAPHIFIER_EMBEDDING_BASE_URL": "https://other.example/v1"}):
            self.assertEqual(configuration()[2], "")
            with patch.dict(os.environ, {"GRAPHIFIER_EMBEDDING_API_KEY": "embedding-key"}):
                self.assertEqual(configuration()[2], "embedding-key")
        with patch.dict(os.environ, {"GRAPHIFIER_EMBEDDING_API_KEY": ""}):
            self.assertEqual(configuration()[2], "")


class ProviderRedirectTests(unittest.TestCase):
    def transport(self, status, location=None, body=None):
        requests = []

        class FakeHTTP(urllib.request.BaseHandler):
            handler_order = 100

            def https_open(self, request):
                requests.append(request)
                headers = Message()
                if location:
                    headers["Location"] = location
                response = urllib.response.addinfourl(
                    io.BytesIO(json.dumps(body or {}).encode()), headers, request.full_url, status
                )
                response.msg = "Test response"
                return response

            http_open = https_open

        build = urllib.request.build_opener
        mocked = patch("urllib.request.build_opener", side_effect=lambda *handlers: build(*handlers, FakeHTTP()))
        mocked.start()
        self.addCleanup(mocked.stop)
        return requests

    def test_all_provider_callers_refuse_redirect_without_second_request(self):
        config = dict(base_url="https://provider.example/v1", api_key="test-key",
                      model="test", api_mode="responses")
        payload = {"model": "test", "input": [], "instructions": "test source", "tools": [], "max_output_tokens": 20}
        for location in ("https://other.example/collect", "http://provider.example/collect",
                         "https://provider.example:444/collect", "/same-origin"):
            for status in (301, 302, 303, 307, 308):
                for caller in (lambda: agent_config.test_agent_connection(config),
                               lambda: agent._response(payload, config),
                               lambda: embeddings._embed(["test source"])):
                    with self.subTest(location=location, status=status, caller=caller):
                        requests = self.transport(status, location)
                        with patch("graphifier.embeddings.configuration", return_value=("test", config["base_url"], "test-key")):
                            with self.assertRaises(RuntimeError):
                                caller()
                        self.assertEqual(len(requests), 1)
                        self.assertEqual(requests[0].get_header("Authorization"), "Bearer test-key")
                        self.doCleanups()

    def test_direct_request_keeps_auth_and_response(self):
        requests = self.transport(200, body={"data": [{"id": "test"}]})
        config = dict(base_url="https://provider.example/v1", api_key="test-key",
                      model="test", api_mode="responses")
        self.assertEqual(agent_config.test_agent_connection(config)["models"], ["test"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer test-key")

    def test_direct_posts_preserve_payload_and_response(self):
        payload = {"model": "test", "input": [], "instructions": "test source", "tools": [], "max_output_tokens": 20}
        for mode, body in (("responses", {"output_text": "ok"}),
                           ("chat_completions", {"choices": [{"message": {"content": "ok"}}]})):
            with self.subTest(mode=mode):
                requests = self.transport(200, body=body)
                config = dict(base_url="https://provider.example/v1", api_key="test-key", model="test", api_mode=mode)
                self.assertEqual(agent._response(payload, config)["output_text"], "ok")
                self.assertEqual(requests[0].get_method(), "POST")
                self.assertEqual(json.loads(requests[0].data)["model"], "test")
                self.assertEqual(requests[0].get_header("Authorization"), "Bearer test-key")
                self.doCleanups()
        requests = self.transport(200, body={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
        with patch("graphifier.embeddings.configuration", return_value=("test", "https://provider.example/v1", "test-key")):
            self.assertEqual(embeddings._embed(["test source"]), [[1.0, 0.0]])
        self.assertEqual(json.loads(requests[0].data)["input"], ["test source"])
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer test-key")
