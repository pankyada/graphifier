"""Deterministic, evidence-backed hierarchy over an immutable detailed graph."""
from collections import defaultdict
from pathlib import PurePosixPath
import hashlib
import json
import re
import math

VERSION = 'hierarchy-ai-6'
STRUCTURAL_EDGES = {'CONTAINS', 'DEFINES', 'HAS_COLUMN', 'RESOLVES_TO'}
SUMMARY_SAMPLE_LIMIT = 12
LARGE_ENTITY_THRESHOLD = 300
LARGE_PROGRAM_THRESHOLD = 30


def _id(*parts):
    return 'group:' + hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:24]


def _repository_scope(node, graph):
    return tuple(sorted(node.get('repositories') or [graph.get('repo_id') or 'workspace']))


def _scope_sizes(graph):
    counts = defaultdict(lambda: [0, 0])
    for node in graph['nodes']:
        key = json.dumps(_repository_scope(node, graph))
        counts[key][0] += 1
        counts[key][1] += node['kind'] == 'program'
    sizes = {key: count[0] > LARGE_ENTITY_THRESHOLD or count[1] > LARGE_PROGRAM_THRESHOLD for key, count in counts.items()}
    sizes.update(graph.get('hierarchy_scope_sizes', {}))
    return sizes


def classify_context(node):
    explicit = node.get('attributes', {}).get('context')
    if explicit in {'test', 'production', 'mixed'}:
        return explicit, 'declared-context'
    paths = [ev.get('file', '') for ev in node.get('evidence', [])]
    if not any(paths):
        paths.append(str(node.get('attributes', {}).get('path', '')))
    if node.get('attributes', {}).get('test_framework') or node.get('attributes', {}).get('is_test') is True:
        return 'test', 'test-declaration'
    paths = [p for p in paths if p]
    def is_test(path):
        parts = PurePosixPath(path.lower()).parts
        return any(p in {'test', 'tests', '__tests__'} for p in parts) or bool(re.search(r'(^conftest\.py$|_spec\.rb$|^test_.*\.py$|_test\.py$|[.](test|spec)[.][^/]+$|_test\.go$)', parts[-1] if parts else ''))
    flags = [is_test(p) for p in paths]
    return ('mixed' if any(flags) and not all(flags) else 'test' if any(flags) else 'production' if paths else 'unknown'), 'source-path' if paths else 'unclassified'


def filter_graph_context(graph, include_tests=False):
    nodes = []
    hidden = 0
    for node in graph['nodes']:
        context, basis = classify_context(node)
        if context == 'test' and not include_tests:
            hidden += 1
            continue
        nodes.append({**node, 'attributes': {**node.get('attributes', {}), 'context': context, 'context_basis': basis}})
    ids = {n['id'] for n in nodes}
    edges = []
    for edge in graph['edges']:
        if edge['source'] not in ids or edge['target'] not in ids:
            continue
        if not include_tests and classify_context(edge)[0] == 'test':
            continue
        if not include_tests:
            edge = {**edge, 'evidence': [ev for ev in edge.get('evidence', []) if classify_context({'evidence': [ev]})[0] != 'test']}
        edges.append(edge)
    return {**graph, 'nodes': nodes, 'edges': edges,
            'hidden_test_nodes': hidden, 'include_tests': include_tests, 'hierarchy_scope_sizes': _scope_sizes(graph)}


