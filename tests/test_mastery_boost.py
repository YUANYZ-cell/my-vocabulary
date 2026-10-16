import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from vocabulary.database import Database
from vocabulary.groups import ConfusionGroupRepository
from vocabulary.items import ItemRepository, ValidationError
from vocabulary.reviews import ReviewRepository


class MasteryBoostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Database(Path(self.temp.name) / 'qa.db')
        self.database.initialize()
        self.items = ItemRepository(self.database)
        self.reviews = ReviewRepository(self.database, self.items, ConfusionGroupRepository(self.database, self.items))

    def boost(self, item, token='once', **overrides):
        arguments = dict(item_id=item['id'], rating='remembered', today=date.today(), mode='recall',
                         answer='', first_try_correct=True, affects_schedule=False,
                         client_token=token, scope='recent', mastery_boost=True)
        arguments.update(overrides)
        return self.reviews.record_review(**arguments)

    def test_one_level_persists_with_one_answer_and_retry_is_idempotent(self):
        for initial, expected in [('wrong', 'new'), ('new', 'learning'), ('learning', 'familiar'), ('familiar', 'mastered'), ('mastered', 'mastered')]:
            with self.subTest(initial=initial):
                item = self.items.create_item({'term': initial, 'chinese_meaning': '测试'})
                item = self.items.update_item(item['id'], {'status': initial})
                saved = self.boost(item, token=initial)
                self.assertEqual(saved['status'], expected)
                self.assertEqual(saved['manual_status'], expected)
                self.assertEqual(saved['interval_days'], item['interval_days'])
                self.assertEqual(saved['next_review_at'], item['next_review_at'])
                self.assertEqual(saved['review_count'], item['review_count'])
                self.assertEqual(self.boost(item, token=initial)['status'], expected)
                self.assertEqual(ItemRepository(Database(self.database.path)).get_item(item['id'])['status'], expected)
                with self.database.transaction() as connection:
                    history = connection.execute('SELECT * FROM review_history WHERE item_id=?', (item['id'],)).fetchall()
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0]['first_try_correct'], 1)
                self.assertEqual(history[0]['previous_status'], initial)
                self.assertEqual(history[0]['new_status'], expected)

    def test_failure_rolls_back_both_promotion_and_history_then_retry_succeeds(self):
        item = self.items.create_item({'term': 'rollback', 'chinese_meaning': '测试'})
        original = self.items._row_to_item
        with patch.object(self.items, '_row_to_item', side_effect=[original(self._row(item['id'])), RuntimeError('simulate failure after insert')]):
            with self.assertRaises(RuntimeError):
                self.boost(item)
        self.assertEqual(self.items.get_item(item['id'])['status'], 'new')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM review_history').fetchone()[0], 0)
        self.assertEqual(self.boost(item)['status'], 'learning')

    def _row(self, item_id):
        with self.database.transaction() as connection:
            return connection.execute('SELECT * FROM vocabulary_items WHERE id=?', (item_id,)).fetchone()

    def test_study_sentences_and_forgotten_answers_cannot_promote(self):
        item = self.items.create_item({'term': 'guard', 'chinese_meaning': '测试'})
        sentence = self.items.create_item({'term': 'This is a sentence.', 'chinese_meaning': '测试句子', 'item_type': 'sentence'})
        for entry, arguments in [(item, {'scope': 'study'}), (sentence, {}), (item, {'rating': 'forgot', 'first_try_correct': False})]:
            with self.assertRaises(ValidationError):
                self.boost(entry, **arguments)
        self.assertEqual(self.items.get_item(item['id'])['status'], 'new')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM review_history').fetchone()[0], 0)

    def test_typing_keeps_first_attempt_accuracy(self):
        item = self.items.create_item({'term': 'accuracy', 'chinese_meaning': '准确'})
        saved = self.boost(item, mode='zh_to_en', answer='acuracy', first_try_correct=False)
        self.assertEqual(saved['status'], 'learning')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT first_try_correct FROM review_history').fetchone()[0], 0)
