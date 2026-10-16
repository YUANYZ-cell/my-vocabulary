from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime

from .database import Database
from .items import ValidationError, category_clause, clean_category_name, normalize_term, parse_category_id


class AcademicCategoryRepository:
    def __init__(self, database: Database):
        self.database = database

    def list_categories(self) -> dict:
        with closing(self.database.connect()) as connection:
            rows = connection.execute("""SELECT c.id,c.name,c.created_at,c.updated_at,
                COUNT(v.id) AS count,
                SUM(CASE WHEN v.item_type IN ('word','phrase') THEN 1 ELSE 0 END) AS vocabulary_count,
                SUM(CASE WHEN v.item_type='sentence' THEN 1 ELSE 0 END) AS sentence_count
                FROM academic_categories c LEFT JOIN vocabulary_items v
                ON v.academic_category_id=c.id AND v.collection='academic'
                GROUP BY c.id ORDER BY c.id""").fetchall()
            summary = connection.execute("""SELECT COUNT(*) AS total,
                COUNT(CASE WHEN academic_category_id IS NULL THEN 1 END) AS uncategorized
                FROM vocabulary_items WHERE collection='academic'""").fetchone()
        return {"items": [dict(row) for row in rows], **dict(summary)}

    def save_category(self, name: str, category_id: int | None = None) -> dict:
        name = clean_category_name(name)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            with self.database.transaction() as connection:
                if category_id is None:
                    category_id = connection.execute(
                        "INSERT INTO academic_categories(name,normalized_name,created_at,updated_at) VALUES(?,?,?,?)",
                        (name, normalize_term(name), now, now),
                    ).lastrowid
                else:
                    cursor = connection.execute(
                        "UPDATE academic_categories SET name=?,normalized_name=?,updated_at=? WHERE id=?",
                        (name, normalize_term(name), now, category_id),
                    )
                    if not cursor.rowcount:
                        raise ValidationError("学术分类不存在。")
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error):
                raise ValidationError("这个分类名称已经存在。") from error
            raise
        return next(row for row in self.list_categories()["items"] if row["id"] == category_id)

    def delete_category(self, category_id: int) -> bool:
        # The foreign key returns terms to Uncategorized without touching learning history.
        with self.database.transaction() as connection:
            return connection.execute("DELETE FROM academic_categories WHERE id=?", (category_id,)).rowcount > 0

    def assign_items(self, item_ids: list, category_id: object = None) -> dict:
        if not isinstance(item_ids, list) or not item_ids or len(item_ids) > 1000:
            raise ValidationError("请勾选 1–1000 个学术词条。")
        ids = list(dict.fromkeys(parse_category_id(value) for value in item_ids))
        if None in ids:
            raise ValidationError("词条选择无效。")
        selected = parse_category_id(category_id)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            category_clause(connection, "academic", selected)
            placeholders = ",".join("?" for _ in ids)
            rows = connection.execute(f"SELECT id,collection FROM vocabulary_items WHERE id IN ({placeholders})", ids).fetchall()
            if len(rows) != len(ids) or any(row["collection"] != "academic" for row in rows):
                raise ValidationError("只能整理现有的学术词汇，请重新选择词条。")
            connection.execute(
                f"UPDATE vocabulary_items SET academic_category_id=?,updated_at=? WHERE id IN ({placeholders})",
                [selected, now, *ids],
            )
        return {"updated": len(ids), "academic_category_id": selected}
