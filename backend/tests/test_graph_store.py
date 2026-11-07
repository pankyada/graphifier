from __future__ import annotations
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from graphifier.db import init_db,connect
from graphifier.graph import build_graph
from graphifier.graph_store import ensure_generation,read_window,edge_support,location,GenerationError


class GraphStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'GRAPHIFIER_DB':str(Path(self.tmp.name)/'db.sqlite')})
        self.env.start(); init_db()
        with connect() as c:
            c.execute("INSERT INTO repositories(id,name,path,created_at) VALUES('r','repo','/tmp/r','now')")
            c.execute("INSERT INTO jobs(id,repo_id,environment,status,created_at,updated_at) VALUES('j','r','dev','completed','now','now')")
            c.execute("INSERT INTO snapshots(id,repo_id,job_id,content_hash,created_at) VALUES('s','r','j','h','now')")
            for key,path in [('a','src/input/a.py'),('b','src/output/b.py'),('t','tests/test_a.py')]:
                n={'id':key,'kind':'program','name':key,'attributes':{},'evidence':{'file':path,'start_line':1,'end_line':2}}
                c.execute("INSERT INTO findings(repo_id,snapshot_id,category,item_key,data) VALUES('r','s','entity',?,?)",(key,json.dumps(n)))
            for a,b in [('a','b'),('t','a')]:
                e={'source':a,'target':b,'kind':'CALLS','attributes':{'role':'control'},'evidence':{'file':'tests/test_a.py' if a=='t' else 'src/input/a.py','start_line':1,'end_line':1}}
                c.execute("INSERT INTO findings(repo_id,snapshot_id,category,item_key,data) VALUES('r','s','relationship',?,?)",(a+b,json.dumps(e)))
    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def test_warm_read_does_not_rebuild_and_support_is_paged(self):
        first=build_graph('r','dev',granularity='overview')
        self.assertEqual(first['counts']['hidden_test_nodes'],1)
        self.assertEqual(len(first['nodes']),2)
        self.assertEqual(len(first['edges']),1)
        with patch('graphifier.graph._build',side_effect=AssertionError('full rebuild')):
            second=build_graph('r','dev',granularity='overview')
        self.assertEqual(first['generation'],second['generation'])
        support=edge_support(first['generation'],first['edges'][0]['id'],limit=1)
        self.assertEqual(support['total'],1)
        self.assertEqual(support['edges'][0]['kind'],'CALLS')
        self.assertTrue(support['edges'][0]['evidence'])
        self.assertNotIn('support_edge_ids',first['edges'][0]['attributes'])

    def test_scope_search_and_context_pin(self):
        graph=build_graph('r','dev',granularity='overview',query='b')
        self.assertEqual(len(graph['search_matches']),1)
        match=graph['search_matches'][0]
        loc=location(graph['generation'],match['node']['id'])
        self.assertEqual(loc['ancestors'],match['ancestors'])
        detail=read_window(graph['generation'],'detail',loc['ancestors'][-1],max_nodes=1)
        self.assertEqual(len(detail['nodes']),1)
        self.assertTrue(detail['boundary_truncated'])
        self.assertTrue(detail['breadcrumbs'])
        with self.assertRaises(GenerationError):
            ensure_generation('r','dev',include_tests=True,generation=graph['generation'])
        tests=build_graph('r','dev',granularity='detail',include_tests=True)
        self.assertEqual(len(tests['nodes']),3)
        self.assertNotEqual(tests['generation'],graph['generation'])

    def test_failed_publication_resumes_saved_hierarchy(self):
        with patch('graphifier.graph_store.publish_generation',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): ensure_generation('r','dev')
        with connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM graph_generations').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT phase FROM graph_build_stages').fetchone()[0],'hierarchy')
        with patch('graphifier.graph._build',side_effect=AssertionError('must resume')):
            gid=ensure_generation('r','dev')
        self.assertEqual(len(read_window(gid)['nodes']),2)
        with connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM graph_build_stages').fetchone()[0],0)

    def test_resolution_revision_invalidates_but_pinned_generation_survives(self):
        first=ensure_generation('r','dev')
        with connect() as c:
            c.execute("INSERT INTO resolutions(id,repo_id,environment,symbol,expression,status,version,created_at,updated_at) VALUES('res','r','dev','X','lib.table','applied',1,'now','now')")
        second=ensure_generation('r','dev')
        self.assertNotEqual(first,second)
        self.assertEqual(ensure_generation('r','dev',generation=first),first)

    def test_pinned_trace_uses_indexed_adjacency_and_validates_scope(self):
        from graphifier.graph import trace_graph
        gid=ensure_generation('r','dev')
        with patch('graphifier.graph._build',side_effect=AssertionError('full rebuild')):
            trace=trace_graph('a','out','r','dev',generation=gid)
        self.assertEqual({n['id'] for n in trace['nodes']},{'a','b'})
        self.assertEqual(trace['generation'],gid)
        with self.assertRaises(GenerationError):
            trace_graph('a','out','r','other',generation=gid)
        limited=trace_graph('a','out','r','dev',generation=gid,max_nodes=1)
        self.assertTrue(limited['truncated'])
        self.assertEqual(len(limited['nodes']),1)

    def test_pinned_trace_does_not_cross_unrelated_component_members(self):
        from graphifier.graph_store import publish_generation,trace_generation
        from graphifier.hierarchy import build_hierarchy
        def node(key,path):
            return {'id':key,'name':key,'kind':'program','attributes':{},'repositories':['r'],'evidence':[{'file':path}]}
        def edge(key,a,b,kind='CALLS'):
            return {'id':key,'source':a,'target':b,'kind':kind,'attributes':{},'evidence':[]}
        graph={'repo_id':'r','nodes':[node('start','a/a.py'),node('middle1','b/b.py'),node('middle2','b/c.py'),node('end','c/c.py')],
               'edges':[edge('one','start','middle1'),edge('two','middle2','end'),edge('struct','middle1','middle2','CONTAINS')],
               'version':'v','warnings':[],'snapshots':[]}
        publish_generation('fixture','fixture',graph,build_hierarchy(graph))
        trace=trace_generation('fixture','start','out')
        self.assertEqual({n['id'] for n in trace['nodes']},{'start','middle1'})

    def test_unknown_generation_and_scope_fail_explicitly(self):
        with self.assertRaises(GenerationError): ensure_generation('r','dev',generation='missing')
        gid=ensure_generation('r','dev')
        with self.assertRaises(GenerationError): read_window(gid,scope_id='missing')

if __name__=='__main__': unittest.main()
