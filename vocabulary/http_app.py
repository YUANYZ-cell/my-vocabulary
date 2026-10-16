from __future__ import annotations

import hashlib
import json
import mimetypes
import socket
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .csv_io import CsvImportError, CsvService
from .academic_categories import AcademicCategoryRepository
from .database import Database
from .daily_expressions import DailyExpressionRepository
from .daily_groups import DailyGroupRepository
from .content_moves import ContentMoveRepository
from .expressions import ExpressionRepository
from .groups import ConfusionGroupRepository
from .items import DuplicateItemError, ItemRepository, ValidationError, validate_collection, validate_collection_filter
from .reviews import ReviewRepository
from .srs import make_cloze
from .stats import StatsRepository


def source_fingerprint() -> str | None:
    """Hash the backend sources that this process has already imported.

    A running service keeps serving the code it imported at start-up while the page is always read
    fresh from disk, so editing the backend silently splits the two halves of the app. The service
    fingerprints itself once and compares that against the files on disk, which is what lets it
    admit that it is no longer the current build instead of answering with a payload the page no
    longer understands.
    """
    try:
        root = Path(__file__).resolve().parent
        sources = sorted(root.glob("*.py")) + [root.parent / "start.py"]
        digest = hashlib.sha256()
        for source in sources:
            if source.is_file():
                digest.update(source.read_bytes())
        return digest.hexdigest()
    except OSError:
        # Never let a fingerprinting problem take the service down: unknown means "not stale".
        return None


class VocabularyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        # Windows SO_REUSEADDR can let two servers bind the same local port.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, handler, idle_timeout: int):
        super().__init__(address, handler)
        self.idle_timeout = idle_timeout
        self.last_heartbeat: float | None = None
        self.source_fingerprint = source_fingerprint()

    def heartbeat(self) -> None:
        self.last_heartbeat = time.monotonic()

    def start_idle_monitor(self) -> None:
        if self.idle_timeout <= 0:
            return

        def monitor():
            while True:
                time.sleep(min(30, max(1, self.idle_timeout // 4)))
                if self.last_heartbeat is not None and time.monotonic() - self.last_heartbeat > self.idle_timeout:
                    self.shutdown()
                    return

        threading.Thread(target=monitor, daemon=True).start()


def create_server(host: str, port: int, database_path: Path, app_dir: Path, idle_timeout: int = 900) -> VocabularyServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("本地服务只能绑定回环地址。")
    database = Database(database_path)
    database.initialize()
    daily_groups = DailyGroupRepository(database)
    items = ItemRepository(database)
    categories = AcademicCategoryRepository(database)
    groups = ConfusionGroupRepository(database, items)
    reviews = ReviewRepository(database, items, groups)
    stats = StatsRepository(database)
    expressions = ExpressionRepository(database)
    daily_expressions = DailyExpressionRepository(database)
    content_moves = ContentMoveRepository(database)
    csv_service = CsvService(items)
    static_root = app_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "MyVocabulary/1.0"

        def log_message(self, format, *args):
            return

        def _json(self, status: int, payload: dict | list) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _is_stale(self) -> bool:
            known = getattr(self.server, "source_fingerprint", None)
            current = source_fingerprint()
            return known is not None and current is not None and known != current

        def _body(self, limit: int) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValidationError("请求长度无效。") from error
            if length > limit:
                raise ValidationError("请求内容过大。")
            return self.rfile.read(length)

        def _json_body(self) -> dict:
            try:
                value = json.loads(self._body(1_048_576).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValidationError("JSON 请求格式无效。") from error
            if not isinstance(value, dict):
                raise ValidationError("JSON 请求必须是对象。")
            return value

        def _download(self, filename: str, content: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def _dispatch(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            if path == "/api/health" and method == "GET":
                # Admitting the drift is what lets the desktop shell replace this process with one
                # built from the current files: a stale payload would otherwise keep passing for as
                # long as the port answers at all.
                # The fingerprint names the build this process is actually running, which is what
                # lets an operator tell a stale service from a current one without guessing.
                build = getattr(self.server, "source_fingerprint", None)
                if self._is_stale():
                    return self._json(503, {"ok": False, "app": "my-vocabulary", "api_version": 4,
                                            "stale": True, "fingerprint": build})
                return self._json(200, {"ok": True, "app": "my-vocabulary", "api_version": 4,
                                        "fingerprint": build})
            if path == "/api/heartbeat" and method == "POST":
                self.server.heartbeat()
                return self._json(200, {"ok": True})
            if path == "/api/dashboard" and method == "GET":
                return self._json(200, stats.dashboard(date.today()))
            if path == "/api/facets" and method == "GET":
                return self._json(200, items.facets(query.get("collection", "general"), query.get("category_id")))
            if path == "/api/content-moves/preview" and method == "POST":
                return self._json(200, content_moves.preview(self._json_body()))
            if path == "/api/content-moves" and method == "POST":
                return self._json(200, content_moves.move(self._json_body()))
            if path == "/api/content-moves/retained" and method == "GET":
                return self._json(200, content_moves.retained(query.get("source"), query.get("item_id")))
            if path == "/api/academic-categories":
                if method == "GET":
                    return self._json(200, categories.list_categories())
                if method == "POST":
                    return self._json(201, categories.save_category(self._json_body().get("name", "")))
            if path == "/api/academic-categories/assign" and method == "PUT":
                payload = self._json_body()
                return self._json(200, categories.assign_items(payload.get("item_ids"), payload.get("academic_category_id")))
            if path.startswith("/api/academic-categories/"):
                category_id = int(path.rsplit("/", 1)[-1])
                if method == "PUT":
                    return self._json(200, categories.save_category(self._json_body().get("name", ""), category_id))
                if method == "DELETE":
                    if not categories.delete_category(category_id):
                        return self._error(404, "not_found", "学术分类不存在。")
                    return self._json(200, {"deleted": True})
            if path == "/api/daily-groups":
                if method == "GET":
                    return self._json(200, daily_groups.list_groups())
                if method == "POST":
                    return self._json(201, daily_groups.save_group(self._json_body().get("name")))
            if path.startswith("/api/daily-groups/"):
                group_id = int(path.rsplit("/", 1)[-1])
                if method == "PUT":
                    group = daily_groups.save_group(self._json_body().get("name"), group_id)
                    return self._json(200, group) if group else self._error(404, "not_found", "合集不存在。")
                if method == "DELETE":
                    if not daily_groups.delete_group(group_id):
                        return self._error(404, "not_found", "合集不存在。")
                    return self._json(200, {"deleted": True})
            if path == "/api/daily-expressions":
                if method == "GET":
                    return self._json(200, daily_expressions.list_items())
                if method == "POST":
                    return self._json(201, daily_expressions.save_item(self._json_body()))
            if path == "/api/daily-expressions/trash" and method == "GET":
                return self._json(200, daily_expressions.list_items(deleted=True))
            if path.startswith("/api/daily-expressions/"):
                parts = path.strip("/").split("/")
                item_id = int(parts[2])
                if len(parts) == 4 and parts[3] == "restore" and method == "POST":
                    item = daily_expressions.restore_item(item_id)
                elif len(parts) != 3:
                    return self._error(404, "not_found", "日常表达不存在。")
                elif method == "DELETE":
                    if not daily_expressions.delete_item(item_id):
                        return self._error(404, "not_found", "日常表达不存在。")
                    return self._json(200, {"deleted": True})
                elif method == "GET":
                    item = daily_expressions.get_item(item_id)
                elif method == "PUT":
                    item = daily_expressions.save_item(self._json_body(), item_id)
                else:
                    return self._error(405, "method_not_allowed", "请求方法不支持。")
                if item is None:
                    return self._error(404, "not_found", "日常表达不存在。")
                return self._json(200, item)
            if path == "/api/expression-summary" and method == "GET":
                return self._json(200, expressions.summary())
            if path == "/api/expression-facets" and method == "GET":
                return self._json(200, expressions.facets())
            if path == "/api/expressions":
                if method == "GET":
                    return self._json(200, expressions.list_items(query))
                if method == "POST":
                    return self._json(201, expressions.create_item(self._json_body()))
            if path.startswith("/api/expressions/"):
                parts = path.strip("/").split("/")
                try:
                    expression_id = int(parts[2])
                except (IndexError, ValueError):
                    return self._error(404, "not_found", "表达素材不存在。")
                action = parts[3] if len(parts) > 3 else ""
                if action == "open" and method == "POST":
                    return self._json(200, expressions.record_open(expression_id))
                if action == "state" and method == "PUT":
                    return self._json(200, expressions.save_reading_state(expression_id, self._json_body()))
                if action == "favorite" and method == "PUT":
                    return self._json(200, expressions.set_favorite(
                        expression_id, bool(self._json_body().get("favorite", False))
                    ))
                if action:
                    return self._error(404, "not_found", "接口不存在。")
                if method == "GET":
                    item = expressions.get_item(expression_id)
                    return self._json(200, item) if item else self._error(404, "not_found", "表达素材不存在。")
                if method == "PUT":
                    return self._json(200, expressions.update_item(expression_id, self._json_body()))
                if method == "DELETE":
                    if not expressions.delete_item(expression_id):
                        return self._error(404, "not_found", "表达素材不存在。")
                    self.send_response(204)
                    self.end_headers()
                    return
            if path == "/api/items":
                if method == "GET":
                    return self._json(200, items.list_items(query))
                if method == "POST":
                    return self._json(201, items.create_item(self._json_body()))
            if path.startswith("/api/items/"):
                try:
                    item_id = int(path.rsplit("/", 1)[-1])
                except ValueError:
                    return self._error(404, "not_found", "词条不存在。")
                if method == "GET":
                    item = items.get_item(item_id)
                    return self._json(200, item) if item else self._error(404, "not_found", "词条不存在。")
                if method == "PUT":
                    return self._json(200, items.update_item(item_id, self._json_body()))
                if method == "DELETE":
                    if not items.delete_item(item_id):
                        return self._error(404, "not_found", "词条不存在。")
                    self.send_response(204)
                    self.end_headers()
                    return
            if path == "/api/reviews" and method == "GET":
                scope = query.get("scope", "due")
                group_id = int(query["group_id"]) if query.get("group_id") else None
                queue = reviews.get_queue(
                    scope, date.today(), int(query.get("limit", 20)), group_id,
                    query.get("item_type", "word"), query.get("collection", "general"), query.get("category_id"),
                )
                return self._json(200, {"items": [{**item, "cloze": make_cloze(item["term"])} for item in queue]})
            if path == "/api/review-round" and method == "GET":
                return self._json(200, reviews.random_round_status(
                    date.today(), query.get("mode", "recall"), query.get("item_type", "word"), query.get("collection", "general"), query.get("category_id")
                ))
            if path == "/api/review-round" and method == "POST":
                payload = self._json_body()
                data = reviews.start_random_round(
                    date.today(), str(payload.get("mode", "recall")), int(payload.get("limit", 20)),
                    str(payload.get("strategy", "balanced")), str(payload.get("item_type", "word")), str(payload.get("collection", "general")), payload.get("category_id"),
                )
                data["items"] = [{**item, "cloze": make_cloze(item["term"])} for item in data["items"]]
                return self._json(200, data)
            if path == "/api/review-round/reset" and method == "POST":
                payload = self._json_body()
                return self._json(200, reviews.reset_random_round(
                    date.today(), str(payload.get("mode", "recall")), str(payload.get("item_type", "word")), str(payload.get("collection", "general")), payload.get("category_id")
                ))
            if path in {"/api/reviews", "/api/reviews/boost"} and method == "POST":
                payload = self._json_body()
                result = reviews.record_review(
                    int(payload.get("item_id", 0)), str(payload.get("rating", "")), date.today(),
                    str(payload.get("mode", "")), str(payload.get("answer", "")),
                    payload.get("first_try_correct"), bool(payload.get("affects_schedule", True)),
                    str(payload.get("client_token", "")), str(payload.get("scope", "due")),
                    mastery_boost=path == "/api/reviews/boost",
                )
                return self._json(200, result)
            if path == "/api/confusion-groups":
                if method == "GET":
                    collection = validate_collection_filter(query.get("collection", "general"))
                    return self._json(200, {"items": [g for g in groups.list_groups()
                        if collection == "all" or all(i["collection"] == collection for i in g["items"])]})
                if method == "POST":
                    payload = self._json_body()
                    return self._json(201, groups.create_group(str(payload.get("name", "")), payload.get("item_ids", [])))
            if path.startswith("/api/confusion-groups/"):
                try:
                    group_id = int(path.rsplit("/", 1)[-1])
                except ValueError:
                    return self._error(404, "not_found", "易混词组不存在。")
                if method == "GET":
                    group = groups.get_group(group_id)
                    return self._json(200, group) if group else self._error(404, "not_found", "易混词组不存在。")
                if method == "PUT":
                    payload = self._json_body()
                    return self._json(200, groups.update_group(group_id, str(payload.get("name", "")), payload.get("item_ids", [])))
                if method == "DELETE":
                    if not groups.delete_group(group_id):
                        return self._error(404, "not_found", "易混词组不存在。")
                    self.send_response(204)
                    self.end_headers()
                    return
            if path == "/api/confusion-suggestions" and method == "GET":
                return self._json(200, {"items": groups.suggest_similar(int(query.get("item_id", 0)))})
            if path == "/api/stats" and method == "GET":
                period = query.get("days", "7")
                return self._json(200, stats.period("all" if period == "all" else int(period), date.today()))
            if path == "/api/activity" and method == "GET":
                return self._json(200, stats.activity(date.today(), int(query.get("days", 371))))
            if path == "/api/template.csv" and method == "GET":
                return self._download("my-vocabulary-template.csv", csv_service.template())
            if path == "/api/export.csv" and method == "GET":
                collection = validate_collection_filter(query.get("collection", "general"))
                return self._download("my-vocabulary.csv", csv_service.export_items(None if collection == "all" else collection, query.get("category_id")))
            if path == "/api/import.csv" and method == "POST":
                collection = validate_collection_filter(query.get("collection", "general"))
                return self._json(200, csv_service.import_bytes(self._body(10_485_760), None if collection == "all" else collection, query.get("category_id")))
            if path.startswith("/api/"):
                return self._error(404, "not_found", "接口不存在。")
            if method != "GET":
                return self._error(405, "method_not_allowed", "请求方法不支持。")
            relative = "index.html" if path == "/" else path.lstrip("/")
            target = (static_root / relative).resolve()
            if static_root not in target.parents and target != static_root:
                return self._error(404, "not_found", "文件不存在。")
            if not target.is_file():
                target = static_root / "index.html"
            if not target.is_file():
                return self._error(404, "not_found", "应用页面尚未安装。")
            content = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)

        def _handle(self, method: str) -> None:
            try:
                self._dispatch(method)
            except DuplicateItemError as error:
                self._error(409, "duplicate_item", str(error))
            except (ValidationError, CsvImportError, ValueError) as error:
                self._error(400, "validation_error", str(error))
            except Exception:
                self._error(500, "server_error", "本地服务处理请求失败。")

        def do_GET(self): self._handle("GET")
        def do_POST(self): self._handle("POST")
        def do_PUT(self): self._handle("PUT")
        def do_DELETE(self): self._handle("DELETE")

    server = VocabularyServer((host, port), Handler, idle_timeout)
    return server
