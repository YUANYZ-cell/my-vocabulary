import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from vocabulary.database import Database
from vocabulary.items import ItemRepository, DuplicateItemError, ValidationError
from vocabulary.groups import ConfusionGroupRepository
from vocabulary.reviews import ReviewRepository
from vocabulary.csv_io import CsvService
from vocabulary.http_app import create_server


class AcademicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name)/'test.db')
        self.db.initialize()
        self.items = ItemRepository(self.db)
        self.groups = ConfusionGroupRepository(self.db, self.items)
        self.reviews = ReviewRepository(self.db, self.items, self.groups)
        self.day = date.today()

    def add(self, collection='general', term='entropy', item_type='word'):
        return self.items.create_item(dict(term=term, chinese_meaning='熵', collection=collection,
            item_type=item_type, source='热力学' if collection=='academic' else 'Reading'), self.day-timedelta(days=2))

    def test_same_word_independent_storage_restart_edit_and_facets(self):
        general = self.add()
        academic = self.add('academic')
        self.assertNotEqual(general['id'], academic['id'])
        with self.assertRaises(DuplicateItemError): self.add('academic')
        self.db.initialize()
        self.assertEqual(self.items.list_items()['items'][0]['id'], general['id'])
        self.assertEqual(self.items.list_items({'collection':'academic'})['items'][0]['id'], academic['id'])
        self.items.update_item(academic['id'], {'notes':'第二章'})
        self.assertEqual(self.items.get_item(academic['id'])['collection'], 'academic')
        self.assertEqual(self.items.facets()['sources'], ['Reading'])
        self.assertEqual(self.items.facets('academic')['sources'], ['热力学'])
        with self.assertRaises(ValidationError): self.items.list_items({'collection':'unknown'})
        with self.assertRaises(ValidationError): self.items.update_item(academic['id'], {'collection':'general'})

    def test_aggregate_library_separates_short_entries_from_sentences(self):
        expected = []
        sentences = []
        for collection in ('general', 'academic'):
            expected.append(self.add(collection)['id'])
            expected.append(self.add(collection, 'thermal equilibrium', 'phrase')['id'])
            sentences.append(self.add(collection, 'The system reaches a state of thermal equilibrium.', 'sentence')['id'])
        result = self.items.list_items({'collection': 'all', 'item_group': 'vocabulary'})
        self.assertEqual({item['id'] for item in result['items']}, set(expected))
        result = self.items.list_items({'collection': 'all', 'item_group': 'sentence'})
        self.assertEqual({item['id'] for item in result['items']}, set(sentences))
        facets = self.items.facets('all')
        self.assertEqual(facets['group_counts'], {'vocabulary': 4, 'sentence': 2})
        self.assertEqual(facets['collection_counts'], {'general': 3, 'academic': 3})
        self.assertEqual(facets['sources'], ['Reading', '热力学'])
        # Aggregation is a view: existing storage and review boundaries stay explicit.
        with self.assertRaises(ValidationError): self.add('all')
        with self.assertRaises(ValidationError): self.reviews.get_queue('recent', self.day, collection='all')

    def test_aggregate_search_sort_and_pagination_filter_before_limiting(self):
        a = self.add('general', 'zebra')
        b = self.add('academic', 'alpha')
        c = self.add('general', 'beta')
        self.add('academic', 'The system reaches a state of thermal equilibrium.', 'sentence')
        params = {'collection': 'all', 'item_group': 'vocabulary', 'sort': 'term_asc', 'page_size': 1}
        pages = [self.items.list_items({**params, 'page': page}) for page in (1, 2, 3)]
        self.assertEqual([page['total'] for page in pages], [3, 3, 3])
        self.assertEqual([page['items'][0]['id'] for page in pages], [b['id'], c['id'], a['id']])
        self.assertEqual(self.items.list_items({**params, 'q': 'alpha'})['items'][0]['id'], b['id'])
        self.assertEqual(self.items.list_items({**params, 'source': 'Reading'})['total'], 2)

    def test_all_review_scopes_filter_before_limiting_and_round_reset_isolated(self):
        a = self.add('academic')
        b = self.add('academic','enthalpy')
        g = self.add()
        group = self.groups.create_group('热力学', [a['id'], b['id']])
        with self.assertRaises(ValidationError): self.groups.create_group('混合', [a['id'],g['id']])
        for item in (a,g): self.reviews.record_review(item['id'],'forgot',self.day,'recall','',False,False)
        for scope in ('due','recent','study','today','mistakes','group'):
            day=self.day
            rows=self.reviews.get_queue(scope,day,1,group['id'],'word','academic')
            self.assertEqual(len(rows),1,scope)
            self.assertEqual(rows[0]['collection'],'academic',scope)
        general=self.reviews.start_random_round(self.day,'recall',100)
        academic=self.reviews.start_random_round(self.day,'recall',100,collection='academic')
        self.assertEqual([i['id'] for i in general['items']],[g['id']])
        self.assertEqual({i['id'] for i in academic['items']},{a['id'],b['id']})
        self.reviews.reset_random_round(self.day,'recall',collection='academic')
        self.assertEqual(self.reviews.random_round_status(self.day,'recall')['remaining'],0)
        self.assertEqual(self.reviews.random_round_status(self.day,'recall',collection='academic')['remaining'],2)
        self.assertEqual(self.reviews.get_queue('recent',self.day,item_type='phrase',collection='academic'),[])

    def test_csv_roundtrip_and_wrong_collection_rejection(self):
        a=self.add('academic'); self.add()
        csv=CsvService(self.items)
        content=csv.export_items('academic')
        self.assertEqual(csv.import_bytes(content,'general')['failed'],1)
        self.assertEqual(csv.import_bytes(content,'academic')['skipped'],1)
        self.items.delete_item(a['id'])
        self.assertEqual(csv.import_bytes(content,'academic')['created'],1)
        self.assertEqual(self.items.list_items({'collection':'academic'})['total'],1)

    def test_legacy_migration_preserves_ids_history_draws_and_groups(self):
        a=self.add(); b=self.add(term='enthalpy')
        self.groups.create_group('原分组',[a['id'],b['id']])
        self.reviews.record_review(a['id'],'forgot',self.day,'recall','',False,False)
        self.reviews.start_random_round(self.day,'recall',1)
        # Recreate the exact legacy unique constraint while retaining all child rows.
        with closing(sqlite3.connect(self.db.path)) as c:
            schema=c.execute("SELECT sql FROM sqlite_master WHERE name='vocabulary_items'").fetchone()[0]
            schema=schema.replace('"vocabulary_items"','vocabulary_items_old',1)
            schema=schema.replace("collection TEXT NOT NULL DEFAULT 'general' CHECK(collection IN ('general','academic')), UNIQUE(collection, normalized_term, normalized_chinese_meaning)", 'UNIQUE(normalized_term, normalized_chinese_meaning)')
            c.execute(schema)
            names=','.join(r[1] for r in c.execute('PRAGMA table_info(vocabulary_items_old)'))
            c.execute(f'INSERT INTO vocabulary_items_old ({names}) SELECT {names} FROM vocabulary_items')
            c.execute('DROP TABLE vocabulary_items')
            c.execute('ALTER TABLE vocabulary_items_old RENAME TO vocabulary_items')
            c.execute("UPDATE app_meta SET value='9' WHERE key='schema_version'")
            before={t:c.execute(f'SELECT * FROM {t}').fetchall() for t in ('review_history','review_method_draws','confusion_group_items')}
            c.commit()
        self.db.initialize()
        with closing(self.db.connect()) as c:
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            for t,rows in before.items(): self.assertEqual([tuple(r) for r in c.execute(f'SELECT * FROM {t}')],rows)
        self.assertEqual(self.items.get_item(a['id'])['collection'],'general')
        self.assertEqual(self.items.get_item(a['id'])['created_at'],a['created_at'])
        self.add('academic')

    def test_http_collection_contract(self):
        self.add(); self.add('academic')
        server=create_server('127.0.0.1',0,self.db.path,Path(__file__).parents[1]/'app',0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            def request(path,payload=None):
                req=Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
                with urlopen(req) as response: return json.load(response)
            for path in ('/api/items?collection=academic','/api/reviews?scope=recent&collection=academic'):
                self.assertEqual(request(path)['items'][0]['collection'],'academic')
            self.assertEqual(request('/api/items?collection=all&item_group=vocabulary')['total'], 2)
            self.assertEqual(request('/api/facets?collection=all')['collection_counts'], {'general': 1, 'academic': 1})
            self.assertEqual(request('/api/confusion-groups?collection=all')['items'], [])
            with urlopen(base+'/api/export.csv?collection=all') as response:
                exported = response.read()
            self.assertIn(b'general', exported)
            self.assertIn(b'academic', exported)
            result=request('/api/review-round',{'collection':'academic'})
            self.assertEqual(result['items'][0]['collection'],'academic')
            self.assertEqual(request('/api/review-round')['remaining'],1)
            self.assertEqual(request('/api/review-round/reset',{'collection':'academic'})['collection'],'academic')
            self.assertEqual(request('/api/facets?collection=academic')['sources'],['热力学'])
        finally:
            server.shutdown(); server.server_close(); thread.join()
