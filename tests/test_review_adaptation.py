import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from vocabulary.database import Database
from vocabulary.groups import ConfusionGroupRepository
from vocabulary.items import ItemRepository, ValidationError
from vocabulary.reviews import ReviewRepository, selection_weight


class ReviewAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Database(Path(self.temp.name) / 'qa.db')
        self.database.initialize()
        self.items = ItemRepository(self.database)
        self.reviews = self.reopen()
        self.day = date.today()
        self.sequence = 0

    def reopen(self):
        db = Database(self.database.path)
        items = ItemRepository(db)
        return ReviewRepository(db, items, ConfusionGroupRepository(db, items))

    def item(self, status='mastered', **fields):
        item = self.items.create_item({'term': 'fragile', 'chinese_meaning': '易碎的', **fields})
        return self.items.update_item(item['id'], {'status': status})

    def answer(self, item, wrong=True, mode='recall', **overrides):
        self.sequence += 1
        arguments = dict(item_id=item['id'], rating='forgot' if wrong else 'remembered',
                         today=self.day, mode=mode, answer='' if mode == 'recall' else 'fragile',
                         first_try_correct=not wrong, affects_schedule=False,
                         client_token=f'answer-{self.sequence}', scope='random')
        arguments.update(overrides)
        return self.reviews.record_review(**arguments)

    def test_third_error_across_methods_drops_one_level_and_survives_reopen(self):
        item = self.item()
        for mode in ('recall', 'zh_to_en'):
            self.assertEqual(self.answer(item, mode=mode)['status'], 'mastered')
        saved = self.answer(item, mode='cloze', scope='mistakes', client_token='third')
        self.assertEqual(saved['status'], 'familiar')
        self.assertEqual(saved['manual_status'], 'familiar')
        self.assertEqual(saved['next_review_at'], item['next_review_at'])
        self.assertEqual(saved['interval_days'], item['interval_days'])
        self.assertEqual(saved['review_count'], item['review_count'])
        self.reviews = self.reopen()
        self.assertEqual(self.answer(item, mode='cloze', scope='mistakes', client_token='third')['status'], 'familiar')
        self.assertEqual(self.items.get_item(item['id'])['status'], 'familiar')
        with self.database.transaction() as c:
            rows = c.execute('SELECT * FROM review_history ORDER BY id').fetchall()
            self.assertEqual(len(rows), 3)
            self.assertEqual((rows[-1]['previous_status'], rows[-1]['new_status']), ('mastered', 'familiar'))
            self.assertEqual(saved['mastery_checkpoint_id'], rows[-1]['id'])

    def test_three_of_five_errors_need_not_be_consecutive(self):
        item = self.item()
        for wrong in (True, False, True, False):
            self.assertEqual(self.answer(item, wrong)['status'], 'mastered')
        self.assertEqual(self.answer(item)['status'], 'familiar')

    def test_sparse_old_errors_do_not_accumulate_forever(self):
        item = self.item()
        for wrong in (True, False, False, False, False, True, False, False, False, False, True):
            self.assertEqual(self.answer(item, wrong)['status'], 'mastered')

    def test_each_demotion_requires_three_new_errors_and_has_a_floor(self):
        item = self.item()
        for expected in ('familiar', 'learning', 'new', 'wrong', 'wrong'):
            before = self.items.get_item(item['id'])['status']
            self.assertEqual(self.answer(item)['status'], before)
            self.assertEqual(self.answer(item)['status'], before)
            self.assertEqual(self.answer(item)['status'], expected)

    def test_manual_change_resets_errors_but_editing_notes_does_not(self):
        item = self.item()
        self.answer(item); self.answer(item)
        self.items.update_item(item['id'], {'status': 'familiar'})
        self.assertEqual(self.answer(item)['status'], 'familiar')
        self.items.update_item(item['id'], {'notes': 'Keep this learning history.'})
        self.assertEqual(self.answer(item)['status'], 'familiar')
        self.assertEqual(self.answer(item)['status'], 'learning')

    def test_boost_wins_over_typing_error_and_starts_fresh_window(self):
        item = self.item('learning')
        self.answer(item); self.answer(item)
        boosted = self.answer(item, mode='zh_to_en', rating='remembered', mastery_boost=True)
        self.assertEqual(boosted['status'], 'familiar')
        self.assertEqual(self.answer(item)['status'], 'familiar')
        self.assertEqual(self.answer(item)['status'], 'familiar')
        self.assertEqual(self.answer(item)['status'], 'learning')

    def test_first_attempt_errors_count_despite_positive_typing_rating(self):
        item = self.item()
        for _ in range(3):
            saved = self.answer(item, mode='zh_to_en', rating='remembered', answer='fraglie')
        self.assertEqual(saved['status'], 'familiar')

    def test_fuzzy_and_unrecalled_are_errors(self):
        item = self.item()
        self.answer(item, rating='unrecalled')
        self.answer(item, mode='cloze', rating='fuzzy', first_try_correct=True)
        self.assertEqual(self.answer(item)['status'], 'familiar')

    def test_sentences_never_lose_mastery_and_legacy_status_does_not_affect_weight(self):
        item = self.item(term='This is a complete test sentence.', item_type='sentence')
        for _ in range(8):
            self.assertEqual(self.answer(item)['status'], 'mastered')
        self.assertEqual(selection_weight(item, self.day),
                         selection_weight({**item, 'status': 'wrong'}, self.day))

    def test_study_answers_cannot_affect_errors(self):
        item = self.item()
        for _ in range(3):
            with self.assertRaises(ValidationError):
                self.answer(item, scope='study')
        self.assertEqual(self.answer(item)['status'], 'mastered')
        with self.database.transaction() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_history').fetchone()[0], 1)

    def test_atomic_failure_rolls_back_demotion_history_and_checkpoint(self):
        item = self.item()
        self.answer(item); self.answer(item)
        original = self.items._row_to_item
        with self.database.transaction() as c:
            row = c.execute('SELECT * FROM vocabulary_items WHERE id=?', (item['id'],)).fetchone()
        with patch.object(self.reviews.items, '_row_to_item', side_effect=[original(row), RuntimeError('after insert')]):
            with self.assertRaises(RuntimeError):
                self.answer(item, client_token='retry')
        saved = self.items.get_item(item['id'])
        self.assertEqual(saved['status'], 'mastered')
        self.assertEqual(saved['mastery_checkpoint_id'], 0)
        with self.database.transaction() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_history').fetchone()[0], 2)
        self.assertEqual(self.answer(item, client_token='retry')['status'], 'familiar')

    def test_scheduled_error_shortens_interval_but_does_not_drop_mastery_once(self):
        item = self.item()
        saved = self.answer(item, affects_schedule=True, scope='due')
        self.assertEqual(saved['status'], 'mastered')
        self.assertEqual(saved['interval_days'], 1)
        self.assertEqual(saved['review_count'], 1)
        self.answer(item, affects_schedule=True, scope='due')
        self.assertEqual(self.answer(item, affects_schedule=True, scope='due')['status'], 'familiar')
        fresh = self.item('new', term='newcomer')
        self.assertEqual(self.answer(fresh, affects_schedule=True, scope='due')['status'], 'new')

    def test_recent_miss_beats_fresh_correct_item_across_modes_and_strategies(self):
        clean = self.item(term='clean')
        missed = self.item(term='missed')
        self.answer(clean, wrong=False)
        self.answer(missed, mode='zh_to_en')
        self.reviews = self.reopen()
        for strategy in ('balanced', 'forgetting'):
            for mode in ('recall', 'zh_to_en', 'cloze'):
                with self.subTest(strategy=strategy, mode=mode):
                    self.reviews.reset_random_round(self.day, mode)
                    with patch('vocabulary.reviews.random.random', return_value=0.5):
                        drawn = self.reviews.start_random_round(self.day, mode, 1, strategy)
                    self.assertEqual(drawn['items'][0]['id'], missed['id'])
                    # Error weighting must still obey the daily no-repeat boundary.
                    remaining = self.reviews.start_random_round(self.day, mode, 1, strategy)
                    self.assertEqual(remaining['items'][0]['id'], clean['id'])

    def test_recent_window_recovers_after_correct_answers(self):
        item = self.item()
        self.answer(item)
        weights = []
        def capture(candidates, today, limit, performance, strategy):
            weights.append((dict(performance[item['id']]), selection_weight(candidates[0], today, performance[item['id']], strategy)))
            return candidates[:limit]
        for successes in (0, 1, 9):
            for _ in range(successes):
                self.answer(item, wrong=False)
            self.reviews.reset_random_round(self.day, 'recall')
            with patch('vocabulary.reviews._weighted_sample', side_effect=capture):
                self.reviews.start_random_round(self.day, 'recall', 1)
        self.assertGreater(weights[0][1], weights[1][1])
        self.assertGreater(weights[1][1], weights[2][1])
        self.assertEqual(weights[2][0]['attempts'], 10)
        self.assertEqual(weights[2][0]['error_score'], 0)

    def test_lifetime_successes_cannot_dilute_a_new_error(self):
        item = self.item()
        for _ in range(30):
            self.answer(item, wrong=False)
        self.answer(item)
        captured = []
        def capture(candidates, today, limit, performance, strategy):
            captured.append(performance[item['id']])
            return candidates
        with patch('vocabulary.reviews._weighted_sample', side_effect=capture):
            self.reviews.start_random_round(self.day, 'cloze', 1)
        self.assertEqual(captured[0]['attempts'], 10)
        self.assertEqual(captured[0]['latest_error_score'], 1.5)

    def test_academic_and_general_homographs_keep_independent_errors(self):
        general = self.item()
        academic = self.item(collection='academic')
        for _ in range(3):
            self.answer(academic)
        self.assertEqual(self.items.get_item(academic['id'])['status'], 'familiar')
        self.assertEqual(self.items.get_item(general['id'])['status'], 'mastered')
        for collection, expected in (('general', general), ('academic', academic)):
            drawn = self.reviews.start_random_round(self.day, 'recall', 20, collection=collection)
            self.assertEqual([i['id'] for i in drawn['items']], [expected['id']])

    def test_upgrade_preserves_status_and_starts_new_demotion_window_once(self):
        item = self.item()
        self.answer(item); self.answer(item)
        with self.database.transaction() as c:
            c.execute('ALTER TABLE vocabulary_items DROP COLUMN mastery_checkpoint_id')
            c.execute("UPDATE app_meta SET value='12' WHERE key='schema_version'")
        self.database.initialize()
        checkpoint = self.items.get_item(item['id'])['mastery_checkpoint_id']
        self.assertGreater(checkpoint, 0)
        self.assertEqual(self.answer(item)['status'], 'mastered')
        self.database.initialize()
        self.assertEqual(self.items.get_item(item['id'])['mastery_checkpoint_id'], checkpoint)
        self.assertEqual(self.answer(item)['status'], 'mastered')
        self.assertEqual(self.answer(item)['status'], 'familiar')
