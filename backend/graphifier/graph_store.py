"""Immutable, indexed graph generations for bounded hierarchy exploration."""
from __future__ import annotations

import hashlib
import json
import os
from .db import connect, json_data

STORE_VERSION = 'hierarchy-store-1'


class GenerationError(ValueError):
    pass


def init_store(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS graph_build_stages (id TEXT PRIMARY KEY, phase TEXT NOT NULL, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS graph_generations (
      id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, metadata TEXT NOT NULL, status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS graph_read_nodes (
      generation TEXT NOT NULL REFERENCES graph_generations(id) ON DELETE CASCADE,
      level TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
      parent_id TEXT, data TEXT NOT NULL, PRIMARY KEY(generation,level,id)
    );
    CREATE INDEX IF NOT EXISTS graph_read_parent ON graph_read_nodes(generation,level,parent_id);
    CREATE TABLE IF NOT EXISTS graph_read_edges (
      generation TEXT NOT NULL REFERENCES graph_generations(id) ON DELETE CASCADE,
      level TEXT NOT NULL, id TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
      data TEXT NOT NULL, PRIMARY KEY(generation,level,id)
    );
    CREATE INDEX IF NOT EXISTS graph_read_source ON graph_read_edges(generation,level,source);
    CREATE INDEX IF NOT EXISTS graph_read_target ON graph_read_edges(generation,level,target);
    CREATE TABLE IF NOT EXISTS graph_read_members (
      generation TEXT NOT NULL REFERENCES graph_generations(id) ON DELETE CASCADE,
      group_id TEXT NOT NULL, node_id TEXT NOT NULL, PRIMARY KEY(generation,group_id,node_id)
    );
    CREATE INDEX IF NOT EXISTS graph_read_member_node ON graph_read_members(generation,node_id,group_id);
    CREATE TABLE IF NOT EXISTS graph_read_support (
      generation TEXT NOT NULL REFERENCES graph_generations(id) ON DELETE CASCADE,
      edge_id TEXT NOT NULL, support_id TEXT NOT NULL, PRIMARY KEY(generation,edge_id,support_id)
    );
    ''')


def load_ai_proposals(c, snapshots):
    """Combine saved per-repository inferences without making model requests."""
    proposals, warnings, models = [], [], set()
    for snapshot in snapshots:
        row = c.execute('SELECT data FROM analysis_ai_hierarchy WHERE job_id=?', (snapshot['job_id'],)).fetchone()
        if row:
            proposal = json.loads(row['data'])
            proposals.append(proposal)
            warnings.extend(proposal.get('warnings', []))
            if proposal.get('model'):
                models.add(proposal['model'])
    if not proposals:
        return None, {'status': 'not_requested', 'warnings': []}
    combined = {'groups': [], 'component_summaries': [], 'validated_component_ids': [], 'validated_node_ids': [],
                'model': ', '.join(sorted(models)), 'prompt_version': 'saved-per-repository'}
    for proposal in proposals:
        for key in ('groups', 'component_summaries'):
            combined[key].extend({**item, 'origin_model': proposal.get('model'), 'origin_prompt_version': proposal.get('prompt_version')} for item in proposal.get(key, []))
        for key in ('validated_component_ids', 'validated_node_ids'):
            combined[key].extend(proposal.get(key, []))
    status = 'partial' if warnings or any(p.get('status') == 'partial' for p in proposals) else 'completed'
    return combined, {'status': status, 'model': combined['model'], 'warnings': warnings,
                      'group_count': len(combined['groups']), 'component_summary_count': len(combined['component_summaries'])}


def _scope(repo_id, environment, namespace, include_tests, hierarchy_mode="ai"):
    return json_data([repo_id, environment, namespace or os.environ.get('GRAPHIFIER_SYSTEM','local-workspace'), bool(include_tests), hierarchy_mode])


def ensure_generation(repo_id=None, environment=None, namespace=None, include_tests=False, generation=None, hierarchy_mode="ai"):
    from . import hierarchy
    from .graph import _load, _build
    from pathlib import Path
    if hierarchy_mode not in {"ai", "deterministic"}:
        raise GenerationError("Unknown hierarchy mode")
    scope_key = _scope(repo_id, environment, namespace, include_tests, hierarchy_mode)
    with connect() as c:
        if generation:
            row = c.execute("SELECT * FROM graph_generations WHERE id=? AND status='ready'", (generation,)).fetchone()
            if not row or row['scope_key'] != scope_key:
                raise GenerationError('Graph generation is unavailable or belongs to a different scope. Refresh the graph.')
            return generation
        # Explicit read transaction pins snapshots and resolutions during construction.
        c.execute('BEGIN')
        snapshots = _load(c, repo_id, environment)
        bindings = []
        for rid, snap in snapshots.items():
            bindings.extend(dict(r) for r in c.execute("SELECT * FROM resolutions WHERE repo_id=? AND environment=? AND status='applied' ORDER BY id", (rid,snap['environment'])))
        proposal, ai_metadata = load_ai_proposals(c, snapshots.values())
        fingerprint = [json_data(proposal),json_data(ai_metadata),hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in ('graph.py', 'code_links.py'))).hexdigest(),STORE_VERSION,getattr(hierarchy,'VERSION','1'),scope_key,[(rid,s['id'],s['content_hash']) for rid,s in snapshots.items()],bindings]
        gid = 'generation:' + hashlib.sha256(json_data(fingerprint).encode()).hexdigest()[:32]
        if c.execute("SELECT 1 FROM graph_generations WHERE id=? AND status='ready'", (gid,)).fetchone():
            return gid
        stage = c.execute('SELECT phase,data FROM graph_build_stages WHERE id=?',(gid,)).fetchone()
        graph = None if stage else _build(c,repo_id,environment,namespace)
    if stage:
        data = json.loads(stage['data'])
        graph = data['graph']
        if stage['phase'] == 'hierarchy':
            publish_generation(gid,scope_key,graph,data['model'],include_tests)
            return gid
    else:
        with connect() as c:
            c.execute("INSERT OR IGNORE INTO graph_build_stages VALUES(?,'extracted',?)",(gid,json_data({'graph':graph})))
    # No partial generation is exposed: all persisted rows publish in one transaction.
    graph = hierarchy.filter_graph_context(graph, include_tests=include_tests)
    graph['hierarchy_mode'] = hierarchy_mode
    graph['ai_hierarchy'] = ai_metadata
    try:
        model = hierarchy.build_hierarchy(graph, proposal=proposal if hierarchy_mode == 'ai' else None)
    except (ValueError, TypeError, KeyError) as exc:
        # Invalid or no-longer-applicable inference cannot invalidate evidence.
        model = hierarchy.build_hierarchy(graph)
        graph['ai_hierarchy'] = {**ai_metadata, 'status': 'partial',
            'warnings': [*ai_metadata.get('warnings', []), 'AI grouping could not be applied to this scope; source structure shown.']}

    graph['warnings'] = [*graph.get('warnings', []), *[
        {'repo_id': repo_id, 'snapshot_id': None, 'warning': message}
        for message in graph['ai_hierarchy'].get('warnings', [])]]

    with connect() as c:
        c.execute("UPDATE graph_build_stages SET phase='hierarchy',data=? WHERE id=?",(json_data({'graph':graph,'model':model}),gid))
    publish_generation(gid,scope_key,graph,model,include_tests)
    return gid


def publish_generation(gid, scope_key, graph, model, include_tests=False):
    groups = model['groups']
    metadata = {k:v for k,v in graph.items() if k not in {'nodes','edges'}}
    metadata.update({'recommended_levels':model['recommended_levels'],'include_tests':include_tests,
                     'total_nodes':len(graph['nodes']),'total_edges':len(graph['edges'])})
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM graph_generations WHERE id=? AND status='ready'",(gid,)).fetchone():
            return
        c.execute("INSERT OR REPLACE INTO graph_generations VALUES(?,?,?,'building')",(gid,scope_key,json_data(metadata)))
        for level, nodes in [('detail',graph['nodes']),('overview',[n for n in groups if n['attributes']['level']=='overview']),('interfaces',[n for n in groups if n['attributes']['level']=='interfaces'])]:
            c.executemany('INSERT INTO graph_read_nodes VALUES(?,?,?,?,?,?,?)',((gid,level,n['id'],n.get('name',''),n.get('kind',''),n.get('attributes',{}).get('parent_id'),json_data(n)) for n in nodes))
        for level, edges in [('detail',graph['edges']),('overview',[e for e in model['rollup_edges'] if e['attributes']['level']=='overview']),('interfaces',[e for e in model['rollup_edges'] if e['attributes']['level']=='interfaces'])]:
            for edge in edges:
                item = {**edge,'attributes':dict(edge.get('attributes',{}))}
                support = item['attributes'].pop('support_edge_ids',[])
                # Detailed evidence is requested separately; summary edges remain small.
                if level != 'detail': item['evidence'] = []
                c.execute('INSERT INTO graph_read_edges VALUES(?,?,?,?,?,?)',(gid,level,item['id'],item['source'],item['target'],json_data(item)))
                c.executemany('INSERT OR IGNORE INTO graph_read_support VALUES(?,?,?)',((gid,item['id'],sid) for sid in support))
        c.executemany('INSERT OR IGNORE INTO graph_read_members VALUES(?,?,?)',((gid,m['group_id'],m['node_id']) for m in model['memberships']))
        # Ancestor membership makes scopes directly queryable without recursive graph loads.
        c.executemany('INSERT OR IGNORE INTO graph_read_members VALUES(?,?,?)',((gid,ancestor,node) for node,ancestors in model['ancestors'].items() for ancestor in ancestors))
        c.execute("UPDATE graph_generations SET status='ready' WHERE id=?",(gid,))
        c.execute('DELETE FROM graph_build_stages WHERE id=?',(gid,))


def _metadata(c,generation):
    row = c.execute("SELECT metadata FROM graph_generations WHERE id=? AND status='ready'",(generation,)).fetchone()
    if not row: raise GenerationError('Graph generation is unavailable. Refresh the graph.')
    return json.loads(row['metadata'])


def location(generation,node_id):
    with connect() as c:
        _metadata(c,generation)
        exists = c.execute('SELECT 1 FROM graph_read_nodes WHERE generation=? AND id=?',(generation,node_id)).fetchone()
        if not exists: raise GenerationError('Entity is unavailable in this graph generation.')
        rows = c.execute("SELECT DISTINCT n.data FROM graph_read_members m JOIN graph_read_nodes n ON n.generation=m.generation AND n.id=m.group_id WHERE m.generation=? AND m.node_id=? ORDER BY n.level DESC,n.id",(generation,node_id)).fetchall()
        groups = [json.loads(r['data']) for r in rows]
        groups.sort(key=lambda n:(n['attributes']['level']!='overview',n['id']))
        return {'generation':generation,'node_id':node_id,'ancestors':[n['id'] for n in groups],'groups':groups}


def edge_support(generation,edge_id,offset=0,limit=50):
    with connect() as c:
        _metadata(c,generation)
        if not c.execute('SELECT 1 FROM graph_read_edges WHERE generation=? AND id=?',(generation,edge_id)).fetchone():
            raise GenerationError('Relationship is unavailable in this graph generation.')
        total = c.execute('SELECT COUNT(*) FROM graph_read_support WHERE generation=? AND edge_id=?',(generation,edge_id)).fetchone()[0]
        rows = c.execute("SELECT e.data FROM graph_read_support s JOIN graph_read_edges e ON e.generation=s.generation AND e.id=s.support_id AND e.level='detail' WHERE s.generation=? AND s.edge_id=? ORDER BY s.support_id LIMIT ? OFFSET ?",(generation,edge_id,limit,offset)).fetchall()
        if total == 0:
            rows = c.execute("SELECT data FROM graph_read_edges WHERE generation=? AND id=? AND level='detail' LIMIT ? OFFSET ?",(generation,edge_id,limit,offset)).fetchall()
            total = c.execute("SELECT COUNT(*) FROM graph_read_edges WHERE generation=? AND id=? AND level='detail'",(generation,edge_id)).fetchone()[0]
        return {'generation':generation,'edge_id':edge_id,'edges':[json.loads(r['data']) for r in rows],'total':total,'offset':offset,'has_more':offset+len(rows)<total}


def read_window(generation,level='overview',scope_id=None,max_nodes=800,query=None,focus_id=None,view='all',offset=0):
    if level not in {'overview','interfaces','detail'}: raise ValueError('Invalid graph level')
    if not 1 <= max_nodes <= 5000: raise ValueError('max_nodes must be between 1 and 5000')
    with connect() as c:
        meta = _metadata(c,generation)
        breadcrumbs=[]
        if scope_id:
            scope = c.execute("SELECT data FROM graph_read_nodes WHERE generation=? AND id=? AND level!='detail'",(generation,scope_id)).fetchone()
            if not scope: raise GenerationError('Graph scope is unavailable in this generation.')
            scope_node=json.loads(scope['data'])
            parent=scope_node['attributes'].get('parent_id')
            if parent:
                row=c.execute('SELECT data FROM graph_read_nodes WHERE generation=? AND id=?',(generation,parent)).fetchone()
                if row:
                    n=json.loads(row['data']); breadcrumbs.append({'id':n['id'],'name':n['name'],'level':n['attributes']['level']})
            breadcrumbs.append({'id':scope_id,'name':scope_node['name'],'level':scope_node['attributes']['level']})
        where=['n.generation=?','n.level=?']; args=[generation,level]
        if scope_id:
            if level=='detail':
                where.append('EXISTS (SELECT 1 FROM graph_read_members m WHERE m.generation=n.generation AND m.group_id=? AND m.node_id=n.id)'); args.append(scope_id)
            elif level=='interfaces':
                where.append('(n.parent_id=? OR n.id=?)'); args.extend([scope_id,scope_id])
            else:
                where.append('(n.id=? OR n.id=?)'); args.extend([scope_id,parent or scope_id])
        if query:
            where.append("instr(lower(n.name || ' ' || n.kind),lower(?))>0"); args.append(query)
        clause=' AND '.join(where)
        count=c.execute('SELECT COUNT(*) FROM graph_read_nodes n WHERE '+clause,args).fetchone()[0]
        rows=c.execute('SELECT n.data FROM graph_read_nodes n WHERE '+clause+' ORDER BY (n.id=?) DESC,n.id LIMIT ? OFFSET ?',[*args,focus_id or '',max_nodes,offset]).fetchall()
        nodes=[json.loads(r['data']) for r in rows]
        selected=[n['id'] for n in nodes]
        # A temporary indexed ID table avoids SQLite parameter limits for large windows.
        c.execute('CREATE TEMP TABLE selected_graph_nodes(id TEXT PRIMARY KEY)')
        c.executemany('INSERT INTO selected_graph_nodes VALUES(?)',((i,) for i in selected))
        boundary_count=0
        boundary_truncated=False
        if scope_id and selected and not query:
            boundary=c.execute('''WITH external_ids AS (
              SELECT target AS id FROM graph_read_edges INDEXED BY graph_read_source WHERE generation=? AND level=? AND source IN (SELECT id FROM selected_graph_nodes)
              UNION
              SELECT source AS id FROM graph_read_edges INDEXED BY graph_read_target WHERE generation=? AND level=? AND target IN (SELECT id FROM selected_graph_nodes)
            ) SELECT n.id,n.data FROM external_ids x JOIN graph_read_nodes n ON n.id=x.id AND n.generation=? AND n.level=?
              WHERE n.id NOT IN (SELECT id FROM selected_graph_nodes) ORDER BY n.id LIMIT ?''',(generation,level,generation,level,generation,level,max_nodes-len(nodes)+1)).fetchall()
            boundary_truncated=len(boundary)>max_nodes-len(nodes)
            boundary=boundary[:max_nodes-len(nodes)]
            for row in boundary:
                n=json.loads(row['data']); n['attributes']={**n.get('attributes',{}),'boundary':True}; nodes.append(n)
                c.execute('INSERT INTO selected_graph_nodes VALUES(?)',(n['id'],))
            boundary_count=len(boundary)
        edge_rows=c.execute('''SELECT data FROM graph_read_edges INDEXED BY graph_read_source WHERE generation=? AND level=?
          AND source IN (SELECT id FROM selected_graph_nodes) AND target IN (SELECT id FROM selected_graph_nodes)
          ORDER BY id LIMIT ?''',(generation,level,max_nodes*8+1)).fetchall()
        edges=[json.loads(r['data']) for r in edge_rows[:max_nodes*8]]
        projected=c.execute('SELECT COUNT(*) FROM graph_read_nodes WHERE generation=? AND level=?',(generation,level)).fetchone()[0]
        matches=[]
        if query:
            found=c.execute("SELECT data FROM graph_read_nodes WHERE generation=? AND level='detail' AND instr(lower(name || ' ' || kind),lower(?))>0 ORDER BY id LIMIT 30",(generation,query)).fetchall()
            for row in found:
                node=json.loads(row['data'])
                ancestors=c.execute("SELECT n.data FROM graph_read_members m JOIN graph_read_nodes n ON n.generation=m.generation AND n.id=m.group_id WHERE m.generation=? AND m.node_id=? ORDER BY n.level DESC,n.id",(generation,node['id'])).fetchall()
                groups=[json.loads(a['data']) for a in ancestors]
                matches.append({'node':node,'ancestors':[n['id'] for n in groups],'groups':groups})
        hidden_tests=meta.get('hidden_test_nodes',meta.get('counts',{}).get('hidden_test_nodes',0))
        return {**meta,'generation':generation,'granularity':level,'scope_id':scope_id,'breadcrumbs':breadcrumbs,'view':view,
                'nodes':nodes,'edges':edges,'search_matches':matches,'entrypoints':[n['id'] for n in nodes if n.get('attributes',{}).get('entrypoint')],
                'truncated':offset+len(selected)<count or len(edge_rows)>max_nodes*8 or boundary_truncated,'boundary_truncated':boundary_truncated,'offset':offset,'has_more':offset+len(selected)<count,
                'next_offset':offset+len(selected) if offset+len(selected)<count else None,
                'counts':{'total_nodes':meta['total_nodes'],'total_edges':meta['total_edges'],'projected_nodes':projected,'scope_nodes':count,
                          'visible_nodes':len(nodes),'visible_edges':len(edges),'boundary_nodes':boundary_count,
                          'hidden_nodes':max(0,meta['total_nodes']-len(nodes)),'hidden_test_nodes':hidden_tests,'outside_window_nodes':max(0,count-offset-len(selected))}}


def trace_generation(generation,entity_id,direction='both',max_depth=20,max_nodes=800,view='all'):
    """Bounded detailed traversal within one immutable generation.

    Structural membership is never a dependency. READS is stored consumer->data
    but traversed in the direction data can influence its consumer.
    """
    from collections import deque
    if direction not in {'in','out','both'}: raise ValueError('Invalid trace direction')
    if not 1 <= max_nodes <= 5000: raise ValueError('max_nodes must be between 1 and 5000')
    max_depth=max(0,min(int(max_depth),100))
    with connect() as c:
        meta=_metadata(c,generation)
        seed_rows=c.execute("SELECT id,data FROM graph_read_nodes WHERE generation=? AND level='detail' AND id=?",(generation,entity_id)).fetchall()
        if not seed_rows:
            seed_rows=c.execute("SELECT n.id,n.data FROM graph_read_members m JOIN graph_read_nodes n ON n.generation=m.generation AND n.id=m.node_id AND n.level='detail' WHERE m.generation=? AND m.group_id=? ORDER BY n.id LIMIT ?",(generation,entity_id,max_nodes+1)).fetchall()
        truncated=len(seed_rows)>max_nodes
        nodes={r['id']:json.loads(r['data']) for r in seed_rows[:max_nodes]}
        depths={nid:0 for nid in nodes}
        queue=deque(nodes)
        edges={}
        max_edges=max_nodes*8
        logical_source="CASE WHEN e.kind='READS' AND s.kind IN ('program','transformation','function','method') AND t.kind IN ('dataset','column','file') THEN e.target ELSE e.source END"
        # The edge kind lives in JSON to keep the storage schema generic.
        # Filter relevant adjacency first through source/target indexes.
        while queue:
            current=queue.popleft()
            depth=depths[current]
            remaining=max_edges-len(edges)
            if remaining<=0:
                truncated=True; break
            clauses=["e.generation=?", "e.level='detail'", '(e.source=? OR e.target=?)', "json_extract(e.data,'$.kind') NOT IN ('CONTAINS','HAS_COLUMN','DEFINES')"]
            args=[generation,current,current]
            source_expr=logical_source.replace('e.kind',"json_extract(e.data,'$.kind')")
            if direction=='out':
                clauses.append("(json_extract(e.data,'$.kind')='RESOLVES_TO' OR ("+source_expr+")=?)"); args.append(current)
            elif direction=='in':
                clauses.append("(json_extract(e.data,'$.kind')='RESOLVES_TO' OR ("+source_expr+")<>?)"); args.append(current)
            # Separate indexed directions: a single OR with ORDER BY makes
            # SQLite scan the entire generation on otherwise sparse graphs.
            adjacent={}
            for side,index in (('source','graph_read_source'),('target','graph_read_target')):
                sql="SELECT e.id,e.data,e.source,e.target FROM graph_read_edges e INDEXED BY "+index+" JOIN graph_read_nodes s ON s.generation=e.generation AND s.level='detail' AND s.id=e.source JOIN graph_read_nodes t ON t.generation=e.generation AND t.level='detail' AND t.id=e.target WHERE "+' AND '.join(clauses)+" AND e."+side+"=? ORDER BY e.id LIMIT ?"
                for row in c.execute(sql,[*args,current,remaining+1]):
                    adjacent[row['id']]=row
            rows=[adjacent[key] for key in sorted(adjacent)]
            if len(rows)>remaining: truncated=True
            for row in rows[:remaining]:
                edge=json.loads(row['data'])
                other=row['target'] if row['source']==current else row['source']
                if other not in nodes:
                    if depth>=max_depth or len(nodes)>=max_nodes:
                        truncated=True; continue
                    node=c.execute("SELECT data FROM graph_read_nodes WHERE generation=? AND level='detail' AND id=?",(generation,other)).fetchone()
                    if not node: continue
                    nodes[other]=json.loads(node['data']); depths[other]=depth+1; queue.append(other)
                edges[edge['id']]=edge
        resolved={e['source'] for e in edges.values() if e['kind']=='RESOLVES_TO'}
        import re
        gaps=[]
        for node in nodes.values():
            if node['kind']=='dataset' and node.get('expression') and node['id'] not in resolved and re.search(r'&\w+|\{[^}]+\}|\$\{?\w+',str(node['expression'])):
                # A bounded trace may omit an alias; check identity directly.
                alias=c.execute("SELECT 1 FROM graph_read_edges WHERE generation=? AND level='detail' AND source=? AND json_extract(data,'$.kind')='RESOLVES_TO' LIMIT 1",(generation,node['id'])).fetchone()
                if not alias:
                    gaps.append({'entity_id':node['id'],'name':node['name'],'expression':node['expression'],'reason':'unresolved symbolic dataset reference','evidence':node.get('evidence',[])})
        return {'generation':generation,'entity_id':entity_id,'direction':direction,'nodes':list(nodes.values()),'edges':list(edges.values()),
                'unresolved_gaps':gaps,'truncated':truncated,'max_depth':max_depth,'graph_version':meta.get('version',generation),
                'warnings':meta.get('warnings',[]),'snapshots':meta.get('snapshots',[]),'view':view,'granularity':'detail',
                'hidden_test_nodes':meta.get('hidden_test_nodes',0)}
