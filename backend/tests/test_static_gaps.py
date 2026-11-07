import unittest
from graphifier.extraction import extract_file


class StaticGapTests(unittest.TestCase):
    def test_ambiguous_gap_statement_evidence_and_candidates(self):
        source = '\nCREATE TABLE target AS\nSELECT amount, rate\nFROM raw.a a JOIN raw.b b ON a.id=b.id;\n'
        result = extract_file('job.sql', source)
        gaps = [g for g in result['gaps'] if g['kind'] == 'ambiguous_column']
        self.assertEqual(len(gaps), 2)
        self.assertEqual(len({g['id'] for g in gaps}), 2)
        for gap in gaps:
            self.assertEqual(gap['evidence'], {'file':'job.sql','start_line':2,'end_line':4})
            self.assertEqual(gap['expression'], '\n'.join(source.splitlines()[1:4]))
            self.assertEqual({c['name'] for c in gap['candidates']}, {'raw.a','raw.b'})
            self.assertIn(gap['message'], result['warnings'])
        self.assertEqual(result['gaps'], extract_file('job.sql', source)['gaps'])

    def test_wildcard_and_nested_queries(self):
        wildcard = extract_file('job.sql', 'SELECT a.* FROM raw.a a;')['gaps'][0]
        self.assertEqual(wildcard['kind'], 'wildcard')
        self.assertEqual(wildcard['candidates'][0]['name'], 'raw.a')
        nested = extract_file('job.sql', 'SELECT x FROM (SELECT x FROM a) sub;')['gaps'][0]
        self.assertEqual(nested['kind'], 'nested_query')

    def test_declared_schema_columns_exact_lines(self):
        source = '\nCREATE TABLE raw.a (\n amount decimal(18,2),\n currency varchar(3),\n CONSTRAINT pk PRIMARY KEY (currency)\n);'
        result = extract_file('schema.ddl', source)
        columns = [e for e in result['entities'] if e['kind'] == 'column']
        self.assertEqual({e['name'] for e in columns}, {'amount','currency'})
        self.assertEqual({e['evidence']['start_line'] for e in columns}, {3,4})
        self.assertTrue(all(e['attributes']['declared'] for e in columns))
        self.assertEqual(len([r for r in result['relationships'] if r['kind'] == 'HAS_COLUMN']), 2)

    def test_python_dynamic_call_exact_evidence(self):
        result = extract_file('job.py', '\n# exec(fake)\nresult = eval(\n    query\n)\n')
        self.assertEqual(len(result['gaps']), 1)
        gap = result['gaps'][0]
        self.assertEqual(gap['kind'], 'python_dynamic')
        self.assertEqual(gap['evidence']['start_line'], 3)
        self.assertEqual(gap['evidence']['end_line'], 5)

    def test_sas_gap_and_proc_sql_lines(self):
        source = 'data result;\n merge raw.a raw.b;\n amount = price * rate;\nrun;'
        gap = extract_file('job.sas', source)['gaps'][0]
        self.assertEqual(gap['kind'], 'sas_ambiguous_column')
        self.assertEqual(gap['evidence']['start_line'], 3)
        self.assertEqual(gap['evidence']['end_line'], 3)
        sql = extract_file('job.sas', 'proc sql;\nselect * from raw.a;\nquit;')['gaps'][0]
        self.assertEqual(sql['evidence']['start_line'], 2)
