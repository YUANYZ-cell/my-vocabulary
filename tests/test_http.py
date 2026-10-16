import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from vocabulary.http_app import create_server


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        app = root / "app"
        app.mkdir()
        (app / "index.html").write_text("<!doctype html><title>My Vocabulary</title>", encoding="utf-8")
        self.server = create_server("127.0.0.1", 0, root / "data.db", app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, payload=None, content_type="application/json"):
        body = None if payload is None else (json.dumps(payload).encode() if content_type == "application/json" else payload)
        request = Request(self.base + path, data=body, method=method, headers={"Content-Type": content_type})
        with urlopen(request) as response:
            data = response.read()
            return response.status, json.loads(data) if "json" in response.headers.get("Content-Type", "") else data

    def test_mixed_vocabulary_queue_round_status_and_reset(self):
        created = []
        for term, kind, collection in [('adapt', 'word', 'general'), ('in turn', 'phrase', 'general'),
                                        ('This is a separate complete sentence.', 'sentence', 'general'),
                                        ('voltage', 'word', 'academic')]:
            _, item = self.request('POST', '/api/items', dict(term=term, chinese_meaning='测试',
                                                            item_type=kind, collection=collection))
            created.append(item)
        expected = {item['id'] for item in created[:2]}
        _, queue = self.request('GET', '/api/reviews?scope=recent&item_type=vocabulary')
        self.assertEqual({i['id'] for i in queue['items']}, expected)
        self.assertTrue(all(i['cloze'] for i in queue['items']))
        payload = dict(mode='recall', item_type='vocabulary', limit=100)
        _, drawn = self.request('POST', '/api/review-round', payload)
        self.assertEqual({i['id'] for i in drawn['items']}, expected)
        self.assertEqual((drawn['total'], drawn['used'], drawn['remaining']), (2, 2, 0))
        _, status = self.request('GET', '/api/review-round?mode=recall&item_type=vocabulary')
        self.assertEqual((status['total'], status['used'], status['remaining']), (2, 2, 0))
        _, exhausted = self.request('POST', '/api/review-round', payload)
        self.assertEqual(exhausted['items'], [])
        self.request('POST', '/api/review-round/reset', payload)
        _, reset = self.request('POST', '/api/review-round', payload)
        self.assertEqual({i['id'] for i in reset['items']}, expected)
        self.assertEqual(reset['round'], 2)
        with self.assertRaises(HTTPError) as error:
            self.request('GET', '/api/reviews?scope=recent&item_type=everything')
        self.assertEqual(error.exception.code, 400)

    def test_crud_review_group_and_csv_routes(self):
        _, health = self.request("GET", "/api/health")
        self.assertEqual(health["app"], "my-vocabulary")
        self.assertEqual(health["api_version"], 4)
        _, adapt = self.request("POST", "/api/items", {"term": "adapt", "chinese_meaning": "适应"})
        _, adopt = self.request("POST", "/api/items", {"term": "adopt", "chinese_meaning": "采用"})
        _, today_words = self.request("GET", "/api/reviews?scope=today")
        self.assertEqual(len(today_words["items"]), 2)
        _, recent_words = self.request("GET", "/api/reviews?scope=recent&limit=1")
        self.assertEqual([item["id"] for item in recent_words["items"]], [adopt["id"]])
        _, listing = self.request("GET", "/api/items?q=adapt")
        self.assertEqual(listing["total"], 1)
        _, group = self.request("POST", "/api/confusion-groups", {"name": "adapt/adopt", "item_ids": [adapt["id"], adopt["id"]]})
        _, queue = self.request("GET", f'/api/reviews?scope=group&group_id={group["id"]}')
        self.assertEqual(len(queue["items"]), 2)
        _, random_round = self.request("POST", "/api/review-round", {"mode": "recall", "limit": 2, "strategy": "forgetting"})
        self.assertEqual(len(random_round["items"]), 2)
        self.assertEqual(random_round["strategy"], "forgetting")
        _, spelling_round = self.request("POST", "/api/review-round", {"mode": "zh_to_en", "limit": 2})
        self.assertEqual(len(spelling_round["items"]), 2)
        _, exhausted = self.request("POST", "/api/review-round", {"mode": "recall", "limit": 2})
        self.assertEqual(exhausted["items"], [])
        _, status = self.request("GET", "/api/review-round?mode=recall")
        self.assertEqual(status["remaining"], 0)
        self.request("POST", "/api/review-round/reset", {"mode": "recall"})
        _, reset_round = self.request("POST", "/api/review-round", {"mode": "recall", "limit": 2})
        self.assertEqual(len(reset_round["items"]), 2)
        _, reviewed = self.request("POST", "/api/reviews", {"item_id": adapt["id"], "rating": "remembered", "mode": "zh_to_en", "answer": "adapt", "first_try_correct": True, "affects_schedule": False, "client_token": "http-token"})
        self.assertEqual(reviewed["next_review_at"], adapt["next_review_at"])
        _, recalled = self.request("POST", "/api/reviews", {"item_id": adopt["id"], "rating": "forgot", "mode": "recall", "answer": "ignored", "first_try_correct": False, "affects_schedule": False, "client_token": "recall-token"})
        self.assertEqual(recalled["next_review_at"], adopt["next_review_at"])
        _, unrecalled = self.request("POST", "/api/reviews", {"item_id": adapt["id"], "rating": "unrecalled", "mode": "recall", "answer": "", "first_try_correct": False, "affects_schedule": False, "client_token": "unrecalled-token"})
        self.assertEqual(unrecalled["next_review_at"], adapt["next_review_at"])
        _, activity = self.request("GET", "/api/activity?days=28")
        self.assertEqual(activity["series"][-1]["added"], 2)
        self.assertEqual(activity["series"][-1]["reviews"], 3)
        self.assertGreater(activity["series"][-1]["score"], 0)
        _, all_stats = self.request("GET", "/api/stats?days=all")
        self.assertEqual(all_stats["days"], "all")
        self.assertEqual(sum(point["added"] for point in all_stats["series"]), 2)
        status, exported = self.request("GET", "/api/export.csv")
        self.assertEqual(status, 200)
        self.assertTrue(exported.startswith(b"\xef\xbb\xbf"))

    def test_repeated_review_errors_adjust_mastery_once_through_http(self):
        _, item = self.request('POST', '/api/items', {'term': 'persistent', 'chinese_meaning': '持久的'})
        self.request('PUT', f'/api/items/{item["id"]}', {'status': 'mastered'})
        for index, mode in enumerate(('recall', 'zh_to_en', 'cloze')):
            payload = {'item_id': item['id'], 'rating': 'forgot', 'mode': mode,
                       'answer': '' if mode == 'recall' else 'persistant', 'first_try_correct': False,
                       'affects_schedule': False, 'scope': 'random', 'client_token': f'adapt-{index}'}
            _, saved = self.request('POST', '/api/reviews', payload)
            self.assertEqual(saved['status'], 'familiar' if index == 2 else 'mastered')
        _, retried = self.request('POST', '/api/reviews', payload)
        self.assertEqual(retried['status'], 'familiar')
        _, loaded = self.request('GET', f'/api/items/{item["id"]}')
        self.assertEqual(loaded['status'], 'familiar')
        self.assertEqual(len(loaded['recent_reviews']), 3)
        self.assertEqual(loaded['next_review_at'], item['next_review_at'])

    def test_daily_expression_routes_are_isolated_from_review_and_stats(self):
        _, before_stats = self.request("GET", "/api/stats?days=7")
        _, before_activity = self.request("GET", "/api/activity?days=28")
        _, before_dashboard = self.request("GET", "/api/dashboard")
        _, listing = self.request("GET", "/api/daily-expressions")
        self.assertEqual(listing["total"], 24)
        starter = listing["items"][0]
        status, custom = self.request("POST", "/api/daily-expressions", {
            "phrase": "Works for me.", "meaning": "我觉得可以", "category": "口语"
        })
        self.assertEqual(status, 201)
        _, saved = self.request("PUT", f'/api/daily-expressions/{starter["id"]}', {"is_favorite": True})
        self.assertTrue(saved["is_favorite"])
        _, custom = self.request("PUT", f'/api/daily-expressions/{custom["id"]}', {"usage": "回应建议"})
        self.assertEqual(custom["usage"], "回应建议")
        for path, expected in (("/api/stats?days=7", before_stats),
                               ("/api/activity?days=28", before_activity),
                               ("/api/dashboard", before_dashboard)):
            self.assertEqual(self.request("GET", path)[1], expected)
        self.assertEqual(self.request("GET", "/api/items")[1]["total"], 0)
        self.assertEqual(self.request("GET", "/api/expressions")[1]["total"], 0)
        for scope in ("due", "recent", "study", "today", "mistakes"):
            for item_type in ("word", "phrase", "sentence"):
                queue = self.request("GET", f"/api/reviews?scope={scope}&item_type={item_type}")[1]
                self.assertEqual(queue["items"], [])
        for item_type in ("word", "phrase", "sentence"):
            queue = self.request("POST", "/api/review-round", {"item_type": item_type})[1]
            self.assertEqual(queue["items"], [])
        with self.assertRaises(HTTPError) as missing:
            self.request("PUT", "/api/daily-expressions/999999", {"is_favorite": True})
        self.assertEqual(missing.exception.code, 404)
        missing.exception.close()

    def test_daily_delete_and_restore_routes_preserve_learning_stats(self):
        _, before = self.request("GET", "/api/stats?days=7")
        _, listing = self.request("GET", "/api/daily-expressions")
        item = listing["items"][0]
        status, _ = self.request("DELETE", f'/api/daily-expressions/{item["id"]}')
        self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", "/api/daily-expressions")[1]["total"], 23)
        for method in ("GET", "DELETE", "PUT"):
            with self.subTest(method=method), self.assertRaises(HTTPError) as missing:
                self.request(method, f'/api/daily-expressions/{item["id"]}', {"is_favorite": True})
            self.assertEqual(missing.exception.code, 404)
            missing.exception.close()
        _, trash = self.request("GET", "/api/daily-expressions/trash")
        self.assertEqual(trash["items"][0]["id"], item["id"])
        status, restored = self.request("POST", f'/api/daily-expressions/{item["id"]}/restore', {})
        self.assertEqual(status, 200)
        self.assertEqual(restored, item)
        self.assertEqual(self.request("GET", "/api/daily-expressions")[1]["deleted_total"], 0)
        self.assertEqual(self.request("GET", "/api/stats?days=7")[1], before)

    def test_validation_and_duplicate_statuses(self):
        with self.assertRaises(HTTPError) as missing:
            self.request("POST", "/api/items", {"term": "", "chinese_meaning": "空"})
        self.assertEqual(missing.exception.code, 400)
        missing.exception.close()
        self.request("POST", "/api/items", {"term": "same", "chinese_meaning": "相同"})
        with self.assertRaises(HTTPError) as duplicate:
            self.request("POST", "/api/items", {"term": "Same", "chinese_meaning": "相同"})
        self.assertEqual(duplicate.exception.code, 409)
        duplicate.exception.close()

    def test_expression_library_api_is_independent_and_persistent(self):
        payload = {
            "content_type": "范文",
            "title": "A two-paragraph essay",
            "english_text": "Opening paragraph.\n\nClosing paragraph.",
            "chinese_text": "开头段。\n\n结尾段。",
            "exam_type": "雅思",
            "topic": "教育与科技",
            "tags": ["Task 2"],
        }
        status, material = self.request("POST", "/api/expressions", payload)
        self.assertEqual(status, 201)
        self.assertEqual(material["english_text"], payload["english_text"])
        _, vocabulary = self.request("GET", "/api/items")
        self.assertEqual(vocabulary["total"], 0)

        _, opened = self.request("POST", f'/api/expressions/{material["id"]}/open', {})
        self.assertEqual(opened["read_count"], 1)
        _, state = self.request("PUT", f'/api/expressions/{material["id"]}/state', {
            "scroll_ratio": .55,
            "translation_visible": False,
            "font_scale": 1.1,
            "line_height": 2.05,
        })
        self.assertAlmostEqual(state["scroll_ratio"], .55)
        self.assertFalse(state["translation_visible"])
        _, favorite = self.request("PUT", f'/api/expressions/{material["id"]}/favorite', {"favorite": True})
        self.assertTrue(favorite["is_favorite"])
        _, summary = self.request("GET", "/api/expression-summary")
        self.assertEqual(summary["favorite_count"], 1)
        self.assertEqual(summary["total_reads"], 1)
        self.assertEqual(summary["continue_reading"]["id"], material["id"])

        _, updated = self.request("PUT", f'/api/expressions/{material["id"]}', {"chinese_text": "后补翻译"})
        self.assertEqual(updated["chinese_text"], "后补翻译")
        deleted, _ = self.request("DELETE", f'/api/expressions/{material["id"]}')
        self.assertEqual(deleted, 204)

    def test_study_mode_selects_recent_words_and_rejects_saved_answers(self):
        old = self.request("POST", "/api/items", {"term": "older", "chinese_meaning": "旧"})[1]
        phrase = self.request("POST", "/api/items", {"term": "Take care on the road.", "chinese_meaning": "路上小心。", "item_type": "phrase"})[1]
        sentence = self.request("POST", "/api/items", {"term": "The figure saw a gradual decline over the period.", "chinese_meaning": "该数据在这一时期逐渐下降。", "item_type": "sentence"})[1]
        new = self.request("POST", "/api/items", {"term": "newer", "chinese_meaning": "新"})[1]
        _, queue = self.request("GET", "/api/reviews?scope=study&limit=1")
        self.assertEqual([item["id"] for item in queue["items"]], [new["id"]])
        _, queue = self.request("GET", "/api/reviews?scope=study&limit=20")
        self.assertEqual([item["id"] for item in queue["items"]], [new["id"], old["id"]])
        _, phrase_queue = self.request("GET", "/api/reviews?scope=study&limit=20&item_type=phrase")
        self.assertEqual([item["id"] for item in phrase_queue["items"]], [phrase["id"]])
        _, sentence_queue = self.request("GET", "/api/reviews?scope=study&limit=20&item_type=sentence")
        self.assertEqual([item["id"] for item in sentence_queue["items"]], [sentence["id"]])
        _, sentence_round = self.request("POST", "/api/review-round", {"mode": "recall", "limit": 20, "item_type": "sentence"})
        self.assertEqual({item["item_type"] for item in sentence_round["items"]}, {"sentence"})
        with self.assertRaises(HTTPError) as invalid_type:
            self.request("GET", "/api/reviews?scope=recent&item_type=all")
        self.assertEqual(invalid_type.exception.code, 400)
        invalid_type.exception.close()
        with self.assertRaises(HTTPError) as rejected:
            self.request("POST", "/api/reviews", {"item_id": new["id"], "scope": "study", "rating": "forgot", "mode": "recall", "first_try_correct": False})
        self.assertEqual(rejected.exception.code, 400)
        rejected.exception.close()
        _, stats = self.request("GET", "/api/stats?days=7")
        self.assertEqual(sum(day["reviews"] for day in stats["series"]), 0)
        _, item = self.request("GET", f'/api/items/{new["id"]}')
        self.assertEqual(item["status"], "new")
        self.assertEqual(item["review_count"], 0)

    def test_source_fingerprint_is_stable_for_unchanged_sources(self):
        from vocabulary import http_app

        first = http_app.source_fingerprint()
        self.assertIsNotNone(first)
        self.assertEqual(first, http_app.source_fingerprint())

    def test_health_reports_a_service_whose_sources_changed_since_startup(self):
        # The page is always read fresh from disk while a running service keeps serving the code it
        # imported at start-up. That drift once left an updated page talking to an old payload, so
        # the service has to admit it instead of passing the health check forever.
        from vocabulary import http_app

        _, health = self.request("GET", "/api/health")
        self.assertTrue(health["ok"])
        self.assertNotIn("stale", health)

        original = http_app.source_fingerprint
        self.addCleanup(setattr, http_app, "source_fingerprint", original)
        http_app.source_fingerprint = lambda: "a-fingerprint-from-a-later-build"

        with self.assertRaises(HTTPError) as raised:
            self.request("GET", "/api/health")
        self.assertEqual(raised.exception.code, 503)
        payload = json.loads(raised.exception.read())
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["stale"])
        # The desktop shell still needs the identity fields, which is how it recognises its own
        # service before it decides to replace it.
        self.assertEqual(payload["app"], "my-vocabulary")
        self.assertEqual(payload["api_version"], 4)


if __name__ == "__main__":
    unittest.main()
