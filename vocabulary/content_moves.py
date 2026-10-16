from __future__ import annotations

import json
import hashlib
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta

from .content_types import ITEM_TYPES, infer_item_type
from .daily_expressions import CATEGORIES, LIMITS
from .database import Database
from .items import DuplicateItemError, ValidationError, category_clause, normalize_chinese, normalize_part_of_speech, normalize_term, parse_category_id


MODULES = {"general": "阅读写作", "academic": "学术词汇", "expressions": "阅读素材", "daily": "生活口语"}
TABLES = {"vocabulary": "vocabulary_items", "expressions": "expression_materials", "daily": "daily_expressions"}
CHILDREN = {"vocabulary": {"review_history": "item_id", "review_draws": "item_id", "review_method_draws": "item_id"},
            "expressions": {"expression_reading_state": "material_id", "expression_read_history": "material_id"}}


def kind(module):
    if not isinstance(module, str) or module not in MODULES:
        raise ValidationError("请选择有效的目标模块；总词库是汇总视图。")
    return "vocabulary" if module in {"general", "academic"} else module


class ContentMoveRepository:
    """Move one active entry atomically; retain native rows and their history for a round trip.

    Archived vocabulary/reading rows do not participate in casual-browsing activity.
    Daily seed rows remain as tombstones so startup cannot recreate a moved expression.
    """

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _version(row):
        return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()

    def _source(self, connection, module, item_id):
        storage = kind(module)
        item_id = parse_category_id(item_id)
        if item_id is None:
            raise ValidationError("词条选择无效。")
        row = connection.execute(f"SELECT * FROM {TABLES[storage]} WHERE id=?", (item_id,)).fetchone()
        if row is None or (storage == "vocabulary" and row["collection"] != module) or (
            storage == "daily" and (row["deleted_at"] or row["moved_at"])
        ):
            raise ValidationError("这条内容已移动或不存在，请刷新后重试。")
        return dict(row)

    @staticmethod
    def _common(module, row):
        if module in {"general", "academic"}:
            return dict(term=row["term"], meaning=row["chinese_meaning"], pronunciation=row["phonetic"],
                        example=row["source_sentence"], translation="", usage=row["notes"], source=row["source"], is_favorite=False)
        if module == "expressions":
            return dict(term=row["english_text"], meaning=row["chinese_text"], pronunciation="", example="", translation="",
                        usage=row["notes"], source=row["source"], is_favorite=bool(row["is_favorite"]))
        return {"term": row["phrase"], "meaning": row["meaning"],
                **{key: row[key] for key in ("pronunciation", "example", "translation", "usage", "source", "is_favorite")}}

    def _preview(self, connection, payload):
        source, target = payload.get("source"), payload.get("target")
        kind(target)
        row = self._source(connection, source, payload.get("item_id"))
        if source == target:
            raise ValidationError("这条内容已经在所选模块中。")
        values = self._common(source, row)
        short_target = target != "expressions"
        long_text = short_target and (len(values["term"]) > 240 or len(values["meaning"]) > 1000)
        # A long reading remains intact in its native archive. The user reviews the short label.
        if short_target and len(values["term"]) > 240:
            values["term"] = row.get("title", "")
        if short_target and len(values["meaning"]) > 1000:
            values["meaning"] = ""
        record = connection.execute("SELECT archives FROM content_moves WHERE active_kind=? AND active_id=?", (kind(source), row["id"])).fetchone()
        retained_snapshot = json.loads(record["archives"]).get("vocabulary", {}) if record else {}
        retained = retained_snapshot.get("row", {})
        category_id = retained_snapshot.get("academic_category_id")
        if category_id and not connection.execute("SELECT 1 FROM academic_categories WHERE id=?", (category_id,)).fetchone():
            category_id = None
        return {"source": source, "target": target, "item_id": row["id"], "source_label": MODULES[source],
                "target_label": MODULES[target], "term": values["term"], "meaning": values["meaning"],
                "item_type": row.get("item_type") or retained.get("item_type") or infer_item_type(values["term"]),
                "category": row.get("category", "口语"), "academic_category_id": category_id,
                "long_text": long_text, "title": row.get("title") or values["term"],
                "retains_history": True, "source_version": self._version(row)}

    def preview(self, payload):
        with closing(self.database.connect()) as connection:
            return self._preview(connection, payload)

    def retained(self, module, item_id):
        with closing(self.database.connect()) as connection:
            row = self._source(connection, module, item_id)
            record = connection.execute("SELECT archives FROM content_moves WHERE active_kind=? AND active_id=?", (kind(module), row["id"])).fetchone()
        archives = json.loads(record["archives"]) if record else {}
        result = []
        labels = {"phonetic": "音标", "part_of_speech": "词性", "english_definition": "英文释义", "source_sentence": "原句",
                  "own_sentence": "自己的例句", "notes": "备注", "source": "来源", "content_type": "素材类型", "topic": "主题",
                  "exam_type": "考试类型", "illustration_path": "配图", "pronunciation": "读音", "example": "例句", "translation": "例句翻译", "usage": "用法"}
        for storage, snapshot in archives.items():
            original = snapshot["row"]
            original_module = original.get("collection") if storage == "vocabulary" else storage
            common = self._common(original_module, original)
            fields = [{"label": label, "value": original[key]} for key, label in labels.items() if original.get(key)]
            for key, label in (("tags", "标签"), ("synonyms", "同义词"), ("collocations", "搭配")):
                if original.get(key) and json.loads(original[key]):
                    fields.append({"label": label, "value": "、".join(json.loads(original[key]))})
            result.append({"label": MODULES[original_module], "term": common["term"], "meaning": common["meaning"], "fields": fields,
                           "history_count": len(snapshot.get("children", {}).get("review_history", [])),
                           "read_count": len(snapshot.get("children", {}).get("expression_read_history", []))})
        return {"items": result}

    @staticmethod
    def _write(connection, table, values, item_id=None):
        # Keys originate exclusively from trusted schema rows or the conversion below.
        if item_id is None:
            keys = ",".join(values)
            marks = ",".join("?" for _ in values)
            return connection.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})", tuple(values.values())).lastrowid
        assignments = ",".join(f"{key}=?" for key in values if key != "id")
        connection.execute(f"UPDATE {table} SET {assignments} WHERE id=?",
                           (*[value for key, value in values.items() if key != "id"], item_id))
        return item_id

    def _remember(self, connection, storage, row, archives):
        previous = archives.get(storage, {})
        children = {table: [dict(r) for r in connection.execute(f"SELECT * FROM {table} WHERE {key}=?", (row["id"],))]
                    for table, key in CHILDREN.get(storage, {}).items()}
        memberships = previous.get("memberships", {})
        if storage == "vocabulary":
            for group in connection.execute("SELECT g.* FROM confusion_groups g JOIN confusion_group_items i ON i.group_id=g.id WHERE i.item_id=?", (row["id"],)):
                memberships[str(group["id"])] = {"collection": row["collection"], "updated_at": group["updated_at"]}
        category_id = row.get("academic_category_id") if row.get("collection") == "academic" else previous.get("academic_category_id")
        archives[storage] = {"row": row, "children": children, "memberships": memberships, "academic_category_id": category_id}

    def _target_values(self, connection, target, source, row, payload, archives, preview, now):
        storage = kind(target)
        saved = archives.get(storage, {}).get("row")
        values = dict(saved or {})
        common = self._common(source, row)
        text = payload.get("term", preview["term"])
        meaning = payload.get("meaning", preview["meaning"])
        if not isinstance(text, str) or not isinstance(meaning, str):
            raise ValidationError("英文和中文必须是文本。")
        text, meaning = text.strip(), meaning.strip()
        limit = 200_000 if target == "expressions" else 240
        if not text or len(text) > limit or (target != "expressions" and (not meaning or len(meaning) > 1000)) or len(meaning) > 200_000:
            raise ValidationError("请填写符合长度要求的英文与中文；长篇原文会保留在原模块资料中。")
        values.update(created_at=values.get("created_at", row["created_at"]), updated_at=now)
        if storage == "vocabulary":
            item_type = payload.get("item_type", preview["item_type"])
            if item_type not in ITEM_TYPES:
                raise ValidationError("词条类型无效。")
            category_id = parse_category_id(payload.get("academic_category_id", preview["academic_category_id"])) if target == "academic" else None
            category_clause(connection, target, category_id)
            values.update(term=text, normalized_term=normalize_term(text), chinese_meaning=meaning,
                          normalized_chinese_meaning=normalize_chinese(meaning), collection=target,
                          item_type=item_type, academic_category_id=category_id)
            if not saved:
                values.update(phonetic=common["pronunciation"], source_sentence=common["example"],
                              notes=common["usage"], source=common["source"],
                              next_review_at=(date.today()+timedelta(days=1)).isoformat())
                if source == "expressions" and row["english_text"] != text:
                    values["source_sentence"] = row["english_text"]
            else:
                values["source"] = common["source"]
                if source == "daily":
                    values["phonetic"] = common["pronunciation"] or values.get("phonetic", "")
                    values["source_sentence"] = common["example"] or values.get("source_sentence", "")
                if len(values.get("notes", "")) <= 2000:
                    values["notes"] = common["usage"]
            values["part_of_speech"] = normalize_part_of_speech(values.get("part_of_speech", ""))
            return values
        if storage == "expressions":
            if not saved:
                values.update(content_type="句式", title=text[:240], english_text=text, chinese_text=meaning,
                              source=common["source"] if len(common["source"]) <= 1000 else "",
                              notes=common["usage"] if len(common["usage"]) <= 20_000 else "", is_favorite=int(common["is_favorite"]))
            else:
                # Retain full articles when a short browse label makes a round trip.
                if len(saved["english_text"]) <= 240:
                    values["english_text"] = text
                if len(saved["chinese_text"]) <= 1000:
                    values["chinese_text"] = meaning
                if len(saved["notes"]) <= 2000:
                    values["notes"] = common["usage"]
                if len(common["source"]) <= 1000:
                    values["source"] = common["source"]
                if source == "daily":
                    values["is_favorite"] = int(common["is_favorite"])
            return values
        category = payload.get("category", preview["category"])
        if category not in CATEGORIES:
            raise ValidationError("请选择口语、俚语、习语或谚语。")
        values.update(phrase=text, meaning=meaning, category=category, moved_at=None, deleted_at=None)
        if values.get("group_id") and not connection.execute("SELECT 1 FROM daily_groups WHERE id=?", (values["group_id"],)).fetchone():
            values["group_id"] = None
        for key in ("pronunciation", "example", "translation", "usage", "source"):
            if len(common[key]) <= LIMITS[key] and (common[key] or not saved):
                values[key] = common[key]
        if not saved or source == "expressions":
            values["is_favorite"] = int(common["is_favorite"])
        return values

    def _duplicates(self, connection, storage, values, exclude=None):
        if storage == "vocabulary":
            row = connection.execute("SELECT id FROM vocabulary_items WHERE collection=? AND normalized_term=? AND normalized_chinese_meaning=? AND id!=?",
                                     (values["collection"], values["normalized_term"], values["normalized_chinese_meaning"], exclude or -1)).fetchone()
            if row:
                raise DuplicateItemError("目标模块已有相同词条，未移动或覆盖任何内容。")
            return
        table = TABLES[storage]
        term_key, meaning_key = ("english_text", "chinese_text") if storage == "expressions" else ("phrase", "meaning")
        condition = " WHERE moved_at IS NULL AND deleted_at IS NULL" if storage == "daily" else ""
        for row in connection.execute(f"SELECT * FROM {table}" + condition):
            if row["id"] != exclude and normalize_term(row[term_key]) == normalize_term(values[term_key]) and normalize_chinese(row[meaning_key]) == normalize_chinese(values[meaning_key]):
                raise DuplicateItemError("目标模块已有相同内容，未移动或覆盖任何内容。")

    def move(self, payload):
        try:
            with self.database.transaction() as connection:
                preview = self._preview(connection, payload)
                source, target = preview["source"], preview["target"]
                before, after = kind(source), kind(target)
                row = self._source(connection, source, preview["item_id"])
                if payload.get('source_version') and payload['source_version'] != self._version(row):
                    raise ValidationError("这条内容已被修改，请重新选择目标模块刷新预览后再移动。")
                record = connection.execute("SELECT * FROM content_moves WHERE active_kind=? AND active_id=?", (before, row["id"])).fetchone()
                archives = json.loads(record["archives"]) if record else {}
                self._remember(connection, before, row, archives)
                now = datetime.now().astimezone().isoformat(timespec="seconds")
                values = self._target_values(connection, target, source, row, payload, archives, preview, now)
                saved = archives.get(after)
                same_table = before == after
                restore_id = row["id"] if same_table else saved["row"]["id"] if saved else None
                self._duplicates(connection, after, values, restore_id)
                if same_table:
                    item_id = self._write(connection, TABLES[after], values, row["id"])
                elif after == "daily" and restore_id:
                    old = connection.execute("SELECT * FROM daily_expressions WHERE id=?", (restore_id,)).fetchone()
                    if old is None or old["moved_at"] is None:
                        raise ValidationError("原生活口语的恢复位置已改变，未移动任何内容。")
                    item_id = self._write(connection, TABLES[after], values, restore_id)
                else:
                    item_id = self._write(connection, TABLES[after], values)
                    if saved:
                        for table, children in saved["children"].items():
                            for child in children:
                                self._write(connection, table, child)
                if before == "vocabulary":
                    connection.execute("DELETE FROM confusion_group_items WHERE item_id=?", (row["id"],))
                if not same_table:
                    if before == "daily":
                        connection.execute("UPDATE daily_expressions SET moved_at=?,updated_at=? WHERE id=?", (now, now, row["id"]))
                    else:
                        connection.execute(f"DELETE FROM {TABLES[before]} WHERE id=?", (row["id"],))
                if after == "vocabulary":
                    for group_id, membership in archives.get("vocabulary", {}).get("memberships", {}).items():
                        group = connection.execute("SELECT * FROM confusion_groups WHERE id=?", (int(group_id),)).fetchone()
                        if group and membership["collection"] == target and group["updated_at"] == membership["updated_at"]:
                            members = connection.execute("SELECT DISTINCT v.collection FROM confusion_group_items i JOIN vocabulary_items v ON v.id=i.item_id WHERE i.group_id=?", (int(group_id),)).fetchall()
                            if all(member["collection"] == target for member in members):
                                connection.execute("INSERT OR IGNORE INTO confusion_group_items(group_id,item_id) VALUES(?,?)", (int(group_id), item_id))
                stamp = {"active_kind": after, "active_id": item_id, "archives": json.dumps(archives, ensure_ascii=False), "updated_at": now}
                if record:
                    self._write(connection, "content_moves", stamp, record["id"])
                else:
                    self._write(connection, "content_moves", {**stamp, "created_at": now})
        except sqlite3.IntegrityError as error:
            raise DuplicateItemError("移动发生数据冲突，原内容与记录已保留。请刷新后重试。") from error
        return {"moved": True, "source": source, "target": target, "item_id": item_id,
                "academic_category_id": values.get("academic_category_id"), "item_type": values.get("item_type"),
                "term": values.get("term") or values.get("phrase") or values.get("title"), "retains_history": True}
