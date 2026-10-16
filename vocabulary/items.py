from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Any

from .content_types import ITEM_TYPES, infer_item_type
from .database import Database


STATUSES = {"new", "learning", "wrong", "familiar", "mastered"}
ITEM_GROUPS = {
    "vocabulary": {"word", "phrase"},
    "sentence": {"sentence"},
}
TEXT_FIELDS = {
    "phonetic",
    "part_of_speech",
    "english_definition",
    "source_sentence",
    "own_sentence",
    "source",
    "notes",
}


class ValidationError(ValueError):
    pass


class DuplicateItemError(ValueError):
    pass


def validate_collection(value: str = "general") -> str:
    if value not in {"general", "academic"}:
        raise ValidationError("词库选择无效。")
    return value


def validate_collection_filter(value: str = "general") -> str:
    """The aggregate library is a view, never a storage or review collection."""
    return value if value == "all" else validate_collection(value)


def parse_category_id(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isascii() or not str(value).isdigit() or int(value) < 1:
        raise ValidationError("学术分类选择无效。")
    return int(value)


def category_clause(connection: sqlite3.Connection, collection: str, value: Any, prefix: str = "") -> tuple[str, list]:
    if value is None or value == "":
        return "", []
    if collection != "academic":
        raise ValidationError("只有学术词汇可以使用学术分类。")
    if value == "uncategorized":
        return f" AND {prefix}academic_category_id IS NULL", []
    category_id = parse_category_id(value)
    if not connection.execute("SELECT 1 FROM academic_categories WHERE id=?", (category_id,)).fetchone():
        raise ValidationError("学术分类不存在，请重新选择。")
    return f" AND {prefix}academic_category_id=?", [category_id]


def normalize_term(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().lower().split())


def normalize_chinese(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def clean_category_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("请输入分类名称。")
    name = " ".join(value.split())
    if not name or len(name) > 60:
        raise ValidationError("分类名称须为 1–60 个字符。")
    if normalize_term(name) in {"未分类", "全部分类", "全部学术词汇"}:
        raise ValidationError("请换一个分类名称，“未分类”和“全部学术词汇”是固定入口。")
    return name


def _string_list(value: Any, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field} 必须是字符串列表。")
    result: list[str] = []
    for part in value:
        if not isinstance(part, str):
            raise ValidationError(f"{field} 必须是字符串列表。")
        clean = part.strip()
        if clean and clean not in result:
            result.append(clean)
    return result


_POS_ALIASES = {
    "n": "noun", "noun": "noun",
    "v": "verb", "vt": "verb", "vi": "verb", "aux": "verb", "verb": "verb",
    "a": "adjective", "adj": "adjective", "adjective": "adjective",
    "adv": "adverb", "adverb": "adverb",
    "pron": "pronoun", "pronoun": "pronoun",
    "prep": "preposition", "preposition": "preposition",
    "conj": "conjunction", "conjunction": "conjunction",
    "int": "interjection", "interj": "interjection", "exclamation": "interjection", "interjection": "interjection",
    "num": "numeral", "numeral": "numeral",
    "art": "article", "article": "article",
    "det": "determiner", "determiner": "determiner",
    "phrasal verb": "phrasal verb", "noun phrase": "noun phrase",
}
_POS_ORDER = {
    label: index for index, label in enumerate((
        "noun", "verb", "adjective", "adverb", "pronoun", "preposition",
        "conjunction", "interjection", "numeral", "article", "determiner",
        "phrasal verb", "noun phrase",
    ))
}
_POS_LABEL = "|".join(re.escape(label) for label in sorted(_POS_ALIASES, key=len, reverse=True))
_POS_PREFIX = re.compile(rf"^({_POS_LABEL})\.?(?=$|\s|[\[（(【<])", re.IGNORECASE)
_POS_SEPARATOR = re.compile(
    rf"[;；]|(?:[,，/|&、]|\band\b|\bor\b)\s*(?=(?:{_POS_LABEL})\.?(?=$|\s|[\[（(【<]))",
    re.IGNORECASE,
)


def _split_pos_labels(value: str) -> list[str]:
    # Delimiters inside usage/countability annotations belong to the annotation.
    closing_brackets = {"(": ")", "[": "]", "（": "）", "【": "】", "<": ">"}
    stack: list[str] = []
    parts: list[str] = []
    start = index = 0
    while index < len(value):
        char = value[index]
        if char in closing_brackets:
            stack.append(closing_brackets[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack:
            separator = _POS_SEPARATOR.match(value, index)
            if separator:
                parts.append(value[start:index])
                start = index = separator.end()
                continue
        index += 1
    parts.append(value[start:])
    return parts


def normalize_part_of_speech(value: str) -> str:
    """Use full English names and a stable order for recognized POS labels."""
    parts: list[str] = []
    ranks: dict[str, int] = {}
    for raw_part in _split_pos_labels(value):
        part = raw_part.strip()
        if not part:
            continue
        prefix = _POS_PREFIX.match(part)
        if prefix:
            label = _POS_ALIASES[prefix.group(1).casefold()]
            annotation = part[prefix.end():].strip()
            canonical = f"{label} {annotation}" if annotation else label
            rank = _POS_ORDER[label]
        else:
            canonical = part
            rank = len(_POS_ORDER)
        if canonical.casefold() not in {existing.casefold() for existing in parts}:
            parts.append(canonical)
            ranks[canonical.casefold()] = rank
    if "phrasal verb" in parts:
        parts = [part for part in parts if part != "verb"]
    return "; ".join(sorted(
        parts,
        key=lambda part: ranks[part.casefold()],
    ))


class ItemRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _row_to_item(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        item["tags"] = json.loads(item["tags"] or "[]")
        item["collocations"] = json.loads(item["collocations"] or "[]")
        item["synonyms"] = json.loads(item.get("synonyms", "[]") or "[]")
        return item

    def create_item(self, payload: dict, today: date | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ValidationError("词条数据格式不正确。")
        term = str(payload.get("term", "")).strip()
        meaning = str(payload.get("chinese_meaning", "")).strip()
        if not term:
            raise ValidationError("请输入单词、短语或长句。")
        if not meaning:
            raise ValidationError("请输入中文释义。")
        if len(term) > 240 or len(meaning) > 1000:
            raise ValidationError("词条或中文释义过长。")
        collection = validate_collection(payload.get("collection") or "general")
        category_id = parse_category_id(payload.get("academic_category_id"))
        category_name = payload.get("academic_category_name")
        if category_name:
            if collection != "academic":
                raise ValidationError("只有学术词汇可以使用学术分类。")
            category_name = clean_category_name(category_name)
        current_day = today or date.today()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        values = {
            field: str(payload.get(field, "") or "").strip() for field in TEXT_FIELDS
        }
        values["part_of_speech"] = normalize_part_of_speech(values["part_of_speech"])
        tags = _string_list(payload.get("tags", []), "标签")
        collocations = _string_list(payload.get("collocations", []), "搭配")
        synonyms = _string_list(payload.get("synonyms", []), "同义词")
        item_type = str(payload.get("item_type") or infer_item_type(term))
        if item_type not in ITEM_TYPES:
            raise ValidationError("词条类型无效。")
        try:
            with self.database.transaction() as connection:
                if category_name and category_id is None:
                    connection.execute(
                        "INSERT OR IGNORE INTO academic_categories(name,normalized_name,created_at,updated_at) VALUES(?,?,?,?)",
                        (category_name, normalize_term(category_name), now, now),
                    )
                    category_id = connection.execute("SELECT id FROM academic_categories WHERE normalized_name=?",
                                                     (normalize_term(category_name),)).fetchone()["id"]
                category_clause(connection, collection, category_id)
                cursor = connection.execute(
                    """
                    INSERT INTO vocabulary_items(
                        term, normalized_term, chinese_meaning, normalized_chinese_meaning,
                        phonetic, part_of_speech, english_definition, source_sentence,
                        own_sentence, collocations, synonyms, item_type, source, tags, notes, status,
                        created_at, updated_at, next_review_at, collection, academic_category_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?)
                    """,
                    (
                        term,
                        normalize_term(term),
                        meaning,
                        normalize_chinese(meaning),
                        values["phonetic"],
                        values["part_of_speech"],
                        values["english_definition"],
                        values["source_sentence"],
                        values["own_sentence"],
                        json.dumps(collocations, ensure_ascii=False),
                        json.dumps(synonyms, ensure_ascii=False),
                        item_type,
                        values["source"],
                        json.dumps(tags, ensure_ascii=False),
                        values["notes"],
                        now,
                        now,
                        (current_day + timedelta(days=1)).isoformat(),
                        collection,
                        category_id,
                    ),
                )
                item_id = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error):
                raise DuplicateItemError("完全相同的词条已经存在。") from error
            raise
        return self.get_item(int(item_id))

    def get_item(self, item_id: int) -> dict | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT v.*, c.name AS academic_category_name FROM vocabulary_items v "
                "LEFT JOIN academic_categories c ON c.id=v.academic_category_id WHERE v.id = ?", (item_id,)
            ).fetchone()
            item = self._row_to_item(row)
            if not item:
                return None
            item["groups"] = [
                dict(group)
                for group in connection.execute(
                    "SELECT g.id, g.name FROM confusion_groups g "
                    "JOIN confusion_group_items gi ON gi.group_id = g.id "
                    "WHERE gi.item_id = ? ORDER BY g.name", (item_id,)
                ).fetchall()
            ]
            item["recent_reviews"] = [
                dict(review)
                for review in connection.execute(
                    "SELECT reviewed_at, scope, mode, rating, answer, first_try_correct, affects_schedule "
                    "FROM review_history WHERE item_id = ? ORDER BY reviewed_at DESC LIMIT 10",
                    (item_id,),
                ).fetchall()
            ]
            return item

    def update_item(self, item_id: int, payload: dict) -> dict:
        existing = self.get_item(item_id)
        if not existing:
            raise ValidationError("词条不存在。")
        merged = {**existing, **payload}
        collection = validate_collection(merged.get("collection", "general"))
        if collection != existing["collection"]:
            raise ValidationError("已有词条的所属词库不能直接更改，请在目标词库另行收录。")
        category_id = parse_category_id(merged.get("academic_category_id"))
        term = str(merged.get("term", "")).strip()
        meaning = str(merged.get("chinese_meaning", "")).strip()
        if not term or not meaning:
            raise ValidationError("单词、短语或长句和中文释义不能为空。")
        status = str(merged.get("status", existing["status"]))
        if status not in STATUSES:
            raise ValidationError("掌握状态无效。")
        manual_status = status if "status" in payload else existing.get("manual_status")
        values = {field: str(merged.get(field, "") or "").strip() for field in TEXT_FIELDS}
        values["part_of_speech"] = normalize_part_of_speech(values["part_of_speech"])
        tags = _string_list(merged.get("tags", []), "标签")
        collocations = _string_list(merged.get("collocations", []), "搭配")
        synonyms = _string_list(merged.get("synonyms", []), "同义词")
        item_type = str(merged.get("item_type", existing.get("item_type", "word")))
        if item_type not in ITEM_TYPES:
            raise ValidationError("词条类型无效。")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            with self.database.transaction() as connection:
                category_clause(connection, collection, category_id)
                if status != existing["status"]:
                    # A deliberate mastery change starts a fresh error window.
                    connection.execute("UPDATE vocabulary_items SET mastery_checkpoint_id="
                                       "COALESCE((SELECT MAX(id) FROM review_history WHERE item_id=?),0) WHERE id=?",
                                       (item_id, item_id))
                connection.execute(
                    """
                    UPDATE vocabulary_items SET term=?, normalized_term=?, chinese_meaning=?,
                    normalized_chinese_meaning=?, phonetic=?, part_of_speech=?, english_definition=?,
                    source_sentence=?, own_sentence=?, collocations=?, synonyms=?, item_type=?, source=?, tags=?, notes=?,
                    status=?, manual_status=?, updated_at=?, academic_category_id=? WHERE id=?
                    """,
                    (
                        term, normalize_term(term), meaning, normalize_chinese(meaning),
                        values["phonetic"], values["part_of_speech"], values["english_definition"],
                        values["source_sentence"], values["own_sentence"],
                        json.dumps(collocations, ensure_ascii=False),
                        json.dumps(synonyms, ensure_ascii=False), item_type, values["source"],
                        json.dumps(tags, ensure_ascii=False), values["notes"], status,
                        manual_status, now, category_id, item_id,
                    ),
                )
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error):
                raise DuplicateItemError("完全相同的词条已经存在。") from error
            raise
        return self.get_item(item_id)

    def delete_item(self, item_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM vocabulary_items WHERE id = ?", (item_id,))
            connection.execute(
                "DELETE FROM confusion_groups WHERE id IN ("
                "SELECT g.id FROM confusion_groups g LEFT JOIN confusion_group_items gi ON gi.group_id=g.id "
                "GROUP BY g.id HAVING COUNT(gi.item_id) < 2)"
            )
            return cursor.rowcount > 0

    def list_items(self, filters: dict | None = None) -> dict:
        filters = filters or {}
        collection = validate_collection_filter(filters.get("collection", "general"))
        items = [item for item in self.all_items() if collection == "all" or item["collection"] == collection]
        items = self.filter_category(items, collection, filters.get("category_id"))
        query = normalize_term(str(filters.get("q", "")))
        if query:
            items = [
                item for item in items
                if query in normalize_term(" ".join([
                    item["term"], item["chinese_meaning"], item["english_definition"],
                    item["source_sentence"], item["own_sentence"], item["notes"], item["source"],
                    " ".join(item["collocations"]), " ".join(item["tags"]),
                    " ".join(item["synonyms"]), item.get("academic_category_name") or "",
                ]))
            ]
        if filters.get("source"):
            items = [item for item in items if item["source"] == filters["source"]]
        if filters.get("status"):
            items = [item for item in items if item["status"] == filters["status"]]
        if filters.get("item_type"):
            if filters["item_type"] not in ITEM_TYPES:
                raise ValidationError("词条类型筛选无效。")
            items = [item for item in items if item["item_type"] == filters["item_type"]]
        if filters.get("item_group"):
            if filters["item_group"] not in ITEM_GROUPS:
                raise ValidationError("词库分组筛选无效。")
            allowed_types = ITEM_GROUPS[filters["item_group"]]
            items = [item for item in items if item["item_type"] in allowed_types]
        if filters.get("tag"):
            items = [item for item in items if filters["tag"] in item["tags"]]
        sort = str(filters.get("sort", "newest"))
        sorters = {
            "newest": (lambda item: (item["created_at"], item["id"]), True),
            "oldest": (lambda item: (item["created_at"], item["id"]), False),
            "term_asc": (lambda item: (normalize_term(item["term"]), item["id"]), False),
            "term_desc": (lambda item: (normalize_term(item["term"]), item["id"]), True),
        }
        if sort not in sorters:
            raise ValidationError("排序参数无效。")
        sort_key, reverse = sorters[sort]
        items.sort(key=sort_key, reverse=reverse)
        total = len(items)
        try:
            page = max(1, int(filters.get("page", 1)))
            page_size = min(100, max(1, int(filters.get("page_size", 50))))
        except (TypeError, ValueError) as error:
            raise ValidationError("分页参数无效。") from error
        start = (page - 1) * page_size
        return {"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size}

    def all_items(self) -> list[dict]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute("SELECT v.*, c.name AS academic_category_name FROM vocabulary_items v "
                                      "LEFT JOIN academic_categories c ON c.id=v.academic_category_id "
                                      "ORDER BY v.created_at DESC, v.id DESC").fetchall()
        return [self._row_to_item(row) for row in rows]

    def filter_category(self, data: list[dict], collection: str, category_id: Any = None) -> list[dict]:
        with closing(self.database.connect()) as connection:
            clause, values = category_clause(connection, collection, category_id)
        if not clause:
            return data
        selected = values[0] if values else None
        return [item for item in data if item["academic_category_id"] == selected]

    def facets(self, collection: str = "general", category_id: Any = None) -> dict:
        collection = validate_collection_filter(collection)
        data = [item for item in self.all_items() if collection == "all" or item["collection"] == collection]
        data = self.filter_category(data, collection, category_id)
        return {
            "sources": sorted({item["source"] for item in data if item["source"]}),
            "tags": sorted({tag for item in data for tag in item["tags"]}),
            "type_counts": {
                kind: sum(item["item_type"] == kind for item in data)
                for kind in ("word", "phrase", "sentence")
            },
            "group_counts": {
                group: sum(item["item_type"] in item_types for item in data)
                for group, item_types in ITEM_GROUPS.items()
            },
            "collection_counts": {
                name: sum(item["collection"] == name for item in data)
                for name in ("general", "academic")
            },
        }
