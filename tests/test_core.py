import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from vocabulary.content_types import infer_item_type
from vocabulary.database import Database
from vocabulary.groups import ConfusionGroupRepository
from vocabulary.items import DuplicateItemError, ItemRepository
from vocabulary.reviews import (
    ReviewRepository,
    forgetting_weight,
    mistake_weight,
    retrievability,
    selection_weight,
)
from vocabulary.srs import ReviewState, make_cloze, schedule_review, spelling_matches
from vocabulary.stats import StatsRepository


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "vocabulary.db"
        self.database = Database(self.path)
        self.database.initialize()
        self.items = ItemRepository(self.database)
        self.groups = ConfusionGroupRepository(self.database, self.items)
        self.reviews = ReviewRepository(self.database, self.items, self.groups)

    def test_minimal_item_survives_reopen_and_is_due_tomorrow(self):
        item = self.items.create_item(
            {"term": "substantial", "chinese_meaning": "大量的；重大的"},
            today=date(2026, 9, 3),
        )
        reopened = ItemRepository(Database(self.path))
        loaded = reopened.get_item(item["id"])
        self.assertEqual(loaded["term"], "substantial")
        self.assertEqual(loaded["next_review_at"], "2026-09-04")

    def test_duplicate_and_distinct_sense_rules(self):
        self.items.create_item({"term": "Substantial ", "chinese_meaning": "大量的"})
        with self.assertRaises(DuplicateItemError):
            self.items.create_item({"term": " substantial", "chinese_meaning": "大量的 "})
        second = self.items.create_item({"term": "substantial", "chinese_meaning": "实质性的"})
        self.assertEqual(second["chinese_meaning"], "实质性的")

    def test_search_filter_update_and_delete(self):
        item = self.items.create_item(
            {
                "term": "play a crucial role in",
                "chinese_meaning": "在……中发挥关键作用",
                "source": "IELTS Writing",
                "tags": ["写作词汇", "词块"],
            }
        )
        result = self.items.list_items({"q": "关键", "source": "IELTS Writing", "tag": "词块"})
        self.assertEqual(result["total"], 1)
        updated = self.items.update_item(item["id"], {"notes": "作文使用", "status": "familiar"})
        self.assertEqual(updated["manual_status"], "familiar")
        self.assertTrue(self.items.delete_item(item["id"]))
        self.assertIsNone(self.items.get_item(item["id"]))

    def test_library_sorting_modes(self):
        self.items.create_item({"term": "Zulu", "chinese_meaning": "末"})
        self.items.create_item({"term": "alpha", "chinese_meaning": "首"})
        self.assertEqual([item["term"] for item in self.items.list_items({"sort": "newest"})["items"]], ["alpha", "Zulu"])
        self.assertEqual([item["term"] for item in self.items.list_items({"sort": "term_asc"})["items"]], ["alpha", "Zulu"])
        self.assertEqual([item["term"] for item in self.items.list_items({"sort": "term_desc"})["items"]], ["Zulu", "alpha"])

    def test_short_phrases_and_long_sentences_are_distinct_and_filterable(self):
        short = self.items.create_item({"term": "peal of laughter", "chinese_meaning": "一阵笑声"})
        long = self.items.create_item({
            "term": "The figure saw a gradual decline over the period.",
            "chinese_meaning": "该数据在这一时期逐渐下降。",
        })
        self.assertEqual(short["item_type"], "phrase")
        self.assertEqual(long["item_type"], "sentence")
        self.assertEqual(infer_item_type("Take care on the road."), "phrase")
        self.assertEqual([item["id"] for item in self.items.list_items({"item_type": "phrase"})["items"]], [short["id"]])
        self.assertEqual([item["id"] for item in self.items.list_items({"item_type": "sentence"})["items"]], [long["id"]])
        self.assertEqual(
            [item["id"] for item in self.items.list_items({"item_group": "vocabulary"})["items"]],
            [short["id"]],
        )
        self.assertEqual(
            [item["id"] for item in self.items.list_items({"item_group": "sentence"})["items"]],
            [long["id"]],
        )
        self.assertEqual(self.items.facets()["group_counts"], {"vocabulary": 1, "sentence": 1})

    def test_version_seven_migration_corrects_clear_words_and_long_sentences(self):
        word = self.items.create_item({
            "term": "ponder", "chinese_meaning": "思考", "item_type": "phrase",
        })
        short = self.items.create_item({
            "term": "peal of laughter", "chinese_meaning": "一阵笑声", "item_type": "phrase",
        })
        long = self.items.create_item({
            "term": "The statistic experienced wild oscillations.",
            "chinese_meaning": "该数据出现剧烈波动。",
            "item_type": "phrase",
        })
        with self.database.transaction() as connection:
            connection.execute("UPDATE app_meta SET value='6' WHERE key='schema_version'")
        self.database.initialize()
        self.assertEqual(self.items.get_item(word["id"])["item_type"], "word")
        self.assertEqual(self.items.get_item(short["id"])["item_type"], "phrase")
        self.assertEqual(self.items.get_item(long["id"])["item_type"], "sentence")

    def test_current_database_reopen_preserves_explicit_compound_word_types(self):
        automatic = self.items.create_item({'term': 'Game changer', 'chinese_meaning': '改变局面的人或事物'})
        explicit = self.items.create_item({'term': 'ice cream', 'chinese_meaning': '冰淇淋', 'item_type': 'word'})
        phrase = self.items.create_item({'term': 'game changer', 'chinese_meaning': '手动选为短语', 'item_type': 'phrase'})
        before = [self.items.get_item(item['id']) for item in (automatic, explicit, phrase)]
        self.assertEqual([item['item_type'] for item in before], ['word', 'word', 'phrase'])
        self.database.initialize()
        self.database.initialize()
        self.assertEqual([self.items.get_item(item['id']) for item in before], before)

    def test_schedule_and_spelling_boundaries(self):
        base = ReviewState(1, 2.0, 0, "new", 0)
        self.assertEqual(schedule_review(base, "forgot", date(2026, 9, 4), []).interval_days, 1)
        self.assertEqual(schedule_review(base, "unrecalled", date(2026, 9, 4), []).interval_days, 1)
        self.assertEqual(schedule_review(base, "fuzzy", date(2026, 9, 4), []).interval_days, 2)
        self.assertEqual(schedule_review(base, "remembered", date(2026, 9, 4), []).interval_days, 4)
        self.assertEqual(schedule_review(base, "easy", date(2026, 9, 4), []).interval_days, 7)
        self.assertTrue(spelling_matches("Play a crucial role in", " play   A crucial role in "))
        self.assertFalse(spelling_matches("well-being", "well being"))
        self.assertFalse(spelling_matches("don't", "dont"))
        self.assertEqual(make_cloze("adapt"), "a_a_t")
        self.assertEqual(make_cloze("play a crucial role in"), "play ___ crucial ___ in")

    def test_due_review_updates_schedule_but_group_practice_does_not(self):
        first = self.items.create_item({"term": "adapt", "chinese_meaning": "适应"}, today=date(2026, 9, 3))
        second = self.items.create_item({"term": "adopt", "chinese_meaning": "采用"}, today=date(2026, 9, 3))
        group = self.groups.create_group("adapt / adopt", [first["id"], second["id"]])
        due = self.reviews.get_queue("due", date(2026, 9, 4), limit=20)
        self.assertEqual({row["id"] for row in due}, {first["id"], second["id"]})
        scheduled = self.reviews.record_review(
            first["id"], "remembered", date(2026, 9, 4), "zh_to_en", "adapt", True, True, "token-a"
        )
        self.assertEqual(scheduled["next_review_at"], "2026-09-08")
        before = self.items.get_item(second["id"])["next_review_at"]
        practiced = self.reviews.record_review(
            second["id"], "forgot", date(2026, 9, 4), "cloze", "adept", False, False, "token-b"
        )
        self.assertEqual(practiced["next_review_at"], before)
        group_queue = self.reviews.get_queue("group", date(2026, 9, 4), group_id=group["id"])
        self.assertEqual(len(group_queue), 2)

    def test_random_round_does_not_repeat_until_reset(self):
        for number in range(4):
            self.items.create_item({"term": f"word {number}", "chinese_meaning": str(number), "item_type": "word"})
        today = date(2026, 9, 4)
        first = self.reviews.start_random_round(today, "recall", 3)
        second = self.reviews.start_random_round(today, "recall", 3)
        self.assertEqual(len(first["items"]), 3)
        self.assertEqual(len(second["items"]), 1)
        self.assertTrue({x["id"] for x in first["items"]}.isdisjoint({x["id"] for x in second["items"]}))
        spelling = self.reviews.start_random_round(today, "zh_to_en", 4)
        self.assertEqual(len(spelling["items"]), 4)
        self.assertEqual(self.reviews.random_round_status(today, "recall")["remaining"], 0)
        self.assertEqual(self.reviews.random_round_status(today, "zh_to_en")["remaining"], 0)
        self.reviews.reset_random_round(today, "recall")
        third = self.reviews.start_random_round(today, "recall", 4)
        self.assertEqual(len(third["items"]), 4)

    def test_forgetting_weight_changes_with_elapsed_time_and_memory_interval(self):
        today = date(2026, 9, 8)
        fresh = {"created_at": today.isoformat(), "interval_days": 1}
        one_day_old = {"created_at": (today - timedelta(days=1)).isoformat(), "interval_days": 1}
        week_old = {"created_at": (today - timedelta(days=7)).isoformat(), "interval_days": 1}
        stable = {**week_old, "interval_days": 14}

        self.assertAlmostEqual(retrievability(fresh, today), 1.0)
        self.assertAlmostEqual(retrievability(one_day_old, today), 0.5)
        self.assertLess(forgetting_weight(fresh, today), forgetting_weight(one_day_old, today))
        self.assertLess(forgetting_weight(one_day_old, today), forgetting_weight(week_old, today))
        self.assertLess(forgetting_weight(stable, today), forgetting_weight(week_old, today))
        self.assertAlmostEqual(
            forgetting_weight(week_old, today, {"last_reviewed_at": today.isoformat()}), 0.45
        )

    def test_global_review_weight_combines_mastery_and_mistakes(self):
        today = date(2026, 9, 8)
        base = {"created_at": today.isoformat()}
        weights = {
            status: selection_weight({**base, "status": status}, today)
            for status in ("new", "learning", "wrong", "familiar", "mastered")
        }
        self.assertGreater(weights["wrong"], weights["learning"])
        self.assertGreater(weights["learning"], weights["new"])
        self.assertGreater(weights["new"], weights["familiar"])
        self.assertGreater(weights["familiar"], weights["mastered"])
        self.assertEqual(mistake_weight(8, 0, False), 1.0)
        self.assertGreater(mistake_weight(8, 4, False), mistake_weight(8, 1, False))
        self.assertGreater(mistake_weight(8, 4, True), mistake_weight(8, 4, False))
        self.assertGreater(
            selection_weight({**base, "status": "mastered"}, today, {"attempts": 4, "errors": 4, "latest_error": 1}),
            selection_weight({**base, "status": "mastered"}, today),
        )
        stale = {"created_at": (today - timedelta(days=20)).isoformat(), "interval_days": 2}
        fresh = {"created_at": today.isoformat(), "interval_days": 2}
        self.assertGreater(
            selection_weight(stale, today, strategy="forgetting"),
            selection_weight(fresh, today, strategy="forgetting"),
        )

    def test_wrong_mastery_can_be_saved_and_filtered(self):
        item = self.items.create_item({"term": "fallible", "chinese_meaning": "会犯错的"})

        updated = self.items.update_item(item["id"], {"status": "wrong"})
        filtered = self.items.list_items({"status": "wrong"})

        self.assertEqual(updated["status"], "wrong")
        self.assertEqual(updated["manual_status"], "wrong")
        self.assertEqual([entry["id"] for entry in filtered["items"]], [item["id"]])

    def test_unrecalled_has_more_review_weight_than_an_incorrect_recall(self):
        today = date(2026, 9, 9)
        item = {"created_at": today.isoformat(), "status": "learning"}
        incorrect = selection_weight(
            item, today, {"attempts": 1, "error_score": 1.5, "latest_error_score": 1.5}
        )
        unrecalled = selection_weight(
            item, today, {"attempts": 1, "error_score": 2.0, "latest_error_score": 2.0}
        )
        self.assertGreater(unrecalled, incorrect)

    def test_recall_accepts_unrecalled_as_a_distinct_result(self):
        item = self.items.create_item({"term": "elusive", "chinese_meaning": "难以捉摸的"})
        recorded = self.reviews.record_review(
            item["id"], "unrecalled", date.today(), "recall", "", False, False,
            "unrecalled-token", "random",
        )
        self.assertEqual(recorded["next_review_at"], item["next_review_at"])
        activity = StatsRepository(self.database).activity(date.today(), 28)["series"][-1]
        self.assertEqual((activity["reviews"], activity["score"]), (1, 6))

    def test_random_round_uses_recorded_mistake_performance(self):
        item = self.items.create_item({"term": "fragile", "chinese_meaning": "易碎的"})
        self.reviews.record_review(
            item["id"], "forgot", date.today(), "recall", "", False, False, "weight-token", "random"
        )
        result = self.reviews.start_random_round(date.today(), "recall", 1)
        self.assertEqual(result["items"][0]["id"], item["id"])

    def test_today_scope_returns_only_items_created_today(self):
        today = date.today()
        current = self.items.create_item({"term": "current", "chinese_meaning": "今天"}, today=today)
        older = self.items.create_item({"term": "older", "chinese_meaning": "更早"}, today=today)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE vocabulary_items SET created_at=? WHERE id=?",
                ((today - timedelta(days=1)).isoformat(), older["id"]),
            )
        queue = self.reviews.get_queue("today", today)
        self.assertEqual([item["id"] for item in queue], [current["id"]])

    def test_recent_scope_returns_the_latest_user_selected_count(self):
        created = [
            self.items.create_item({"term": f"recent {number}", "chinese_meaning": str(number), "item_type": "word"})
            for number in range(25)
        ]
        queue = self.reviews.get_queue("recent", date.today(), limit=20)

        self.assertEqual(len(queue), 20)
        self.assertEqual([item["id"] for item in queue], [item["id"] for item in reversed(created[-20:])])

    def test_every_review_queue_keeps_words_phrases_and_sentences_separate(self):
        today = date.today()
        word = self.items.create_item(
            {"term": "separate", "chinese_meaning": "分开", "item_type": "word"},
            today=today - timedelta(days=1),
        )
        phrase = self.items.create_item(
            {"term": "Keep the two libraries separate.", "chinese_meaning": "把两个库分开。", "item_type": "phrase"},
            today=today - timedelta(days=1),
        )
        sentence = self.items.create_item(
            {"term": "The figure saw a gradual decline over the period.", "chinese_meaning": "该数据在这一时期逐渐下降。", "item_type": "sentence"},
            today=today - timedelta(days=1),
        )
        group = self.groups.create_group("separate types", [word["id"], phrase["id"], sentence["id"]])
        self.reviews.record_review(word["id"], "forgot", today, "recall", "", False, False, "word-miss")
        self.reviews.record_review(phrase["id"], "forgot", today, "recall", "", False, False, "phrase-miss")
        self.reviews.record_review(sentence["id"], "forgot", today, "recall", "", False, False, "sentence-miss")

        for scope in ("due", "recent", "study", "mistakes"):
            words = self.reviews.get_queue(scope, today, item_type="word")
            phrases = self.reviews.get_queue(scope, today, item_type="phrase")
            self.assertEqual({item["item_type"] for item in words}, {"word"})
            self.assertEqual({item["item_type"] for item in phrases}, {"phrase"})
            sentences = self.reviews.get_queue(scope, today, item_type="sentence")
            self.assertEqual({item["item_type"] for item in sentences}, {"sentence"})
        self.assertEqual(
            [item["id"] for item in self.reviews.get_queue("group", today, group_id=group["id"], item_type="word")],
            [word["id"]],
        )
        self.assertEqual(
            [item["id"] for item in self.reviews.get_queue("group", today, group_id=group["id"], item_type="phrase")],
            [phrase["id"]],
        )
        self.assertEqual(
            [item["id"] for item in self.reviews.get_queue("group", today, group_id=group["id"], item_type="sentence")],
            [sentence["id"]],
        )

        word_round = self.reviews.start_random_round(today, "recall", 10, item_type="word")
        phrase_round = self.reviews.start_random_round(today, "recall", 10, item_type="phrase")
        sentence_round = self.reviews.start_random_round(today, "recall", 10, item_type="sentence")
        self.assertEqual({item["item_type"] for item in word_round["items"]}, {"word"})
        self.assertEqual({item["item_type"] for item in phrase_round["items"]}, {"phrase"})
        self.assertEqual({item["item_type"] for item in sentence_round["items"]}, {"sentence"})
        self.assertEqual(self.reviews.random_round_status(today, "recall", "word")["remaining"], 0)
        self.assertEqual(self.reviews.random_round_status(today, "recall", "phrase")["remaining"], 0)
        self.assertEqual(self.reviews.random_round_status(today, "recall", "sentence")["remaining"], 0)
        self.reviews.reset_random_round(today, "recall", "word")
        self.assertEqual(self.reviews.random_round_status(today, "recall", "word")["remaining"], 1)
        self.assertEqual(self.reviews.random_round_status(today, "recall", "phrase")["remaining"], 0)

    def test_activity_records_real_additions_and_reviews(self):
        today = date.today()
        item = self.items.create_item({"term": "retain", "chinese_meaning": "记住"}, today=today)
        self.reviews.record_review(
            item["id"], "forgot", today, "recall", "", False, False, "activity-token", "random"
        )
        activity = StatsRepository(self.database).activity(today, 28)
        latest = activity["series"][-1]
        self.assertEqual((latest["added"], latest["reviews"], latest["score"]), (1, 1, 5))
        self.assertEqual(activity["active_days"], 1)
        self.assertEqual(activity["current_streak"], 1)

    def test_expression_reading_adds_activity_without_changing_word_review_count(self):
        from vocabulary.expressions import ExpressionRepository

        today = date.today()
        expressions = ExpressionRepository(self.database)
        material = expressions.create_item({
            "content_type": "段落",
            "title": "A short paragraph",
            "english_text": "Reading is activity, not a scored answer.",
        })
        expressions.record_open(material["id"])
        latest = StatsRepository(self.database).activity(today, 28)["series"][-1]

        self.assertEqual(latest["expression_reads"], 1)
        self.assertEqual(latest["reviews"], 0)
        self.assertEqual(latest["score"], 1)

    def test_period_exposes_status_hours_and_accuracy_for_the_insight_module(self):
        today = date.today()
        item = self.items.create_item({"term": "coherent", "chinese_meaning": "连贯的"}, today=today)
        self.reviews.record_review(
            item["id"], "remembered", today, "recall", "", True, True, "insight-token-1", "random"
        )
        self.reviews.record_review(
            item["id"], "forgot", today, "recall", "", False, True, "insight-token-2", "random"
        )
        period = StatsRepository(self.database).period(7, today)

        # The four learning blocks are labelled in the learner's own day order and between them
        # they hold every review in the window, so nothing is silently dropped by a timezone shift.
        self.assertEqual(
            [bucket["label"] for bucket in period["hours"]],
            ["0–6时", "6–12时", "12–18时", "18–24时"],
        )
        self.assertEqual(sum(bucket["reviews"] for bucket in period["hours"]), 2)
        self.assertEqual(len(period["accuracy"]), 7)
        self.assertEqual(sum(point["attempts"] for point in period["accuracy"]), 2)
        self.assertEqual(sum(point["correct"] for point in period["accuracy"]), 1)
        self.assertEqual(period["accuracy_summary"]["rate"], 50)
        self.assertEqual(sum(period["status"].values()), 1)

    def _backdated_review(self, item_id, day, rating, correct, token):
        """A review stamped on another day, which record_review cannot express (it uses today)."""
        stamp = f"{day.isoformat()}T09:00:00+08:00"
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO review_history(item_id,reviewed_at,scope,mode,rating,answer,first_try_correct,"
                "affects_schedule,client_token,previous_interval_days,new_interval_days,previous_status,"
                "new_status,next_review_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item_id, stamp, "random", "recall", rating, "", int(correct), 1, token,
                 1, 1, "new", "learning", stamp),
            )

    def test_error_map_summarises_one_window_of_the_same_records(self):
        today = date(2026, 9, 25)
        items = {
            name: self.items.create_item({"term": name, "chinese_meaning": meaning}, today=today)["id"]
            for name, meaning in (
                ("pant", "喘息"),
                ("queer", "古怪的"),
                ("indulgently", "纵容的"),
                ("ponder", "思考"),
                ("coherent", "连贯的"),
            )
        }
        sequence = {
            "pant": [False, False, False, True, False],
            "queer": [False, False, True],
            "indulgently": [False],
            "ponder": [False, True, True, True],
            "coherent": [True, True],
        }
        for name, results in sequence.items():
            for index, correct in enumerate(results):
                self.reviews.record_review(
                    items[name], "remembered" if correct else "forgot", today, "recall", "",
                    correct, True, f"em-{name}-{index}", "random",
                )
        # An error from nine days ago sits in the previous window, not this one.
        self._backdated_review(items["coherent"], today - timedelta(days=9), "forgot", False, "em-old")

        repository = StatsRepository(self.database)
        week = repository.period(7, today)["error_map"]

        # 4+2+1+1 errors over 5+3+1+4+2 attempts; the never-wrong word keeps its attempts in the
        # denominator but stays out of the ranking.
        self.assertEqual(
            week["summary"],
            {"errors": 8, "words": 4, "error_rate": 53, "avg_streak": 1.6},
        )
        # Errors first, then the rate: indulgently (one wrong answer out of one) outranks ponder
        # (one out of four) even though both went wrong once.
        self.assertEqual(
            [(word["term"], word["errors"], word["attempts"], word["error_rate"], word["band"])
             for word in week["words"]],
            [
                ("pant", 4, 5, 80, "high"),
                ("queer", 2, 3, 67, "mid"),
                ("indulgently", 1, 1, 100, "low"),
                ("ponder", 1, 4, 25, "rare"),
            ],
        )
        self.assertTrue(week["words"][0]["last_error_at"].startswith(today.isoformat()))
        # The ring partitions exactly the words the ranking lists, so its slices cannot disagree
        # with the number printed in the middle.
        self.assertEqual([band["key"] for band in week["bands"]], ["high", "mid", "low", "rare"])
        self.assertEqual(sum(band["value"] for band in week["bands"]), week["summary"]["words"])
        self.assertEqual([band["value"] for band in week["bands"]], [1, 1, 1, 1])
        # Compared with the previous seven days, which hold the one backdated error.
        self.assertEqual(week["previous"], {"start": "2026-09-12", "end": "2026-09-18"})
        self.assertEqual(
            week["deltas"],
            {"errors": 700, "words": 300, "error_rate": -47, "avg_streak": 60},
        )

        everything = repository.period("all", today)["error_map"]
        self.assertIn("coherent", [word["term"] for word in everything["words"]])
        # Nothing precedes the whole collection, so no figure claims a comparison.
        self.assertIsNone(everything["previous"])
        self.assertEqual(everything["deltas"], {"errors": None, "words": None, "error_rate": None, "avg_streak": None})

    def test_error_map_stays_quiet_without_any_wrong_answer(self):
        today = date(2026, 9, 25)
        item = self.items.create_item({"term": "coherent", "chinese_meaning": "连贯的"}, today=today)
        self.reviews.record_review(item["id"], "remembered", today, "recall", "", True, True, "clean-1", "random")

        week = StatsRepository(self.database).period(7, today)["error_map"]
        # A window with attempts but no mistakes reports a real zero rate, and a mean streak that
        # is unknown rather than zero - there is nothing to divide.
        self.assertEqual(week["summary"], {"errors": 0, "words": 0, "error_rate": 0, "avg_streak": None})
        self.assertEqual(week["words"], [])
        self.assertEqual(sum(band["value"] for band in week["bands"]), 0)

        empty = StatsRepository(self.database).period(7, today + timedelta(days=60))["error_map"]
        # A window with no attempts at all has no rate: the page prints a dash, never NaN.
        self.assertEqual(empty["summary"], {"errors": 0, "words": 0, "error_rate": None, "avg_streak": None})

    def test_activity_carries_the_daily_accuracy_used_by_the_heatmap_tooltip(self):
        today = date.today()
        item = self.items.create_item({"term": "sparse", "chinese_meaning": "稀少的"}, today=today)
        self.reviews.record_review(
            item["id"], "remembered", today, "recall", "", True, True, "activity-accuracy-1", "random"
        )
        self.reviews.record_review(
            item["id"], "forgot", today, "recall", "", False, True, "activity-accuracy-2", "random"
        )
        latest = StatsRepository(self.database).activity(today, 28)["series"][-1]

        self.assertEqual((latest["graded"], latest["correct"]), (2, 1))

    def test_synonyms_phrase_type_and_oldest_sort_survive_edit(self):
        first = self.items.create_item({"term": "in light of", "chinese_meaning": "鉴于", "item_type": "phrase", "synonyms": ["considering"]})
        second = self.items.create_item({"term": "sparse", "chinese_meaning": "稀少的"})
        created_at = first["created_at"]
        updated = self.items.update_item(first["id"], {"synonyms": ["considering", "given"]})
        self.assertEqual(updated["created_at"], created_at)
        self.assertEqual(updated["item_type"], "phrase")
        self.assertEqual(updated["synonyms"], ["considering", "given"])
        self.assertEqual([x["id"] for x in self.items.list_items({"sort": "oldest"})["items"]], [first["id"], second["id"]])

    def test_similarity_suggestions_and_group_lifecycle(self):
        adapt = self.items.create_item({"term": "adapt", "chinese_meaning": "适应"})
        adopt = self.items.create_item({"term": "adopt", "chinese_meaning": "采用"})
        self.items.create_item({"term": "substantial", "chinese_meaning": "大量的"})
        suggestions = self.groups.suggest_similar(adapt["id"])
        self.assertEqual([row["term"] for row in suggestions], ["adopt"])
        group = self.groups.create_group("易混 1", [adapt["id"], adopt["id"]])
        self.assertEqual(len(group["items"]), 2)
        self.groups.delete_group(group["id"])
        self.assertEqual(self.groups.list_groups(), [])


if __name__ == "__main__":
    unittest.main()
