from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from contextlib import closing

from .database import Database
from .items import ItemRepository, ValidationError, normalize_term


class ConfusionGroupRepository:
    def __init__(self, database: Database, items: ItemRepository):
        self.database = database
        self.items = items

    def _get_with(self, connection, group_id: int) -> dict | None:
        group = connection.execute("SELECT * FROM confusion_groups WHERE id=?", (group_id,)).fetchone()
        if not group:
            return None
        rows = connection.execute(
            "SELECT v.* FROM vocabulary_items v JOIN confusion_group_items gi ON gi.item_id=v.id "
            "WHERE gi.group_id=? ORDER BY v.term", (group_id,)
        ).fetchall()
        result = dict(group)
        result["items"] = [self.items._row_to_item(row) for row in rows]
        return result

    def get_group(self, group_id: int) -> dict | None:
        with closing(self.database.connect()) as connection:
            return self._get_with(connection, group_id)

    def list_groups(self) -> list[dict]:
        with closing(self.database.connect()) as connection:
            ids = [row["id"] for row in connection.execute(
                "SELECT g.id FROM confusion_groups g JOIN confusion_group_items gi ON gi.group_id=g.id "
                "GROUP BY g.id HAVING COUNT(gi.item_id)>=2 ORDER BY g.updated_at DESC"
            ).fetchall()]
            return [self._get_with(connection, group_id) for group_id in ids]

    def _validate_ids(self, connection, item_ids: list[int]) -> list[int]:
        unique = list(dict.fromkeys(int(item_id) for item_id in item_ids))
        if len(unique) < 2:
            raise ValidationError("易混词组至少需要两个词条。")
        placeholders = ",".join("?" for _ in unique)
        count = connection.execute(
            f"SELECT COUNT(*) AS count FROM vocabulary_items WHERE id IN ({placeholders})", unique
        ).fetchone()["count"]
        if count != len(unique):
            raise ValidationError("易混词组中包含不存在的词条。")
        collections = connection.execute(
            f"SELECT DISTINCT collection FROM vocabulary_items WHERE id IN ({placeholders})", unique
        ).fetchall()
        if len(collections) != 1:
            raise ValidationError("通用词库和学术词汇不能建立混合分组。")
        return unique

    def create_group(self, name: str, item_ids: list[int]) -> dict:
        clean_name = name.strip() or "易混词组"
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            unique = self._validate_ids(connection, item_ids)
            cursor = connection.execute(
                "INSERT INTO confusion_groups(name, created_at, updated_at) VALUES(?,?,?)",
                (clean_name, now, now),
            )
            group_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO confusion_group_items(group_id,item_id) VALUES(?,?)",
                [(group_id, item_id) for item_id in unique],
            )
        return self.get_group(group_id)

    def update_group(self, group_id: int, name: str, item_ids: list[int]) -> dict:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            if not connection.execute("SELECT 1 FROM confusion_groups WHERE id=?", (group_id,)).fetchone():
                raise ValidationError("易混词组不存在。")
            unique = self._validate_ids(connection, item_ids)
            connection.execute(
                "UPDATE confusion_groups SET name=?, updated_at=? WHERE id=?",
                (name.strip() or "易混词组", now, group_id),
            )
            connection.execute("DELETE FROM confusion_group_items WHERE group_id=?", (group_id,))
            connection.executemany(
                "INSERT INTO confusion_group_items(group_id,item_id) VALUES(?,?)",
                [(group_id, item_id) for item_id in unique],
            )
        return self.get_group(group_id)

    def delete_group(self, group_id: int) -> bool:
        with self.database.transaction() as connection:
            return connection.execute("DELETE FROM confusion_groups WHERE id=?", (group_id,)).rowcount > 0

    def suggest_similar(self, item_id: int) -> list[dict]:
        target = self.items.get_item(item_id)
        if not target:
            raise ValidationError("词条不存在。")
        target_term = normalize_term(target["term"])
        if len(target_term.replace(" ", "")) < 4:
            return []
        candidates = [item for item in self.items.all_items() if item["collection"] == target["collection"]]
        suggestions = []
        for item in candidates:
            if item["id"] == item_id:
                continue
            term = normalize_term(item["term"])
            compact_target, compact = target_term.replace(" ", ""), term.replace(" ", "")
            if len(compact) < 4 or abs(len(compact_target) - len(compact)) > 3:
                continue
            score = SequenceMatcher(None, compact_target, compact).ratio()
            if score >= 0.72:
                suggestions.append({**item, "similarity": round(score, 3)})
        return sorted(suggestions, key=lambda row: (-row["similarity"], row["term"].lower()))
