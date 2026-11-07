import unittest
from graphifier.extraction import extract_file


class ColumnLineageTests(unittest.TestCase):
    def test_sql_aliases_functions_filters_and_insert(self):
        result = extract_file('job.sql', "INSERT INTO mart.totals (total) SELECT coalesce(a.amount, 0) * b.rate AS value FROM raw.orders a JOIN raw.rates b ON a.currency = b.currency WHERE a.active = 1;")
        entities = {e['id']: e for e in result['entities']}
        columns = [e for e in entities.values() if e['kind'] == 'column']
        self.assertTrue(any(e['name'] == 'total' for e in columns))
        self.assertFalse(any(e['name'] in {'a', 'b', 'coalesce'} for e in columns))
        roles = {r.get('attributes', {}).get('role') for r in result['relationships'] if r['kind'] == 'INPUT_TO'}
        self.assertTrue({'value', 'filter', 'join'} <= roles)
        amounts = [e for e in columns if e['name'] == 'amount']
        self.assertEqual(entities[amounts[0]['attributes']['parent_dataset_id']]['name'], 'raw.orders')

    def test_ambiguous_sql_columns_and_nested_queries(self):
        result = extract_file('job.sql', 'CREATE TABLE target AS SELECT amount FROM a JOIN b ON a.id = b.id;')
        self.assertTrue(any('ambiguous' in w for w in result['warnings']))
        self.assertFalse(any(e['kind'] == 'column' and e['name'] == 'amount' and e['attributes']['parent_dataset_id'] != next(x['id'] for x in result['entities'] if x['name'] == 'target') for e in result['entities']))
        nested = extract_file('job.sql', 'CREATE TABLE target AS SELECT x FROM (SELECT x FROM a) sub;')
        self.assertTrue(any('nested/compound' in w for w in nested['warnings']))

    def test_dataframe_file_column_flow(self):
        source = "import pandas as pd\ndf = pd.read_csv('input.csv')\ndf['total'] = df['amount'] * df['rate']\ndf.to_csv('output.csv')\n"
        result = extract_file('job.py', source)
        entities = {e['id']: e for e in result['entities']}
        input_id = next(e['id'] for e in entities.values() if e['name'] == 'input.csv')
        output_id = next(e['id'] for e in entities.values() if e['name'] == 'output.csv')
        self.assertTrue(any(e['kind'] == 'column' and e['name'] == 'amount' and e['attributes']['parent_dataset_id'] == input_id for e in entities.values()))
        self.assertTrue(any(e['kind'] == 'column' and e['name'] == 'total' and e['attributes']['parent_dataset_id'] == output_id for e in entities.values()))
        self.assertTrue(any(r['kind'] == 'READS' and r['target'] == input_id for r in result['relationships']))
        self.assertTrue(any(r['kind'] == 'WRITES' and r['target'] == output_id for r in result['relationships']))

    def test_sql_evidence_leading_newlines(self):
        result = extract_file('job.sql', '\n\nCREATE TABLE b AS SELECT x FROM a;')
        self.assertTrue(all(e['evidence']['start_line'] == 3 for e in result['entities'] if e['kind'] == 'column'))
