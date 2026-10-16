import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from vocabulary.database import Database, SCHEMA_VERSION
from vocabulary.daily_expressions import DailyExpressionRepository
from vocabulary.expressions import ExpressionRepository
from vocabulary.items import ItemRepository, ValidationError


class DailyExpressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        self.daily = DailyExpressionRepository(self.database)

    def snapshot_learning_tables(self):
        with closing(self.database.connect()) as connection:
            tables = [row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) if row["name"] not in ("app_meta", "daily_expressions", "sqlite_sequence")]
            return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
                    for table in tables}

    def test_browse_add_edit_and_favorite_never_change_learning_data(self):
        ItemRepository(self.database).create_item({"term": "apple", "chinese_meaning": "苹果"})
        ExpressionRepository(self.database).create_item({
            "content_type": "范文", "title": "Existing essay", "english_text": "An essay."
        })
        before = self.snapshot_learning_tables()
        starter = self.daily.list_items()["items"][0]
        self.daily.get_item(starter["id"])
        self.daily.save_item({"is_favorite": True}, starter["id"])
        custom = self.daily.save_item({"phrase": "Works for me.", "meaning": "我觉得可以", "category": "口语"})
        self.daily.save_item({"usage": "随意回应建议。"}, custom["id"])
        self.assertEqual(self.snapshot_learning_tables(), before)

    def test_migration_and_restart_preserve_existing_content_and_daily_edits(self):
        before = self.snapshot_learning_tables()
        starter = self.daily.list_items()["items"][0]
        self.daily.save_item({"meaning": "自己的解释", "is_favorite": True}, starter["id"])
        with self.database.transaction() as connection:
            connection.execute("UPDATE app_meta SET value='7' WHERE key='schema_version'")
        self.database.initialize()
        self.database.initialize()
        self.assertEqual(self.daily.list_items()["total"], 24)
        saved = self.daily.get_item(starter["id"])
        self.assertEqual(saved["meaning"], "自己的解释")
        self.assertTrue(saved["is_favorite"])
        self.assertEqual(self.snapshot_learning_tables(), before)
        with closing(self.database.connect()) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()[0], str(SCHEMA_VERSION))

    def test_delete_starter_and_custom_survive_restart_and_restore_without_data_loss(self):
        ItemRepository(self.database).create_item({"term": "apple", "chinese_meaning": "苹果"})
        before = self.snapshot_learning_tables()
        starter = self.daily.list_items()["items"][0]
        saved = self.daily.save_item({"meaning": "自己的解释", "is_favorite": True}, starter["id"])
        custom = self.daily.save_item({"phrase": "Works for me.", "meaning": "我觉得可以", "category": "口语"})
        for item in (saved, custom):
            self.assertTrue(self.daily.delete_item(item["id"]))
            self.assertIsNone(self.daily.get_item(item["id"]))
            self.assertIsNone(self.daily.save_item({"is_favorite": False}, item["id"]))
            self.assertFalse(self.daily.delete_item(item["id"]))
        self.database.initialize()
        restarted = DailyExpressionRepository(Database(self.database.path))
        self.assertEqual(restarted.list_items()["total"], 23)
        self.assertEqual(restarted.list_items()["deleted_total"], 2)
        self.assertEqual({item["id"] for item in restarted.list_items(deleted=True)["items"]},
                         {saved["id"], custom["id"]})
        for original in (saved, custom):
            self.assertEqual(restarted.restore_item(original["id"]), original)
            self.assertIsNone(restarted.restore_item(original["id"]))
        self.assertFalse(restarted.delete_item(999999))
        self.assertIsNone(restarted.restore_item(999999))
        self.assertEqual(restarted.list_items()["total"], 25)
        self.assertEqual(restarted.list_items()["deleted_total"], 0)
        self.assertEqual(self.snapshot_learning_tables(), before)

    def test_version_eight_database_migrates_without_losing_favorites(self):
        starter = self.daily.list_items()["items"][0]
        self.daily.save_item({"is_favorite": True}, starter["id"])
        with self.database.transaction() as connection:
            connection.execute("ALTER TABLE daily_expressions DROP COLUMN deleted_at")
            connection.execute("UPDATE app_meta SET value='8' WHERE key='schema_version'")
        self.database.initialize()
        self.assertTrue(self.daily.get_item(starter["id"])["is_favorite"])
        self.assertTrue(self.daily.delete_item(starter["id"]))
        self.database.initialize()
        self.assertIsNone(self.daily.get_item(starter["id"]))

    def test_invalid_fields_do_not_create_or_modify_content(self):
        valid = {"phrase": "Test", "meaning": "测试", "category": "口语"}
        for changes in ({"phrase": " "}, {"meaning": ""}, {"category": "练习"},
                        {"usage": []}, {"phrase": "x" * 241}, {"is_favorite": "false"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.daily.save_item({**valid, **changes})
        self.assertEqual(self.daily.list_items()["total"], 24)
        self.assertIsNone(self.daily.save_item(valid, 999999))
