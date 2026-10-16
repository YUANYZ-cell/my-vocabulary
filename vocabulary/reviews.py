from __future__ import annotations

import math
import random
import uuid
from contextlib import closing
from datetime import date, datetime

from .content_types import ITEM_TYPES
from .database import Database
from .groups import ConfusionGroupRepository
from .items import ItemRepository, ValidationError, category_clause, validate_collection
from .srs import RATINGS, RATING_ERROR_WEIGHTS, ReviewState, schedule_review

MODES = {"cloze", "zh_to_en", "en_to_zh", "recall"}
SCOPES = {"due", "group", "random", "mistakes", "today", "recent", "topic"}
REVIEW_STRATEGIES = {"balanced", "forgetting"}
REVIEW_ITEM_TYPES = ITEM_TYPES | {"vocabulary"}
MASTERY_WEIGHTS = {"new": 1.2, "learning": 1.55, "wrong": 1.9, "familiar": 0.9, "mastered": 0.65}
MASTERY_LEVELS = ("wrong", "new", "learning", "familiar", "mastered")
MISTAKE_WINDOW = 10
MASTERY_ERROR_WINDOW = 5
MASTERY_ERROR_THRESHOLD = 3


def review_error_score(rating: str, first_try_correct: bool | int | None) -> float:
    """Keep first-attempt spelling mistakes even if the final self-rating is positive."""
    return RATING_ERROR_WEIGHTS.get(rating, 1.0 if first_try_correct == 0 else 0.0)


def _item_age_days(value: object, today: date) -> int:
    """Return whole elapsed days for a stored local ISO date/time."""
    text = str(value or today.isoformat())
    try:
        anchor = date.fromisoformat(text[:10])
    except ValueError:
        anchor = today
    return max(0, (today - anchor).days)


def retrievability(item: dict, today: date, performance: dict | None = None) -> float:
    """Estimate recall probability with a transparent half-life curve."""
    performance = performance or {}
    anchor = performance.get("last_reviewed_at") or item.get("created_at")
    elapsed_days = _item_age_days(anchor, today)
    stability_days = max(0.5, float(item.get("interval_days") or 1.0))
    return math.pow(2.0, -elapsed_days / stability_days)


def forgetting_weight(item: dict, today: date, performance: dict | None = None) -> float:
    """Map current forgetting risk to a bounded, continuously changing priority."""
    risk = 1.0 - retrievability(item, today, performance)
    return 0.45 + 2.55 * risk


def mistake_weight(attempts: int, error_score: float, latest_error_score: float) -> float:
    """Boost missed items using explicit severity and recency without certainty."""
    attempts = max(0, int(attempts))
    error_score = max(0.0, float(error_score))
    latest_error_score = max(0.0, float(latest_error_score))
    if not attempts or not error_score:
        return 1.0
    error_rate = min(1.0, error_score / attempts)
    return min(
        3.0,
        1.0 + min(error_score, 6.0) * 0.12 + error_rate * 0.85 + min(latest_error_score, 2.0) * 0.25,
    )


def selection_weight(
    item: dict, today: date, performance: dict | None = None, strategy: str = "balanced"
) -> float:
    """Combine current retrievability with bounded mastery and mistake signals."""
    performance = performance or {}
    if strategy not in REVIEW_STRATEGIES:
        raise ValidationError("全局复习策略无效。")
    mastery = 1.0 if item.get("item_type") == "sentence" else MASTERY_WEIGHTS.get(str(item.get("status", "new")), MASTERY_WEIGHTS["new"])
    mistakes = mistake_weight(
        performance.get("attempts", 0),
        performance.get("error_score", performance.get("errors", 0)),
        performance.get("latest_error_score", performance.get("latest_error", 0)),
    )
    risk = 1.0 - retrievability(item, today, performance)
    # A just-missed item needs another chance even though its time anchor is now fresh.
    recent_error = min(2.0, max(0.0, float(performance.get("latest_error_score", performance.get("latest_error", 0))))) * 0.9
    if strategy == "forgetting":
        # Forgetting-curve mode is driven mainly by predicted recall loss.  The
        # small mistake modifier breaks ties without overwhelming elapsed time.
        return (0.15 + 5.85 * math.pow(risk, 1.7) + recent_error) * math.pow(mistakes, 0.35)
    return (forgetting_weight(item, today, performance) + recent_error) * mastery * mistakes


