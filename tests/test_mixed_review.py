import tempfile
import unittest
from datetime import date
from pathlib import Path

from vocabulary.academic_categories import AcademicCategoryRepository
from vocabulary.database import Database
from vocabulary.groups import ConfusionGroupRepository
from vocabulary.items import ItemRepository
from vocabulary.reviews import ReviewRepository


class MixedReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Database(Path(temp.name) / 'qa.db')
        self.db.initialize()
        self.items = ItemRepository(self.db)
        self.groups = ConfusionGroupRepository(self.db, self.items)
        self.reviews = ReviewRepository(self.db, self.items, self.groups)
        self.day = date.today()
        self.word = self.add('adapt', 'word')
        self.phrase = self.add('in turn', 'phrase')
        self.sentence = self.add('This is a separate complete sentence.', 'sentence')
        self.academic = self.add('voltage', 'word', collection='academic')
        self.expected = {self.word['id'], self.phrase['id']}
        with self.db.transaction() as connection:
            connection.execute('UPDATE vocabulary_items SET next_review_at=?', [self.day.isoformat()])

    def add(self, term, kind, **extra):
        return self.items.create_item(dict(term=term, chinese_meaning='测试', item_type=kind, **extra))

    def test_scopes_mix_words_and_phrases_with_one_shared_limit(self):
        group = self.groups.create_group('Mixed', [self.word['id'], self.phrase['id'], self.sentence['id']])
        for scope in ('due', 'today', 'recent', 'study', 'group'):
            with self.subTest(scope=scope):
                queue = self.reviews.get_queue(scope, self.day, 100, group['id'], 'vocabulary')
                self.assertEqual({i['id'] for i in queue}, self.expected)
                limited = self.reviews.get_queue(scope, self.day, 1, group['id'], 'vocabulary')
                self.assertEqual(len(limited), 1)
        queue = self.reviews.get_queue('recent', self.day, 1, item_type='vocabulary')
        self.assertEqual(queue[0]['id'], self.phrase['id'])

    def test_mistakes_include_both_types_and_use_latest_result(self):
        for item in (self.word, self.phrase, self.sentence, self.academic):
            self.reviews.record_review(item['id'], 'forgot', self.day, 'recall', '', False, False)
        queue = self.reviews.get_queue('mistakes', self.day, 100, item_type='vocabulary')
        self.assertEqual({i['id'] for i in queue}, self.expected)
        self.reviews.record_review(self.phrase['id'], 'remembered', self.day, 'recall', '', True, False)
        queue = self.reviews.get_queue('mistakes', self.day, 100, item_type='vocabulary')
        self.assertEqual([i['id'] for i in queue], [self.word['id']])

    def test_random_rounds_deduplicate_and_keep_modes_selections_separate(self):
        for mode in ('recall', 'zh_to_en', 'cloze'):
            for strategy in ('balanced', 'forgetting'):
                with self.subTest(mode=mode, strategy=strategy):
                    first = self.reviews.start_random_round(self.day, mode, 1, strategy, 'vocabulary')
                    second = self.reviews.start_random_round(self.day, mode, 100, strategy, 'vocabulary')
                    self.assertEqual({i['id'] for i in first['items'] + second['items']}, self.expected)
                    self.assertEqual((first['used'], first['remaining']), (1, 1))
                    self.assertEqual((second['used'], second['remaining']), (2, 0))
                    self.assertEqual(self.reviews.start_random_round(self.day, mode, item_type='vocabulary')['items'], [])
                    self.reviews.reset_random_round(self.day, mode, 'vocabulary')
            single = self.reviews.start_random_round(self.day, mode, item_type='word')
            self.assertEqual([i['id'] for i in single['items']], [self.word['id']])
            self.reviews.reset_random_round(self.day, mode, 'vocabulary')
            self.assertEqual(self.reviews.random_round_status(self.day, mode, 'word')['remaining'], 0)

    def test_category_filter_and_empty_or_phrase_only_selection(self):
        categories = AcademicCategoryRepository(self.db)
        category = categories.save_category('Physics')
        phrase = self.add('electric field', 'phrase', collection='academic', academic_category_id=category['id'])
        with self.db.transaction() as connection:
            connection.execute('UPDATE vocabulary_items SET next_review_at=? WHERE id=?', [self.day.isoformat(), phrase['id']])
        for scope in ('recent', 'study', 'due'):
            queue = self.reviews.get_queue(scope, self.day, item_type='vocabulary', collection='academic', category_id=category['id'])
            self.assertEqual([i['id'] for i in queue], [phrase['id']])
        drawn = self.reviews.start_random_round(self.day, 'recall', item_type='vocabulary', collection='academic', category_id=category['id'])
        self.assertEqual([i['id'] for i in drawn['items']], [phrase['id']])
        self.assertEqual((drawn['total'], drawn['used'], drawn['remaining']), (1, 1, 0))
        empty = categories.save_category('Empty')
        status = self.reviews.random_round_status(self.day, 'recall', 'vocabulary', 'academic', empty['id'])
        self.assertEqual((status['total'], status['used'], status['remaining']), (0, 0, 0))


if __name__ == '__main__':
    unittest.main()
