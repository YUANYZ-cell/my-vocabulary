from __future__ import annotations

import json
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime
from typing import Any

from .database import Database
from .items import ValidationError


TEXT_LIMITS = {
    "content_type": 80,
    "title": 240,
    "english_text": 200_000,
    "chinese_text": 200_000,
    "exam_type": 80,
    "topic": 120,
    "source": 1000,
    "notes": 20_000,
    "illustration_path": 500,
}


def _clean_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _string_list(value: Any, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field}必须是字符串列表。")
    result: list[str] = []
    for part in value:
        if not isinstance(part, str):
            raise ValidationError(f"{field}必须是字符串列表。")
        clean = _clean_text(part)
        if clean and clean not in result:
            result.append(clean)
    return result


class ExpressionRepository:
    """Independent reading library that never participates in vocabulary review."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _row_to_item(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        item["tags"] = json.loads(item.get("tags", "[]") or "[]")
        item["is_favorite"] = bool(item.get("is_favorite"))
        item["translation_visible"] = bool(item.get("translation_visible"))
        item["read_count"] = int(item.get("read_count") or 0)
        item["scroll_ratio"] = float(item.get("scroll_ratio") or 0)
        item["font_scale"] = float(item.get("font_scale") or 1)
        item["line_height"] = float(item.get("line_height") or 1.85)
        return item

    def _validated(self, payload: dict, existing: dict | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ValidationError("表达素材数据格式不正确。")
        merged = {**(existing or {}), **payload}
        values = {field: _clean_text(merged.get(field, "")) for field in TEXT_LIMITS}
        if not values["content_type"]:
            raise ValidationError("请选择内容类型。")
        if not values["title"]:
            raise ValidationError("请输入标题。")
        if not values["english_text"]:
            raise ValidationError("请输入英文原文。")
        for field, limit in TEXT_LIMITS.items():
            if len(values[field]) > limit:
                raise ValidationError(f"{field} 内容过长。")
        illustration_path = values["illustration_path"].replace("\\", "/")
        if illustration_path and (
            not illustration_path.startswith("/assets/")
            or ".." in illustration_path.split("/")
        ):
            raise ValidationError("插图路径必须指向应用 assets 目录。")
        values["illustration_path"] = illustration_path
        values["tags"] = _string_list(merged.get("tags", []), "自定义标签")
        values["is_favorite"] = bool(merged.get("is_favorite", False))
        return values

    def create_item(self, payload: dict) -> dict:
        values = self._validated(payload)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO expression_materials(
                    content_type, title, english_text, chinese_text, exam_type,
                    topic, tags, source, notes, illustration_path, is_favorite,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["content_type"], values["title"], values["english_text"],
                    values["chinese_text"], values["exam_type"], values["topic"],
                    json.dumps(values["tags"], ensure_ascii=False), values["source"],
                    values["notes"], values["illustration_path"],
                    int(values["is_favorite"]), now, now,
                ),
            )
            item_id = int(cursor.lastrowid)
        return self.get_item(item_id)

    def get_item(self, item_id: int) -> dict | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                """
                SELECT m.*, COALESCE(r.read_count, 0) AS read_count,
                       r.last_read_at, COALESCE(r.scroll_ratio, 0) AS scroll_ratio,
                       COALESCE(r.translation_visible, 1) AS translation_visible,
                       COALESCE(r.font_scale, 1) AS font_scale,
                       COALESCE(r.line_height, 1.85) AS line_height
                FROM expression_materials m
                LEFT JOIN expression_reading_state r ON r.material_id = m.id
                WHERE m.id = ?
                """,
                (item_id,),
            ).fetchone()
        return self._row_to_item(row)

    def update_item(self, item_id: int, payload: dict) -> dict:
        existing = self.get_item(item_id)
        if not existing:
            raise ValidationError("表达素材不存在。")
        values = self._validated(payload, existing)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE expression_materials SET content_type=?, title=?, english_text=?,
                    chinese_text=?, exam_type=?, topic=?, tags=?, source=?, notes=?,
                    illustration_path=?, is_favorite=?, updated_at=? WHERE id=?
                """,
                (
                    values["content_type"], values["title"], values["english_text"],
                    values["chinese_text"], values["exam_type"], values["topic"],
                    json.dumps(values["tags"], ensure_ascii=False), values["source"],
                    values["notes"], values["illustration_path"],
                    int(values["is_favorite"]), now, item_id,
                ),
            )
        return self.get_item(item_id)

    def set_favorite(self, item_id: int, favorite: bool) -> dict:
        if not self.get_item(item_id):
            raise ValidationError("表达素材不存在。")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE expression_materials SET is_favorite=?, updated_at=? WHERE id=?",
                (int(favorite), now, item_id),
            )
        return self.get_item(item_id)

    def delete_item(self, item_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM expression_materials WHERE id=?", (item_id,))
            return cursor.rowcount > 0

    def record_open(self, item_id: int) -> dict:
        if not self.get_item(item_id):
            raise ValidationError("表达素材不存在。")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO expression_read_history(material_id, opened_at) VALUES(?, ?)",
                (item_id, now),
            )
            connection.execute(
                """
                INSERT INTO expression_reading_state(material_id, read_count, last_read_at)
                VALUES(?, 1, ?)
                ON CONFLICT(material_id) DO UPDATE SET
                    read_count=expression_reading_state.read_count + 1,
                    last_read_at=excluded.last_read_at
                """,
                (item_id, now),
            )
        return self.get_item(item_id)

    def save_reading_state(self, item_id: int, payload: dict) -> dict:
        if not self.get_item(item_id):
            raise ValidationError("表达素材不存在。")
        try:
            scroll_ratio = min(1, max(0, float(payload.get("scroll_ratio", 0))))
            font_scale = min(1.35, max(0.85, float(payload.get("font_scale", 1))))
            line_height = min(2.2, max(1.45, float(payload.get("line_height", 1.85))))
        except (TypeError, ValueError) as error:
            raise ValidationError("阅读设置格式无效。") from error
        translation_visible = bool(payload.get("translation_visible", True))
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO expression_reading_state(
                    material_id, scroll_ratio, translation_visible, font_scale, line_height
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(material_id) DO UPDATE SET
                    scroll_ratio=excluded.scroll_ratio,
                    translation_visible=excluded.translation_visible,
                    font_scale=excluded.font_scale,
                    line_height=excluded.line_height
                """,
                (item_id, scroll_ratio, int(translation_visible), font_scale, line_height),
            )
        return self.get_item(item_id)

    def all_items(self) -> list[dict]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                """
                SELECT m.*, COALESCE(r.read_count, 0) AS read_count,
                       r.last_read_at, COALESCE(r.scroll_ratio, 0) AS scroll_ratio,
                       COALESCE(r.translation_visible, 1) AS translation_visible,
                       COALESCE(r.font_scale, 1) AS font_scale,
                       COALESCE(r.line_height, 1.85) AS line_height
                FROM expression_materials m
                LEFT JOIN expression_reading_state r ON r.material_id = m.id
                """
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def list_items(self, filters: dict | None = None) -> dict:
        filters = filters or {}
        items = self.all_items()
        query = _clean_text(filters.get("q", "")).casefold()
        if query:
            items = [
                item for item in items
                if query in " ".join([
                    item["title"], item["english_text"], item["chinese_text"],
                    item["exam_type"], item["topic"], item["source"], item["notes"],
                    " ".join(item["tags"]),
                ]).casefold()
            ]
        for filter_key, item_key in (("type", "content_type"), ("exam", "exam_type"), ("topic", "topic")):
            if filters.get(filter_key):
                items = [item for item in items if item[item_key] == filters[filter_key]]
        if filters.get("tag"):
            items = [item for item in items if filters["tag"] in item["tags"]]
        if str(filters.get("favorite", "")).lower() in {"1", "true", "yes"}:
            items = [item for item in items if item["is_favorite"]]
        sort = str(filters.get("sort", "recent"))
        sorters = {
            "recent": (lambda item: (item["last_read_at"] or "", item["updated_at"], item["id"]), True),
            "newest": (lambda item: (item["created_at"], item["id"]), True),
            "oldest": (lambda item: (item["created_at"], item["id"]), False),
            "title": (lambda item: (item["title"].casefold(), item["id"]), False),
            "most_read": (lambda item: (item["read_count"], item["last_read_at"] or ""), True),
        }
        if sort not in sorters:
            raise ValidationError("表达库排序参数无效。")
        key, reverse = sorters[sort]
        items.sort(key=key, reverse=reverse)
        total = len(items)
        try:
            page = max(1, int(filters.get("page", 1)))
            page_size = min(100, max(1, int(filters.get("page_size", 50))))
        except (TypeError, ValueError) as error:
            raise ValidationError("分页参数无效。") from error
        start = (page - 1) * page_size
        return {"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size}

    def facets(self) -> dict:
        items = self.all_items()
        return {
            "types": sorted({item["content_type"] for item in items if item["content_type"]}),
            "exams": sorted({item["exam_type"] for item in items if item["exam_type"]}),
            "topics": sorted({item["topic"] for item in items if item["topic"]}),
            "tags": sorted({tag for item in items for tag in item["tags"]}),
        }

    def summary(self) -> dict:
        items = self.all_items()
        counts: dict[str, int] = {}
        for item in items:
            counts[item["content_type"]] = counts.get(item["content_type"], 0) + 1
        recent = sorted(
            (item for item in items if item["last_read_at"]),
            key=lambda item: item["last_read_at"], reverse=True,
        )[:5]
        return {
            "total": len(items),
            "favorite_count": sum(1 for item in items if item["is_favorite"]),
            "total_reads": sum(item["read_count"] for item in items),
            "counts_by_type": counts,
            "recent": recent,
            "continue_reading": recent[0] if recent else None,
        }
