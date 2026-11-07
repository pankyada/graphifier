"""Conservative repository review with reversible source identity mappings."""
import copy
import json


def _unique(items):
    return list({json.dumps(item, sort_keys=True): item for item in items}.values())


def consolidate_findings(entities, relationships):
    groups, mapping, warnings = {}, {}, []
    for source in entities:
        item = copy.deepcopy(source)
        attrs = item.get('attributes') or {}
        evidence = item.get('evidence') or {}
        # Exact source location and module are required even for qualified names.
        # Invocation-dependent names must remain separate across source locations.
        semantic_attrs = {k: v for k, v in attrs.items() if k not in {'method', 'source_methods', 'source_ids'}}
        key = json.dumps([item.get('kind'), item.get('name'), item.get('expression'),
                          semantic_attrs, evidence], sort_keys=True)
        existing = groups.get(key)
        if existing is None:
            existing = item
            existing.setdefault('attributes', {})['source_ids'] = [item['id']]
            existing['evidence_spans'] = item.get('evidence_spans') or ([evidence] if evidence else [])
            groups[key] = existing
        else:
            existing['attributes']['source_ids'].append(item['id'])
            existing['evidence_spans'] = _unique(existing['evidence_spans'] + item.get('evidence_spans', []) + ([evidence] if evidence else []))
            methods = set(existing['attributes'].get('source_methods', [existing['attributes'].get('method', 'static')]))
            methods.update(attrs.get('source_methods', [attrs.get('method', 'static')]))
            existing['attributes']['source_methods'] = sorted(methods)
        mapping[item['id']] = existing['id']
    edges = {}
    for source in relationships:
        item = copy.deepcopy(source)
        if item.get('source') not in mapping or item.get('target') not in mapping:
            warnings.append('Consolidation excluded a relationship with an unknown endpoint')
            continue
        item['source'], item['target'] = mapping[item['source']], mapping[item['target']]
        attrs = item.get('attributes') or {}
        # Preserve role and condition differences rather than erasing semantics.
        semantic_attrs = {k: v for k, v in attrs.items() if k not in {'method', 'source_methods'}}
        key = json.dumps([item['source'], item['target'], item.get('kind'), semantic_attrs], sort_keys=True)
        evidence = item.get('evidence') or {}
        spans = item.get('evidence_spans') or ([evidence] if evidence else [])
        if key in edges:
            edges[key]['evidence_spans'] = _unique(edges[key]['evidence_spans'] + spans)
            previous_attrs = edges[key].setdefault('attributes', {})
            methods = set(previous_attrs.get('source_methods', [previous_attrs.get('method', 'static')]))
            methods.update(attrs.get('source_methods', [attrs.get('method', 'static')]))
            previous_attrs['source_methods'] = sorted(methods)
        else:
            item['evidence_spans'] = spans
            edges[key] = item
    return {'entities': list(groups.values()), 'relationships': list(edges.values()), 'warnings': sorted(set(warnings)),
            'summary': {'input_entities': len(entities), 'output_entities': len(groups),
                        'input_relationships': len(relationships), 'output_relationships': len(edges),
                        'id_mapping': mapping}}
