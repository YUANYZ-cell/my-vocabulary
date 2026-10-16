import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from vocabulary.database import Database
from vocabulary.daily_expressions import DailyExpressionRepository
from vocabulary.daily_groups import DailyGroupRepository
from vocabulary.content_moves import ContentMoveRepository
from vocabulary.items import ValidationError
from scripts.import_daily_groups import import_groups


class DailyGroupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / 'test.db')
        self.db.initialize()
        self.daily = DailyExpressionRepository(self.db)
        self.groups = DailyGroupRepository(self.db)

    def word(self, group_id):
        return self.daily.save_item(dict(phrase='pomelo', meaning='柚子', category='词汇', group_id=group_id))

    def test_edit_favorite_delete_restore_and_restart_retain_membership(self):
        group = self.groups.save_group('水果')
        item = self.word(group['id'])
        self.daily.save_item({'is_favorite': True}, item['id'])
        self.daily.save_item({'meaning': '柚子（水果）'}, item['id'])
        self.assertEqual(self.groups.list_groups()['items'][0]['item_count'], 1)
        self.daily.delete_item(item['id'])
        self.assertEqual(self.groups.list_groups()['items'][0]['item_count'], 0)
        self.db.initialize()
        restored = self.daily.restore_item(item['id'])
        self.assertEqual(restored['group_id'], group['id'])
        self.assertTrue(restored['is_favorite'])
        self.assertEqual(restored['meaning'], '柚子（水果）')
        self.assertEqual(self.groups.list_groups()['items'][0]['item_count'], 1)

    def test_rename_and_dissolve_preserve_active_and_trashed_content(self):
        group = self.groups.save_group('水果')
        active = self.word(group['id'])
        deleted = self.daily.save_item(dict(phrase='papaya', meaning='木瓜', category='词汇', group_id=group['id']))
        self.daily.delete_item(deleted['id'])
        self.groups.save_group('水果与甘蔗', group['id'])
        self.assertEqual(self.daily.get_item(active['id'])['group_id'], group['id'])
        self.groups.delete_group(group['id'])
        self.assertIsNone(self.daily.get_item(active['id'])['group_id'])
        self.assertIsNone(self.daily.restore_item(deleted['id'])['group_id'])
        self.db.initialize()
        self.assertEqual(self.daily.list_items()['total'], 26)
        with closing(self.db.connect()) as connection:
            self.assertEqual(list(connection.execute('PRAGMA foreign_key_check')), [])

    def test_unknown_or_invalid_group_never_creates_or_changes_word(self):
        item = self.word(None)
        for value in [99999, True, -1, 1.2, {}, 'bad']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.daily.save_item({'group_id': value}, item['id'])
            self.assertIsNone(self.daily.get_item(item['id'])['group_id'])
        self.assertEqual(self.daily.list_items()['total'], 25)

    def test_empty_group_persists_and_duplicate_names_are_rejected(self):
        group = self.groups.save_group(' Fruits ')
        self.db.initialize()
        self.assertEqual(self.groups.list_groups()['items'][0]['item_count'], 0)
        self.assertEqual(self.groups.list_groups()['items'][0]['id'], group['id'])
        for name in ['fruits', 'FRUITS', '', ' ', None, 'x'*81]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self.groups.save_group(name)
        self.assertIsNone(self.groups.save_group('missing', 99999))
        self.assertFalse(self.groups.delete_group(99999))

    def test_group_round_trip_survives_dissolving_while_word_is_moved(self):
        group = self.groups.save_group('水果')
        item = self.word(group['id'])
        moves = ContentMoveRepository(self.db)
        moved = moves.move(dict(source='daily', target='general', item_id=item['id']))
        self.groups.delete_group(group['id'])
        restored = moves.move(dict(source='general', target='daily', item_id=moved['item_id']))
        self.assertEqual(restored['item_id'], item['id'])
        self.assertIsNone(self.daily.get_item(item['id'])['group_id'])

    def test_collections_and_membership_do_not_write_learning_tables(self):
        def snapshot():
            with closing(self.db.connect()) as connection:
                return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table}')]
                        for table in ['vocabulary_items', 'review_history', 'review_rounds', 'review_draws', 'review_method_rounds', 'review_method_draws', 'expression_read_history']}
        before = snapshot()
        group = self.groups.save_group('水果')
        self.word(group['id'])
        self.groups.save_group('水果合集', group['id'])
        self.groups.list_groups()
        self.daily.list_items()
        self.assertEqual(snapshot(), before)

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / 'docs/intakes/20261009-gym-fruit/intake.json').exists(), 'Private intake fixture is not distributed')
    def test_screenshot_intake_is_idempotent_and_preserves_later_edits_and_deletion(self):
        source = Path(__file__).resolve().parents[1] / 'docs/intakes/20261009-gym-fruit/intake.json'
        first = import_groups(self.db.path, source)
        self.assertEqual([group['added'] for group in first], [23, 8])
        items = self.daily.list_items()['items']
        pomelo = next(item for item in items if item['phrase'] == 'pomelo')
        dragon = next(item for item in items if item['phrase'] == 'dragon fruit')
        self.daily.save_item(dict(meaning='自己的释义', is_favorite=True), pomelo['id'])
        self.daily.delete_item(dragon['id'])
        second = import_groups(self.db.path, source)
        self.assertEqual([group['added'] for group in second], [0, 0])
        self.assertEqual([group['total'] for group in second], [23, 7])
        self.assertEqual(self.daily.get_item(pomelo['id'])['meaning'], '自己的释义')
        self.assertTrue(self.daily.get_item(pomelo['id'])['is_favorite'])
        self.assertIsNone(self.daily.get_item(dragon['id']))
