from __future__ import annotations
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from graphifier import ai_hierarchy as ai
from graphifier.db import init_db,connect
from graphifier.hierarchy import build_hierarchy


class AiHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'GRAPHIFIER_DB':str(Path(self.tmp.name)/'db.sqlite')});self.env.start();init_db()
        with connect() as c:
            c.execute("INSERT INTO repositories(id,name,path,created_at) VALUES('r','repo','/tmp/r','now')")
            c.execute("INSERT INTO jobs(id,repo_id,environment,status,created_at,updated_at) VALUES('j','r','dev','running','now','now')")
        self.config={'model':'test-model','api_mode':'responses','base_url':'https://example.invalid/v1','api_key':'secret-key','reasoning_effort':'low'}
        self.graph={'repo_id':'r','nodes':[self.node('a','ingest/a.py'),self.node('b','publish/b.py')],'edges':[]}
    def tearDown(self): self.env.stop();self.tmp.cleanup()
    def node(self,key,path):
        return {'id':key,'name':key,'kind':'function','attributes':{},'repositories':['r'],'evidence':[{'file':path,'start_line':1,'end_line':2}]}
    def answer(self,payload,config=None):
        request=json.loads(payload['input'][0]['content']);components=request['components']
        base={'name':'Customer data','summary':'Prepares and publishes customer records.','rationale':'Observed component inputs and outputs.','confidence':0.8}
        if request['phase']=='components':
            result={'groups':[],'component_summaries':[{**base,'component_id':c['component_id'],'evidence_node_ids':[c['evidence_nodes'][0]['id']]} for c in components],'warnings':[]}
        else:
            result={'groups':[{**base,'id':'customer-data','component_ids':[c['component_id'] for c in components],'evidence_node_ids':[c['evidence_nodes'][0]['id'] for c in components]}],'component_summaries':[],'warnings':[]}
        return {'output_text':json.dumps(result)}

    def test_bottom_up_proposals_persist_and_apply_without_credentials(self):
        with patch.object(ai.agent,'_response',side_effect=self.answer) as provider:
            proposal=ai.run_ai_hierarchy('j',self.graph,self.config)
        self.assertEqual(provider.call_count,2)
        self.assertEqual(proposal['status'],'completed')
        self.assertEqual(len(proposal['component_summaries']),2)
        self.assertEqual(len(proposal['groups']),1)
        hierarchy=build_hierarchy(self.graph,proposal)
        self.assertTrue(any(g['attributes'].get('provenance')=='model-inferred' for g in hierarchy['groups']))
        self.assertNotIn('secret-key',json.dumps(proposal))
        self.assertNotIn('api_key',json.dumps(proposal))
        with patch.object(ai.agent,'_response',side_effect=AssertionError('must reuse')):
            self.assertEqual(ai.run_ai_hierarchy('j',self.graph,self.config),proposal)
        self.assertEqual(ai.load_proposal('j'),proposal)

    def test_response_checkpoint_survives_cancellation_before_validation(self):
        state={'cancel':False}
        def responding(payload,config=None):
            result=self.answer(payload,config);state['cancel']=True;return result
        with patch.object(ai.agent,'_response',side_effect=responding):
            with self.assertRaises(ai.agent.AnalysisCancelled):
                ai.run_ai_hierarchy('j',self.graph,self.config,lambda:state['cancel'])
        with connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM analysis_ai_hierarchy_units').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM analysis_ai_hierarchy').fetchone()[0],0)
        with patch.object(ai.agent,'_response',side_effect=self.answer) as provider:
            proposal=ai.run_ai_hierarchy('j',self.graph,self.config)
        self.assertEqual(provider.call_count,1)
        self.assertEqual(proposal['status'],'completed')

    def test_invalid_json_is_saved_once_and_marks_partial(self):
        with patch.object(ai.agent,'_response',return_value={'output_text':'not json'}) as provider:
            proposal=ai.run_ai_hierarchy('j',self.graph,self.config)
        self.assertEqual(provider.call_count,2)
        self.assertEqual(proposal['status'],'partial')
        self.assertFalse(proposal['groups'])
        with patch.object(ai.agent,'_response',side_effect=AssertionError('must reuse')):
            self.assertEqual(ai.run_ai_hierarchy('j',self.graph,self.config),proposal)

    def test_transport_failure_remains_resumable(self):
        with patch.object(ai.agent,'_response',side_effect=ai.agent.ModelTransportError('failed')):
            with self.assertRaises(ai.agent.ModelTransportError): ai.run_ai_hierarchy('j',self.graph,self.config)
        self.assertIsNone(ai.load_proposal('j'))
        with patch.object(ai.agent,'_response',side_effect=self.answer):
            self.assertEqual(ai.run_ai_hierarchy('j',self.graph,self.config)['status'],'completed')

    def test_no_call_after_cancellation_or_beyond_budget(self):
        with patch.object(ai.agent,'_response') as provider:
            with self.assertRaises(ai.agent.AnalysisCancelled): ai.run_ai_hierarchy('j',self.graph,self.config,lambda:True)
        provider.assert_not_called()
        with patch.object(ai.agent,'_response',side_effect=self.answer) as provider:
            proposal=ai.run_ai_hierarchy('j',self.graph,{**self.config,'hierarchy_max_batches':1})
        self.assertEqual(provider.call_count,1)
        self.assertEqual(proposal['status'],'partial')
        self.assertEqual(len(proposal['component_summaries']),2)
        self.assertFalse(proposal['groups'])

    def test_forged_references_nonfinite_confidence_and_duplicate_assignments_rejected(self):
        components={'c':{'repositories':['r'],'context':'production'}};citations={'c':{'n'}}
        base={'component_id':'c','name':'Name','summary':'Summary','rationale':'Evidence','confidence':0.8,'evidence_node_ids':['n']}
        for invalid in ({**base,'evidence_node_ids':['invented']},{**base,'confidence':float('nan')},{**base,'component_id':'unknown'}):
            _,summaries,warnings=ai._validate(json.dumps({'groups':[],'component_summaries':[invalid],'warnings':[]}),'components',components,citations)
            self.assertEqual(summaries,[]);self.assertTrue(warnings)
        _,summaries,warnings=ai._validate(json.dumps({'groups':[],'component_summaries':[base,base],'warnings':[]}),'components',components,citations)
        self.assertEqual(len(summaries),1);self.assertTrue(warnings)
        _,summaries,warnings=ai._validate(json.dumps({'groups':[],'component_summaries':[base],'warnings':[],'validated_node_ids':['invented']}),'components',components,citations)
        self.assertEqual(summaries,[])

    def test_test_and_production_components_are_separate_calls(self):
        graph={**self.graph,'nodes':[self.node('a','src/ingest/a.py'),self.node('t','tests/test_a.py')]}
        seen=[]
        def provider(payload,config=None):
            request=json.loads(payload['input'][0]['content']);seen.append({c['context'] for c in request['components']})
            return self.answer(payload,config)
        with patch.object(ai.agent,'_response',side_effect=provider):
            proposal=ai.run_ai_hierarchy('j',graph,self.config)
        self.assertTrue(all(len(contexts)==1 for contexts in seen))
        self.assertEqual(len(proposal['groups']),2)

    def test_source_excerpts_and_dependencies_are_bounded_and_fingerprinted(self):
        graph={**self.graph,'edges':[{'id':'read','source':'a','target':'b','kind':'CALLS','attributes':{},'evidence':[]}]}
        sources={'ingest/a.py':'transform_customer_data = '+('x'*4000),'publish/b.py':'publish_customer_data()'}
        captured=[]
        def provider(payload,config=None):
            request=json.loads(payload['input'][0]['content']);captured.extend(request['components'])
            self.assertLessEqual(len(json.dumps(payload)),ai.MAX_PROMPT_CHARS)
            return self.answer(payload,config)
        with patch.object(ai.agent,'_response',side_effect=provider):
            proposal=ai.run_ai_hierarchy('j',graph,self.config,sources=sources)
        excerpts=[n['source_excerpt'] for c in captured for n in c['evidence_nodes']]
        self.assertTrue(all(len(e['text'])<=1500 for e in excerpts))
        self.assertTrue(any(c['dependencies'] for c in captured))
        self.assertTrue(any('transform_customer_data' in e['text'] for e in excerpts))
        with patch.object(ai.agent,'_response',side_effect=provider) as model:
            changed=ai.run_ai_hierarchy('j',graph,self.config,sources={**sources,'publish/b.py':'publish_updated_data()'})
        self.assertEqual(model.call_count,2)
        self.assertNotEqual(proposal['input_hash'],changed['input_hash'])

    def test_batches_are_bounded_and_model_change_invalidates(self):
        graph={**self.graph,'nodes':[self.node(str(i),f'area{i}/a.py') for i in range(26)]}
        def provider(payload,config=None):
            self.assertLessEqual(len(json.dumps(payload)),ai.MAX_PROMPT_CHARS)
            self.assertLessEqual(len(json.loads(payload['input'][0]['content'])['components']),24)
            return self.answer(payload,config)
        with patch.object(ai.agent,'_response',side_effect=provider) as model:
            proposal=ai.run_ai_hierarchy('j',graph,self.config)
        self.assertEqual(model.call_count,4)
        self.assertEqual(len(proposal['component_summaries']),26)
        with patch.object(ai.agent,'_response',side_effect=provider) as model:
            newer=ai.run_ai_hierarchy('j',graph,{**self.config,'model':'next-model'})
        self.assertEqual(model.call_count,4)
        self.assertNotEqual(newer['input_hash'],proposal['input_hash'])

if __name__=='__main__': unittest.main()
