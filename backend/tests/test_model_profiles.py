import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from graphifier.api import app
from graphifier.agent_config import load_agent_config,save_agent_config,candidate_agent_config,profile_config
from graphifier.db import connect


class ModelProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'GRAPHIFIER_DB':str(Path(self.tmp.name)/'db.sqlite'),'GRAPHIFIER_REPO_ROOT':str(Path(self.tmp.name)/'repos'),'OPENAI_BASE_URL':'https://api.openai.com/v1','GRAPHIFIER_API_TOKEN':''})
        self.env.start()
        self.removed={k:os.environ.pop(k) for k in ('GRAPHIFIER_AGENT_MODEL','GRAPHIFIER_AGENT_REASONING_EFFORT','GRAPHIFIER_HIERARCHY_MODEL','GRAPHIFIER_HIERARCHY_REASONING_EFFORT') if k in os.environ}
        self.client=TestClient(app,base_url='http://127.0.0.1');self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None);os.environ.update(self.removed);self.env.stop();self.tmp.cleanup()
    def test_official_defaults_are_separate_profiles(self):
        config=load_agent_config()
        self.assertEqual((config['model'],config['reasoning_effort']),('gpt-6-luna','low'))
        hierarchy=profile_config(config,'hierarchy')
        self.assertEqual((hierarchy['model'],hierarchy['reasoning_effort']),('gpt-6-luna','high'))
        self.assertEqual(config['reasoning_effort'],'low')
    def test_legacy_saved_harness_settings_are_preserved(self):
        with connect() as c:
            c.execute("INSERT INTO agent_configuration(id,base_url,model,api_mode,api_key,reasoning_effort) VALUES(1,'https://api.openai.com/v1','saved-model','responses',NULL,NULL)")
        config=load_agent_config()
        self.assertEqual(config['model'],'saved-model');self.assertIsNone(config['reasoning_effort'])
        self.assertEqual(config['hierarchy_reasoning_effort'],'high')
    def test_custom_endpoint_inherits_without_new_luna_override(self):
        save_agent_config('http://localhost:8080/v1','local-model','chat_completions',reasoning_effort='medium')
        config=load_agent_config();h=profile_config(config,'hierarchy')
        self.assertEqual((h['model'],h['reasoning_effort']),('local-model','medium'))
        candidate=candidate_agent_config('http://localhost:9000/v1','other-model','responses',reasoning_effort='low')
        self.assertEqual(candidate['hierarchy_model'],'other-model')
    def test_older_clients_preserve_hierarchy_and_explicit_null_effort(self):
        base={'base_url':'https://api.openai.com/v1','model':'harness-model','api_mode':'responses'}
        response=self.client.post('/api/settings/agent',json={**base,'reasoning_effort':'low','hierarchy_model':'summary-model','hierarchy_reasoning_effort':'high'})
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.post('/api/settings/agent',json={**base,'model':'changed-harness'})
        self.assertEqual(response.json()['hierarchy_model'],'summary-model')
        self.assertEqual(response.json()['hierarchy_reasoning_effort'],'high')
        self.assertEqual(response.json()['reasoning_effort'],'low')
        response=self.client.post('/api/settings/agent',json={**base,'hierarchy_reasoning_effort':None})
        self.assertIsNone(response.json()['hierarchy_reasoning_effort'])
        self.client.post('/api/settings/agent',json=base)
        self.assertIsNone(load_agent_config()['hierarchy_reasoning_effort'])
    def test_null_model_resets_auto_and_validation_does_not_echo_secret(self):
        base={'base_url':'http://localhost:8080/v1','model':'local','api_mode':'responses'}
        self.client.post('/api/settings/agent',json={**base,'hierarchy_model':'override'})
        response=self.client.post('/api/settings/agent',json={**base,'hierarchy_model':None})
        self.assertEqual(response.json()['hierarchy_model'],'local')
        invalid=self.client.post('/api/settings/agent',json={**base,'hierarchy_reasoning_effort':'invalid','api_key':'secret-not-echoed'})
        self.assertEqual(invalid.status_code,422);self.assertNotIn('secret-not-echoed',invalid.text)
        invalid=self.client.post('/api/settings/agent',json={**base,'hierarchy_model':'bad\nmodel'})
        self.assertEqual(invalid.status_code,400)
    def test_candidate_custom_endpoint_does_not_carry_official_default(self):
        config=candidate_agent_config('http://localhost:8080/v1','custom','responses')
        self.assertIsNone(config['reasoning_effort']);self.assertIsNone(config['hierarchy_reasoning_effort'])
        self.assertEqual(config['hierarchy_model'],'custom')
    def test_environment_can_override_independent_profiles(self):
        with patch.dict(os.environ,{'GRAPHIFIER_AGENT_MODEL':'harness','GRAPHIFIER_AGENT_REASONING_EFFORT':'minimal','GRAPHIFIER_HIERARCHY_MODEL':'summary','GRAPHIFIER_HIERARCHY_REASONING_EFFORT':'high'}):
            config=load_agent_config()
        self.assertEqual(profile_config(config)['model'],'harness')
        self.assertEqual(profile_config(config,'hierarchy')['model'],'summary')
        self.assertEqual(profile_config(config,'hierarchy')['reasoning_effort'],'high')

if __name__=='__main__':unittest.main()