def build_hierarchy(graph, proposal=None):
    nodes = {n['id']: n for n in graph['nodes']}
    groups, ancestors, memberships = {}, {}, []
    modules = defaultdict(list)
    def repo(n):
        return _repository_scope(n, graph)
    for n in nodes.values():
        if n['kind'] == 'module':
            modules[repo(n)].append(n)
    def group(key, name, level, parent, basis, repositories):
        gid = _id(*key)
        if gid not in groups:
            groups[gid] = {'id': gid, 'kind': 'architecture' if level == 'overview' else 'component',
                'name': name, 'attributes': {'level': level, 'parent_id': parent, 'basis': basis,
                'member_count': 0, 'summary': '', 'method': 'deterministic-grouping'},
                'evidence': [], 'repositories': list(repositories)}
        return gid
    scope_sizes = _scope_sizes(graph)
    for nid, n in sorted(nodes.items()):
        repositories = repo(n)
        large = scope_sizes.get(json.dumps(repositories), False)
        ev = n.get('evidence') or []
        path = str(n.get('attributes', {}).get('path') if n['kind'] == 'module' else (ev[0].get('file', '') if ev else '') or n.get('attributes', {}).get('path') or '')
        # Shared resources retain a single identity and a separate navigable group.
        shared = len(repositories) > 1
        candidates = [m for m in modules[repositories] if str(m.get('attributes', {}).get('path', '.')) == '.' or path == m.get('attributes', {}).get('path') or path.startswith(str(m.get('attributes', {}).get('path', '')) + '/')]
        module = max(candidates, key=lambda m: len(m.get('attributes', {}).get('path', '')), default=None)
        parts = PurePosixPath(path).parts
        boundary = (parts[0] if len(parts) > 1 else 'root') if path else 'unclassified'
        module_path = str(module.get('attributes', {}).get('path', '.')) if module else '.'
        manifest_boundary = module is not None and module_path not in {'.', '', '/'}
        if manifest_boundary:
            boundary = module_path
        elif len(parts) > 2 and parts[0] in {'src', 'lib', 'packages', 'services', 'apps'}:
            boundary = '/'.join(parts[:2])
        if shared:
            boundary = 'shared-resources'
        aid = group(('architecture', repositories, boundary), boundary.replace('-', ' ').replace('_', ' ').title(), 'overview', None,
                    'shared-resource' if shared else 'manifest' if manifest_boundary else 'directory' if path else 'unclassified', repositories)
        component_key = module['id'] if module else str(PurePosixPath(path).parent) if path else 'unclassified'
        if large and path and n['kind'] != 'module':
            component_key = path
        elif module_path in {'.', '', '/'}:
            component_key = path if large and path else str(PurePosixPath(path).parent) if path else 'unclassified'
        cname = module['name'] if module and module_path not in {'.', '', '/'} and not large else component_key if component_key != '.' else 'Root implementation'
        cid = group(('component', repositories, boundary, component_key), cname, 'interfaces', aid,
                    'manifest' if module else 'directory' if path else 'unclassified', repositories)
        ancestors[nid] = [aid, cid]
        for gid in (aid, cid):
            memberships.append({'group_id': gid, 'node_id': nid})
            groups[gid]['attributes']['member_count'] += 1
            for span in ev:
                if len(groups[gid]['evidence']) < 3 and span not in groups[gid]['evidence']:
                    groups[gid]['evidence'].append(span)
    overlays = {}
    if proposal:
        overlays = _apply_proposal(proposal, nodes, groups, ancestors)
        memberships = []
        active = {gid for chain in ancestors.values() for gid in chain}
        groups = {gid: group for gid, group in groups.items() if gid in active}
        for group in groups.values():
            group['attributes']['member_count'] = 0
            group['evidence'] = []
        for nid, chain in ancestors.items():
            for gid in chain:
                memberships.append({'group_id': gid, 'node_id': nid})
                groups[gid]['attributes']['member_count'] += 1
                for span in nodes[nid].get('evidence', []):
                    if len(groups[gid]['evidence']) < 3 and span not in groups[gid]['evidence']:
                        groups[gid]['evidence'].append(span)
    rollups, support_sets = {}, defaultdict(set)
    for e in graph['edges']:
        if e['kind'] in STRUCTURAL_EDGES:
            continue
        if e['source'] not in ancestors or e['target'] not in ancestors:
            continue
        for i, level in enumerate(('overview', 'interfaces')):
            source, target = ancestors[e['source']][i], ancestors[e['target']][i]
            if source == target:
                continue
            # Import spellings and reference IDs identify supporting occurrences,
            # not different architecture dependencies. Preserve them on the
            # detailed support edges while retaining roles/conditions here.
            attrs = {k: v for k, v in e.get('attributes', {}).items()
                     if k not in {'source_ids', 'source_methods', 'module', 'via_reference', 'source_id'}}
            key = json.dumps([level, source, target, e['kind'], attrs], sort_keys=True)
            if key not in rollups:
                rollups[key] = {'id': _id('rollup', key), 'source': source, 'target': target, 'kind': e['kind'],
                    'attributes': {**attrs, 'level': level, 'derived': True, 'support_edge_ids': [], 'support_count': 0},
                    'evidence': [], 'repositories': sorted(set(groups[source]['repositories'] + groups[target]['repositories']))}
            r = rollups[key]
            if e['id'] not in support_sets[key]:
                support_sets[key].add(e['id'])
                r['attributes']['support_edge_ids'].append(e['id'])
                r['attributes']['support_count'] += 1
    structured = {gid: {'inputs': {}, 'outputs': {}, 'dependencies': {}, 'behaviour': defaultdict(int), 'unknowns': [], 'descriptions': []} for gid in groups}
    for nid, chain in ancestors.items():
        n = nodes[nid]
        for gid in chain:
            if n.get('attributes', {}).get('description') and n['kind'] == 'module':
                structured[gid]['descriptions'].append(str(n['attributes']['description']))
            if n['kind'] in {'unresolved', 'symbol'}:
                structured[gid]['unknowns'].append({'id': nid, 'name': n['name']})
    for e in graph['edges']:
        if e['kind'] in STRUCTURAL_EDGES:
            continue
        if e['source'] not in ancestors or e['target'] not in ancestors:
            continue
        for i in (0, 1):
            source, target = ancestors[e['source']][i], ancestors[e['target']][i]
            structured[source]['behaviour'][e['kind']] += 1
            if source == target:
                continue
            item_target = {'id': e['target'], 'name': nodes[e['target']]['name'], 'kind': e['kind']}
            item_source = {'id': e['source'], 'name': nodes[e['source']]['name'], 'kind': e['kind']}
            if e['kind'] in {'WRITES', 'PRODUCES', 'TRANSFERS'}:
                structured[source]['outputs'][e['target']] = item_target
                structured[target]['inputs'][e['source']] = item_source
            elif e['kind'] in {'INPUT_TO'}:
                structured[target]['inputs'][e['source']] = item_source
            elif e['kind'] in {'READS', 'DERIVES_FROM'}:
                structured[source]['inputs'][e['target']] = item_target
            else:
                structured[source]['dependencies'][e['target']] = item_target
    group_contexts, child_counts = defaultdict(list), defaultdict(int)
    for nid, chain in ancestors.items():
        context = classify_context(nodes[nid])[0]
        for gid in chain:
            group_contexts[gid].append(context)
    for g in groups.values():
        child_counts[g['attributes']['parent_id']] += 1
    for g in groups.values():
        contexts = group_contexts[g['id']]
        g['attributes']['context'] = contexts[0] if len(set(contexts)) == 1 else 'mixed'
        g['attributes']['context_basis'] = 'member-contexts'
        g['attributes']['test_member_count'] = contexts.count('test')
        info = structured[g['id']]
        for key in ('inputs', 'outputs', 'dependencies'):
            values = sorted(info[key].values(), key=lambda x: x['id'])
            g['attributes'][key + '_count'] = len(values)
            g['attributes'][key + '_truncated'] = len(values) > SUMMARY_SAMPLE_LIMIT
            g['attributes'][key] = values[:SUMMARY_SAMPLE_LIMIT]
        g['attributes']['behaviour'] = dict(sorted(info['behaviour'].items()))
        g['attributes']['unknowns'] = info['unknowns'][:SUMMARY_SAMPLE_LIMIT]
        g['attributes']['unknowns_count'] = len(info['unknowns'])
        g['attributes']['unknowns_truncated'] = len(info['unknowns']) > SUMMARY_SAMPLE_LIMIT
        phrases = []
        for key, verb in (('inputs', 'Reads'), ('outputs', 'Produces'), ('dependencies', 'Depends on')):
            values = g['attributes'][key]
            if values:
                phrases.append(verb + ' ' + ', '.join(x['name'] for x in values[:3]) + (f" and {g['attributes'][key + '_count']-3} more" if g['attributes'][key + '_count']>3 else ''))
        summary = '. '.join(dict.fromkeys(info['descriptions'] + phrases))
        g['attributes']['summary'] = summary or f"Contains {g['attributes']['member_count']} detailed entities; no cross-boundary behaviour identified."
        g['attributes']['child_count'] = child_counts[g['id']] if g['kind'] == 'architecture' else g['attributes']['member_count']
    for gid, overlay in overlays.items():
        if gid in groups:
            groups[gid]['name'] = overlay.pop('name')
            groups[gid]['attributes']['observed_summary'] = groups[gid]['attributes']['summary']
            groups[gid]['attributes'].update(overlay)
            # Show the source spans actually cited by the inference.
            cited_spans = []
            for nid in overlay.get('cited_node_ids', []):
                for span in nodes[nid].get('evidence', []):
                    if span not in cited_spans:
                        cited_spans.append(span)
            groups[gid]['attributes']['ai_evidence_count'] = len(cited_spans)
            groups[gid]['evidence'] = cited_spans[:12]
    meaningful = any(g['attributes']['child_count'] > 1 for g in groups.values() if g['kind'] == 'architecture')
    return {'version': VERSION, 'groups': list(groups.values()), 'memberships': memberships,
            'rollup_edges': list(rollups.values()), 'ancestors': ancestors,
            'recommended_levels': ['overview', 'interfaces', 'detail'] if meaningful else ['overview', 'detail']}



