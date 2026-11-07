import unittest
from graphifier.consolidation import consolidate_findings
from graphifier.graph_views import project_graph

class ConsolidationTests(unittest.TestCase):
    def test_scope_and_semantic_edges(self):
        def entity(key, module):
            return {'id':key,'kind':'dataset','name':'work.temp','attributes':{'module':module},'evidence':{'file':'a.sas','start_line':1,'end_line':1}}
        entities=[entity('a','one'),entity('b','one'),entity('c','two')]
        rels=[{'source':'a','target':'c','kind':'INPUT_TO','attributes':{'role':role},'evidence':{'file':'a.sas','start_line':line,'end_line':line}} for role,line in [('value',1),('value',2),('filter',3)]]
        result=consolidate_findings(entities,rels)
        self.assertEqual(len(result['entities']),2)
        self.assertEqual(len(result['relationships']),2)
        self.assertEqual(len(result['relationships'][0]['evidence_spans']),2)
        self.assertEqual(result['summary']['id_mapping']['b'],'a')
        self.assertNotIn('source_ids',entities[0]['attributes'])

    def test_levels_are_independent_of_layout(self):
        nodes=[{'id':x,'kind':kind,'name':x,'attributes':{}} for x,kind in [('input','dataset'),('step','transformation'),('output','dataset')]]
        edges=[{'id':str(i),'source':a,'target':b,'kind':kind,'attributes':{},'evidence':[]} for i,(a,b,kind) in enumerate([('input','step','INPUT_TO'),('step','output','PRODUCES')])]
        graph={'nodes':nodes,'edges':edges}
        for view in ['flow','constellation']:
            overview=project_graph(graph,view,granularity='overview')
            self.assertEqual(len(overview['nodes']),2)
            self.assertEqual(overview['edges'][0]['attributes']['via_nodes'],['step'])
            self.assertEqual(len(project_graph(graph,view,granularity='detail')['nodes']),3)

    def test_semantic_entity_variants_and_mixed_edge_provenance(self):
        entities = [{'id': key, 'kind': 'transformation', 'name': 'calc', 'expression': 'a+b',
                     'attributes': {'condition': condition},
                     'evidence': {'file': 'job.py', 'start_line': 1, 'end_line': 1}}
                    for key, condition in [('a', 'x'), ('b', 'y')]]
        rels = [{'source': 'a', 'target': 'b', 'kind': 'INPUT_TO',
                 'attributes': {'method': method}, 'evidence': {}}
                for method in ['static', 'model-inferred']]
        result = consolidate_findings(entities, rels)
        self.assertEqual(len(result['entities']), 2)
        self.assertEqual(len(result['relationships']), 1)
        self.assertEqual(result['relationships'][0]['attributes']['source_methods'], ['model-inferred', 'static'])