def _weighted_sample(
    items: list[dict], today: date, limit: int, performance_by_id: dict[int, dict] | None = None,
    strategy: str = "balanced",
) -> list[dict]:
    """Weighted sampling without replacement, retaining useful randomness."""
    performance_by_id = performance_by_id or {}
    ranked = sorted(
        items,
        key=lambda item: random.random()
        ** (1.0 / selection_weight(item, today, performance_by_id.get(item["id"]), strategy)),
        reverse=True,
    )
    return ranked[:limit]

class ReviewRepository:
    def __init__(self, database: Database, items: ItemRepository, groups: ConfusionGroupRepository):
        self.database, self.items, self.groups = database, items, groups

    @staticmethod
    def _review_item_type(item_type: str) -> str:
        if item_type not in REVIEW_ITEM_TYPES:
            raise ValidationError("复习内容类型无效。")
        return item_type

    @staticmethod
    def _round_mode(mode: str, item_type: str, collection: str = "general", category_id: object = None) -> str:
        """Keep answer modes, content selections and collections in independent draw rounds."""
        key = f"{mode}:{item_type}" if collection == "general" else f"{mode}:{item_type}:{collection}"
        return f"{key}:category:{category_id}" if category_id not in (None, "") else key

    def get_queue(
        self, scope: str, today: date, limit: int = 20, group_id: int | None = None,
        item_type: str = "word", collection: str = "general", category_id: object = None,
    ) -> list[dict]:
        limit = min(100, max(1, int(limit)))
        collection = validate_collection(collection)
        item_type = self._review_item_type(item_type)
        types = ("word", "phrase") if item_type == "vocabulary" else (item_type,)
        type_sql = "v.item_type IN (" + ",".join("?" for _ in types) + ")"
        with closing(self.database.connect()) as connection:
            category_sql, category_params = category_clause(connection, collection, category_id, "v.")
            if scope == "topic":
                if collection != "academic" or category_id in (None, ""):
                    raise ValidationError("专题复习需要选择一个专业分类。")
                rows = connection.execute(
                    "SELECT v.* FROM vocabulary_items v WHERE collection=? "
                    + category_sql + " ORDER BY v.term COLLATE NOCASE,v.id",
                    [collection, *category_params],
                ).fetchall()
            elif scope == "due":
                rows = connection.execute(
                    f"SELECT v.* FROM vocabulary_items v WHERE next_review_at<=? AND {type_sql} AND collection=? "
                    + category_sql + " ORDER BY next_review_at,id LIMIT ?", [today.isoformat(), *types, collection, *category_params, limit]
                ).fetchall()
            elif scope == "group" and group_id is not None:
                rows = connection.execute(
                    "SELECT v.* FROM vocabulary_items v JOIN confusion_group_items gi ON gi.item_id=v.id "
                    f"WHERE gi.group_id=? AND {type_sql} AND v.collection=? " + category_sql + " ORDER BY v.term LIMIT ?",
                    [group_id, *types, collection, *category_params, limit],
                ).fetchall()
            elif scope == "mistakes":
                rows = connection.execute(f"""SELECT v.* FROM vocabulary_items v JOIN (
                    SELECT h.item_id FROM review_history h JOIN
                    (SELECT item_id,MAX(id) last_id FROM review_history GROUP BY item_id) last ON last.last_id=h.id
                    WHERE h.first_try_correct=0 OR h.rating IN ('forgot','fuzzy','unrecalled')
                    ) wrong ON wrong.item_id=v.id WHERE {type_sql} AND v.collection=? """ + category_sql + " ORDER BY v.term LIMIT ?",
                    [*types, collection, *category_params, limit],
                ).fetchall()
            elif scope == "today":
                rows = connection.execute(
                    f"SELECT v.* FROM vocabulary_items v WHERE date(created_at)=? AND {type_sql} AND collection=? "
                    + category_sql + " ORDER BY created_at DESC,id DESC LIMIT ?",
                    [today.isoformat(), *types, collection, *category_params, limit],
                ).fetchall()
            elif scope == "recent":
                rows = connection.execute(
                    f"SELECT v.* FROM vocabulary_items v WHERE {type_sql} AND collection=? "
                    + category_sql + " ORDER BY created_at DESC,id DESC LIMIT ?", [*types, collection, *category_params, limit]
                ).fetchall()
            elif scope == "study":
                rows = connection.execute(
                    f"SELECT v.* FROM vocabulary_items v WHERE {type_sql} AND collection=? "
                    + category_sql + " ORDER BY created_at DESC,id DESC LIMIT ?", [*types, collection, *category_params, limit]
                ).fetchall()
            else:
                raise ValidationError("复习范围无效。")
        return [self.items._row_to_item(row) for row in rows]

    def random_round_status(self, today: date, mode: str, item_type: str = "word", collection: str = "general", category_id: object = None) -> dict:
        if mode not in MODES:
            raise ValidationError("复习方式无效。")
        collection = validate_collection(collection)
        item_type = self._review_item_type(item_type)
        types = ("word", "phrase") if item_type == "vocabulary" else (item_type,)
        type_sql = "v.item_type IN (" + ",".join("?" for _ in types) + ")"
        day = today.isoformat()
        with self.database.transaction() as connection:
            category_sql, category_params = category_clause(connection, collection, category_id, "v.")
            category_id = category_params[0] if category_params else ("uncategorized" if category_sql else None)
            round_mode = self._round_mode(mode, item_type, collection, category_id)
            round_row = connection.execute(
                "SELECT round_no FROM review_method_rounds WHERE day=? AND mode=?", (day, round_mode)
            ).fetchone()
            round_no = round_row["round_no"] if round_row else 1
            used = connection.execute(
                "SELECT COUNT(*) c FROM review_method_draws d JOIN vocabulary_items v ON v.id=d.item_id "
                f"WHERE day=? AND mode=? AND round_no=? AND {type_sql} AND v.collection=? " + category_sql,
                [day, round_mode, round_no, *types, collection, *category_params],
            ).fetchone()["c"]
            total = connection.execute(
                f"SELECT COUNT(*) c FROM vocabulary_items v WHERE {type_sql} AND collection=? " + category_sql,
                [*types, collection, *category_params],
            ).fetchone()["c"]
        return {"mode": mode, "item_type": item_type, "collection": collection, "category_id": category_id, "round": round_no, "used": used, "remaining": max(0, total - used), "total": total}

    def start_random_round(
        self, today: date, mode: str, limit: int = 20, strategy: str = "balanced",
        item_type: str = "word", collection: str = "general", category_id: object = None,
    ) -> dict:
        if mode not in MODES:
            raise ValidationError("复习方式无效。")
        if strategy not in REVIEW_STRATEGIES:
            raise ValidationError("全局复习策略无效。")
        collection = validate_collection(collection)
        item_type = self._review_item_type(item_type)
        types = ("word", "phrase") if item_type == "vocabulary" else (item_type,)
        type_sql = "v.item_type IN (" + ",".join("?" for _ in types) + ")"
        limit, day = min(100, max(1, int(limit))), today.isoformat()
        clock = datetime.now().astimezone()
        now = f"{today.isoformat()}T{clock.strftime('%H:%M:%S')}{clock.strftime('%z')[:3]}:{clock.strftime('%z')[3:]}"
        with self.database.transaction() as connection:
            category_sql, category_params = category_clause(connection, collection, category_id, "v.")
            category_id = category_params[0] if category_params else ("uncategorized" if category_sql else None)
            round_mode = self._round_mode(mode, item_type, collection, category_id)
            connection.execute(
                "INSERT OR IGNORE INTO review_method_rounds(day,mode,round_no,reset_at) VALUES(?,?,1,?)",
                (day, round_mode, now),
            )
            round_no = connection.execute(
                "SELECT round_no FROM review_method_rounds WHERE day=? AND mode=?", (day, round_mode)
            ).fetchone()["round_no"]
            rows = connection.execute(f"SELECT v.* FROM vocabulary_items v WHERE {type_sql} AND collection=? "
                + category_sql + " AND id NOT IN (SELECT item_id FROM review_method_draws WHERE day=? AND mode=? AND round_no=?)",
                [*types, collection, *category_params, day, round_mode, round_no]).fetchall()
            candidates = [self.items._row_to_item(row) for row in rows]
            performance_by_id = {
                row["item_id"]: dict(row)
                for row in connection.execute(
                    f"""WITH ranked AS (
                    SELECT h.*,ROW_NUMBER() OVER (PARTITION BY h.item_id ORDER BY h.id DESC) position
                    FROM review_history h JOIN vocabulary_items v ON v.id=h.item_id
                    WHERE {type_sql} AND v.collection=? {category_sql}
                    ) SELECT h.item_id,COUNT(*) attempts,
                    MAX(h.reviewed_at) last_reviewed_at,
                    SUM(CASE
                        WHEN h.rating='unrecalled' THEN {RATING_ERROR_WEIGHTS['unrecalled']}
                        WHEN h.rating='forgot' THEN {RATING_ERROR_WEIGHTS['forgot']}
                        WHEN h.rating='fuzzy' OR h.first_try_correct=0 THEN {RATING_ERROR_WEIGHTS['fuzzy']}
                        ELSE 0.0 END) error_score,
                    MAX(CASE WHEN h.position=1 THEN CASE
                        WHEN h.rating='unrecalled' THEN {RATING_ERROR_WEIGHTS['unrecalled']}
                        WHEN h.rating='forgot' THEN {RATING_ERROR_WEIGHTS['forgot']}
                        WHEN h.rating='fuzzy' OR h.first_try_correct=0 THEN {RATING_ERROR_WEIGHTS['fuzzy']}
                        ELSE 0.0 END ELSE 0.0 END) latest_error_score
                    FROM ranked h WHERE h.position<={MISTAKE_WINDOW}
                    GROUP BY h.item_id""", [*types, collection, *category_params]
                ).fetchall()
            }
            selected = _weighted_sample(candidates, today, limit, performance_by_id, strategy)
            connection.executemany(
                "INSERT OR IGNORE INTO review_method_draws(day,mode,round_no,item_id,drawn_at) VALUES(?,?,?,?,?)",
                [(day, round_mode, round_no, item["id"], now) for item in selected],
            )
            used = connection.execute(
                "SELECT COUNT(*) c FROM review_method_draws d JOIN vocabulary_items v ON v.id=d.item_id "
                f"WHERE day=? AND mode=? AND round_no=? AND {type_sql} AND v.collection=? " + category_sql,
                [day, round_mode, round_no, *types, collection, *category_params],
            ).fetchone()["c"]
            total = connection.execute(
                f"SELECT COUNT(*) c FROM vocabulary_items v WHERE {type_sql} AND collection=? " + category_sql,
                [*types, collection, *category_params],
            ).fetchone()["c"]
        return {"items": selected, "mode": mode, "item_type": item_type, "collection": collection, "category_id": category_id, "strategy": strategy, "round": round_no, "used": used, "remaining": max(0, total-used), "total": total}

    def reset_random_round(self, today: date, mode: str, item_type: str = "word", collection: str = "general", category_id: object = None) -> dict:
        if mode not in MODES:
            raise ValidationError("复习方式无效。")
        collection = validate_collection(collection)
        item_type = self._review_item_type(item_type)
        day, now = today.isoformat(), datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            category_sql, category_params = category_clause(connection, collection, category_id)
            category_id = category_params[0] if category_params else ("uncategorized" if category_sql else None)
            round_mode = self._round_mode(mode, item_type, collection, category_id)
            connection.execute(
                "INSERT INTO review_method_rounds(day,mode,round_no,reset_at) VALUES(?,?,2,?) "
                "ON CONFLICT(day,mode) DO UPDATE SET round_no=round_no+1,reset_at=excluded.reset_at",
                (day, round_mode, now),
            )
            round_no = connection.execute(
                "SELECT round_no FROM review_method_rounds WHERE day=? AND mode=?", (day, round_mode)
            ).fetchone()["round_no"]
        return {"mode": mode, "item_type": item_type, "collection": collection, "category_id": category_id, "round": round_no}

    def record_review(self, item_id: int, rating: str, today: date, mode: str, answer: str,
                      first_try_correct: bool | None, affects_schedule: bool, client_token: str = "", scope: str = "due", mastery_boost: bool = False) -> dict:
        if scope == "study":
            raise ValidationError("学习模式不保存作答记录。")
        if rating not in RATINGS: raise ValidationError("复习评分无效。")
        if mastery_boost and rating != "remembered":
            raise ValidationError("斩词需要确认已经记住。")
        if mode not in MODES: raise ValidationError("复习模式无效。")
        if mode == "recall":
            if rating not in {"remembered", "forgot", "unrecalled"} or not isinstance(first_try_correct, bool):
                raise ValidationError("请先揭晓中文，再选择回忆结果。")
            if first_try_correct != (rating == "remembered"):
                raise ValidationError("自评结果与评分不一致。")
            answer = ""
        elif rating == "unrecalled":
            raise ValidationError("未能回忆只适用于遮罩自评。")
        elif not str(answer).strip(): raise ValidationError("请先输入答案。")
        if mode != "en_to_zh" and not isinstance(first_try_correct, bool): raise ValidationError("缺少英文答案判定结果。")
        token = client_token or str(uuid.uuid4())
        clock = datetime.now().astimezone()
        now = f"{today.isoformat()}T{clock.strftime('%H:%M:%S')}{clock.strftime('%z')[:3]}:{clock.strftime('%z')[3:]}"
        with self.database.transaction() as connection:
            duplicate = connection.execute("SELECT item_id FROM review_history WHERE client_token=?", (token,)).fetchone()
            if duplicate:
                return self.items._row_to_item(connection.execute("SELECT * FROM vocabulary_items WHERE id=?", (duplicate["item_id"],)).fetchone())
            row = connection.execute("SELECT * FROM vocabulary_items WHERE id=?", (item_id,)).fetchone()
            if not row: raise ValidationError("词条不存在。")
            item = self.items._row_to_item(row)
            if mastery_boost and item["item_type"] == "sentence":
                raise ValidationError("长句不使用斩词提档。")
            previous_interval, previous_status = item["interval_days"], item["status"]
            error_score = review_error_score(rating, first_try_correct)
            if affects_schedule:
                recent = [h["rating"] for h in connection.execute("SELECT rating FROM review_history WHERE item_id=? AND affects_schedule=1 ORDER BY reviewed_at DESC LIMIT 3", (item_id,)).fetchall()][::-1]
                result = schedule_review(ReviewState(item["interval_days"], item["ease_factor"], item["successful_streak"], item["status"], item["review_count"]), rating, today, recent)
                correct_increment = int(not error_score)
                new_status = result.status
                if item["item_type"] != "sentence" and (error_score or MASTERY_LEVELS.index(new_status) < MASTERY_LEVELS.index(previous_status)):
                    # Scheduling may shorten the interval on one error; mastery needs repeated evidence.
                    new_status = previous_status
                connection.execute("UPDATE vocabulary_items SET interval_days=?,ease_factor=?,successful_streak=?,status=?,manual_status=?,next_review_at=?,review_count=review_count+1,correct_count=correct_count+?,updated_at=? WHERE id=?", (result.interval_days,result.ease_factor,result.successful_streak,new_status,item.get("manual_status") if new_status == previous_status else None,result.next_review_at.isoformat(),correct_increment,now,item_id))
                new_interval, next_review = result.interval_days, result.next_review_at.isoformat()
            else:
                new_interval, new_status, next_review = previous_interval, previous_status, item["next_review_at"]
            if mastery_boost:
                # Promote exactly once from the persisted state, in the same transaction as the answer.
                new_status = MASTERY_LEVELS[min(MASTERY_LEVELS.index(previous_status) + 1, len(MASTERY_LEVELS) - 1)]
                connection.execute("UPDATE vocabulary_items SET status=?,manual_status=?,updated_at=? WHERE id=?", (new_status,new_status,now,item_id))
            elif error_score and item["item_type"] != "sentence":
                recent = connection.execute(
                    "SELECT rating,first_try_correct FROM review_history WHERE item_id=? AND id>? ORDER BY id DESC LIMIT ?",
                    (item_id, item["mastery_checkpoint_id"], MASTERY_ERROR_WINDOW - 1),
                ).fetchall()
                errors = 1 + sum(review_error_score(h["rating"], h["first_try_correct"]) > 0 for h in recent)
                if errors >= MASTERY_ERROR_THRESHOLD:
                    new_status = MASTERY_LEVELS[max(0, MASTERY_LEVELS.index(previous_status) - 1)]
                    connection.execute("UPDATE vocabulary_items SET status=?,manual_status=?,updated_at=? WHERE id=?", (new_status,new_status,now,item_id))
            cursor = connection.execute("""INSERT INTO review_history(item_id,reviewed_at,scope,mode,rating,answer,first_try_correct,affects_schedule,client_token,previous_interval_days,new_interval_days,previous_status,new_status,next_review_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (item_id,now,scope if scope in SCOPES else "random",mode,rating,str(answer).strip(),None if first_try_correct is None else int(first_try_correct),int(affects_schedule),token,previous_interval,new_interval,previous_status,new_status,next_review))
            if mastery_boost or new_status != previous_status:
                connection.execute("UPDATE vocabulary_items SET mastery_checkpoint_id=? WHERE id=?", (cursor.lastrowid,item_id))
            return self.items._row_to_item(connection.execute("SELECT * FROM vocabulary_items WHERE id=?", (item_id,)).fetchone())