def _apply_proposal(proposal, nodes, groups, ancestors):
    """Apply only cited memberships; never create or merge detailed entities."""
    components = {gid: g for gid, g in groups.items() if g['kind'] == 'component'}
    known_components = set(components) | set(proposal.get('validated_component_ids', []))
    known_nodes = set(nodes) | set(proposal.get('validated_node_ids', []))
    assigned, summary_assigned, overlays = set(), set(), {}
    members = defaultdict(set)
    for nid, chain in ancestors.items():
        members[chain[1]].add(nid)
    def validate(item, cids):
        if not cids or len(cids) != len(set(cids)) or any(cid not in known_components for cid in cids):
            raise ValueError('AI grouping contains unknown or duplicate component IDs')
        citations = item.get('evidence_node_ids', [])
        if not citations or len(citations) != len(set(citations)) or any(nid not in known_nodes for nid in citations):
            raise ValueError('AI summary requires unique existing evidence nodes')
        visible = [cid for cid in cids if cid in components]
        visible_members = set().union(*(members[cid] for cid in visible)) if visible else set()
        if any(nid in nodes and nid not in visible_members for nid in citations):
            raise ValueError('AI evidence must belong to proposed components')
        if visible and not any(nid in visible_members for nid in citations):
            raise ValueError('AI summary has no visible supporting evidence')
        repos = {tuple(sorted(components[cid].get('repositories', []))) for cid in visible}
        if len(repos) > 1:
            raise ValueError('AI grouping cannot span repository scopes')
        contexts = {classify_context(nodes[nid])[0] for nid in visible_members}
        if 'test' in contexts and ('production' in contexts or 'mixed' in contexts):
            raise ValueError('AI grouping cannot mix production and test contexts')
        confidence = item.get('confidence')
        if isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('AI confidence must be between zero and one')
        for field in ('name', 'summary', 'rationale'):
            if not isinstance(item.get(field), str) or not item[field].strip() or len(item[field]) > 4000:
                raise ValueError('AI grouping requires bounded name, summary and rationale')
        return visible, {'name': item['name'], 'summary': item['summary'], 'ai_summary': item['summary'],
            'rationale': item['rationale'], 'confidence': confidence, 'model': item.get('origin_model') or proposal.get('model'),
            'prompt_version': item.get('origin_prompt_version') or proposal.get('prompt_version'), 'cited_node_ids': [nid for nid in citations if nid in nodes],
            'provenance': 'model-inferred', 'method': 'model-inferred'}
    for item in proposal.get('groups', []):
        cids = item.get('component_ids', [])
        visible, overlay = validate(item, cids)
        if assigned.intersection(cids):
            raise ValueError('AI component assigned to multiple architecture groups')
        assigned.update(cids)
        if not visible:
            continue
        gid = _id('ai-architecture', sorted(cids))
        groups[gid] = {'id': gid, 'name': overlay['name'], 'kind': 'architecture', 'repositories': components[visible[0]].get('repositories', []),
            'evidence': [], 'attributes': {'level': 'overview', 'parent_id': None, 'basis': 'model-inferred', 'member_count': 0}}
        for cid in visible:
            components[cid]['attributes']['parent_id'] = gid
            for nid in members[cid]:
                ancestors[nid][0] = gid
        overlays[gid] = overlay
    for item in proposal.get('component_summaries', []):
        cid = item.get('component_id')
        visible, overlay = validate(item, [cid])
        if cid in summary_assigned:
            raise ValueError('Duplicate AI component summary')
        summary_assigned.add(cid)
        if visible:
            overlays[cid] = overlay
    return overlays


