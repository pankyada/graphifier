import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphifier.db import connect, init_db
from graphifier import embeddings


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"GRAPHIFIER_DB": str(Path(self.tmp.name)/"test.db"), "GRAPHIFIER_EMBEDDING_MODEL": "test", "GRAPHIFIER_EMBEDDING_BATCH_SIZE": "1"})
        self.env.start()
        init_db()
        with connect() as c:
            c.execute("INSERT INTO repositories(id,name,path,created_at) VALUES('r','r','/r','1')")
            c.execute("INSERT INTO jobs(id,repo_id,status,environment,created_at,updated_at) VALUES('j','r','completed','dev','1','1')")
            c.execute("INSERT INTO snapshots VALUES('s','r','j',NULL,'h','1')")
            c.execute("INSERT INTO source_files VALUES('r','s','a.py','hello\nworld','h')")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_chunks_preserve_content_and_line_ranges(self):
        content = 'abc\n' + 'x'*9000 + '\nend'
        result = list(embeddings.chunks(content))
        self.assertEqual(''.join(x['content'] for x in result), content)
        self.assertTrue(all(len(x['content']) <= 4000 for x in result))
        self.assertEqual(result[-1]['end_line'], 3)

    @patch('graphifier.embeddings._embed', return_value=[[1.0, 0.0]])
    def test_scoped_search_and_stale_snapshot(self, embed):
        embeddings.index_snapshot('r','s')
        self.assertEqual(embeddings.status('r','dev')['indexed_chunks'],1)
        self.assertEqual(embeddings.search('hello','r','dev')['matches'][0]['score'],1.0)
        self.assertEqual(embeddings.search('hello','r','prod')['matches'],[])
        with connect() as c:
            c.execute("INSERT INTO jobs(id,repo_id,status,environment,created_at,updated_at) VALUES('j2','r','completed','dev','2','2')")
            c.execute("INSERT INTO snapshots VALUES('s2','r','j2',NULL,'h','2')")
        self.assertEqual(embeddings.search('hello','r','dev')['matches'],[])

    @patch('graphifier.embeddings._embed', side_effect=RuntimeError('provider failed'))
    def test_failure_never_publishes_partial_index(self, embed):
        with self.assertRaises(RuntimeError):
            embeddings.index_snapshot('r','s')
        self.assertEqual(embeddings.status()['indexed_chunks'],0)
        with connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM code_chunks').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT status FROM embedding_indexes').fetchone()[0],'failed')

    def test_cancel_before_remote_call(self):
        with patch('graphifier.embeddings._embed') as embed:
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                embeddings.index_snapshot('r','s',cancelled=lambda: True)
            embed.assert_not_called()

    def test_migration_is_repeatable(self):
        init_db()
        with connect() as c:
            self.assertEqual(c.execute('SELECT use_embeddings FROM jobs').fetchone()[0],0)
