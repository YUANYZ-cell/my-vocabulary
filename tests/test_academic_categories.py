import csv
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from vocabulary.academic_categories import AcademicCategoryRepository
from vocabulary.csv_io import CsvService
from vocabulary.database import Database
from vocabulary.groups import ConfusionGroupRepository
from vocabulary.http_app import create_server
from vocabulary.items import DuplicateItemError, ItemRepository, ValidationError
from vocabulary.reviews import ReviewRepository


class AcademicCategoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / 'categories.db')
        self.db.initialize()
        self.items = ItemRepository(self.db)
        self.categories = AcademicCategoryRepository(self.db)
        self.groups = ConfusionGroupRepository(self.db, self.items)
        self.reviews = ReviewRepository(self.db, self.items, self.groups)
        self.day = date.today()

    def add(self, term, category=None, collection='academic', kind='word'):
        return self.items.create_item(dict(term=term, chinese_meaning='测试释义', collection=collection,
            item_type=kind, academic_category_id=category, tags=['章节一'], source=term))

    def test_empty_categories_names_rename_and_restart(self):
        category = self.categories.save_category('  单片机  ')
        self.assertEqual(category['count'], 0)
        for name in ('单片机', '未分类', '', ' ' * 5, 'x' * 61, None):
            with self.assertRaises(ValidationError):
                self.categories.save_category(name)
        first = self.add('microcontroller', category['id'])
        renamed = self.categories.save_category('嵌入式系统', category['id'])
        self.assertEqual(renamed['count'], 1)
        self.db.initialize()
        self.assertEqual(self.items.get_item(first['id'])['academic_category_name'], '嵌入式系统')
        self.assertEqual(self.categories.list_categories()['items'][0]['id'], category['id'])

    def test_category_filter_counts_search_and_pagination(self):
        one = self.categories.save_category('单片机')['id']
        two = self.categories.save_category('自动控制')['id']
        a = self.add('alpha', one)
        b = self.add('beta', one, kind='phrase')
        self.add('A complete academic sentence.', one, kind='sentence')
        self.add('zeta', two)
        self.add('unassigned')
        self.add('reading', collection='general')
        options = dict(collection='academic', category_id=one, item_group='vocabulary', page_size=1, sort='term_asc')
        self.assertEqual(self.items.list_items(options)['items'][0]['id'], a['id'])
        self.assertEqual(self.items.list_items({**options, 'page': 2})['items'][0]['id'], b['id'])
        self.assertEqual(self.items.list_items(options)['total'], 2)
        self.assertEqual(self.items.facets('academic', one)['group_counts'], {'vocabulary': 2, 'sentence': 1})
        self.assertEqual(self.items.facets('academic', one)['type_counts'], {'word': 1, 'phrase': 1, 'sentence': 1})
        self.assertEqual(self.items.facets('academic', two)['type_counts'], {'word': 1, 'phrase': 0, 'sentence': 0})
        self.assertEqual(self.items.facets('general')['type_counts'], {'word': 1, 'phrase': 0, 'sentence': 0})
        self.assertEqual(self.items.facets('academic', 'uncategorized')['type_counts'], {'word': 1, 'phrase': 0, 'sentence': 0})
        self.assertEqual(self.items.facets('academic', one)['sources'], ['A complete academic sentence.', 'alpha', 'beta'])
        self.assertEqual(self.items.list_items({'collection': 'all', 'q': '单片机'})['total'], 3)
        self.assertEqual(self.items.list_items({'collection': 'academic', 'category_id': 'uncategorized'})['total'], 1)
        self.assertEqual(self.categories.list_categories()['total'], 5)

    def test_category_assignment_is_atomic_and_preserves_learning(self):
        category = self.categories.save_category('单片机')['id']
        a = self.add('register')
        b = self.add('interrupt')
        general = self.add('general', collection='general')
        self.reviews.record_review(a['id'], 'remembered', self.day, 'recall', '', True, True)
        before = self.items.get_item(a['id'])
        for ids in ([a['id'], general['id']], [a['id'], 9999], [True], [], [None], 'bad'):
            with self.assertRaises(ValidationError):
                self.categories.assign_items(ids, category)
            self.assertIsNone(self.items.get_item(a['id'])['academic_category_id'])
        self.assertEqual(self.categories.assign_items([a['id'], b['id'], a['id']], category)['updated'], 2)
        after = self.items.get_item(a['id'])
        for key in ('id', 'created_at', 'status', 'next_review_at', 'review_count', 'correct_count', 'recent_reviews'):
            self.assertEqual(before[key], after[key], key)
        self.items.update_item(a['id'], {'academic_category_id': None})
        self.assertIsNone(self.items.get_item(a['id'])['academic_category_id'])

    def test_invalid_category_cannot_cross_collection_boundary(self):
        category = self.categories.save_category('单片机')['id']
        with self.assertRaises(ValidationError):
            self.add('word', category, 'general')
        item = self.add('general', collection='general')
        with self.assertRaises(ValidationError):
            self.items.update_item(item['id'], {'academic_category_id': category})
        for invalid in (True, 0, -1, 1.5, '1.5', [], 9999):
            with self.assertRaises(ValidationError):
                self.add('bad', invalid)
        with self.assertRaises(ValidationError):
            self.items.list_items({'collection': 'general', 'category_id': category})
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as connection:
                connection.execute('UPDATE vocabulary_items SET academic_category_id=? WHERE id=?', (category, item['id']))

    def test_deleting_category_retains_words_groups_and_history(self):
        category = self.categories.save_category('单片机')['id']
        a = self.add('register', category)
        b = self.add('interrupt', category)
        group = self.groups.create_group('寄存器与中断', [a['id'], b['id']])
        self.reviews.record_review(a['id'], 'forgot', self.day, 'recall', '', False, False)
        before = self.items.get_item(a['id'])
        self.assertTrue(self.categories.delete_category(category))
        self.assertFalse(self.categories.delete_category(category))
        after = self.items.get_item(a['id'])
        self.assertIsNone(after['academic_category_id'])
        self.assertEqual(before['recent_reviews'], after['recent_reviews'])
        self.assertEqual({item['id'] for item in self.groups.get_group(group['id'])['items']}, {a['id'], b['id']})
        self.assertEqual(self.categories.list_categories()['uncategorized'], 2)
        self.db.initialize()
        self.assertEqual(self.items.list_items({'collection': 'academic'})['total'], 2)

    def test_every_review_scope_filters_before_limit(self):
        category = self.categories.save_category('单片机')['id']
        a = self.add('alpha', category)
        b = self.add('beta', category)
        other = self.add('zzz')
        group = self.groups.create_group('专项分组', [a['id'], b['id'], other['id']])
        for item in (a, other):
            self.reviews.record_review(item['id'], 'forgot', self.day, 'recall', '', False, False)
        with self.db.transaction() as connection:
            connection.execute('UPDATE vocabulary_items SET next_review_at=?', (self.day.isoformat(),))
        for scope in ('due', 'recent', 'study', 'today', 'mistakes', 'group'):
            queue = self.reviews.get_queue(scope, self.day, 1, group['id'], 'word', 'academic', category)
            self.assertEqual(len(queue), 1, scope)
            self.assertEqual(queue[0]['academic_category_id'], category, scope)

    def test_topic_review_contains_entire_folder_and_preserves_boundaries(self):
        category = self.categories.save_category('单片机')['id']
        expected = [self.add(f'pin {index:03}', category)['id'] for index in range(101)]
        expected.append(self.add('pull up', category, kind='phrase')['id'])
        expected.append(self.add('The pin is high.', category, kind='sentence')['id'])
        self.add('other subject', self.categories.save_category('自动控制')['id'])
        uncategorized = self.add('unassigned')
        self.add('general', collection='general')
        queue = self.reviews.get_queue('topic', self.day, 1, collection='academic', category_id=category)
        self.assertEqual([item['id'] for item in queue], expected)
        self.assertEqual(len(queue), 103)
        self.assertEqual([item['id'] for item in self.reviews.get_queue(
            'topic', self.day, collection='academic', category_id='uncategorized')], [uncategorized['id']])
        for collection, selected in [('general', None), ('academic', None), ('academic', ''), ('academic', 9999)]:
            with self.assertRaises(ValidationError):
                self.reviews.get_queue('topic', self.day, collection=collection, category_id=selected)
        first = queue[0]
        self.reviews.record_review(first['id'], 'remembered', self.day, 'recall', '', True, False, scope='topic')
        with closing(self.db.connect()) as connection:
            self.assertEqual(connection.execute('SELECT scope FROM review_history').fetchone()[0], 'topic')
        self.assertEqual(self.items.get_item(first['id'])['review_count'], first['review_count'])
        self.assertEqual(self.items.get_item(first['id'])['next_review_at'], first['next_review_at'])

    def test_category_random_rounds_and_resets_are_independent(self):
        one = self.categories.save_category('单片机')['id']
        two = self.categories.save_category('自动控制')['id']
        a = self.add('register', one)
        b = self.add('feedback', two)
        self.add('uncategorized')
        first = self.reviews.start_random_round(self.day, 'recall', 100, collection='academic', category_id=one)
        self.assertEqual([item['id'] for item in first['items']], [a['id']])
        self.assertEqual(self.reviews.start_random_round(self.day, 'recall', collection='academic', category_id=f'{one:03}')['items'], [])
        self.assertEqual(self.reviews.random_round_status(self.day, 'recall', collection='academic', category_id=two)['remaining'], 1)
        self.assertEqual(self.reviews.start_random_round(self.day, 'recall', collection='academic', category_id=two)['items'][0]['id'], b['id'])
        self.reviews.reset_random_round(self.day, 'recall', collection='academic', category_id=one)
        self.assertEqual(self.reviews.random_round_status(self.day, 'recall', collection='academic', category_id=one)['remaining'], 1)
        self.assertEqual(self.reviews.random_round_status(self.day, 'recall', collection='academic', category_id=two)['remaining'], 0)
        self.assertEqual(self.reviews.random_round_status(self.day, 'recall', collection='academic')['remaining'], 3)
        self.categories.assign_items([b['id']], one)
        self.assertEqual(self.reviews.random_round_status(self.day, 'recall', collection='academic', category_id=two)['total'], 0)

    def test_csv_roundtrip_restores_names_and_handles_legacy_rows(self):
        category = self.categories.save_category('单片机')['id']
        self.add('register', category)
        self.add('uncategorized')
        self.add('reading', collection='general')
        csv_service = CsvService(self.items)
        content = csv_service.export_items()
        other = Database(Path(self.temp.name) / 'restored.db')
        other.initialize()
        AcademicCategoryRepository(other).save_category('其他分类')
        restored = ItemRepository(other)
        self.assertEqual(CsvService(restored).import_bytes(content)['created'], 3)
        restored_category = AcademicCategoryRepository(other).list_categories()['items'][1]
        self.assertEqual(restored_category['name'], '单片机')
        self.assertEqual(restored_category['count'], 1)
        self.assertNotEqual(restored_category['id'], category)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(csv_service.export_items('academic', category).decode('utf-8-sig'))))), 1)
        old_csv = '单词 / 短语 / 长句,中文释义\noscillator,振荡器\n'.encode('utf-8')
        self.assertEqual(csv_service.import_bytes(old_csv, 'academic', category)['created'], 1)
        self.assertEqual(csv_service.import_bytes(old_csv)['created'], 1)
        self.assertEqual(CsvService(restored).import_bytes(csv_service.export_items('academic', category), 'academic', restored_category['id'])['skipped'], 1)
        self.assertEqual(csv_service.import_bytes(content, 'academic', 'uncategorized')['failed'], 2)

    def test_failed_csv_row_does_not_create_empty_category(self):
        self.add('register')
        content = '单词 / 短语 / 长句,中文释义,所属词库,学术分类\nregister,测试释义,academic,单片机\n'.encode('utf-8')
        self.assertEqual(CsvService(self.items).import_bytes(content)['skipped'], 1)
        self.assertEqual(self.categories.list_categories()['items'], [])

    def test_version_ten_migration_preserves_rows(self):
        a = self.add('register')
        self.reviews.record_review(a['id'], 'forgot', self.day, 'recall', '', False, False)
        with self.db.transaction() as connection:
            for operation in ('insert', 'update'):
                connection.execute(f'DROP TRIGGER academic_category_{operation}_guard')
            connection.execute('DROP INDEX idx_items_academic_category')
            connection.execute('ALTER TABLE vocabulary_items DROP COLUMN academic_category_id')
            connection.execute('DROP TABLE academic_categories')
            connection.execute("UPDATE app_meta SET value='10' WHERE key='schema_version'")
            before = [tuple(row) for row in connection.execute('SELECT * FROM vocabulary_items')]
            history = [tuple(row) for row in connection.execute('SELECT * FROM review_history')]
        self.db.initialize()
        self.db.initialize()
        with closing(self.db.connect()) as connection:
            self.assertEqual([tuple(row)[:-1] for row in connection.execute('SELECT * FROM vocabulary_items')], before)
            self.assertEqual([tuple(row) for row in connection.execute('SELECT * FROM review_history')], history)
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_http_category_contract(self):
        server = create_server('127.0.0.1', 0, self.db.path, Path(__file__).parents[1] / 'app', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        def request(path, payload=None, method=None):
            req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                          headers={'Content-Type': 'application/json'}, method=method)
            with urlopen(req) as response:
                return json.load(response)
        category = request('/api/academic-categories', {'name': '单片机'})['id']
        item = request('/api/items', {'term': 'interrupt', 'chinese_meaning': '中断', 'collection': 'academic'})
        request('/api/academic-categories/assign', {'item_ids': [item['id']], 'academic_category_id': category}, 'PUT')
        self.assertEqual(request(f'/api/items?collection=academic&category_id={category}')['total'], 1)
        self.assertEqual(request(f'/api/facets?collection=academic&category_id={category}')['group_counts']['vocabulary'], 1)
        self.assertEqual(request(f'/api/facets?collection=academic&category_id={category}')['type_counts'], {'word': 1, 'phrase': 0, 'sentence': 0})
        self.assertEqual(request(f'/api/reviews?scope=recent&collection=academic&category_id={category}')['items'][0]['id'], item['id'])
        self.assertEqual(request('/api/review-round', {'collection': 'academic', 'category_id': category})['total'], 1)
        self.assertEqual(request(f'/api/review-round?collection=academic&category_id={category}')['remaining'], 0)
        self.assertEqual(request('/api/review-round/reset', {'collection': 'academic', 'category_id': category})['round'], 2)
        request(f'/api/academic-categories/{category}', {'name': '嵌入式'}, 'PUT')
        self.assertEqual(request(f'/api/items/{item["id"]}')['academic_category_name'], '嵌入式')
        request(f'/api/academic-categories/{category}', method='DELETE')
        self.assertEqual(request('/api/items?collection=academic&category_id=uncategorized')['total'], 1)
        with self.assertRaises(HTTPError) as error:
            request('/api/items', {'term': 'bad', 'chinese_meaning': '无效', 'collection': 'general', 'academic_category_id': category})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
