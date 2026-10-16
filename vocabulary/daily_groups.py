from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime

from .items import ValidationError


class DailyGroupRepository:
    """Small everyday collections, independent of vocabulary review scheduling."""

    def __init__(self, database):
        self.database = database

    def list_groups(self):
        with closing(self.database.connect()) as connection:
            return {"items": [dict(row) for row in connection.execute("""
                SELECT g.*, count(d.id) AS item_count FROM daily_groups g
                LEFT JOIN daily_expressions d ON d.group_id=g.id
                    AND d.deleted_at IS NULL AND d.moved_at IS NULL
                GROUP BY g.id ORDER BY g.id
            """)]}

    def save_group(self, name, group_id=None):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValidationError("请填写 1–80 字的合集名称。")
        name = name.strip()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            with self.database.transaction() as connection:
                if group_id is None:
                    cursor = connection.execute(
                        "INSERT INTO daily_groups(name,normalized_name,created_at,updated_at) VALUES(?,?,?,?)",
                        (name, name.casefold(), now, now))
                    group_id = cursor.lastrowid
                else:
                    cursor = connection.execute(
                        "UPDATE daily_groups SET name=?,normalized_name=?,updated_at=? WHERE id=?",
                        (name, name.casefold(), now, group_id))
                    if not cursor.rowcount:
                        return None
        except sqlite3.IntegrityError as error:
            raise ValidationError("已有同名合集，请使用其他名称。") from error
        return next(group for group in self.list_groups()["items"] if group["id"] == group_id)

    def delete_group(self, group_id):
        # Foreign keys detach members, including deleted/moved rows, without deleting any content.
        with self.database.transaction() as connection:
            return bool(connection.execute("DELETE FROM daily_groups WHERE id=?", (group_id,)).rowcount)
