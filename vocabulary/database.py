from __future__ import annotations

import sqlite3
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .content_types import infer_item_type

SCHEMA_VERSION = 14


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self, foreign_keys: bool = True) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            if not foreign_keys:
                connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction(foreign_keys=False) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM app_meta WHERE key = 'schema_version'"
            ).fetchone()
            previous_version = int(row["value"]) if row else 0
            if previous_version > SCHEMA_VERSION:
                raise RuntimeError("数据库版本高于当前程序，不能自动降级。")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vocabulary_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL,
                    normalized_term TEXT NOT NULL,
                    chinese_meaning TEXT NOT NULL,
                    normalized_chinese_meaning TEXT NOT NULL,
                    phonetic TEXT NOT NULL DEFAULT '',
                    part_of_speech TEXT NOT NULL DEFAULT '',
                    english_definition TEXT NOT NULL DEFAULT '',
                    source_sentence TEXT NOT NULL DEFAULT '',
                    own_sentence TEXT NOT NULL DEFAULT '',
                    collocations TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'new',
                    manual_status TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_review_at TEXT NOT NULL,
                    interval_days INTEGER NOT NULL DEFAULT 1,
                    ease_factor REAL NOT NULL DEFAULT 2.0,
                    successful_streak INTEGER NOT NULL DEFAULT 0,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(normalized_term, normalized_chinese_meaning)
                );

                CREATE TABLE IF NOT EXISTS confusion_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS confusion_group_items (
                    group_id INTEGER NOT NULL REFERENCES confusion_groups(id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES vocabulary_items(id) ON DELETE CASCADE,
                    PRIMARY KEY(group_id, item_id)
                );

                CREATE TABLE IF NOT EXISTS review_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES vocabulary_items(id) ON DELETE CASCADE,
                    reviewed_at TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    answer TEXT NOT NULL DEFAULT '',
                    first_try_correct INTEGER,
                    affects_schedule INTEGER NOT NULL,
                    client_token TEXT NOT NULL UNIQUE,
                    previous_interval_days INTEGER NOT NULL,
                    new_interval_days INTEGER NOT NULL,
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    next_review_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_items_due ON vocabulary_items(next_review_at);
                CREATE INDEX IF NOT EXISTS idx_items_status ON vocabulary_items(status);
                CREATE INDEX IF NOT EXISTS idx_history_item_time ON review_history(item_id, reviewed_at DESC);

                CREATE TABLE IF NOT EXISTS review_rounds (
                    day TEXT PRIMARY KEY,
                    round_no INTEGER NOT NULL DEFAULT 1,
                    reset_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS review_draws (
                    day TEXT NOT NULL,
                    round_no INTEGER NOT NULL,
                    item_id INTEGER NOT NULL REFERENCES vocabulary_items(id) ON DELETE CASCADE,
                    drawn_at TEXT NOT NULL,
                    PRIMARY KEY(day, round_no, item_id)
                );

                -- A practice method owns its own daily draw list.  The older
                -- review_rounds tables are deliberately retained so existing
                -- local history remains intact while new rounds are isolated
                -- by method.
                CREATE TABLE IF NOT EXISTS review_method_rounds (
                    day TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    round_no INTEGER NOT NULL DEFAULT 1,
                    reset_at TEXT NOT NULL,
                    PRIMARY KEY(day, mode)
                );

                CREATE TABLE IF NOT EXISTS review_method_draws (
                    day TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    round_no INTEGER NOT NULL,
                    item_id INTEGER NOT NULL REFERENCES vocabulary_items(id) ON DELETE CASCADE,
                    drawn_at TEXT NOT NULL,
                    PRIMARY KEY(day, mode, round_no, item_id)
                );

                CREATE TABLE IF NOT EXISTS expression_materials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    english_text TEXT NOT NULL,
                    chinese_text TEXT NOT NULL DEFAULT '',
                    exam_type TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    illustration_path TEXT NOT NULL DEFAULT '',
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS expression_reading_state (
                    material_id INTEGER PRIMARY KEY REFERENCES expression_materials(id) ON DELETE CASCADE,
                    read_count INTEGER NOT NULL DEFAULT 0,
                    last_read_at TEXT,
                    scroll_ratio REAL NOT NULL DEFAULT 0,
                    translation_visible INTEGER NOT NULL DEFAULT 1,
                    font_scale REAL NOT NULL DEFAULT 1,
                    line_height REAL NOT NULL DEFAULT 1.85
                );

                CREATE TABLE IF NOT EXISTS expression_read_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL REFERENCES expression_materials(id) ON DELETE CASCADE,
                    opened_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_expression_type ON expression_materials(content_type);
                CREATE INDEX IF NOT EXISTS idx_expression_favorite ON expression_materials(is_favorite);
                CREATE INDEX IF NOT EXISTS idx_expression_recent ON expression_reading_state(last_read_at DESC);
                CREATE INDEX IF NOT EXISTS idx_expression_history_day ON expression_read_history(opened_at);

                -- Casual browsing is isolated from both vocabulary and reading activity.
                CREATE TABLE IF NOT EXISTS daily_expressions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seed_key TEXT UNIQUE,
                    phrase TEXT NOT NULL,
                    meaning TEXT NOT NULL,
                    category TEXT NOT NULL,
                    pronunciation TEXT NOT NULL DEFAULT '',
                    example TEXT NOT NULL DEFAULT '',
                    translation TEXT NOT NULL DEFAULT '',
                    usage TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            columns = {column["name"] for column in connection.execute("PRAGMA table_info(vocabulary_items)")}
            if "synonyms" not in columns:
                connection.execute("ALTER TABLE vocabulary_items ADD COLUMN synonyms TEXT NOT NULL DEFAULT '[]'")
            if "item_type" not in columns:
                connection.execute("ALTER TABLE vocabulary_items ADD COLUMN item_type TEXT NOT NULL DEFAULT 'word'")
            if "collection" not in columns:
                # Rebuild only the parent table to replace the legacy global unique key.
                # IDs and all child references remain unchanged; the transaction is atomic.
                sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='vocabulary_items'").fetchone()
                schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='vocabulary_items'").fetchone()[0]
                schema = re.sub(r'CREATE TABLE\s+"?vocabulary_items"?', 'CREATE TABLE vocabulary_items_new', schema, count=1)
                schema = schema.replace("UNIQUE(normalized_term, normalized_chinese_meaning)",
                    "collection TEXT NOT NULL DEFAULT 'general' CHECK(collection IN ('general','academic')), UNIQUE(collection, normalized_term, normalized_chinese_meaning)")
                connection.execute(schema)
                names = ','.join('"' + c['name'] + '"' for c in connection.execute("PRAGMA table_info(vocabulary_items)"))
                connection.execute(f"INSERT INTO vocabulary_items_new ({names}) SELECT {names} FROM vocabulary_items")
                connection.execute("DROP TABLE vocabulary_items")
                connection.execute("ALTER TABLE vocabulary_items_new RENAME TO vocabulary_items")
                if sequence:
                    connection.execute("UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name='vocabulary_items'", (sequence[0],))
                connection.execute("CREATE INDEX idx_items_due ON vocabulary_items(next_review_at)")
                connection.execute("CREATE INDEX idx_items_status ON vocabulary_items(status)")
                connection.execute("CREATE INDEX idx_items_collection ON vocabulary_items(collection, item_type)")
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError("词库迁移的关联校验失败。")
            connection.execute("""CREATE TABLE IF NOT EXISTS academic_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            category_columns = {column["name"] for column in connection.execute("PRAGMA table_info(vocabulary_items)")}
            if "academic_category_id" not in category_columns:
                connection.execute("ALTER TABLE vocabulary_items ADD COLUMN academic_category_id INTEGER "
                                   "REFERENCES academic_categories(id) ON DELETE SET NULL")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_items_academic_category "
                               "ON vocabulary_items(collection, academic_category_id, item_type)")
            if "mastery_checkpoint_id" not in category_columns:
                connection.execute("ALTER TABLE vocabulary_items ADD COLUMN mastery_checkpoint_id INTEGER NOT NULL DEFAULT 0")
                # Existing mistakes inform sampling, but never retroactively deduct mastery.
                connection.execute("UPDATE vocabulary_items SET mastery_checkpoint_id="
                                   "COALESCE((SELECT MAX(id) FROM review_history WHERE item_id=vocabulary_items.id),0)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_history_item_id ON review_history(item_id,id DESC)")
            for operation in ("INSERT", "UPDATE"):
                connection.execute(f"""CREATE TRIGGER IF NOT EXISTS academic_category_{operation.lower()}_guard
                    BEFORE {operation} ON vocabulary_items
                    WHEN NEW.academic_category_id IS NOT NULL AND NEW.collection != 'academic'
                    BEGIN SELECT RAISE(ABORT, 'academic category requires academic collection'); END""")
            expression_columns = {
                column["name"]
                for column in connection.execute("PRAGMA table_info(expression_materials)")
            }
            if "illustration_path" not in expression_columns:
                connection.execute(
                    "ALTER TABLE expression_materials "
                    "ADD COLUMN illustration_path TEXT NOT NULL DEFAULT ''"
                )
            daily_columns = {
                column["name"]
                for column in connection.execute("PRAGMA table_info(daily_expressions)")
            }
            if "deleted_at" not in daily_columns:
                connection.execute("ALTER TABLE daily_expressions ADD COLUMN deleted_at TEXT")
            if "moved_at" not in daily_columns:
                connection.execute("ALTER TABLE daily_expressions ADD COLUMN moved_at TEXT")
            connection.execute("""CREATE TABLE IF NOT EXISTS daily_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            if "group_id" not in daily_columns:
                connection.execute("ALTER TABLE daily_expressions ADD COLUMN group_id INTEGER "
                                   "REFERENCES daily_groups(id) ON DELETE SET NULL")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_daily_group ON daily_expressions(group_id)")
            connection.execute("""CREATE TABLE IF NOT EXISTS content_moves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                active_kind TEXT NOT NULL CHECK(active_kind IN ('vocabulary','expressions','daily')),
                active_id INTEGER NOT NULL,
                archives TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(active_kind, active_id)
            )""")
            if previous_version < 7:
                # Legacy repair runs once, never over a current user's explicit type.
                connection.execute(
                    "UPDATE vocabulary_items SET item_type='phrase' "
                    "WHERE item_type='word' AND instr(trim(term),' ')>0"
                )
                phrase_rows = connection.execute(
                    "SELECT id, term FROM vocabulary_items WHERE item_type='phrase'"
                ).fetchall()
                corrected_types = [
                    (inferred, row["id"])
                    for row in phrase_rows
                    if (inferred := infer_item_type(row["term"])) != "phrase"
                ]
                connection.executemany(
                    "UPDATE vocabulary_items SET item_type=? WHERE id=?",
                    corrected_types,
                )
            connection.execute(
                "INSERT INTO app_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            from .daily_expressions import seed_daily_expressions

            seed_daily_expressions(connection)
