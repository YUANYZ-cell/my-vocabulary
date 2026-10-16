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
from vocabulary.content_moves import ContentMoveRepository
from vocabulary.daily_expressions import DailyExpressionRepository
from vocabulary.database import Database
from vocabulary.expressions import ExpressionRepository
from vocabulary.groups import ConfusionGroupRepository
from vocabulary.items import DuplicateItemError, ItemRepository, ValidationError
from vocabulary.reviews import ReviewRepository
from vocabulary.stats import StatsRepository
from vocabulary.http_app import create_server


class ContentMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / 'moves.db')
        self.db.initialize()
        self.items = ItemRepository(self.db)
        self.expressions = ExpressionRepository(self.db)
        self.daily = DailyExpressionRepository(self.db)
        self.moves = ContentMoveRepository(self.db)
        self.categories = AcademicCategoryRepository(self.db)
        self.groups = ConfusionGroupRepository(self.db, self.items)
        self.reviews = ReviewRepository(self.db, self.items, self.groups)

    def move(self, source, item_id, target, **fields):
        return self.moves.move(dict(source=source, item_id=item_id, target=target, **fields))

    def assert_integrity(self):
        with closing(self.db.connect()) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_expression_to_daily_and_back_preserves_reading_history_and_favorite_edits(self):
        original = self.expressions.create_item(dict(content_type='句式', title='A useful reply', english_text='Works for me.',
            chinese_text='我觉得可以', exam_type='通用', topic='聊天', tags=['回应'], notes='轻松回应建议', source='个人笔记', is_favorite=True))
        original = self.expressions.record_open(original['id'])
        original = self.expressions.save_reading_state(original['id'], dict(scroll_ratio=.62, font_scale=1.2, translation_visible=False))
        before = StatsRepository(self.db).period(7, date.today())
        daily_id = self.move('expressions', original['id'], 'daily')['item_id']
        self.assertIsNone(self.expressions.get_item(original['id']))
        self.assertEqual(self.expressions.summary()['total'], 0)
        daily = self.daily.get_item(daily_id)
        self.assertEqual((daily['phrase'], daily['meaning'], daily['usage'], daily['is_favorite']),
                         ('Works for me.', '我觉得可以', '轻松回应建议', True))
        self.assertEqual(StatsRepository(self.db).period(7, date.today()), before)
        self.daily.save_item(dict(meaning='这样我可以接受', is_favorite=False), daily_id)
        self.db.initialize()
        restored_id = self.move('daily', daily_id, 'expressions')['item_id']
        restored = self.expressions.get_item(restored_id)
        self.assertEqual(restored_id, original['id'])
        self.assertEqual(restored['chinese_text'], '这样我可以接受')
        self.assertFalse(restored['is_favorite'])
        for key in ('title', 'english_text', 'exam_type', 'topic', 'tags', 'read_count', 'last_read_at', 'scroll_ratio', 'font_scale', 'translation_visible', 'created_at'):
            self.assertEqual(restored[key], original[key], key)
        self.assertIsNone(self.daily.get_item(daily_id))
        self.assertEqual(self.daily.list_items(deleted=True)['total'], 0)
        self.assert_integrity()

    def test_vocabulary_round_trip_restores_id_mastery_draws_groups_and_full_history(self):
        word = self.items.create_item(dict(term='adapt', chinese_meaning='适应', synonyms=['adjust'], phonetic='/əˈdæpt/',
            part_of_speech='verb', english_definition='change to suit a situation', source_sentence='We adapt to change.',
            own_sentence='I adapt quickly.', collocations=['adapt to'], tags=['阅读'], notes='注意与 adopt 区别'))
        sibling = self.items.create_item(dict(term='adopt', chinese_meaning='采用'))
        group = self.groups.create_group('adapt / adopt', [word['id'], sibling['id']])
        self.reviews.start_random_round(date.today(), 'recall', 2, 'balanced', 'word', 'general')
        self.reviews.record_review(word['id'], 'remembered', date.today(), 'recall', '', True, True, 'move-review')
        before = self.items.get_item(word['id'])
        with closing(self.db.connect()) as c:
            history = [tuple(r) for r in c.execute('SELECT * FROM review_history')]
            draws = [tuple(r) for r in c.execute('SELECT * FROM review_method_draws ORDER BY item_id')]
        moved_id = self.move('general', word['id'], 'daily')['item_id']
        self.assertIsNone(self.items.get_item(word['id']))
        self.assertEqual(self.groups.list_groups(), [])
        for scope in ('due', 'recent', 'study', 'today', 'mistakes'):
            self.assertNotIn(word['id'], [r['id'] for r in self.reviews.get_queue(scope, date.today(), 100)])
        with closing(self.db.connect()) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_history').fetchone()[0], 0)
        self.db.initialize()
        returned = self.move('daily', moved_id, 'general')
        self.assertEqual(returned['item_id'], word['id'])
        restored = self.items.get_item(word['id'])
        for key in before:
            if key != 'updated_at':
                self.assertEqual(restored[key], before[key], key)
        with closing(self.db.connect()) as c:
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM review_history')], history)
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM review_method_draws ORDER BY item_id')], draws)
        self.assertEqual(self.groups.list_groups()[0]['id'], group['id'])
        self.assert_integrity()

    def test_general_academic_move_keeps_identity_and_does_not_create_mixed_groups(self):
        category = self.categories.save_category('单片机')
        word = self.items.create_item(dict(term='register', chinese_meaning='寄存器'))
        sibling = self.items.create_item(dict(term='registry', chinese_meaning='登记处'))
        group = self.groups.create_group('register / registry', [word['id'], sibling['id']])
        result = self.move('general', word['id'], 'academic', academic_category_id=category['id'])
        self.assertEqual(result['item_id'], word['id'])
        self.assertEqual(self.items.get_item(word['id'])['academic_category_id'], category['id'])
        self.assertEqual(self.items.list_items({'collection':'general'})['total'], 1)
        self.assertEqual(self.items.list_items({'collection':'academic'})['total'], 1)
        self.assertEqual(self.groups.list_groups(), [])
        self.move('academic', word['id'], 'general')
        self.assertEqual(self.groups.list_groups()[0]['id'], group['id'])
        self.assertIsNone(self.items.get_item(word['id'])['academic_category_id'])
        preview = self.moves.preview(dict(source='general', item_id=word['id'], target='academic'))
        self.assertEqual(preview['academic_category_id'], category['id'])
        self.move('general', word['id'], 'academic')
        self.assertEqual(self.items.get_item(word['id'])['academic_category_id'], category['id'])
        self.assert_integrity()

    def test_seed_move_is_not_reseeded_or_shown_in_trash_and_round_trip_reuses_seed(self):
        seed = self.daily.list_items()['items'][0]
        result = self.move('daily', seed['id'], 'expressions')
        for _ in range(2):
            self.db.initialize()
        self.assertEqual(self.daily.list_items()['total'], 23)
        self.assertEqual(self.daily.list_items(deleted=True)['total'], 0)
        self.assertIsNone(self.daily.restore_item(seed['id']))
        self.assertFalse(self.daily.delete_item(seed['id']))
        returned = self.move('expressions', result['item_id'], 'daily')
        self.assertEqual(returned['item_id'], seed['id'])
        self.assertEqual(self.daily.get_item(seed['id'])['seed_key'], seed['seed_key'])
        self.assertEqual(self.daily.list_items()['total'], 24)
        self.assert_integrity()

    def test_duplicates_leave_source_and_target_untouched(self):
        for target in ('general', 'academic', 'expressions', 'daily'):
            with self.subTest(target=target):
                phrase = f'Unique {target}.'
                source = self.daily.save_item(dict(phrase=phrase, meaning='重复测试', category='口语')) if target != 'daily' else self.expressions.create_item(dict(title='Duplicate', english_text=phrase, chinese_text='重复测试', content_type='句式'))
                module = 'daily' if target != 'daily' else 'expressions'
                if target in ('general', 'academic'):
                    self.items.create_item(dict(term=phrase, chinese_meaning='重复测试', collection=target))
                elif target == 'expressions':
                    self.expressions.create_item(dict(title='Same', english_text=phrase, chinese_text='重复测试', content_type='句式'))
                else:
                    self.daily.save_item(dict(phrase=phrase, meaning='重复测试', category='口语'))
                with closing(self.db.connect()) as c:
                    before = {table:[tuple(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in ('vocabulary_items','expression_materials','daily_expressions','content_moves')}
                with self.assertRaises(DuplicateItemError):
                    self.move(module, source['id'], target)
                with closing(self.db.connect()) as c:
                    for table, rows in before.items():
                        self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY rowid')], rows)
        self.assert_integrity()

    def test_long_article_requires_short_meaning_and_retains_every_paragraph_on_return(self):
        english = 'A full paragraph that must remain intact.\n\n'*80
        chinese = '完整中文原文，不能截断。\n\n'*100
        expression = self.expressions.create_item(dict(title='A long reading', content_type='范文', english_text=english, chinese_text=chinese, notes='长篇笔记'*1000))
        preview = self.moves.preview(dict(source='expressions', item_id=expression['id'], target='daily'))
        self.assertTrue(preview['long_text'])
        self.assertEqual(preview['term'], expression['title'])
        self.assertEqual(preview['meaning'], '')
        with self.assertRaises(ValidationError):
            self.move('expressions', expression['id'], 'daily')
        daily_id = self.move('expressions', expression['id'], 'daily', meaning='这是一篇长文')['item_id']
        retained = self.moves.retained('daily', daily_id)['items'][0]
        self.assertEqual(retained['term'], expression['english_text'])
        self.assertEqual(retained['meaning'], expression['chinese_text'])
        returned = self.move('daily', daily_id, 'expressions')['item_id']
        restored = self.expressions.get_item(returned)
        self.assertEqual(restored['english_text'], expression['english_text'])
        self.assertEqual(restored['chinese_text'], expression['chinese_text'])
        self.assertEqual(restored['notes'], expression['notes'])
        self.assert_integrity()

    def test_category_deleted_while_away_returns_to_uncategorized(self):
        category = self.categories.save_category('已删除合集')
        word = self.items.create_item(dict(term='entropy', chinese_meaning='熵', collection='academic', academic_category_id=category['id']))
        daily_id = self.move('academic', word['id'], 'daily')['item_id']
        self.categories.delete_category(category['id'])
        returned = self.move('daily', daily_id, 'academic')['item_id']
        self.assertIsNone(self.items.get_item(returned)['academic_category_id'])
        self.assert_integrity()

    def test_failed_restore_rolls_back_target_insert_and_leaves_active_source(self):
        word = self.items.create_item(dict(term='history', chinese_meaning='历史'))
        self.reviews.record_review(word['id'], 'remembered', date.today(), 'recall', '', True, True, 'conflicting-history-token')
        daily_id = self.move('general', word['id'], 'daily')['item_id']
        other = self.items.create_item(dict(term='other', chinese_meaning='其他'))
        self.reviews.record_review(other['id'], 'remembered', date.today(), 'recall', '', True, True, 'conflicting-history-token')
        with self.assertRaises(DuplicateItemError):
            self.move('daily', daily_id, 'general')
        self.assertIsNotNone(self.daily.get_item(daily_id))
        self.assertIsNone(self.items.get_item(word['id']))
        self.assertEqual(len(self.items.all_items()), 1)
        self.assert_integrity()

    def test_all_module_pairs_and_repeated_moves_keep_one_active_entry(self):
        for source in ('general', 'academic', 'expressions', 'daily'):
            for target in ('general', 'academic', 'expressions', 'daily'):
                if source == target:
                    continue
                with self.subTest(source=source, target=target):
                    term = f'pair {source} {target}'
                    if source in ('general', 'academic'):
                        original = self.items.create_item(dict(term=term, chinese_meaning='往返', collection=source))
                    elif source == 'expressions':
                        original = self.expressions.create_item(dict(title=term, english_text=term, chinese_text='往返', content_type='句式'))
                    else:
                        original = self.daily.save_item(dict(phrase=term, meaning='往返', category='口语'))
                    moved = self.move(source, original['id'], target)
                    with self.assertRaises(ValidationError):
                        self.move(source, original['id'], target)
                    returned = self.move(target, moved['item_id'], source)
                    self.assertEqual(returned['item_id'], original['id'])
        self.assert_integrity()

    def test_preview_is_read_only_and_invalid_target_or_category_does_not_move(self):
        word = self.items.create_item(dict(term='safe', chinese_meaning='安全'))
        with closing(self.db.connect()) as c:
            before = c.execute('SELECT COUNT(*) FROM content_moves').fetchone()[0]
        self.moves.preview(dict(source='general', item_id=word['id'], target='academic'))
        for fields in (dict(target='all'), dict(target=[]), dict(target='general'), dict(target='academic', academic_category_id=999999), dict(target='daily', category='无效分类'), dict(target='daily', term='x'*241), dict(target='daily', meaning='')):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.moves.move(dict(source='general', item_id=word['id'], **fields))
        with closing(self.db.connect()) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM content_moves').fetchone()[0], before)
        self.assertIsNotNone(self.items.get_item(word['id']))

    def test_changed_source_rejects_stale_preview_instead_of_overwriting_new_content(self):
        word = self.items.create_item(dict(term='current', chinese_meaning='当前'))
        preview = self.moves.preview(dict(source='general', item_id=word['id'], target='daily'))
        self.items.update_item(word['id'], dict(chinese_meaning='用户刚修改的释义'))
        with self.assertRaises(ValidationError):
            self.move('general', word['id'], 'daily', term=preview['term'], meaning=preview['meaning'], source_version=preview['source_version'])
        self.assertEqual(self.items.get_item(word['id'])['chinese_meaning'], '用户刚修改的释义')
        self.assertEqual(self.daily.list_items()['total'], 24)
        self.assert_integrity()


class ContentMoveHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.server = create_server('127.0.0.1', 0, root/'http.db', root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        with urlopen(Request(self.url+path, data=body, method=method, headers={'Content-Type':'application/json'})) as response:
            return response.status, json.loads(response.read())

    def test_move_preview_and_retained_routes_form_a_complete_round_trip(self):
        _, original = self.request('POST','/api/expressions',dict(content_type='句式',title='HTTP reply',english_text='Works for me.',chinese_text='我觉得可以',notes='完整备注',is_favorite=True))
        payload = dict(source='expressions', item_id=original['id'], target='daily')
        _, preview = self.request('POST','/api/content-moves/preview',payload)
        self.assertEqual(preview['target_label'],'生活口语')
        status, moved = self.request('POST','/api/content-moves',{**payload,'source_version':preview['source_version']})
        self.assertEqual(status,200)
        self.assertEqual(self.request('GET','/api/expressions')[1]['total'],0)
        _, retained = self.request('GET',f'/api/content-moves/retained?source=daily&item_id={moved["item_id"]}')
        self.assertEqual(retained['items'][0]['term'],'Works for me.')
        _, returned = self.request('POST','/api/content-moves',dict(source='daily',item_id=moved['item_id'],target='expressions'))
        self.assertEqual(returned['item_id'],original['id'])
        self.assertTrue(self.request('GET',f'/api/expressions/{original["id"]}')[1]['is_favorite'])

    def test_http_conflict_and_validation_responses_preserve_original(self):
        _, source = self.request('POST','/api/items',dict(term='same',chinese_meaning='相同'))
        self.request('POST','/api/daily-expressions',dict(phrase='same',meaning='相同',category='口语'))
        for target, status in (('daily',409),('all',400)):
            with self.assertRaises(HTTPError) as raised:
                self.request('POST','/api/content-moves',dict(source='general',item_id=source['id'],target=target))
            self.assertEqual(raised.exception.code,status)
            raised.exception.close()
        self.assertEqual(self.request('GET',f'/api/items/{source["id"]}')[1]['term'],'same')


if __name__ == '__main__':
    unittest.main()
