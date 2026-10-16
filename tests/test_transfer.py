import codecs
import tempfile
import unittest
from datetime import date
from pathlib import Path

from vocabulary.csv_io import CsvService
from vocabulary.database import Database
from vocabulary.items import ItemRepository
from vocabulary.reviews import ReviewRepository
from vocabulary.groups import ConfusionGroupRepository
from vocabulary.stats import StatsRepository


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "one.db")
        self.db.initialize()
        self.items = ItemRepository(self.db)

    def test_csv_round_trip_and_duplicate_skip(self):
        self.items.create_item({
            "term": "be attributed to", "chinese_meaning": "归因于", "part_of_speech": "phrase",
            "english_definition": "be caused by", "source_sentence": "The change can be attributed to policy.",
            "collocations": ["largely be attributed to"], "source": "IELTS Writing", "tags": ["写作词汇"],
        })
        exported = CsvService(self.items).export_items()
        self.assertTrue(exported.startswith(codecs.BOM_UTF8))
        other_db = Database(Path(self.temp.name) / "two.db")
        other_db.initialize()
        other_items = ItemRepository(other_db)
        service = CsvService(other_items)
        self.assertEqual(service.import_bytes(exported)["created"], 1)
        self.assertEqual(service.import_bytes(exported)["skipped"], 1)
        loaded = other_items.list_items({})["items"][0]
        self.assertEqual(loaded["collocations"], ["largely be attributed to"])

    def test_dashboard_and_period_have_stable_shape(self):
        item = self.items.create_item({"term": "adapt", "chinese_meaning": "适应"}, today=date(2026, 9, 2))
        groups = ConfusionGroupRepository(self.db, self.items)
        reviews = ReviewRepository(self.db, self.items, groups)
        reviews.record_review(item["id"], "remembered", date(2026, 9, 3), "zh_to_en", "adapt", True, True, "stats-token")
        dashboard = StatsRepository(self.db).dashboard(date(2026, 9, 3))
        self.assertEqual(dashboard["total"], 1)
        self.assertEqual(dashboard["learned_this_week"], 1)
        period = StatsRepository(self.db).period(7, date(2026, 9, 3))
        self.assertEqual(len(period["series"]), 7)
        self.assertEqual(period["series"][-1]["reviews"], 1)


if __name__ == "__main__":
    unittest.main()
