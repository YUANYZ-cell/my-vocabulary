from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from vocabulary.database import Database
from vocabulary.expressions import ExpressionRepository
from vocabulary.items import ItemRepository, ValidationError


class ExpressionRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.db.initialize()
        self.expressions = ExpressionRepository(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def sample(self, **overrides):
        payload = {
            "content_type": "范文",
            "title": "Why public transport matters",
            "english_text": "First paragraph.\n\nSecond paragraph.",
            "chinese_text": "第一段。\n\n第二段。",
            "exam_type": "雅思",
            "topic": "社会与发展",
            "tags": ["Task 2", "transport"],
            "source": "个人笔记",
            "notes": "保留段落",
        }
        payload.update(overrides)
        return payload

    def test_crud_keeps_paragraphs_and_stays_out_of_vocabulary(self):
        item = self.expressions.create_item(self.sample())
        self.assertEqual(item["english_text"], "First paragraph.\n\nSecond paragraph.")
        self.assertEqual(ItemRepository(self.db).list_items({})["total"], 0)

        updated = self.expressions.update_item(item["id"], {"chinese_text": "稍后补充的翻译"})
        self.assertEqual(updated["chinese_text"], "稍后补充的翻译")
        self.assertTrue(self.expressions.delete_item(item["id"]))
        self.assertIsNone(self.expressions.get_item(item["id"]))

    def test_search_facets_favorites_and_recent_reading(self):
        first = self.expressions.create_item(self.sample())
        self.expressions.create_item(self.sample(
            content_type="句式", title="A useful transition", english_text="Nevertheless, ...",
            chinese_text="", exam_type="六级", topic="连接与过渡", tags=["transition"],
        ))
        self.expressions.set_favorite(first["id"], True)
        opened = self.expressions.record_open(first["id"])
        self.assertEqual(opened["read_count"], 1)
        with closing(self.db.connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM expression_read_history").fetchone()[0], 1)
        self.expressions.save_reading_state(first["id"], {
            "scroll_ratio": 0.62, "translation_visible": False,
            "font_scale": 1.1, "line_height": 2.0,
        })

        listing = self.expressions.list_items({"q": "transport", "favorite": "true"})
        self.assertEqual([item["id"] for item in listing["items"]], [first["id"]])
        self.assertIn("句式", self.expressions.facets()["types"])
        summary = self.expressions.summary()
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["favorite_count"], 1)
        self.assertEqual(summary["total_reads"], 1)
        self.assertEqual(summary["continue_reading"]["id"], first["id"])

    def test_translation_is_optional_but_title_and_english_are_required(self):
        item = self.expressions.create_item(self.sample(chinese_text=""))
        self.assertEqual(item["chinese_text"], "")
        with self.assertRaises(ValidationError):
            self.expressions.create_item(self.sample(title=""))
        with self.assertRaises(ValidationError):
            self.expressions.create_item(self.sample(english_text=""))


if __name__ == "__main__":
    unittest.main()