def project_hierarchy(graph, hierarchy, granularity, scope_id=None):
    if granularity not in {'overview', 'interfaces', 'detail'}:
        raise ValueError('Unknown hierarchy level')
    groups = {n['id']: n for n in hierarchy['groups']}
    if scope_id and scope_id not in groups:
        raise ValueError('Unknown hierarchy scope')
    ancestors = hierarchy['ancestors']
    members = {nid for nid, chain in ancestors.items() if not scope_id or scope_id in chain}
    if granularity == 'detail':
        chosen = {n['id']: n for n in graph['nodes'] if n['id'] in members}
        edges = []
        # External endpoints are represented by their component, preserving support.
        for e in graph['edges']:
            if e['source'] not in members and e['target'] not in members:
                continue
            if e['source'] in members and e['target'] in members:
                edges.append(e)
                continue
            mapped = dict(e)
            for side in ('source', 'target'):
                nid = e[side]
                if nid not in members and nid in ancestors:
                    gid = ancestors[nid][-1]
                    chosen[gid] = groups[gid]
                    mapped[side] = gid
            if mapped['source'] in chosen and mapped['target'] in chosen:
                mapped['attributes'] = {**e.get('attributes', {}), 'support_edge_ids': [e['id']], 'support_count': 1, 'derived': True}
                edges.append(mapped)
    else:
        index = 0 if granularity == 'overview' else 1
        ids = {ancestors[nid][index] for nid in members}
        chosen = {gid: groups[gid] for gid in ids}
        edges = []
        for e in hierarchy['rollup_edges']:
            if e['attributes']['level'] == granularity and (e['source'] in ids or e['target'] in ids):
                chosen[e['source']] = groups[e['source']]
                chosen[e['target']] = groups[e['target']]
                edges.append(e)
    breadcrumbs = []
    current = scope_id
    while current:
        breadcrumbs.insert(0, {'id': current, 'name': groups[current]['name'], 'level': groups[current]['attributes']['level']})
        current = groups[current]['attributes']['parent_id']
    return {**graph, 'nodes': list(chosen.values()), 'edges': edges, 'granularity': granularity,
            'scope_id': scope_id, 'breadcrumbs': breadcrumbs, 'recommended_levels': hierarchy['recommended_levels'],
            'counts': {'total_nodes': len(graph['nodes']), 'total_edges': len(graph['edges']), 'visible_nodes': len(chosen), 'visible_edges': len(edges), 'scope_members': len(members)}}
